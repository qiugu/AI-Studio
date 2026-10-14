import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "p2_permission_metadata.py"


def _load():
    spec = importlib.util.spec_from_file_location("p2_permission_metadata", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_permission_metadata_migration_adds_and_backfills_catalog_fields():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255)),
    )
    sa.Table(
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.Column("permission_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, resource, action, description) "
                "VALUES ('p-platform', 'platform', 'tenant_provision', 'old')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, resource, action, description) "
                "VALUES ('p-platform-duplicate', 'platform', 'tenant_provision', 'duplicate')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES ('role-a', 'p-platform-duplicate')"
            )
        )

    module = _load()
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original_op

    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT scope, sensitivity, is_delegable FROM permissions "
                "WHERE id='p-platform'"
            )
        ).one()
        binding = connection.execute(
            sa.text(
                "SELECT permission_id FROM role_permissions WHERE role_id='role-a'"
            )
        ).scalar_one()
        unique_index = next(
            index
            for index in sa.inspect(connection).get_indexes("permissions")
            if index["name"] == "uq_permissions_resource_action"
        )
    assert row == ("platform", "critical", False)
    assert binding == "p-platform"
    assert unique_index["unique"] == 1
