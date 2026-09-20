"""为 knowledge_chunks.heading_path_mixed 补 server_default

该列在 phase5 以「NOT NULL + 默认 False」的语义引入，但当时迁移只写了
``nullable=False``，漏了 ``server_default``。ORM 层用 ``default=False``（Python 侧）
兜底，ORM 插入不受影响；但 **Core 批量插入**（rebuild 脚本、或任何 omit 该列的
写入路径）不会带 Python 默认值，而列又无 DB 默认 → MySQL 1364
（``Field 'heading_path_mixed' doesn't have a default value'``）。

本迁移补 ``server_default false``，与 ``chunk_type``（已带 ``server_default 'text'``）
对齐，使该列在任意写入路径下自洽，避免「容器代码比模型旧」这类脱节再次触发 1364。
"""
from alembic import op
import sqlalchemy as sa


revision = "k6l7m8n9o0p3"
# 线性接在 l7m8n9o0p1q2（message_citations）之后；二者同以 k6l7m8n9o0p2 为父，
# 必须串成单链，否则 ``alembic upgrade head`` 会因多 head 拒绝执行。
down_revision = "l7m8n9o0p1q2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_chunks",
        "heading_path_mixed",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("0"),
    )


def downgrade() -> None:
    op.alter_column(
        "knowledge_chunks",
        "heading_path_mixed",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=None,
    )
