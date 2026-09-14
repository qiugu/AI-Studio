"""多租户隔离与分层约定测试

CLAUDE.md 规定「所有数据访问必须通过 ``BaseRepository``，禁止在 Service 层裸写
``db.query(Model)``」。这条约定无法靠人眼长期维持，因此转化为两组可执行检查：

1. **隔离性**：Repository 产出的查询条件必须包含 ``tenant_id`` 与软删过滤；
2. **分层**：知识库 Service 中不得出现裸 ``db.query`` 调用。
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.repositories.knowledge import (
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"
TENANT = "tenant-alpha"


def _filter_mock(mock_db: MagicMock):
    """定位真正被调用的 ``filter`` 调用记录

    Repository 的查询链长度不一（``query().filter()``、``query().options().filter()``），
    因此不能硬编码层级，否则新增一个中转方法就会让断言全部失效。
    """
    candidates = {
        "query().filter": mock_db.query.return_value.filter,
        "query().options().filter": mock_db.query.return_value.options.return_value.filter,
    }
    for description, mock in candidates.items():
        if mock.called:
            return mock, description
    raise AssertionError(f"未观察到 filter 调用，检查过的调用链：{sorted(candidates)}")


def _captured_condition(mock_db: MagicMock):
    """取出传给 ``db.query(...).filter(...)`` 的条件表达式"""
    mock, _ = _filter_mock(mock_db)
    return mock.call_args.args[0]


def _compiled(condition) -> str:
    """将 SQLAlchemy 条件编译为字面量 SQL，便于断言过滤字段"""
    return str(condition.compile(compile_kwargs={"literal_binds": True}))


@pytest.fixture
def chunk_repo() -> KnowledgeChunkRepository:
    return KnowledgeChunkRepository(db=MagicMock(), tenant_id=TENANT)


@pytest.fixture
def doc_repo() -> KnowledgeDocumentRepository:
    return KnowledgeDocumentRepository(db=MagicMock(), tenant_id=TENANT)


class TestChunkRepositoryIsolation:
    def test_get_by_vector_id_filters_tenant(self, chunk_repo):
        """按向量 ID 取分块必须带租户过滤

        早期实现遗漏该过滤：只要猜到（或从其他渠道获得）vector_id，
        就能读到其它租户的分块内容——属于跨租户越权读取。
        """
        chunk_repo.get_by_vector_id("vec-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "vec-1" in sql

    def test_get_by_vector_id_excludes_soft_deleted(self, chunk_repo):
        chunk_repo.get_by_vector_id("vec-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.deleted_at IS NULL" in sql

    def test_list_by_vector_ids_filters_tenant_and_deleted(self, chunk_repo):
        """批量回表路径同样必须带租户过滤（N+1 优化后新增的方法）"""
        chunk_repo.list_by_vector_ids(["v1", "v2"])
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "knowledge_chunks.deleted_at IS NULL" in sql
        assert "IN (" in sql

    def test_list_by_vector_ids_empty_input_skips_query(self, chunk_repo):
        """空输入直接返回，不产生无意义的 ``IN ()`` 查询"""
        assert chunk_repo.list_by_vector_ids([]) == []
        chunk_repo.db.query.assert_not_called()

    def test_list_by_document_filters_tenant(self, chunk_repo):
        chunk_repo.list_by_document("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql

    def test_count_by_document_filters_tenant(self, chunk_repo):
        chunk_repo.count_by_document("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql

    def test_list_by_doc_id_filters_tenant(self, chunk_repo):
        """删除文档时用于清理向量的查询路径也必须带租户过滤"""
        chunk_repo.list_by_doc_id("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert "doc-1" in sql

    def test_soft_delete_by_doc_id_filters_tenant_and_skips_deleted(self, chunk_repo):
        """级联软删除必须带租户过滤，且只更新尚未删除的行（保证幂等）"""
        from datetime import datetime

        chunk_repo.soft_delete_by_doc_id("doc-1", datetime(2026, 9, 11, 12, 0, 0))
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "doc-1" in sql
        assert "knowledge_chunks.deleted_at IS NULL" in sql

    def test_soft_delete_by_doc_id_returns_row_count(self):
        """返回受影响行数，便于调用方记录日志与校验"""
        repo = KnowledgeChunkRepository(db=MagicMock(), tenant_id=TENANT)
        repo.db.query.return_value.filter.return_value.update.return_value = 7
        from datetime import datetime

        assert repo.soft_delete_by_doc_id("doc-1", datetime(2026, 9, 11)) == 7

    def test_different_tenants_produce_different_conditions(self):
        first = KnowledgeChunkRepository(db=MagicMock(), tenant_id="tenant-a")
        second = KnowledgeChunkRepository(db=MagicMock(), tenant_id="tenant-b")
        first.list_by_doc_id("doc-1")
        second.list_by_doc_id("doc-1")
        assert "tenant-a" not in _compiled(_captured_condition(second.db))
        assert "tenant-b" not in _compiled(_captured_condition(first.db))


class TestDocumentRepositoryIsolation:
    def test_list_by_kb_filters_tenant(self, doc_repo):
        doc_repo.list_by_kb("kb-1")
        sql = _compiled(_captured_condition(doc_repo.db))
        assert "knowledge_documents.tenant_id" in sql
        assert TENANT in sql

    def test_count_by_kb_filters_tenant(self, doc_repo):
        doc_repo.count_by_kb("kb-1")
        sql = _compiled(_captured_condition(doc_repo.db))
        assert "knowledge_documents.tenant_id" in sql


class TestServiceLayerLayering:
    """知识库 Service 不得裸写 ORM 查询（必须经由 Repository）"""

    def _raw_query_calls(self, relative_path: str):
        source = (APP_DIR / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "query":
                offenders.append(node.lineno)
        return offenders

    def test_knowledge_service_has_no_raw_query(self):
        offenders = self._raw_query_calls("services/knowledge.py")
        assert offenders == [], f"services/knowledge.py 存在裸 db.query 调用：行 {offenders}"

    def test_delete_document_routes_through_repository(self):
        """删除文档的向量清理必须经 Repository 取分块（曾为裸 db.query）"""
        source = (APP_DIR / "services/knowledge.py").read_text(encoding="utf-8")
        assert "self.chunk_repo.list_by_doc_id(" in source
