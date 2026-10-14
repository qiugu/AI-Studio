"""S5：knowledge_chunks 增加 chunk_type 列

块类型（``text`` / ``table`` / ``code`` / ``title``）由解析层识别，入库后用于
前端差异化展示与检索装配层 ``[表格]`` / ``[代码]`` 标记。

历史分块行没有该列：列设 ``NOT NULL`` + ``server_default='text'``，并在升级时把
存量行统一回填为 ``text``（既有的旧代次分块本就是纯文本），避免「未设置」与
「正文」不可区分导致的误标。
"""
from alembic import op
import sqlalchemy as sa


revision = "k6l7m8n9o0p2"
# 接在真实链头 k5l6m7n8o9p1（P3 的 chunk 区间/混合标题迁移）之后，形成单链；
# 旧值 j4k5l6m7n8o9 会让本迁移与 k5l6m7n8o9p1 并列为双 head，``alembic upgrade head``
# 会拒绝执行。
down_revision = "k5l6m7n8o9p1"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """检查列是否存在，使本迁移可幂等重跑（MySQL DDL 非事务，失败可能已部分生效）。"""
    bind = op.get_bind()
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not _has_column("knowledge_chunks", "chunk_type"):
        op.add_column(
            "knowledge_chunks",
                sa.Column(
                "chunk_type",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'text'"),
            ),
        )
        # 存量行回填为 text（旧代次分块均为纯文本；新代次由重建脚本写入真实类型）。
        op.execute(
            sa.text("UPDATE knowledge_chunks SET chunk_type = 'text' WHERE chunk_type IS NULL")
        )


def downgrade() -> None:
    if _has_column("knowledge_chunks", "chunk_type"):
        op.drop_column("knowledge_chunks", "chunk_type")
