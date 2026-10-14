"""存量数据一致性校准脚本的单测（P3-I 计数对齐）

覆盖三层：

1. **检出**——KB 级 ``document_count`` / ``chunk_count``、文档级 ``chunk_count`` 漂移；
2. **修正**——``_apply_counter_drift`` 只回写真正偏差的字段，且回写后复检为 clean；
3. **不误报**——一致数据必须判定为 ``is_clean``。这是诊断工具最要紧的一条：
   假阳性会让运维在正常数据上执行写入，把「无病」变成「有病」。

实现取舍：用**真实 SQL 跑在内存 SQLite** 上（脚本语句均为可移植的标准 SQL），
因此验证的是 SQL 语义本身，而非替身是否被调用。

计数字段口径 = **当前代**分块（``chunk_epoch = document.active_chunk_epoch``）
且其文档存活。代次条件不是装饰：重建期间新旧两代分块行同时存活（旧行支撑回滚
窗口），不带它会得出「每次重建后计数都漂移」这一永远修不掉的假告警。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import config
from app.core.database import Base
from app.models.knowledge_base import KnowledgeBase  # noqa: F401  - 注册 metadata
from app.models.knowledge_chunk import KnowledgeChunk  # noqa: F401
from app.models.knowledge_document import DocumentStatus, KnowledgeDocument  # noqa: F401

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "repair_orphan_vectors.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("repair_orphan_vectors_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # 脚本启用 ``from __future__ import annotations``，@dataclass 解析字符串注解时
    # 需要 ``sys.modules[cls.__module__]`` 已存在，否则报 NoneType.__dict__。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


repair = _load_script_module()

STAMP = datetime(2026, 1, 1, 0, 0, 0)

#: 测试默认使用的分块代次——**从配置派生**，不写字面量。代次含策略版本分量
#: （``448-64-p1``），硬编码会在策略版本递增时让本文件的断言莫名失败。
EPOCH = config.chunk_epoch
#: 一个更早的代次，用于构造「旧代分块行与当前代共存」的重建窗口场景
OLD_EPOCH = "1024-0"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            KnowledgeBase.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _kb(db, kb_id="kb-1", *, docs=None, chunks=None, deleted=False, name="库A"):
    """新增知识库；``docs`` / ``chunks`` 为 None 表示不写该计数字段（留 0）"""
    db.add(
        KnowledgeBase(
            id=kb_id,
            tenant_id="t1",
            name=name,
            document_count=docs or 0,
            chunk_count=chunks or 0,
            deleted_at=STAMP if deleted else None,
        )
    )


def _doc(
    db,
    doc_id,
    kb_id="kb-1",
    *,
    chunks=None,
    deleted=False,
    file_name="a.txt",
    epoch=EPOCH,
):
    """新增文档；``epoch`` 为「该文档当前生效的分块代次」"""
    db.add(
        KnowledgeDocument(
            id=doc_id,
            tenant_id="t1",
            kb_id=kb_id,
            file_name=file_name,
            file_type="txt",
            file_size=10,
            chunk_count=chunks or 0,
            active_chunk_epoch=epoch,
            status=DocumentStatus.COMPLETED,
            deleted_at=STAMP if deleted else None,
        )
    )


def _chunk(db, chunk_id, doc_id, kb_id="kb-1", *, epoch=EPOCH):
    """新增分块行

    分块表**没有**软删列（派生数据，删除即物理删除），因此这里只能通过 ``epoch``
    构造「旧代残留」场景——这正是取消软删后代次列接管的职责。
    """
    db.add(
        KnowledgeChunk(
            id=chunk_id,
            tenant_id="t1",
            kb_id=kb_id,
            doc_id=doc_id,
            content="内容",
            chunk_index=0,
            vector_id=f"v-{chunk_id}",
            chunk_epoch=epoch,
        )
    )


def _commit(db):
    db.commit()


def _stored_kb(db, kb_id):
    row = db.execute(
        text("SELECT document_count, chunk_count FROM knowledge_bases WHERE id = :i"),
        {"i": kb_id},
    ).fetchone()
    return {"document_count": row[0], "chunk_count": row[1]}


def _stored_doc(db, doc_id):
    row = db.execute(
        text("SELECT chunk_count FROM knowledge_documents WHERE id = :i"), {"i": doc_id}
    ).fetchone()
    return {"chunk_count": row[0]}


class TestNoFalsePositives:
    def test_consistent_kb_and_doc_reports_no_drift(self, db):
        """计数与存量一致 → 必须零漂移（假阳性会让正常库被判为需修复）"""
        _kb(db, "kb-1", docs=1, chunks=2)
        _doc(db, "doc-1", chunks=2)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _commit(db)

        assert repair.collect_kb_counter_drift(db) == []
        assert repair.collect_doc_counter_drift(db) == []
        assert repair.collect_counter_drift(db) == []

    def test_empty_kb_with_zero_counters_reports_no_drift(self, db):
        _kb(db, "kb-1")
        _commit(db)
        assert repair.collect_counter_drift(db) == []

    def test_soft_deleted_kb_is_out_of_scope(self, db):
        """软删知识库的计数无展示意义，不应被纳管（否则会反复触发无谓写入）"""
        _kb(db, "kb-1", docs=99, chunks=99, deleted=True)
        _doc(db, "doc-1", chunks=99)
        _commit(db)
        assert repair.collect_kb_counter_drift(db) == []


class TestDetection:
    def test_kb_document_count_drift_detected(self, db):
        _kb(db, "kb-1", docs=5, chunks=2)
        _doc(db, "doc-1", chunks=2)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _commit(db)

        drifts = repair.collect_kb_counter_drift(db)
        assert len(drifts) == 1
        drift = drifts[0]
        assert drift.scope == "kb"
        assert drift.target_id == "kb-1"
        assert drift.stored["document_count"] == 5
        assert drift.actual["document_count"] == 1
        # 分块数一致，不得进入 corrections
        assert drift.corrections == {"document_count": 1}

    def test_kb_chunk_count_drift_detected(self, db):
        _kb(db, "kb-1", docs=1, chunks=99)
        _doc(db, "doc-1", chunks=2)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _commit(db)

        drifts = repair.collect_kb_counter_drift(db)
        assert len(drifts) == 1
        assert drifts[0].corrections == {"chunk_count": 2}

    def test_both_kb_counters_drift_detected_together(self, db):
        _kb(db, "kb-1", docs=7, chunks=70)
        _doc(db, "doc-1", chunks=1)
        _chunk(db, "c-1", "doc-1")
        _commit(db)

        drifts = repair.collect_kb_counter_drift(db)
        assert drifts[0].corrections == {"document_count": 1, "chunk_count": 1}
        assert "document_count: 7 → 1" in drifts[0].describe()
        assert "chunk_count: 70 → 1" in drifts[0].describe()

    def test_doc_chunk_count_drift_detected(self, db):
        _kb(db, "kb-1", docs=1, chunks=2)
        _doc(db, "doc-1", chunks=7)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _commit(db)

        drifts = repair.collect_doc_counter_drift(db)
        assert len(drifts) == 1
        assert drifts[0].scope == "doc"
        assert drifts[0].kb_id == "kb-1"
        assert drifts[0].corrections == {"chunk_count": 2}

    def test_superseded_epoch_chunks_are_not_counted_as_live(self, db):
        """非当前代的分块不算存量——否则重建后台账会出现修不掉的假漂移

        重建期间旧代分块行必须留在库里（支撑指针回滚），若计数把两代一起算进去，
        每次重建后 ``is_clean`` 都会为假，运维会试图去「修」一个本来正确的值。
        """
        _kb(db, "kb-1", docs=1, chunks=1)
        _doc(db, "doc-1", chunks=1)
        _chunk(db, "c-1", "doc-1")                     # 当前代
        _chunk(db, "c-2", "doc-1", epoch=OLD_EPOCH)    # 旧代残留，仍在库里
        _commit(db)

        assert repair.collect_kb_counter_drift(db) == []
        assert repair.collect_doc_counter_drift(db) == []

    def test_doc_with_no_active_epoch_counts_zero_chunks(self, db):
        """``active_chunk_epoch`` 为 NULL（从未产出分块）时不得把残留行算成存量

        NULL 与任何代次比较都不为真，因此那些行天然不计入——这正是我们要的：
        口径跟着「文档自述的当前代」走，而不是跟着「表里有什么行」走。
        """
        _kb(db, "kb-1", docs=1, chunks=0)
        _doc(db, "doc-1", chunks=0, epoch=None)
        _chunk(db, "c-1", "doc-1")
        _commit(db)

        assert repair.collect_kb_counter_drift(db) == []
        assert repair.collect_doc_counter_drift(db) == []

    def test_chunks_of_soft_deleted_doc_are_not_counted_as_live(self, db):
        """文档软删后其分块不计入存量——与检索侧 P1-A 的可见性口径同源

        此处正是 P1-A 的交叉验证：检索要求 ``chunk.deleted_at IS NULL``
        **且** ``doc.deleted_at IS NULL``；若计数仍把「已删文档的存活分块」算进去，
        计数就会系统性高于真实可召回量。
        """
        _kb(db, "kb-1", docs=1, chunks=2)
        _doc(db, "doc-1", chunks=2)
        _doc(db, "doc-2", chunks=0, deleted=True)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _chunk(db, "c-3", "doc-2")  # 文档已删、分块仍存活 → 不应计入
        _commit(db)

        assert repair.collect_kb_counter_drift(db) == []
        assert repair.collect_doc_counter_drift(db) == []

    def test_kb_id_filter_narrows_output_only(self, db):
        """``--kb-id`` 只收窄输出范围，不改口径：只报指定的那个库"""
        _kb(db, "kb-1", docs=9, chunks=9, name="库A")
        _kb(db, "kb-2", docs=9, chunks=9, name="库B")
        _commit(db)

        all_drifts = repair.collect_kb_counter_drift(db)
        assert {d.target_id for d in all_drifts} == {"kb-1", "kb-2"}

        scoped = repair.collect_kb_counter_drift(db, kb_id="kb-2")
        assert [d.target_id for d in scoped] == ["kb-2"]


class TestApply:
    def test_apply_writes_values_and_then_data_is_clean(self, db):
        _kb(db, "kb-1", docs=7, chunks=70)
        _doc(db, "doc-1", chunks=7)
        _chunk(db, "c-1", "doc-1")
        _commit(db)

        plan = repair.RepairPlan(counter_drifts=repair.collect_counter_drift(db))
        assert plan.n_counter_drifts == 2
        assert not plan.is_clean

        for drift in plan.counter_drifts:
            repair._apply_counter_drift(db, drift)
        db.commit()

        assert _stored_kb(db, "kb-1") == {"document_count": 1, "chunk_count": 1}
        assert _stored_doc(db, "doc-1") == {"chunk_count": 1}
        # 复检：修正后必须无剩余漂移
        assert repair.collect_counter_drift(db) == []

    def test_apply_is_noop_for_already_correct_drift(self, db):
        """``corrections`` 为空的漂移不得产生 UPDATE（幂等/最小写入面）"""
        drift = repair.CounterDrift(
            scope="kb",
            target_id="kb-1",
            kb_id="kb-1",
            label="库A",
            stored={"document_count": 3, "chunk_count": 9},
            actual={"document_count": 3, "chunk_count": 9},
        )
        assert drift.corrections == {}
        assert repair._apply_counter_drift(db, drift) == 0

    def test_apply_can_raise_counter_when_stored_is_too_low(self, db):
        """漂移方向不只有「偏高」：存量为 0 而实际有分块时也必须修正"""
        _kb(db, "kb-1", docs=0, chunks=0)
        _doc(db, "doc-1", chunks=0)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _commit(db)

        drift = repair.collect_kb_counter_drift(db)[0]
        assert drift.corrections == {"document_count": 1, "chunk_count": 2}
        repair._apply_counter_drift(db, drift)
        db.commit()
        assert _stored_kb(db, "kb-1") == {"document_count": 1, "chunk_count": 2}

    def test_plan_is_clean_only_when_all_three_sources_are_empty(self):
        plan = repair.RepairPlan()
        assert plan.is_clean

        plan.counter_drifts = [
            repair.CounterDrift("doc", "d-1", "kb-1", "a.txt", {"chunk_count": 1}, {"chunk_count": 0})
        ]
        assert not plan.is_clean

        plan.counter_drifts = []
        plan.orphan_points = {"kb_kb-1": ["p-1"]}
        assert not plan.is_clean

        plan.orphan_points = {}
        plan.stale_chunks = [repair.StaleChunk("c-1", "v-1", "doc-1", "kb-1")]
        assert not plan.is_clean


class TestStaleChunkCleanup:
    """「文档已软删、分块行仍在」的历史残留处置

    这类行是 D9 时代的产物（当时分块只有软删列、写入侧从不级联标记）。取消分块
    软删后新代码不会再产出它们，但历史行仍可能存在，且它们占着 ``vector_id``
    唯一索引、让文档计数失真，故由本工具清理——方式是**物理删除**。
    """

    def test_stale_chunks_are_detected_for_soft_deleted_docs(self, db):
        _kb(db, "kb-1", docs=1, chunks=2)
        _doc(db, "doc-1", chunks=2)
        _doc(db, "doc-2", chunks=1, deleted=True)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1")
        _chunk(db, "c-3", "doc-2")
        _commit(db)

        stale = repair.collect_stale_chunks(db)
        assert [s.chunk_id for s in stale] == ["c-3"]

    def test_superseded_epoch_rows_are_not_stale(self, db):
        """旧代残留**不是**失效数据：它是回滚窗口的有效内容，绝不能清掉

        这条是安全边界——若把「非当前代」当成失效，指针一回滚，检索命中的旧代
        id 就查不到内容，回滚反而把检索打断。
        """
        _kb(db, "kb-1", docs=1, chunks=1)
        _doc(db, "doc-1", chunks=1)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-1", epoch=OLD_EPOCH)
        _commit(db)

        assert repair.collect_stale_chunks(db) == []

    def test_execute_physically_deletes_stale_rows(self, db):
        """执行后行必须**消失**（而非标记软删）：占着唯一索引的墓碑行毫无价值"""
        _kb(db, "kb-1", docs=1, chunks=1)
        _doc(db, "doc-1", chunks=1)
        _doc(db, "doc-2", chunks=1, deleted=True)
        _chunk(db, "c-1", "doc-1")
        _chunk(db, "c-2", "doc-2")
        _commit(db)

        plan = repair.RepairPlan(stale_chunks=repair.collect_stale_chunks(db))
        client = _StubQdrant({"kb_kb-1": ["v-c-1", "v-c-2"]})
        repair.execute_plan(db, client, plan, kb_id=None)

        remaining = {
            row[0] for row in db.execute(text("SELECT id FROM knowledge_chunks")).fetchall()
        }
        assert remaining == {"c-1"}, "残留分块行必须被物理删除"
        assert client.deleted == [("kb_kb-1", ["v-c-2"])], "其向量也要一并清理"


class TestCliContract:
    def test_parser_keeps_execute_and_kb_id_switches(self):
        parser = repair.build_parser()
        args = parser.parse_args([])
        assert args.execute is False, "默认必须为只读诊断"
        assert args.kb_id is None

        args = parser.parse_args(["--kb-id", "kb-9", "--execute"])
        assert args.kb_id == "kb-9"
        assert args.execute is True

    def test_counter_table_map_is_literal(self):
        """表名必须是代码内字面量映射，不可由外部输入拼接（注入面）"""
        assert repair.COUNTER_TABLES == {
            "kb": "knowledge_bases",
            "doc": "knowledge_documents",
        }


class _StubQdrant:
    """最小 Qdrant 替身：只实现脚本用到的 get_collections / scroll / delete"""

    def __init__(self, collections):
        self._collections = collections
        self.deleted = []

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self._collections]
        )

    def scroll(self, collection_name, limit, offset, with_payload, with_vectors):
        ids = self._collections[collection_name]
        start = offset or 0
        window = ids[start : start + limit]
        next_offset = start + limit if start + limit < len(ids) else None
        return [SimpleNamespace(id=pid) for pid in window], next_offset

    def delete(self, collection_name, points_selector):
        self.deleted.append((collection_name, list(points_selector.points)))


class TestCollectionScopeGate:
    """孤儿判定的纳管闸门——本工具最危险的一处假阳性

    ``kb_rageval_t2r``（RAG 评测语料）由 ``scripts/index_rag_eval_corpus.py``
    直接写 Qdrant、从不写 MySQL，其全部 point 天然「无对应分块」。
    缺此闸门时 ``--execute`` 会把它整批删除（实测 28771 个），
    评测索引不可逆损毁。
    """

    def test_collection_without_kb_row_is_never_deleted(self, db):
        _kb(db, "kb-1", docs=1, chunks=1)
        _doc(db, "doc-1", chunks=1)
        _chunk(db, "c-1", "doc-1")  # vector_id = v-c-1
        _commit(db)

        client = _StubQdrant(
            {
                "kb_kb-1": ["v-c-1", "v-ghost"],
                "kb_rageval_t2r": [f"eval-{i}" for i in range(500)],
            }
        )

        orphans = repair.collect_orphan_points(db, client)
        assert orphans == {"kb_kb-1": ["v-ghost"]}, "非纳管集合的向量不得被判为孤儿"

        plan = repair.RepairPlan(orphan_points=orphans)
        purge = plan.points_to_purge()
        assert "kb_rageval_t2r" not in purge
        assert all(not pid.startswith("eval-") for ids in purge.values() for pid in ids)

    def test_unknown_collections_are_reported(self, db):
        _kb(db, "kb-1")
        _commit(db)
        client = _StubQdrant({"kb_kb-1": [], "kb_rageval_t2r": ["e-1"], "kb_orphan_x": ["o-1"]})

        assert repair.find_unknown_collections(db, client) == ["kb_orphan_x", "kb_rageval_t2r"]

    def test_unknown_collections_do_not_make_plan_dirty(self):
        """未纳管集合是信息项而非待修复项，不得让计划判为「不一致」"""
        plan = repair.RepairPlan(unknown_collections=["kb_rageval_t2r"])
        assert plan.is_clean

    def test_soft_deleted_kb_collection_is_still_managed(self, db):
        """软删知识库的集合仍属纳管范围：其残留向量是真实垃圾，应当清理"""
        _kb(db, "kb-dead", docs=0, chunks=0, deleted=True)
        _commit(db)
        client = _StubQdrant({"kb_kb-dead": ["v-1", "v-2"]})

        assert repair.find_unknown_collections(db, client) == []
        assert repair.collect_orphan_points(db, client) == {"kb_kb-dead": ["v-1", "v-2"]}

    def test_kb_id_scope_limits_unknown_collection_listing(self, db):
        _kb(db, "kb-1")
        _commit(db)
        client = _StubQdrant({"kb_rageval_t2r": ["e-1"]})

        # kb_id 指到未纳管集合时，仍会被如实报告（而不是静默当作「无集合」）
        assert repair.find_unknown_collections(db, client, kb_id="rageval_t2r") == [
            "kb_rageval_t2r"
        ]
        assert repair.find_unknown_collections(db, client, kb_id="kb-1") == []

    def test_execute_never_touches_unknown_collection(self, db):
        """端到端护栏：即使与实体修复同时执行，未纳管集合也不被删除"""
        _kb(db, "kb-1", docs=1, chunks=1)
        _doc(db, "doc-1", chunks=1)
        _chunk(db, "c-1", "doc-1")  # v-c-1
        _commit(db)

        client = _StubQdrant({"kb_kb-1": ["v-c-1", "v-ghost"], "kb_rageval_t2r": ["e-1", "e-2"]})
        plan = repair.build_plan(db, client)
        assert plan.unknown_collections == ["kb_rageval_t2r"]

        repair.execute_plan(db, client, plan, kb_id=None)

        touched = [name for name, _ in client.deleted]
        assert "kb_rageval_t2r" not in touched
        assert ("kb_kb-1", ["v-ghost"]) in client.deleted

