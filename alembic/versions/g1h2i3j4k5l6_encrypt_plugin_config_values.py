"""encrypt plugin config values (review §3.2)

为 plugin_configs 增加 value_encrypted 列：真实凭据以 Fernet 密文落库，
原有明文 value 列退化为脱敏回显。迁移时回填历史明文行（加密 + 脱敏）。

回填依赖 FERNET_KEY；若环境未配置或任意行处理失败，则跳过该行，
legacy 行的运行时读取仍由 PluginService._load_config_dict / _masked_value 的
回退逻辑兜底（明文但仅回显脱敏值），不影响可用性。
"""
from __future__ import annotations

from typing import Any, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None

_SECRET_KEY_HINTS = (
    "key", "secret", "token", "password", "pwd", "credential",
    "authorization", "auth",
)


def _is_secret_key(name: str) -> bool:
    return any(hint in name.lower() for hint in _SECRET_KEY_HINTS)


def _mask_config(value: Any, name_hint: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _mask_config(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_config(v) for v in value]
    if isinstance(value, str) and value and _is_secret_key(name_hint):
        return "********"
    return value


def upgrade() -> None:
    op.add_column(
        "plugin_configs",
        sa.Column("value_encrypted", sa.Text(), nullable=True),
    )

    # 回填历史明文行：加密真实值、脱敏 value 列。
    bind = op.get_bind()
    try:
        import json

        from app.utils.encryption import encrypt
    except Exception:
        return

    result = bind.execute(
        sa.text(
            "SELECT id, name, value FROM plugin_configs "
            "WHERE value_encrypted IS NULL AND value IS NOT NULL"
        )
    )
    for row in result.fetchall():
        rid, name, raw = row[0], row[1], row[2]
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            ciphertext = encrypt(json.dumps(value, ensure_ascii=False))
            masked = json.dumps(_mask_config(value), ensure_ascii=False)
            bind.execute(
                sa.text(
                    "UPDATE plugin_configs "
                    "SET value_encrypted = :c, value = :v WHERE id = :id"
                ),
                {"c": ciphertext, "v": masked, "id": rid},
            )
        except Exception:
            # 单条失败不影响整体迁移；legacy 回退逻辑兜底
            continue


def downgrade() -> None:
    op.drop_column("plugin_configs", "value_encrypted")
