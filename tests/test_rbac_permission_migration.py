import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "o3_rbac_permission_catalog.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("o3_rbac_permission_catalog", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(engine):
    module = _load_migration()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original_op


def _create_schema(engine):
    metadata = sa.MetaData()
    sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255)),
    )
    sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
    )
    sa.Table(
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.Column("permission_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    metadata.create_all(engine)


def test_permission_catalog_migration_is_idempotent_and_grants_admins():
    engine = sa.create_engine("sqlite:///:memory:")
    _create_schema(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO tenants (id) VALUES ('tenant-a')"))
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, tenant_id, code, is_admin) "
                "VALUES ('role-admin', 'tenant-a', 'tenant_admin_tenant-a', 1)"
            )
        )

    _run_upgrade(engine)
    _run_upgrade(engine)

    with engine.connect() as connection:
        permission_count = connection.execute(sa.text("SELECT COUNT(*) FROM permissions")).scalar_one()
        duplicate_keys = connection.execute(
            sa.text(
                "SELECT COUNT(*) - COUNT(DISTINCT resource || '.' || action) "
                "FROM permissions"
            )
        ).scalar_one()
        admin_binding = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE rp.role_id = 'role-admin' AND p.resource = 'agent' AND p.action = 'chat'"
            )
        ).scalar_one()

    assert permission_count >= 50
    assert duplicate_keys == 0
    assert admin_binding == 1
