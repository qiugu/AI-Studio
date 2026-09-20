import logging
import uuid
from datetime import datetime
from typing import List

from qdrant_client.models import PointStruct
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.config import config
from app.core.database import sessionLocal
from app.core.exceptions import ValidationException
from app.core.vector_db import (
    collection_layout,
    collection_name_for,
    get_or_create_collection,
    get_qdrant_client,
    get_vector_size_for_model,
    hybrid_point_vector,
)
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.knowledge import KnowledgeChunkRepository
from app.utils.document import DocumentParser, TextSplitter, chunk_type_for
from app.utils.embedding import get_embedding_client
from app.utils.sparse import default_encoder

logger = logging.getLogger(__name__)

NAMED_DENSE_VECTOR = "dense"


def vector_id_for(doc_id: str, index: int, epoch: str) -> str:
    """分块向量 id：``uuid5(doc_id + 序号 + 分块代次)``

    **代次后缀是必须的**，不是装饰：``knowledge_chunks.vector_id`` 上有唯一索引，
    而重建期间新旧两代分块行会同时存活（旧行支撑回滚窗口），若 id 只由
    ``(doc_id, index)`` 决定，两代就会算出同一个值并撞唯一约束。

    代次入 id 还顺带带来两个性质：

    * **检索无歧义**：id 全局唯一，回表时命中的 id 只对应一行，不会因两代共存
      而取错内容；
    * **同配置重跑幂等**：同一 ``(doc_id, index, epoch)`` 永远得到同一个 id，
      重复处理一份文档不会产生重复向量。

    与 ``app/core/config.py::chunk_epoch`` 的关系：代次字符串只有一个定义处，
    此处只做拼接。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}_{index}@{epoch}"))


@celery_app.task(name="process_document_task", bind=False)
def process_document_task(doc_id: str, file_path: str, tenant_id: str) -> None:
    session: Session = sessionLocal()
    try:
        doc = session.query(KnowledgeDocument).filter(
            KnowledgeDocument.id == doc_id,
            KnowledgeDocument.tenant_id == tenant_id,
        ).first()
        if not doc:
            logger.warning("Document not found for processing: %s", doc_id)
            return

        kb = session.query(KnowledgeBase).filter(
            KnowledgeBase.id == doc.kb_id,
            KnowledgeBase.tenant_id == tenant_id,
        ).first()
        if not kb:
            logger.warning("Knowledge base not found for document %s", doc_id)
            return

        doc.status = DocumentStatus.PROCESSING
        session.commit()

        # 分段解析 → 段内切分：块的 source_page / heading_path 由所属段直接下发，
        # 归属因此可精确断言（详见 app/utils/document.py 模块说明）。
        segments = DocumentParser.parse_segments(file_path, doc.file_type)
        splitter = TextSplitter()
        chunks = splitter.split_segments(segments)
        if not chunks:
            raise ValidationException("No text chunks were generated from the document")

        epoch = config.chunk_epoch
        # 记录**生效**的分块参数与代次。分块参数来自配置且直接决定块数与向量截断
        # 风险（bge 系列 ``max_seq_length=512``，超长输入会被静默截断），排查
        # 「同一文档块数为何变了」时，这一行是唯一能把结论钉在参数上的证据。
        logger.info(
            f"document={doc.id} chunk_size={splitter.chunk_size} "
            f"chunk_overlap={splitter.chunk_overlap} chunk_epoch={epoch} "
            f"segments={len(segments)} chunks={len(chunks)}"
        )

        embedding_client = get_embedding_client(model=kb.embedding_model)
        embeddings = embedding_client.embed([chunk.text for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise ValidationException("Embedding service returned invalid result shape")

        vector_size = get_vector_size_for_model(kb.embedding_model)
        logger.info(f"vector_size={vector_size}")

        # 是否以混合布局入库。
        # 旧布局（匿名稠密）的库**无法原地升级**——Qdrant 拒绝向匿名集合追加稀疏
        # 向量。因此这里先探测：集合不存在（新建即用新布局）或已回填 → 以混合布局写入；
        # 仍是旧布局 → 继续按稠密写入并告警，**不让一次开关变更把上传链路打断**，
        # 待回填/重建脚本执行完毕自动切换。
        # 集合名一律带灰度指针解析：写入与检索必须用同一个解析，否则会出现
        # 「写进 A 集合、从 B 集合查」且没有任何报错的静默故障。
        collection = collection_name_for(kb.id, kb.active_collection)
        hybrid_ingest = False
        if config.retrieval_hybrid_enabled:
            layout = collection_layout(collection)
            if layout in ("missing", "hybrid"):
                hybrid_ingest = True
            else:
                logger.warning(
                    "Knowledge base %s still uses the legacy dense-only collection; "
                    "writing dense-only until scripts/backfill_hybrid_collection.py runs",
                    kb.id,
                )

        collection_name = get_or_create_collection(
            kb_id=kb.id,
            vector_size=vector_size,
            hybrid=hybrid_ingest,
            active=kb.active_collection,
        )
        qdrant = get_qdrant_client()
        encoder = default_encoder() if hybrid_ingest else None

        # 幂等守卫：同一代次的分块若已存在（重复投递同一任务），先清理再写入。
        # 不清会撞 ``vector_id`` 唯一索引并以 IntegrityError 收场，而那个报错完全
        # 看不出「这是重复投递」。代次相同意味着分块结果必然相同，重写是安全的。
        stale = (
            session.query(KnowledgeChunk)
            .filter(
                KnowledgeChunk.doc_id == doc.id,
                KnowledgeChunk.chunk_epoch == epoch,
            )
            .delete(synchronize_session=False)
        )
        if stale:
            logger.warning(
                "Reprocessing document %s: removed %d existing chunks of epoch %s",
                doc.id, stale, epoch,
            )

        points: List[PointStruct] = []
        created_chunks = []
        for position, chunk in enumerate(chunks):
            # 用**位置**而非 ``chunk.index`` 取嵌入：虽然当前两者恒等（index 由
            # split_segments 顺序生成），但把「嵌入顺序 == 分块顺序」写成显式依赖
            # 更可靠——一旦哪天分块被重排或并行化，错配会是静默的（向量与文本对不上，
            # 检索能跑但答非所问）。
            embedding = embeddings[position]
            vector_id = vector_id_for(doc.id, chunk.index, epoch)
            row = KnowledgeChunk(
                tenant_id=tenant_id,
                kb_id=kb.id,
                doc_id=doc.id,
                content=chunk.text,
                chunk_index=chunk.index,
                # ``chunk_type`` 必须在这里落库，且必须经 ``chunk_type_for`` 映射：
                # 该列是前端选择渲染方式的唯一依据（表格按列渲染、代码保换行），
                # 而 ``chunk.kind`` 是解析层的内部标识，取值域含 ``toc`` /
                # ``caption`` / ``list_item`` 等对显示无意义的值。直接透传会让这些
                # 值静默入库——列是 ``String(16)``，不会拒绝它们，但前端从未适配过。
                chunk_type=chunk_type_for(chunk.kind),
                source_page=chunk.page,
                source_page_end=chunk.page_end,
                heading_path=chunk.heading_path,
                heading_path_mixed=chunk.heading_path_mixed,
                vector_id=vector_id,
                chunk_epoch=epoch,
            )
            session.add(row)
            created_chunks.append(row)
            if encoder is not None:
                # 稀疏向量由分块原文**确定性推导**，无需额外模型推理，
                # 因此不会给入库链路引入新的外部依赖或显著延迟。
                sparse_indices, sparse_values = encoder.document_vector(chunk.text)
                vector = hybrid_point_vector(embedding, sparse_indices, sparse_values)
            else:
                vector = embedding
            points.append(
                PointStruct(
                    id=vector_id,
                    vector={
                        NAMED_DENSE_VECTOR: vector
                    },
                    # payload 刻意只保留这四个键：页码/标题已落在 MySQL 列上，而检索
                    # 必须回表取 ``content``，加一份 payload 副本不会省掉任何一次回表，
                    # 只会多出一处需要同步的状态。若将来要做「限定某章节检索」这类
                    # 过滤下推，再加才有依据（见方案 §2.4）。
                    payload={
                        "tenant_id": tenant_id,
                        "kb_id": kb.id,
                        "doc_id": doc.id,
                        "chunk_index": chunk.index,
                    },
                )
            )

        session.flush()
        logger.info(f"point={points[0]}, points={len(points)}, output_vector_size={len(embeddings[0])}")
        qdrant.upsert(collection_name=collection_name, points=points)

        # 不存储完整原文到数据库（已通过 file_url 存储在磁盘，分块内容存于 chunks 表）
        # doc.original_content = text  # 注释掉，避免大文件超过数据库字段限制
        doc.chunk_count = len(created_chunks)
        # 记录「当前代」：重建期间新旧两代分块行会共存，分块列表与计数都以它为准。
        doc.active_chunk_epoch = epoch
        doc.status = DocumentStatus.COMPLETED
        doc.processed_at = datetime.utcnow()
        # 库计数**重算**而非累加。累加在两处必然漂移：同一代次被重复投递时，
        # 上面的幂等守卫已删掉旧行，累加会把同一批分块算两次；跨代重建时旧代行
        # 仍在表中，累加会把两代都算上。两者都只表现为「数字偏大」，不报错。
        # 重算后与分块列表接口同口径（当前代 + 文档存活），计数与列表长度恒等。
        kb.chunk_count = KnowledgeChunkRepository(
            session, tenant_id
        ).count_live_by_kb(kb.id)

        session.commit()
    except Exception as exc:
        logger.exception("Knowledge document processing failed: %s", exc)
        session.rollback()
        try:
            doc = session.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(exc)
                session.add(doc)
                session.commit()
        except Exception:
            session.rollback()
    finally:
        session.close()
