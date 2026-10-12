"""临时诊断脚本：打印指定 prompt 的版本行，判断前端"查看"按钮无反应的原因。

用法：python scripts/inspect_prompt_versions.py <prompt_id>
"""
from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.database import engine


def main() -> None:
    prompt_id = sys.argv[1] if len(sys.argv) > 1 else "d0ac65cd-35d3-4bd4-8ad3-d3505940ad6b"
    with engine.connect() as conn:
        print("=== prompt ===")
        row = conn.execute(
            text(
                "SELECT id, tenant_id, name, status, deleted_at "
                "FROM prompts WHERE id = :pid"
            ),
            {"pid": prompt_id},
        ).fetchone()
        print(row)

        print("\n=== versions (raw, no tenant filter) ===")
        rows = conn.execute(
            text(
                "SELECT id, prompt_id, tenant_id, version_number, is_current, "
                "created_by, CHAR_LENGTH(content) AS content_len "
                "FROM prompt_versions WHERE prompt_id = :pid "
                "ORDER BY version_number DESC"
            ),
            {"pid": prompt_id},
        ).fetchall()
        for r in rows:
            print(r)
        print("total versions:", len(rows))

        print("\n=== distinct tenant_id in prompt_versions ===")
        rows = conn.execute(
            text(
                "SELECT tenant_id, COUNT(*) FROM prompt_versions "
                "WHERE prompt_id = :pid GROUP BY tenant_id"
            ),
            {"pid": prompt_id},
        ).fetchall()
        print(rows)


if __name__ == "__main__":
    main()
