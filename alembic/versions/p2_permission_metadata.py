"""Persist stable permission catalog metadata for cross-process authorization."""

from alembic import op
import sqlalchemy as sa

from app.core.permissions import PERMISSION_CATALOG


revision = "p2_permission_metadata"
down_revision = "p1_tenant_memberships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "permissions",
        sa.Column("scope", sa.String(20), nullable=False, server_default="tenant"),
    )
    op.add_column(
        "permissions",
        sa.Column(
            "sensitivity", sa.String(20), nullable=False, server_default="normal"
        ),
    )
    op.add_column(
        "permissions",
        sa.Column("is_delegable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    bind = op.get_bind()
    # Collapse duplicate legacy keys before creating the database-level unique
    # index.  Role bindings are rewired to the first stable permission row;
    # duplicate bindings are removed only when the canonical row already has
    # the same role assignment.
    permission_rows = bind.execute(
        sa.text(
            "SELECT id, resource, action FROM permissions "
            "ORDER BY resource, action, id"
        )
    ).mappings().all()
    canonical: dict[tuple[str, str], str] = {}
    for row in permission_rows:
        key = (row["resource"], row["action"])
        if key not in canonical:
            canonical[key] = str(row["id"])
            continue
        duplicate_id = str(row["id"])
        canonical_id = canonical[key]
        role_ids = bind.execute(
            sa.text(
                "SELECT role_id FROM role_permissions WHERE permission_id=:permission_id"
            ),
            {"permission_id": duplicate_id},
        ).scalars().all()
        for role_id in role_ids:
            already_bound = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions "
                    "WHERE role_id=:role_id AND permission_id=:permission_id"
                ),
                {"role_id": role_id, "permission_id": canonical_id},
            ).first()
            if already_bound is not None:
                bind.execute(
                    sa.text(
                        "DELETE FROM role_permissions "
                        "WHERE role_id=:role_id AND permission_id=:permission_id"
                    ),
                    {"role_id": role_id, "permission_id": duplicate_id},
                )
            else:
                bind.execute(
                    sa.text(
                        "UPDATE role_permissions SET permission_id=:canonical_id "
                        "WHERE role_id=:role_id AND permission_id=:duplicate_id"
                    ),
                    {
                        "canonical_id": canonical_id,
                        "role_id": role_id,
                        "duplicate_id": duplicate_id,
                    },
                )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE id=:permission_id"),
            {"permission_id": duplicate_id},
        )

    for definition in PERMISSION_CATALOG.values():
        bind.execute(
            sa.text(
                "UPDATE permissions SET description=:description, scope=:scope, "
                "sensitivity=:sensitivity, is_delegable=:is_delegable "
                "WHERE resource=:resource AND action=:action"
            ),
            {
                "description": definition.description,
                "scope": definition.scope,
                "sensitivity": definition.sensitivity,
                "is_delegable": definition.is_delegable,
                "resource": definition.resource,
                "action": definition.action,
            },
        )
    op.create_index(
        "uq_permissions_resource_action",
        "permissions",
        ["resource", "action"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_permissions_resource_action", table_name="permissions")
    op.drop_column("permissions", "is_delegable")
    op.drop_column("permissions", "sensitivity")
    op.drop_column("permissions", "scope")
