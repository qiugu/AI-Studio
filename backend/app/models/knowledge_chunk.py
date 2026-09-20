from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, func, ForeignKey, LargeBinary
import sqlalchemy as sa
from sqlalchemy.orm import mapped_column, Mapped, relationship
from datetime import datetime
import uuid

from app.core.config import config
from app.core.database import Base


class KnowledgeChunk(Base):
    """知识库文档分块（文本片段）

    **本表刻意没有 ``deleted_at``（无软删除）**，插入与删除都是物理操作。

    分块是**派生数据**：它是「上传原件 + 解析器 + 分块参数 + 嵌入模型」的确定性
    函数，重算即可得，不属于软删的适用对象（软删是为**不可再生**数据保留追溯能力）。
    在本表的语境下软删还有三个具体代价：

    1. **软删语义自相矛盾**：删除文档时 Qdrant 侧的点是被硬删的，MySQL 行却标记为
       「已软删」——该行既不可恢复（向量已不存在）又不可检索，只剩墓碑；
    2. **占死唯一索引**：``vector_id`` 上有唯一索引，软删不释放该值。实测 1206 行中
       905 行为墓碑（占 3/4），使「重建时沿用同一 ``doc.id`` 与序号」必然撞唯一约束；
    3. **要求每处读取都记得过滤**：``deleted_at IS NULL`` 一旦漏写，已下架内容就会
       被检索命中并进入回答上下文（本项目 P1-A / D9 两次事故的成因）。
       列不存在后，这类漏写在构造上不可能发生。

    删除文档时的级联清理改为物理删除；「文档是否下架」的权威判定在
    ``KnowledgeDocument.deleted_at``（读取侧 ``_query_with_live_document`` 的
    INNER JOIN 会排除已软删文档的分块），因此去掉分块级软删不会削弱下架语义。
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kb_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(String(36), ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    
    # 分块内容与元数据
    content = Column(Text, nullable=False)  # 分块文本
    chunk_index = Column(Integer, nullable=False)  # 在文档中的序号（从0开始）
    source_page = Column(Integer, nullable=True)  # 覆盖页码的**起始页**（PDF）；非 PDF 恒为 None
    source_page_end = Column(Integer, nullable=True)  # 覆盖页码的**结束页**；单页块与 source_page 相同
    heading_path = Column(String(512), nullable=True)  # 标题路径（md/docx）；PDF 恒为 None
    # ``heading_path`` 是否**粗于**本块的实际覆盖范围（见 app/utils/document.py::TextChunk）。
    # 为 True 表示本块只覆盖了若干兄弟子节、而 heading_path 只能标到它们的公共祖先，
    # 前端应呈现为「A 等小节」。NOT NULL + 默认 False：三态会让「未设置」与
    # 「精确」不可区分，而库中绝大多数行本来就是精确的。
    heading_path_mixed = Column(Boolean, nullable=False, default=False, server_default=sa.text("0"))

    # 块类型（S5 引入）：``text`` / ``table`` / ``code`` / ``title``，源自解析层
    # :class:`app.utils.document.TextChunk.kind`。用途有二：① 前端差异化展示
    # （表格渲染、代码高亮、标题锚点）；② 检索装配层据此给 ``llm_content`` 前缀
    # ``[表格]`` / ``[代码]`` 标记（沿用 P4 三键契约，不改 ``content``）。
    # NOT NULL + 默认 ``text``：历史分块行没有该列，迁移统一补 ``text``，
    # 且「未设置」与「正文」不可区分会带来误标，故不接受 NULL。
    chunk_type = Column(String(16), nullable=False, default="text", server_default="text")

    # 向量ID（指向Qdrant中的point_id）
    # 取值 = uuid5(NAMESPACE_DNS, f"{doc_id}_{chunk_index}@{chunk_epoch}")，
    # 带代次后缀是**必须的**：唯一索引不因换集合而释放，不带后缀时新旧两代
    # 会算出同一个 id 并撞唯一约束（详见 app/core/config.py::chunk_epoch）。
    vector_id = Column(String(255), nullable=True, unique=True)  # Qdrant中的point_id（UUID格式）

    # 分块代次（"448-64-p1" = 尺寸-重叠-策略版本），由 config.chunk_epoch 提供默认值。
    # NOT NULL 且必须可查：重建期间新旧两代分块行同时存活，验收计数
    # （「当前代存活分块数」）与旧代 GC 都依赖它区分。
    chunk_epoch = Column(
        String(32),
        nullable=False,
        default=lambda: config.chunk_epoch,
        index=True,
    )

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 关系
    document = relationship("KnowledgeDocument", back_populates="chunks")
