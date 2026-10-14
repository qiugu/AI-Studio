"""注册重设计（方案 B）：显式租户 owner + 邮箱验证 + 显式管理员角色

一次迁移完成三件事（对应 docs/register-owner-redesign-plan.md 阶段 1）：

1. ``users.email_verified``——新增，默认未验证；**存量用户回填为已验证**（他们注册时
   本就处于活跃态，不能因新功能被锁死登录）。
2. ``tenants.owner_id``——新增，指向创建者；**存量租户回填**：取该租户持有
   ``tenant_admin`` 角色的用户（无则留空）。
3. ``roles.is_admin``——新增，显式声明管理员角色；**存量 ``tenant_admin`` 角色回填为
   True**。以此替代前后端 ``'admin' in role.code`` 的字符串匹配。
4. ``email_verifications``——新增令牌表，支撑邮箱验证流程。

幂等性：MySQL DDL 非事务，失败可能已部分生效，故所有 DDL 均先 ``_has_*`` 探测再执行；
数据回填均带 ``WHERE`` 条件，可安全重跑。

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "j4k5l6m7n8o9"
down_revision = "i3j4k5l6m7n8"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {c["name"] for c in inspect(bind).get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    bind = op.get_bind()
    return name in {i["name"] for i in inspect(bind).get_indexes(table)}


def _has_fk(table: str, name: str) -> bool:
    bind = op.get_bind()
    return name in {fk["name"] for fk in inspect(bind).get_foreign_keys(table)}


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return name in inspect(bind).get_table_names()


def upgrade() -> None:
    # 1) users.email_verified
    if not _has_column("users", "email_verified"):
        op.add_column(
            "users",
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    # 存量用户视为已验证，避免新功能锁死既有登录
    op.execute(sa.text("UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE"))

    # 2) tenants.owner_id（可空，指向创建者）
    if not _has_column("tenants", "owner_id"):
        op.add_column(
            "tenants",
            sa.Column("owner_id", sa.String(length=36), nullable=True),
        )
    if not _has_index("tenants", "ix_tenants_owner_id"):
        op.create_index("ix_tenants_owner_id", "tenants", ["owner_id"], unique=False)
    if not _has_fk("tenants", "fk_tenants_owner_id"):
        op.create_foreign_key(
            "fk_tenants_owner_id", "tenants", "users", ["owner_id"], ["id"]
        )
    # 存量回填：取租户内持有 tenant_admin 角色的用户（多取其一）
    op.execute(
        sa.text(
            "UPDATE tenants t SET t.owner_id = ("
            "SELECT ur.user_id FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE r.tenant_id = t.id AND r.code LIKE 'tenant_admin%' "
            "LIMIT 1"
            ") WHERE t.owner_id IS NULL"
        )
    )

    # 3) roles.is_admin
    if not _has_column("roles", "is_admin"):
        op.add_column(
            "roles",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.execute(
        sa.text(
            "UPDATE roles SET is_admin = TRUE WHERE code LIKE 'tenant_admin%' AND is_admin = FALSE"
        )
    )

    # 4) email_verifications 表
    if not _has_table("email_verifications"):
        op.create_table(
            "email_verifications",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.Index("ix_email_verifications_user_id", "user_id"),
        )


def downgrade() -> None:
    if _has_table("email_verifications"):
        op.drop_table("email_verifications")

    if _has_column("roles", "is_admin"):
        op.drop_column("roles", "is_admin")

    if _has_fk("tenants", "fk_tenants_owner_id"):
        op.drop_constraint("fk_tenants_owner_id", "tenants", type_="foreignkey")
    if _has_index("tenants", "ix_tenants_owner_id"):
        op.drop_index("ix_tenants_owner_id", table_name="tenants")
    if _has_column("tenants", "owner_id"):
        op.drop_column("tenants", "owner_id")

    if _has_column("users", "email_verified"):
        op.drop_column("users", "email_verified")
