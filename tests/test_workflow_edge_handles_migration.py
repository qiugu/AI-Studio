"""Regression test for persisting React Flow handle directions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


MIGRATION_PATH = Path(__file__).parents[1] / "alembic" / "versions" / "n2_workflow_edge_handles.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("n2_workflow_edge_handles", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration(connection, operation):
    context = MigrationContext.configure(connection)
    operations = Operations(context)
    module = _load_migration()
    original_op = module.op
    module.op = operations
    try:
        operation(module)
    finally:
        module.op = original_op


def test_workflow_edge_handle_columns_are_additive_and_reversible():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "workflow_edges",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_node_id", sa.String(36), nullable=False),
        sa.Column("target_node_id", sa.String(36), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        _run_migration(connection, lambda module: module.upgrade())
        columns = {column["name"] for column in sa.inspect(connection).get_columns("workflow_edges")}
        assert {"source_handle", "target_handle"}.issubset(columns)

        _run_migration(connection, lambda module: module.downgrade())
        columns = {column["name"] for column in sa.inspect(connection).get_columns("workflow_edges")}
        assert "source_handle" not in columns
        assert "target_handle" not in columns
