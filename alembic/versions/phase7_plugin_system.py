"""phase7 plugin system: plugins, plugin_configs, plugin_endpoints

Revision ID: phase7_plugin_system
Revises: phase8_audit_monitoring
Create Date: 2026-07-21

新增阶段七插件系统所需的三张表：插件、插件配置（按租户）、插件端点。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'phase7_plugin_system'
down_revision: Union[str, Sequence[str], None] = 'phase8_audit_monitoring'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── plugins ──
    op.create_table(
        'plugins',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('plugin_type', sa.String(length=50), nullable=False, server_default='tool'),
        sa.Column('version', sa.String(length=20), nullable=False, server_default='1.0.0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('config_schema', sa.JSON(), nullable=True),
        sa.Column('icon', sa.String(length=100), nullable=True),
        sa.Column('author', sa.String(length=255), nullable=True),
        sa.Column('homepage_url', sa.String(length=500), nullable=True),
        sa.Column('api_spec', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
    )
    op.create_index(op.f('ix_plugins_tenant_id'), 'plugins', ['tenant_id'], unique=False)

    # ── plugin_configs ──
    op.create_table(
        'plugin_configs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('plugin_id', sa.String(length=36), sa.ForeignKey('plugins.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=True),
        sa.UniqueConstraint('plugin_id', 'tenant_id', 'name', name='uq_plugin_config'),
    )
    op.create_index(op.f('ix_plugin_configs_plugin_id'), 'plugin_configs', ['plugin_id'], unique=False)
    op.create_index(op.f('ix_plugin_configs_tenant_id'), 'plugin_configs', ['tenant_id'], unique=False)

    # ── plugin_endpoints ──
    op.create_table(
        'plugin_endpoints',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('plugin_id', sa.String(length=36), sa.ForeignKey('plugins.id', ondelete='CASCADE'), nullable=False),
        sa.Column('endpoint', sa.String(length=500), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=False, server_default='POST'),
        sa.Column('headers', sa.JSON(), nullable=True),
        sa.Column('request_body_schema', sa.JSON(), nullable=True),
        sa.Column('response_schema', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    )
    op.create_index(op.f('ix_plugin_endpoints_plugin_id'), 'plugin_endpoints', ['plugin_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_plugin_endpoints_plugin_id'), table_name='plugin_endpoints')
    op.drop_table('plugin_endpoints')

    op.drop_index(op.f('ix_plugin_configs_tenant_id'), table_name='plugin_configs')
    op.drop_index(op.f('ix_plugin_configs_plugin_id'), table_name='plugin_configs')
    op.drop_table('plugin_configs')

    op.drop_index(op.f('ix_plugins_tenant_id'), table_name='plugins')
    op.drop_table('plugins')
