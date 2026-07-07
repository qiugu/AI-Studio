"""change uuid columns to varchar(36)

Revision ID: f7a3b8c7d9e0
Revises: e68e3349b2c5
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f7a3b8c7d9e0'
down_revision = 'e68e3349b2c5'
branch_labels = None
depends_on = None


COLUMNS_BY_TABLE = {
    'tenants': ['id'],
    'users': ['id', 'tenant_id'],
    'roles': ['id', 'tenant_id'],
    'permissions': ['id'],
    'api_keys': ['id', 'tenant_id', 'user_id'],
    'ai_providers': ['id', 'tenant_id'],
    'ai_models': ['id', 'tenant_id', 'provider_id'],
    'prompts': ['id', 'tenant_id', 'created_by'],
    'prompt_versions': ['id', 'prompt_id', 'created_by'],
    'prompt_test_logs': ['id', 'prompt_id', 'version_id', 'tenant_id', 'model_id'],
    'knowledge_bases': ['id', 'tenant_id'],
    'knowledge_documents': ['id', 'tenant_id', 'kb_id'],
    'knowledge_chunks': ['id', 'tenant_id', 'kb_id', 'doc_id'],
    'agents': ['id', 'tenant_id', 'model_id', 'created_by'],
    'agent_tools': ['id', 'tenant_id', 'agent_id'],
    'conversations': ['id', 'tenant_id', 'agent_id', 'created_by'],
    'messages': ['id', 'tenant_id', 'conversation_id'],
    'token_usages': ['id', 'tenant_id', 'agent_id', 'model_id', 'user_id', 'conversation_id'],
    'workflows': ['id', 'tenant_id', 'created_by'],
    'workflow_nodes': ['id', 'tenant_id', 'workflow_id'],
    'workflow_edges': ['id', 'tenant_id', 'workflow_id', 'source_node_id', 'target_node_id'],
    'workflow_executions': ['id', 'tenant_id', 'workflow_id', 'created_by'],
    'node_executions': ['id', 'tenant_id', 'execution_id', 'node_id'],
    'user_roles': ['user_id', 'role_id'],
    'role_permissions': ['role_id', 'permission_id'],
}


def _get_target_tables(inspector):
    return [table_name for table_name in COLUMNS_BY_TABLE if inspector.has_table(table_name)]


def _drop_foreign_keys(bind, table_name, inspector):
    foreign_keys = inspector.get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if not foreign_key.get('name'):
            continue
        try:
            op.drop_constraint(foreign_key['name'], table_name, type_='foreignkey')
        except Exception:
            pass


def _recreate_foreign_keys(bind, table_name, inspector):
    foreign_keys = inspector.get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if not foreign_key.get('name'):
            continue
        constraint_name = foreign_key['name']
        try:
            op.create_foreign_key(
                constraint_name,
                table_name,
                foreign_key['referred_table'],
                foreign_key['constrained_columns'],
                foreign_key['referred_columns'],
                ondelete=foreign_key.get('options', {}).get('ondelete'),
                onupdate=foreign_key.get('options', {}).get('onupdate'),
            )
        except Exception:
            pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    target_tables = _get_target_tables(inspector)

    bind.execute(sa.text("SET foreign_key_checks = 0"))
    try:
        for table_name in target_tables:
            _drop_foreign_keys(bind, table_name, inspector)

        for table_name in target_tables:
            existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            if not existing_columns:
                continue

            with op.batch_alter_table(table_name, schema=None) as batch_op:
                for column_name in COLUMNS_BY_TABLE[table_name]:
                    if column_name not in existing_columns:
                        continue

                    column = existing_columns[column_name]
                    existing_type = column['type']
                    if isinstance(existing_type, sa.String):
                        continue

                    batch_op.alter_column(
                        column_name,
                        existing_type=existing_type,
                        type_=sa.String(length=36),
                        existing_nullable=column['nullable'],
                    )

        for table_name in target_tables:
            _recreate_foreign_keys(bind, table_name, inspector)
    finally:
        bind.execute(sa.text("SET foreign_key_checks = 1"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    target_tables = _get_target_tables(inspector)

    bind.execute(sa.text("SET foreign_key_checks = 0"))
    try:
        for table_name in target_tables:
            _drop_foreign_keys(bind, table_name, inspector)

        for table_name in target_tables:
            existing_columns = {col['name']: col for col in inspector.get_columns(table_name)}
            for column_name in COLUMNS_BY_TABLE[table_name]:
                if column_name not in existing_columns:
                    continue
                column = existing_columns[column_name]
                if isinstance(column['type'], sa.String):
                    with op.batch_alter_table(table_name, schema=None) as batch_op:
                        batch_op.alter_column(
                            column_name,
                            existing_type=sa.String(length=36),
                            type_=sa.BigInteger(),
                            existing_nullable=column['nullable'],
                        )

        for table_name in target_tables:
            _recreate_foreign_keys(bind, table_name, inspector)
    finally:
        bind.execute(sa.text("SET foreign_key_checks = 1"))
