"""phase8 audit & monitoring: audit_logs, model_call_logs (merge heads)

Revision ID: phase8_audit_monitoring
Revises: f7a3b8c7d9e0, a1b2c3d4e5f6
Create Date: 2026-07-21

该迁移同时作为合并点，统一此前分叉的两个 head（f7a3b8c7d9e0 与 a1b2c3d4e5f6），
并新增阶段八所需的审计日志表与模型调用日志表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'phase8_audit_monitoring'
down_revision: Union[str, Sequence[str], None] = ('f7a3b8c7d9e0', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── audit_logs ──
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('resource', sa.String(length=100), nullable=False),
        sa.Column('resource_id', sa.String(length=36), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index(op.f('ix_audit_logs_tenant_id'), 'audit_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_resource'), 'audit_logs', ['resource'], unique=False)

    # ── model_call_logs ──
    op.create_table(
        'model_call_logs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('agent_id', sa.String(length=36), nullable=True),
        sa.Column('model_id', sa.String(length=36), nullable=False),
        sa.Column('provider_id', sa.String(length=36), nullable=True),
        sa.Column('conversation_id', sa.String(length=36), nullable=True),
        sa.Column('prompt_tokens', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('completion_tokens', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('total_tokens', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index(op.f('ix_model_call_logs_tenant_id'), 'model_call_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_model_call_logs_user_id'), 'model_call_logs', ['user_id'], unique=False)
    op.create_index(op.f('ix_model_call_logs_agent_id'), 'model_call_logs', ['agent_id'], unique=False)
    op.create_index(op.f('ix_model_call_logs_model_id'), 'model_call_logs', ['model_id'], unique=False)
    op.create_index(op.f('ix_model_call_logs_provider_id'), 'model_call_logs', ['provider_id'], unique=False)
    op.create_index(op.f('ix_model_call_logs_conversation_id'), 'model_call_logs', ['conversation_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_model_call_logs_conversation_id'), table_name='model_call_logs')
    op.drop_index(op.f('ix_model_call_logs_provider_id'), table_name='model_call_logs')
    op.drop_index(op.f('ix_model_call_logs_model_id'), table_name='model_call_logs')
    op.drop_index(op.f('ix_model_call_logs_agent_id'), table_name='model_call_logs')
    op.drop_index(op.f('ix_model_call_logs_user_id'), table_name='model_call_logs')
    op.drop_index(op.f('ix_model_call_logs_tenant_id'), table_name='model_call_logs')
    op.drop_table('model_call_logs')

    op.drop_index(op.f('ix_audit_logs_resource'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_tenant_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
