import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"


def _load(name: str):
    path = VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(engine, module):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original_op


def _run_downgrade(engine, module):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = module.op
        module.op = operations
        try:
            module.downgrade()
        finally:
            module.op = original_op


def test_resource_grant_migration_creates_tenant_scoped_table():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    metadata.create_all(engine)

    _run_upgrade(engine, _load("o5_resource_grants"))

    inspector = sa.inspect(engine)
    assert "resource_grants" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("resource_grants")}
    assert {"tenant_id", "resource_type", "resource_id", "subject_id", "actions"} <= columns


def test_authorization_audit_migration_adds_structured_columns():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "audit_logs",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36)),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    metadata.create_all(engine)

    _run_upgrade(engine, _load("o6_authorization_audit_fields"))

    columns = {column["name"] for column in sa.inspect(engine).get_columns("audit_logs")}
    assert {
        "user_agent",
        "request_id",
        "decision",
        "permission_key",
        "target_type",
        "target_id",
        "reason",
        "metadata",
    } <= columns


def test_ai_model_test_permission_migration_is_idempotent():
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
        "roles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
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
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO roles (id, is_admin) VALUES ('role-admin', 1)")
        )

    module = _load("o7_ai_model_test_permission")
    _run_upgrade(engine, module)
    _run_upgrade(engine, module)

    with engine.connect() as connection:
        permission_id = connection.execute(
            sa.text(
                "SELECT id FROM permissions "
                "WHERE resource='ai_model' AND action='test'"
            )
        ).scalar_one()
        binding_count = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM role_permissions "
                "WHERE role_id='role-admin' AND permission_id=:permission_id"
            ),
            {"permission_id": permission_id},
        ).scalar_one()

    assert binding_count == 1


def test_knowledge_base_creator_migration_adds_nullable_column():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "knowledge_bases",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
    )
    metadata.create_all(engine)

    _run_upgrade(engine, _load("o8_knowledge_base_created_by"))

    columns = {
        column["name"]
        for column in sa.inspect(engine).get_columns("knowledge_bases")
    }
    assert "created_by" in columns
    assert any(
        index["name"] == "ix_knowledge_bases_created_by"
        for index in sa.inspect(engine).get_indexes("knowledge_bases")
    )


def test_authorization_outbox_migration_creates_replayable_event_table():
    engine = sa.create_engine("sqlite:///:memory:")

    _run_upgrade(engine, _load("o9_authorization_outbox"))

    inspector = sa.inspect(engine)
    assert "authorization_outbox" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("authorization_outbox")}
    assert {
        "tenant_id",
        "actor_id",
        "event_type",
        "target_type",
        "target_id",
        "payload",
        "status",
        "attempts",
        "last_error",
        "processed_at",
    } <= columns


def test_tenant_membership_migration_backfills_legacy_users_and_roles():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36)),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "user_roles",
        metadata,
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("role_id", sa.String(36), primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO tenants (id) VALUES ('tenant-a')"))
        connection.execute(
            sa.text(
                "INSERT INTO users (id, tenant_id, status) "
                "VALUES ('user-a', 'tenant-a', 1)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, tenant_id) VALUES ('role-a', 'tenant-a')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO user_roles (user_id, role_id) VALUES ('user-a', 'role-a')"
            )
        )

    _run_upgrade(engine, _load("p1_tenant_memberships"))

    with engine.connect() as connection:
        membership = connection.execute(
            sa.text(
                "SELECT id, tenant_id, user_id, status, is_owner "
                "FROM tenant_memberships"
            )
        ).one()
        assignment = connection.execute(
            sa.text("SELECT membership_id, role_id FROM membership_roles")
        ).one()
    assert membership[1:] == ("tenant-a", "user-a", True, False)
    assert assignment == (membership[0], "role-a")


def test_rbac_migration_rehearsal_covers_backfill_dual_read_and_rollback():
    """Run the RBAC cutover against a sanitized legacy-shaped database.

    This is deliberately independent of the developer database: it proves the
    ordered schema/backfill/rollback contract and compares the staged role
    graph with the legacy graph before a read switch is considered safe.
    """
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "tenants",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36)),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "user_roles",
        metadata,
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
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
        "role_permissions",
        metadata,
        sa.Column("role_id", sa.String(36), nullable=False),
        sa.Column("permission_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.text("INSERT INTO tenants (id, owner_id) VALUES ('tenant-a', 'user-a')")
        )
        connection.execute(
            sa.text("INSERT INTO tenants (id, owner_id) VALUES ('tenant-b', 'user-b')")
        )
        connection.execute(
            sa.text(
                "INSERT INTO users (id, tenant_id, status) VALUES "
                "('user-a', 'tenant-a', 1), ('user-b', 'tenant-b', 1)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, tenant_id) VALUES "
                "('role-a', 'tenant-a'), ('role-b', 'tenant-b')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO user_roles (user_id, role_id) VALUES "
                "('user-a', 'role-a'), ('user-a', 'role-b'), ('user-b', 'role-b')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO permissions (id, resource, action, description) VALUES "
                "('perm-a', 'agent', 'read', 'legacy'), "
                "('perm-platform', 'platform', 'tenant_provision', 'legacy')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES "
                "('role-a', 'perm-a')"
            )
        )

    p1 = _load("p1_tenant_memberships")
    p2 = _load("p2_permission_metadata")
    _run_upgrade(engine, p1)

    with engine.connect() as connection:
        legacy_rows = connection.execute(
            sa.text(
                "SELECT ur.user_id, ur.role_id FROM user_roles ur "
                "JOIN users u ON u.id=ur.user_id "
                "JOIN roles r ON r.id=ur.role_id "
                "WHERE u.tenant_id=r.tenant_id ORDER BY ur.user_id, ur.role_id"
            )
        ).all()
        membership_rows = connection.execute(
            sa.text(
                "SELECT m.user_id, mr.role_id FROM tenant_memberships m "
                "JOIN membership_roles mr ON mr.membership_id=m.id "
                "ORDER BY m.user_id, mr.role_id"
            )
        ).all()
        assert membership_rows == legacy_rows

    _run_upgrade(engine, p2)
    inspector = sa.inspect(engine)
    permission_columns = {column["name"] for column in inspector.get_columns("permissions")}
    assert {"scope", "sensitivity", "is_delegable"} <= permission_columns
    assert any(
        index["name"] == "uq_permissions_resource_action"
        and index["unique"] == 1
        for index in inspector.get_indexes("permissions")
    )

    # Rollback is schema-only and must preserve the legacy graph as the
    # emergency read path; the staged tables/metadata are removed in reverse
    # dependency order.
    _run_downgrade(engine, p2)
    _run_downgrade(engine, p1)
    inspector = sa.inspect(engine)
    assert "tenant_memberships" not in inspector.get_table_names()
    assert "membership_roles" not in inspector.get_table_names()
    assert {
        column["name"] for column in inspector.get_columns("permissions")
    } == {"id", "resource", "action", "description"}
