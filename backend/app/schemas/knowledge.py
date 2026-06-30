from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from app.schemas.common import ResponseBase, PaginatedResponse

class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    id: int
    name: str
    description: Optional[str]
    embedding_model: str
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeDocumentResponse(BaseModel):
    """文档响应"""
    id: int
    kb_id: int
    file_name: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: Optional[str]
    processed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeChunkResponse(BaseModel):
    """分块响应"""
    id: int
    content: str
    chunk_index: int
    source_page: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchResult(BaseModel):
    """检索结果"""
    id: int
    content: str
    score: float
    doc_id: int
    doc_name: Optional[str]
    chunk_index: int