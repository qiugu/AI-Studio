"""引用溯源：messages 增加 citations 列

承载「知识库检索命中块」的结构化引用快照（文档名 / 页码 / 小节 / 命中块原文等，
见 docs/citation-traceability.md §5.1），供前端「角标 + 来源卡片」回溯到具体分块，
并在会话重新打开后持久化（G3）。

列设为 ``JSON`` + ``nullable=True``：无引用时为 NULL（而非空数组），与既有
``tool_calls`` 列风格一致；引用对象结构自包含，不依赖存活的分块行，故分块代次
重建（chunk_id 失效）后仍可展示快照（R1 降级）。

幂等：MySQL DDL 非事务，迁移失败可能已部分生效，故先探列再添加，可安全重跑。
"""
from alembic import op
import sqlalchemy as sa


revision = "l7m8n9o0p1q2"
# 接在真实链头 k6l7m8n9o0p2（S5 的 chunk_type 迁移）之后，形成单链。
down_revision = "k6l7m8n9o0p2"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """检查列是否存在，使本迁移可幂等重跑（MySQL DDL 非事务，失败可能已部分生效）。"""
    bind = op.get_bind()
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not _has_column("messages", "citations"):
        op.add_column(
            "messages",
            sa.Column("citations", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("messages", "citations"):
        op.drop_column("messages", "citations")
