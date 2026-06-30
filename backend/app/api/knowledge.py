"""知识库 API 路由"""
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.dependencies import get_current_user, require_permission
from app.models.user import User
from app.services.knowledge import KnowledgeBaseService
from app.models.knowledge_document import DocumentStatus
from app.schemas.common import ResponseBase, PaginatedResponse
from app.schemas.knowledge import KnowledgeBaseResponse, KnowledgeDocumentResponse
from app.core.exceptions import AppException
import tempfile
import os

router = APIRouter()

@router.post(
    "/knowledge-bases",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("knowledge", "create"))],
)
async def create_knowledge_base(
    name: str = Query(..., min_length=1, max_length=255),
    description: Optional[str] = Query(None, max_length=500),
    embedding_model: Optional[str] = Query("text-embedding-3-small"),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """创建知识库"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        kb = service.create_knowledge_base(
            name=name,
            description=description,
            embedding_model=embedding_model,
        )
        return ResponseBase.ok(
            data=KnowledgeBaseResponse.model_validate(kb).model_dump()
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get(
    "/knowledge-bases",
    response_model=PaginatedResponse,
)
async def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """列出知识库"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        kbs, total = service.list_knowledge_bases(page=page, page_size=page_size)
        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": [
                    {
                        "id": kb.id,
                        "name": kb.name,
                        "description": kb.description,
                        "embedding_model": kb.embedding_model,
                        "document_count": kb.document_count,
                        "chunk_count": kb.chunk_count,
                        "created_at": kb.created_at.isoformat(),
                        "updated_at": kb.updated_at.isoformat(),
                    }
                    for kb in kbs
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get(
    "/knowledge-bases/{kb_id}",
    response_model=ResponseBase,
)
async def get_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取知识库详情"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        kb = service.get_knowledge_base(kb_id)
        return ResponseBase.ok(
            data=KnowledgeBaseResponse.model_validate(kb).model_dump()
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.put(
    "/knowledge-bases/{kb_id}",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("knowledge", "update"))],
)
async def update_knowledge_base(
    kb_id: int,
    name: Optional[str] = Query(None, min_length=1, max_length=255),
    description: Optional[str] = Query(None, max_length=500),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """更新知识库"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        kb = service.update_knowledge_base(kb_id=kb_id, name=name, description=description)
        return ResponseBase.ok(
            data=KnowledgeBaseResponse.model_validate(kb).model_dump()
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete(
    "/knowledge-bases/{kb_id}",
    dependencies=[Depends(require_permission("knowledge", "delete"))],
)
async def delete_knowledge_base(
    kb_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除知识库"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        service.delete_knowledge_base(kb_id)
        return {"code": 0, "message": "success", "data": None}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ── 文档 API ─────────────────────────────────────────────────────────────────

@router.post(
    "/knowledge-bases/{kb_id}/documents/upload",
    response_model=ResponseBase,
    dependencies=[Depends(require_permission("knowledge", "upload"))],
)
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """上传文档"""
    try:
        # 验证文件类型
        valid_types = ["txt", "pdf", "docx", "md"]
        file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        if file_ext not in valid_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type: {file_ext}",
            )

        # 保存临时文件
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
            doc = service.upload_document(
                kb_id=kb_id,
                file_path=tmp_path,
                file_name=file.filename,
                file_type=file_ext,
            )
            return ResponseBase.ok(
                data=KnowledgeDocumentResponse.model_validate(doc).model_dump()
            )
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass

    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=PaginatedResponse,
)
async def list_documents(
    kb_id: int,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """列出知识库的文档"""
    try:
        doc_status = None
        if status:
            try:
                doc_status = DocumentStatus(status)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status}",
                )

        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        docs, total = service.list_documents(
            kb_id=kb_id,
            status=doc_status,
            page=page,
            page_size=page_size,
        )
        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": [
                    {
                        "id": doc.id,
                        "kb_id": doc.kb_id,
                        "file_name": doc.file_name,
                        "file_type": doc.file_type,
                        "file_size": doc.file_size,
                        "status": doc.status.value,
                        "chunk_count": doc.chunk_count,
                        "error_message": doc.error_message,
                        "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
                        "created_at": doc.created_at.isoformat(),
                    }
                    for doc in docs
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.get(
    "/documents/{doc_id}",
    response_model=ResponseBase,
)
async def get_document(
    doc_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取文档详情"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        doc = service.get_document(doc_id)
        return ResponseBase.ok(
            data=KnowledgeDocumentResponse.model_validate(doc).model_dump()
        )
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete(
    "/documents/{doc_id}",
    dependencies=[Depends(require_permission("knowledge", "delete"))],
)
async def delete_document(
    doc_id: int,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """删除文档"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        service.delete_document(doc_id)
        return {"code": 0, "message": "success", "data": None}
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ── 分块 API ─────────────────────────────────────────────────────────────────

@router.get(
    "/documents/{doc_id}/chunks",
    response_model=PaginatedResponse,
)
async def get_document_chunks(
    doc_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """获取文档的分块列表"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        chunks, total = service.get_chunks(doc_id=doc_id, page=page, page_size=page_size)
        return {
            "code": 0,
            "message": "success",
            "data": {
                "items": [
                    {
                        "id": chunk.id,
                        "content": chunk.content,
                        "chunk_index": chunk.chunk_index,
                        "source_page": chunk.source_page,
                        "created_at": chunk.created_at.isoformat(),
                    }
                    for chunk in chunks
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ── 向量检索 API ─────────────────────────────────────────────────────────────

@router.post(
    "/knowledge-bases/{kb_id}/search",
)
async def search_knowledge_base(
    kb_id: int,
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=50),
    score_threshold: float = Query(0.5, ge=0.0, le=1.0),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """检索知识库"""
    try:
        service = KnowledgeBaseService(db=db, tenant_id=current_user.tenant_id)
        results = service.search(
            kb_id=kb_id,
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        return {
            "code": 0,
            "message": "success",
            "data": results,
        }
    except AppException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
