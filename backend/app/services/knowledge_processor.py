import logging
import uuid
from datetime import datetime
from typing import List

from qdrant_client.models import PointStruct
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.database import sessionLocal
from app.core.exceptions import ValidationException
from app.core.vector_db import (
    get_or_create_collection,
    get_qdrant_client,
    get_vector_size_for_model,
)
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_document import KnowledgeDocument, DocumentStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.utils.document import DocumentParser, TextSplitter
from app.utils.embedding import get_embedding_client

logger = logging.getLogger(__name__)


@celery_app.task(name="process_document_task", bind=False)
def process_document_task(doc_id: int, file_path: str, tenant_id: int) -> None:
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

        text = DocumentParser.parse(file_path, doc.file_type)
        if not text or not text.strip():
            raise ValidationException("Document contains no usable text")

        chunks = TextSplitter().split(text)
        if not chunks:
            raise ValidationException("No text chunks were generated from the document")

        embedding_client = get_embedding_client(model=kb.embedding_model)
        embeddings = embedding_client.embed(chunks)
        if len(embeddings) != len(chunks):
            raise ValidationException("Embedding service returned invalid result shape")

        vector_size = get_vector_size_for_model(kb.embedding_model)
        logger.info(f"vector_size={vector_size}")
        collection_name = get_or_create_collection(kb_id=kb.id, vector_size=vector_size)
        qdrant = get_qdrant_client()

        points: List[PointStruct] = []
        created_chunks = []
        for index, (content, embedding) in enumerate(zip(chunks, embeddings)):
            vector_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc.id}_{index}"))
            chunk = KnowledgeChunk(
                tenant_id=tenant_id,
                kb_id=kb.id,
                doc_id=doc.id,
                content=content,
                chunk_index=index,
                source_page=None,
                vector_id=vector_id,
            )
            session.add(chunk)
            created_chunks.append(chunk)
            points.append(
                PointStruct(
                    id=vector_id,
                    vector=embedding,
                    payload={
                        "tenant_id": tenant_id,
                        "kb_id": kb.id,
                        "doc_id": doc.id,
                        "chunk_index": index,
                    },
                )
            )

        session.flush()
        logger.info(f"points={len(points)}, output_vector_size={len(embeddings[0])}")
        qdrant.upsert(collection_name=collection_name, points=points)

        # 不存储完整原文到数据库（已通过 file_url 存储在磁盘，分块内容存于 chunks 表）
        # doc.original_content = text  # 注释掉，避免大文件超过数据库字段限制
        doc.chunk_count = len(created_chunks)
        doc.status = DocumentStatus.COMPLETED
        doc.processed_at = datetime.utcnow()
        kb.chunk_count = (kb.chunk_count or 0) + len(created_chunks)

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
