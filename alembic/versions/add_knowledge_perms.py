"""add knowledge base permissions

Revision ID: add_knowledge_perms
Revises: 3ddd2b3263c9
Create Date: 2026-06-22 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_knowledge_perms'
down_revision = '3ddd2b3263c9'
branch_labels = None
depends_on = None


def upgrade():
    """添加知识库权限"""
    # 插入知识库相关的权限
    op.execute("""
        INSERT INTO permissions (resource, action, description, created_at)
        VALUES
        ('knowledge', 'create', '创建知识库', NOW()),
        ('knowledge', 'read', '查看知识库', NOW()),
        ('knowledge', 'update', '编辑知识库', NOW()),
        ('knowledge', 'delete', '删除知识库', NOW()),
        ('knowledge', 'upload', '上传文档', NOW())
        ON DUPLICATE KEY UPDATE description=VALUES(description)
    """)


def downgrade():
    """移除知识库权限"""
    op.execute("""
        DELETE FROM permissions WHERE resource = 'knowledge'
    """)
