from typing import Optional, List

from sqlalchemy.orm import Session, contains_eager
from sqlalchemy import and_, func

from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.repositories.base import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    """知识库 Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeBase, db, tenant_id)

    def get_by_id_including_deleted(self, kb_id: str) -> Optional[KnowledgeBase]:
        """按 ID 取知识库，**不过滤软删**

        为什么需要：删除文档时要维护所属知识库的计数，而该知识库可能已经被软删
        （历史数据与异常路径都会留下这种状态）。若沿用过 ``get_by_id``，知识库不可见
        会让校验直接失败，其文档就再也无法通过任何接口清理。

        仅限**回收 / 审计**路径使用，不可用于对外读取——对外读取必须看不到软删知识库。
        """
        return self.db.query(KnowledgeBase).filter(
            and_(
                KnowledgeBase.tenant_id == self.tenant_id,
                KnowledgeBase.id == kb_id,
            )
        ).first()


class KnowledgeDocumentRepository(BaseRepository[KnowledgeDocument]):
    """知识库文档 Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeDocument, db, tenant_id)

    def list_by_kb(
        self,
        kb_id: str,
        status: Optional[DocumentStatus] = None,
        page: int = 1,
        page_size: int = 10,
        order_by: Optional[str] = 'created_at desc',
    ) -> List[KnowledgeDocument]:
        """按知识库ID查询文档"""
        query = self.db.query(KnowledgeDocument).filter(
            and_(
                KnowledgeDocument.tenant_id == self.tenant_id,
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).order_by(KnowledgeDocument.created_at.desc())
        if status:
            query = query.filter(KnowledgeDocument.status == status)
        
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_kb(self, kb_id: str, status: Optional[DocumentStatus] = None) -> int:
        """统计知识库中的文档数"""
        query = self.db.query(KnowledgeDocument).filter(
            and_(
                KnowledgeDocument.tenant_id == self.tenant_id,
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
        if status:
            query = query.filter(KnowledgeDocument.status == status)
        return query.count()

    def list_all_by_kb(self, kb_id: str) -> List[KnowledgeDocument]:
        """取出知识库下**全部**存活文档，不分页

        删除知识库时必须一次拿到全部文档才能完成级联回收；沿用 ``list_by_kb``
        会受 ``page_size`` 上限截断，导致「删了库、只回收了第一页的文档」——
        这种部分成功既不会报错，也难以在事后发现。
        """
        return self.db.query(KnowledgeDocument).filter(
            and_(
                KnowledgeDocument.tenant_id == self.tenant_id,
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).all()


class KnowledgeChunkRepository(BaseRepository[KnowledgeChunk]):
    """知识库分块 Repository"""

    def __init__(self, db: Session, tenant_id: str):
        super().__init__(KnowledgeChunk, db, tenant_id)

    def _query_with_live_document(self, *extra_conditions):
        """构造「所属文档存活」的分块查询，附加条件一次传入

        **文档级判定是分块可见性的唯一权威**：``knowledge_chunks`` 已取消软删列
        （分块是派生数据，删除即物理删除，理由见模型注释），因此「已下架内容不得被
        检索命中」完全由这里承担。写入侧的级联删除只对修复之后发生的删除有效，
        历史数据与任何异常路径都会留下「文档已软删、分块残留、向量在库」的状态——
        读取侧自带该判定后，就不再依赖写入侧的历史正确性（P1-A）。

        三个实现细节都是有意的：

        * ``join`` 用 **INNER JOIN**——没有对应文档行的孤儿分块（文档被硬删而分块
          残留）不应被任何调用方读到，直接由连接条件排除，而不是留给上层判断。
        * 用 ``contains_eager`` 而非 ``joinedload``——查询已显式 join 文档表，
          若再让 eager load 生成第二个 join，会得到一条冗余的重复 join。
        * 附加条件**并入同一次 ``filter``**——分散成多次 ``filter`` 在语义上等价，
          但会让「这个查询到底过滤了什么」需要跨多层调用链才能读出，测试与后续
          修改都容易漏掉其中一层。

        同时约束文档的 ``tenant_id``：分块与文档理论上同租户，但显式约束可避免
        数据异常时跨租户内容随文档名一并泄漏。
        """
        return (
            self.db.query(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.doc_id)
            .options(contains_eager(KnowledgeChunk.document))
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeDocument.tenant_id == self.tenant_id,
                    KnowledgeDocument.deleted_at.is_(None),
                    *extra_conditions,
                )
            )
        )

    def list_by_document(
        self,
        doc_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> List[KnowledgeChunk]:
        """按文档ID查询分块（**仅当前代**）

        代次过滤刻意写成 ``chunk_epoch == document.active_chunk_epoch`` 而不是拿
        配置值比对：重建期间新旧两代分块行会同时存活，只有文档上那一列才是
        「这份文档现在该看哪一代」的权威记录。用 ``config.chunk_epoch`` 会让刚
        改过配置、尚未重建的文档**静默返回空列表**。
        """
        query = self._query_with_live_document(
            KnowledgeChunk.doc_id == doc_id,
            KnowledgeChunk.chunk_epoch == KnowledgeDocument.active_chunk_epoch,
        )
        offset = (page - 1) * page_size
        return query.offset(offset).limit(page_size).all()

    def count_by_document(self, doc_id: str) -> int:
        """统计文档中当前代的分块数"""
        return self._query_with_live_document(
            KnowledgeChunk.doc_id == doc_id,
            KnowledgeChunk.chunk_epoch == KnowledgeDocument.active_chunk_epoch,
        ).count()

    def count_live_by_kb(self, kb_id: str) -> int:
        """知识库的**当前代存活分块数**

        ``knowledge_bases.chunk_count`` 的唯一权威口径：与分块列表接口（同为
        「当前代 + 文档存活」）逐行一致，因此「计数 == 列表长度」是一条不需要
        额外维护的恒等式，而不是一个需要两侧分别记着更新的缓存。

        **为什么必须提供这个方法**：写入侧曾经用 ``+ len(new_chunks)`` 累加，
        在同一代次被重复投递（幂等守卫先删旧行）或跨代重建（旧代行仍在表中）时
        都会漂移，而漂移只体现为一个偏大的数字，没有任何报错。仓库作为「按口径
        取数」的单一定义处，让写入侧、重建脚本与修复脚本共用同一段 SQL 语义。
        """
        return (
            self.db.query(func.count(KnowledgeChunk.id))
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.doc_id)
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeDocument.tenant_id == self.tenant_id,
                    KnowledgeDocument.deleted_at.is_(None),
                    KnowledgeChunk.kb_id == kb_id,
                    KnowledgeChunk.chunk_epoch == KnowledgeDocument.active_chunk_epoch,
                )
            )
            .scalar()
            or 0
        )

    def get_by_vector_id(self, vector_id: str) -> Optional[KnowledgeChunk]:
        """按 Qdrant vector_id 查询单个分块

        注意三点，缺一即产生越权或内容泄漏：

        * 必须带 ``tenant_id`` 过滤，否则可能读到其他租户的分块；
        * 必须经由 :meth:`_query_with_live_document`，否则「文档已软删、分块残留」
          的历史数据会被照常返回（P1-A）；
        * **刻意不加代次过滤**。``vector_id`` 全局唯一（且带代次后缀），命中的
          id 本身就唯一确定了是哪一代；若在此按 ``active_chunk_epoch`` 过滤，
          一旦把 ``active_collection`` 回滚到旧集合，旧代 id 就会全部查不到内容，
          **回滚等于把检索打断**。
        """
        return (
            self._query_with_live_document(KnowledgeChunk.vector_id == vector_id)
            .first()
        )

    def list_by_vector_ids(self, vector_ids: List[str]) -> List[KnowledgeChunk]:
        """按一组 Qdrant vector_id 批量查询分块

        检索回表时使用，避免逐条 get_by_vector_id 造成的 N+1 查询；
        同时预加载 document 关系，供结果中回填文档名。

        **本方法是检索结果进入回答上下文的唯一闸门**（REST / Agent 工具 / 工作流
        节点都经由它），因此文档级的软删过滤必须在这里生效，而不是在各调用方
        各写一遍——后者必然漏掉某一条路径（P1-A 正是如此发生的）。
        代次过滤的理由同 :meth:`get_by_vector_id`：加了反而会让回归旧集合的
        回滚路径失效。
        """
        if not vector_ids:
            return []
        return self._query_with_live_document(
            KnowledgeChunk.vector_id.in_(vector_ids)
        ).all()

    def list_neighbors(
        self,
        doc_id: str,
        chunk_epoch: str,
        chunk_indexes: List[int],
    ) -> List[KnowledgeChunk]:
        """按「文档 + 代次 + chunk_index 集合」批量查询分块（邻块扩展用）

        检索命中块后需要把它前后的邻块一并取出（P4「答案跨块」的修复手段），
        本方法把「每个命中块查一次」收敛为「每个 (文档, 代次) 查一次」——
        top_k=10 且这些命中各自请求 ±1 邻块时，逐条查询会产生 30 次往返。

        **代次由调用方按命中块自身给出，而不是取 ``document.active_chunk_epoch``**：
        与 :meth:`get_by_vector_id` 同一理由——回滚 ``active_collection`` 到旧集合
        后，命中块属于旧代，若此处按「文档当前代」过滤就会一条邻块都取不到，邻块
        扩展在回滚期间静默失效（不报错，只是窗口退化成单块）。以命中块自述的代次
        为准则与检索结果自洽。

        仍经 :meth:`_query_with_live_document`：邻块扩展是**注入 LLM 上下文**的
        路径，已软删文档的分块绝不能从这里漏出去，否则「删了文档却还能被引用到」
        会以「邻块」这种隐蔽形式重现（P1-A）。
        """
        if not chunk_indexes:
            return []
        return (
            self._query_with_live_document(
                KnowledgeChunk.doc_id == doc_id,
                KnowledgeChunk.chunk_epoch == chunk_epoch,
                KnowledgeChunk.chunk_index.in_(chunk_indexes),
            )
            .order_by(KnowledgeChunk.chunk_index)
            .all()
        )

    def list_by_doc_id(self, doc_id: str) -> List[KnowledgeChunk]:
        """查询指定文档下的**全部代次**分块（用于清理向量等场景）

        两处刻意为之：

        * **不**加文档级过滤：本方法的用途是「把某文档的分块找出来清理」，
          若文档已软删就查不到分块，向量清理会静默跳过并留下孤儿向量。
        * **不**加代次过滤：重建窗口内两代分块各自对应**不同集合**里的向量，
          只取当前代会把旧集合里的向量漏成孤儿。

        即这里需要的是「按 doc_id 全量取」，而非「可对外服务的内容」。
        """
        return self.db.query(KnowledgeChunk).filter(
            and_(
                KnowledgeChunk.tenant_id == self.tenant_id,
                KnowledgeChunk.doc_id == doc_id,
            )
        ).all()

    def delete_by_doc_id(self, doc_id: str) -> int:
        """**物理删除**指定文档下的全部分块，返回删除行数

        与 ``deleted_at`` 时代的关键差别：这是真删除，``vector_id`` 唯一索引随之
        释放，因此重建沿用同一 ``doc.id`` 与序号也不会再撞约束。

        **为什么删除必须级联到分块**：检索回表（``list_by_vector_ids``）只认
        「文档存活」，但分块行若残留，其 ``vector_id`` 会一直被占着，且孤儿行会
        让「某文档有多少分块」这类统计持续偏离事实。写入侧对齐后，读取侧就不再
        是唯一防线。

        不在此处 ``commit``：删除知识库需要在一个事务内回收其全部文档，逐份提交
        会产生「部分成功」的中间状态，且失败后难以判断回收到了哪一份。
        """
        return (
            self.db.query(KnowledgeChunk)
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeChunk.doc_id == doc_id,
                )
            )
            .delete(synchronize_session=False)
        )

    def delete_superseded_by_doc_id(self, doc_id: str, keep_epoch: str) -> int:
        """回收指定文档下**非当前代**的分块行，返回删除行数

        旧代行在重建的校验期内必须保留（``active_collection`` 一指回旧集合，检索
        命中的就是旧代 id），因此不能与 cutover 同时删；本方法供校验窗口关闭后
        显式回收，避免「一次重建永久留下 2 倍行数」。
        """
        return (
            self.db.query(KnowledgeChunk)
            .filter(
                and_(
                    KnowledgeChunk.tenant_id == self.tenant_id,
                    KnowledgeChunk.doc_id == doc_id,
                    KnowledgeChunk.chunk_epoch != keep_epoch,
                )
            )
            .delete(synchronize_session=False)
        )

