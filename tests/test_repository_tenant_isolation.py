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

from app.models.knowledge_document import KnowledgeDocument
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
        # 读取侧文档级过滤（P1-A）在 query 之后先 join 文档表，链路随之变长。
        # 这里显式补齐候选，而不是改成「随便取一层被调用过的 filter」——后者会在
        # 链路再次变化时静默匹配到错误的 filter，让断言失去意义。
        "query().join().filter": mock_db.query.return_value.join.return_value.filter,
        "query().join().options().filter": (
            mock_db.query.return_value.join.return_value.options.return_value.filter
        ),
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

    def test_chunk_has_no_soft_delete_column(self):
        """**移除守卫**：分块表已取消软删列，任何地方都不应再出现分块级软删条件

        软删在分块表上是自相矛盾的（删除文档时向量被硬删、行却标记"已软删"，
        既不可恢复也不可检索），且软删行会长期占用 ``vector_id`` 唯一索引。
        这条断言防止后续改动把 ``deleted_at`` 悄悄加回来——一旦加回，那 8 处
        "记得写过滤"的负担就同时回来了，而漏写一处即意味着已下架内容仍被检索命中。
        """
        from app.models.knowledge_chunk import KnowledgeChunk

        assert "deleted_at" not in KnowledgeChunk.__table__.columns

    def test_get_by_vector_id_has_no_chunk_soft_delete_filter(self, chunk_repo):
        """单条读取路径：不得再有分块级软删条件，但必须保留文档级闸门"""
        chunk_repo.get_by_vector_id("vec-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.deleted_at" not in sql
        assert "knowledge_documents.deleted_at IS NULL" in sql

    def test_list_by_vector_ids_filters_tenant(self, chunk_repo):
        """批量回表路径同样必须带租户过滤（N+1 优化后新增的方法）

        分块级软删条件已随列一并移除；「已下架内容不得被检索到」改由文档级闸门
        承担，故此处断言的是文档级条件而非分块级。
        """
        chunk_repo.list_by_vector_ids(["v1", "v2"])
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "knowledge_chunks.deleted_at" not in sql
        assert "knowledge_documents.deleted_at IS NULL" in sql
        assert "IN (" in sql

    def test_list_by_vector_ids_empty_input_skips_query(self, chunk_repo):
        """空输入直接返回，不产生无意义的 ``IN ()`` 查询"""
        assert chunk_repo.list_by_vector_ids([]) == []
        chunk_repo.db.query.assert_not_called()

    def test_list_by_vector_ids_excludes_chunks_of_deleted_document(self, chunk_repo):
        """回表必须排除「所属文档已软删」的分块（P1-A）

        写入侧级联只对修复之后发生的删除有效；历史数据会留下「文档已软删、
        分块存活、向量在库」的状态。读取侧若只判定分块级 deleted_at，已下架文档
        仍会作为回答依据返回给 Agent 与前端——属内容下架失效。
        """
        chunk_repo.list_by_vector_ids(["v1"])
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_documents.deleted_at IS NULL" in sql
        assert "knowledge_documents.tenant_id" in sql

        # join 属于 FROM 子句，不在 filter 条件文本内，因此单独断言 join 调用：
        # 目标表必须是 knowledge_documents，连接键必须是 doc_id = id。
        join_args = chunk_repo.db.query.return_value.join.call_args.args
        assert join_args[0] is KnowledgeDocument
        assert "knowledge_documents.id = knowledge_chunks.doc_id" in str(join_args[1])

    def test_get_by_vector_id_excludes_chunks_of_deleted_document(self, chunk_repo):
        """单条读取路径必须有同样的文档级过滤，避免两条路径行为不一致"""
        chunk_repo.get_by_vector_id("vec-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_documents.deleted_at IS NULL" in sql

    def test_list_by_doc_id_keeps_no_document_filter(self, chunk_repo):
        """清理路径刻意不加文档级过滤

        若加上，则「文档已软删」时按 doc_id 取分块会得到空集，删除文档时的
        向量清理会静默跳过并留下孤儿向量——过滤方向恰好相反。
        """
        chunk_repo.list_by_doc_id("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_documents.deleted_at IS NULL" not in sql

    def test_list_by_document_filters_tenant_and_current_epoch(self, chunk_repo):
        """分块列表必须限制在**文档当前代**之内

        重建期间新旧两代分块行同时存活（旧行支撑回滚窗口），不带代次条件会把两代
        混在一起展示。代次取 ``document.active_chunk_epoch`` 而非配置值：刚改过
        分块参数、尚未重建的文档，若拿配置值过滤会**静默返回空列表**。
        """
        chunk_repo.list_by_document("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "knowledge_chunks.chunk_epoch = knowledge_documents.active_chunk_epoch" in sql

    def test_count_by_document_filters_tenant_and_current_epoch(self, chunk_repo):
        chunk_repo.count_by_document("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert "knowledge_chunks.chunk_epoch = knowledge_documents.active_chunk_epoch" in sql

    def test_count_live_by_kb_filters_tenant_epoch_and_document(self, chunk_repo):
        """库级计数必须与分块列表**同口径**：本租户 + 当前代 + 文档存活

        ``knowledge_bases.chunk_count`` 曾被写入侧用 ``+ len(new_chunks)`` 累加维护，
        在同一代次被重复投递（幂等守卫先删旧行）或跨代重建（旧代行仍在表中）时都会
        偏大，且只表现为一个错误的数字、不产生任何报错。改为按此口径重算后，
        「计数 == 列表长度」成为恒等式。本用例把该口径钉死，防止有人图省事退回累加。
        """
        chunk_repo.count_live_by_kb("kb-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "knowledge_chunks.kb_id" in sql
        assert "kb-1" in sql
        assert (
            "knowledge_chunks.chunk_epoch = knowledge_documents.active_chunk_epoch" in sql
        )
        assert "knowledge_documents.deleted_at IS NULL" in sql

    def test_list_by_doc_id_filters_tenant(self, chunk_repo):
        """删除文档时用于清理向量的查询路径也必须带租户过滤"""
        chunk_repo.list_by_doc_id("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert "doc-1" in sql

    def test_delete_by_doc_id_filters_tenant_and_is_physical(self, chunk_repo):
        """级联删除必须是**物理删除**且带租户过滤

        物理删除的意义：``vector_id`` 唯一索引随行消失而释放，重建沿用同一
        ``doc.id`` 与序号才不会撞唯一约束。若退回软删，重建会以
        ``IntegrityError`` 失败，而报错内容完全看不出「这是墓碑行占着 id」。
        """
        chunk_repo.delete_by_doc_id("doc-1")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert TENANT in sql
        assert "doc-1" in sql
        assert "knowledge_chunks.deleted_at" not in sql

    def test_delete_by_doc_id_returns_row_count(self):
        """返回受影响行数，便于调用方记录日志与校验"""
        repo = KnowledgeChunkRepository(db=MagicMock(), tenant_id=TENANT)
        repo.db.query.return_value.filter.return_value.delete.return_value = 7

        assert repo.delete_by_doc_id("doc-1") == 7

    def test_delete_superseded_keeps_current_epoch(self, chunk_repo):
        """旧代回收：只删非当前代的行，当前代必须原样保留

        这条断言保护的是「回收」与「清空」的区别——写错成删除全部，
        生效集合里的向量就会立刻失去对应的行，检索回表查不到内容。
        """
        chunk_repo.delete_superseded_by_doc_id("doc-1", "448-64")
        sql = _compiled(_captured_condition(chunk_repo.db))
        assert "knowledge_chunks.tenant_id" in sql
        assert "doc-1" in sql
        assert "chunk_epoch != " in sql
        assert "448-64" in sql

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
