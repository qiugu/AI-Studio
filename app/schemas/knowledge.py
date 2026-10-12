from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from app.schemas.common import ResponseBase, PaginatedResponse

class KnowledgeBaseResponse(BaseModel):
    """知识库响应"""
    id: str
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
    id: str
    kb_id: str
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
    """分块响应

    出处升级为**区间 + 粗化标记**（P2 结构组合并的产物）：

    * ``source_page`` / ``source_page_end``：块覆盖页码的闭区间。单页块两者相等；
      非 PDF 两者同为 ``None``。前端显示「第 37–38 页」。
    * ``heading_path_mixed``：``heading_path`` 是否**粗于**实际覆盖范围。为真时
      前端应显示「§A 等小节」，不得断言「本块出自 A」。
    * ``chunk_type``：块类型，取值域见 :data:`app.utils.document.CHUNK_TYPES`
      （``text`` / ``table`` / ``code`` / ``title`` / ``image``）。前端据此选择
      渲染方式——表格需要按列渲染、代码需要保留换行。历史代次的分块行由迁移
      回填为 ``text``，故该字段**永不为空**。
    """
    id: str
    content: str
    chunk_index: int
    chunk_type: str = "text"
    source_page: Optional[int]
    source_page_end: Optional[int]
    heading_path: Optional[str]
    heading_path_mixed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SearchResult(BaseModel):
    """检索结果

    ``source_page`` / ``source_page_end`` / ``heading_path`` / ``heading_path_mixed``
    四键在服务层**恒显式出现**（可能为 ``None``），故此处一并声明，使本 schema 与
    实际响应一致。可得性因格式而异：PDF 有页码无标题路径，md/docx 反之。

    ``llm_content`` / ``context_header`` / ``context_expanded`` 是 P4 上下文装配的
    产物：``llm_content`` 是**应当喂给 LLM 的文本**（出处标记 + 含邻块的窗口），
    ``content`` 仍是块原文，供界面展示与去重。两者分开而非就地改写 ``content``，
    是因为后者同时被当作去重键与展示文本，注入即产生脏数据与重复计数。

    .. note::
       本类目前**未被任何端点引用**（路由直接返回服务层字典）。保留它是为了让响应
       契约有单一可读定义；若继续不接线，应显式删除而不是留成第二份真相。
    """
    id: str
    content: str
    score: float
    doc_id: str
    doc_name: Optional[str]
    chunk_index: int
    #: 块类型（取值域见 :data:`app.utils.document.CHUNK_TYPES`）。与
    #: ``KnowledgeChunkResponse.chunk_type`` 同义，用于让检索结果也能差异化展示
    #: ——命中的如果是表格或代码块，按纯文本渲染会丢掉列结构或换行。
    chunk_type: str = "text"
    source_page: Optional[int] = None
    source_page_end: Optional[int] = None
    heading_path: Optional[str] = None
    heading_path_mixed: bool = False
    llm_content: Optional[str] = None
    context_header: Optional[str] = None
    context_expanded: bool = False
    #: **响应内编号**（该次响应数组下标 + 1），仅在该次响应内有效。
    #:
    #: 与 Agent 侧 ``Citation.marker``（**轮次内编号**，跨工具调用单调递增并按
    #: ``chunk_id`` 去重）是两套作用域，数值可能不同，不可互换使用。
    marker: Optional[int] = None
