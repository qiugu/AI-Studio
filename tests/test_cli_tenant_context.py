"""Contract tests for tenant context in database-backed maintenance CLIs."""

from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
DATABASE_SCRIPTS = (
    "backfill_hybrid_collection.py",
    "bootstrap_platform_admin.py",
    "chunking_quality_report.py",
    "init_knowledge_permissions.py",
    "inspect_prompt_versions.py",
    "rebuild_knowledge_vectors.py",
    "repair_orphan_vectors.py",
    "seed_demo_search_plugin.py",
    "verify_rbac_migration.py",
)


@pytest.mark.parametrize("script_name", DATABASE_SCRIPTS)
def test_database_backed_cli_declares_explicit_tenant_scope(script_name: str):
    source = (SCRIPTS_DIR / script_name).read_text(encoding="utf-8")
    assert "tenant_scope_context" in source, (
        f"{script_name} must declare tenant_scope_context around database work"
    )


def test_alembic_environment_declares_platform_migration_scope():
    source = (SCRIPTS_DIR.parent / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "tenant_scope_context" in source
    assert "alembic-migration" in source
    assert "allow_cross_tenant=True" in source
