"""业务库重建脚本单测（``scripts/rebuild_knowledge_vectors.py``）

本脚本会**写生产数据**，因此测试的重心不是「功能是否可用」，而是**四道安全闸门**
是否真的存在：

1. 干跑不写任何数据（缺省只读）；
2. 目标集合已存在且未加 ``--recreate`` 时**拒绝执行**（防半成品续写）；
3. 原件落盘缺失时**显式失败**而不是静默跳过（静默跳过会让一篇文档凭空少掉分块）；
4. 重复执行**幂等**（同代次先删后插，不产生重复行，也不撞 ``vector_id`` 唯一索引）。

另覆盖灰度与回滚的语义：``--cutover`` 只翻指针（旧代次行必须保留），
``--rollback`` 立即生效并把 ``doc.active_chunk_epoch`` 还原——若不还原，管理端的
分块列表会显示新一代内容而检索走旧集合，两者对不上。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.knowledge_processor import vector_id_for

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "rebuild_knowledge_vectors.py"

NEW_EPOCH = "448-64"
OLD_EPOCH = "1024-0"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("rebuild_knowledge_vectors_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rb = _load_script_module()


# ────────────────────────────── 夹具 ──────────────────────────────

@pytest.fixture()
def db():
    # ``autoflush=False`` 与生产的 ``app.core.database.sessionLocal`` 保持一致。
    # 用默认的 autoflush=True 会让「先改代次、再按代计数」这类顺序缺陷在测试里
    # 因为自动刷盘而**不可见**——线上曾因此落库出「doc 代次是 1024-0（301 行）、
    # kb.chunk_count 却是 635」的自相矛盾状态。
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            KnowledgeBase.__table__,
            KnowledgeDocument.__table__,
            KnowledgeChunk.__table__,
        ],
    )
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def _make_kb(session, kb_id="kb-1", tenant_id="t-1", chunk_count=0):
    kb = KnowledgeBase(
        id=kb_id,
        tenant_id=tenant_id,
        name="测试库",
        embedding_model="BAAI/bge-base-zh-v1.5",
        chunk_count=chunk_count,
        document_count=1,
    )
    session.add(kb)
    session.commit()
    return kb


def _make_doc(session, kb, path: Path, *, file_type="txt", chunk_count=0, epoch=None):
    doc = KnowledgeDocument(
        id="doc-1",
        tenant_id=kb.tenant_id,
        kb_id=kb.id,
        file_name=path.name,
        file_type=file_type,
        file_size=path.stat().st_size if path.exists() else 0,
        file_url=str(path),
        chunk_count=chunk_count,
        active_chunk_epoch=epoch,
    )
    session.add(doc)
    session.commit()
    return doc


def _make_source(tmp_path, text: str) -> Path:
    path = tmp_path / "sample.txt"
    path.write_text(text, encoding="utf-8")
    return path


class _FakeEmbeddingClient:
    DIM = 8

    def embed(self, texts):
        return [[0.0] * self.DIM for _ in texts]


class _FakeQdrant:
    def __init__(self, count: int = 0):
        self.upserts = []
        self._count = count

    def upsert(self, collection_name, points):
        self.upserts.append({"collection": collection_name, "points": list(points)})

    def count(self, collection_name, exact=True):
        return SimpleNamespace(count=self._count)

    @property
    def all_points(self):
        return [p for call in self.upserts for p in call["points"]]


@pytest.fixture()
def fake_io(monkeypatch):
    """替换嵌入与 Qdrant；返回替身以便断言写入内容"""
    qdrant = _FakeQdrant()
    monkeypatch.setattr(rb, "get_embedding_client", lambda model=None: _FakeEmbeddingClient())
    monkeypatch.setattr(rb, "get_qdrant_client", lambda: qdrant)
    return qdrant


# ────────────────────────────── 纯函数 ──────────────────────────────

class TestTargetCollectionName:
    def test_default_suffix_is_v2(self):
        """目标名必须是新名字：新旧两代要同时可查，回滚才有实体可回"""
        assert rb.target_collection_name("kb-1") == "kb_kb-1_v2"

    def test_override_wins(self):
        assert rb.target_collection_name("kb-1", "custom") == "custom"


class TestChunkDocument:
    def test_missing_file_raises_instead_of_skipping(self, db, tmp_path):
        """原件缺失必须显式失败——静默跳过会让文档在重建后凭空少掉分块"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, tmp_path / "missing.txt", file_type="txt")

        with pytest.raises(FileNotFoundError):
            rb.chunk_document(doc)

    def test_produces_chunks_with_metadata(self, db, tmp_path):
        kb = _make_kb(db)
        path = _make_source(tmp_path, "# 标题\n" + "内容。" * 400)
        doc = _make_doc(db, kb, path, file_type="md")

        chunks = rb.chunk_document(doc)

        assert len(chunks) > 1
        assert [c.index for c in chunks] == list(range(len(chunks)))
        assert chunks[0].heading_path == "标题"


# ────────────────────────────── 单篇重建 ──────────────────────────────

class TestRebuildDocument:
    def test_writes_new_generation_rows(self, db, tmp_path, fake_io):
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        doc.active_chunk_epoch = OLD_EPOCH
        db.commit()

        count = rb.rebuild_document(
            db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
            kb.embedding_model, NEW_EPOCH,
        )

        rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).all()
        assert count == len(rows) > 1
        assert {r.chunk_epoch for r in rows} == {NEW_EPOCH}
        assert all(r.vector_id == vector_id_for(doc.id, r.chunk_index, NEW_EPOCH) for r in rows)
        # 文档元数据同步翻代次，分块列表与库级计数才有据可依
        assert doc.chunk_count == count
        assert doc.active_chunk_epoch == NEW_EPOCH
        # 写入目标集合，且为混合布局的命名向量
        assert fake_io.upserts and fake_io.upserts[0]["collection"] == "kb_kb-1_v2"
        assert set(fake_io.all_points[0].vector) == {"dense", "text"}

    def test_legacy_generation_rows_are_preserved(self, db, tmp_path, fake_io):
        """重建**不得**动上一代的行：它们是回滚窗口的实体"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        doc.active_chunk_epoch = OLD_EPOCH
        db.add(KnowledgeChunk(tenant_id=kb.tenant_id, kb_id=kb.id, doc_id=doc.id,
                              content="旧块", chunk_index=0, chunk_epoch=OLD_EPOCH,
                              vector_id=vector_id_for(doc.id, 0, OLD_EPOCH)))
        db.commit()

        rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                            kb.embedding_model, NEW_EPOCH)

        legacy = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.doc_id == doc.id,
                    KnowledgeChunk.chunk_epoch == OLD_EPOCH)
            .all()
        )
        assert len(legacy) == 1

    def test_rerun_is_idempotent(self, db, tmp_path, fake_io):
        """重复执行必须幂等：同代次先删后插，不产生重复行、不撞唯一索引"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))

        first = rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                                    kb.embedding_model, NEW_EPOCH)
        second = rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                                     kb.embedding_model, NEW_EPOCH)

        assert first == second
        rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).all()
        assert len(rows) == first  # 没有翻倍

    def test_rejects_embedding_count_mismatch(self, db, tmp_path, monkeypatch):
        """嵌入数量与分块数量不一致时必须报错，而不是错位配对"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))

        class _Bad(_FakeEmbeddingClient):
            def embed(self, texts):
                return [[0.0] * self.DIM]

        monkeypatch.setattr(rb, "get_embedding_client", lambda model=None: _Bad())
        monkeypatch.setattr(rb, "get_qdrant_client", lambda: _FakeQdrant())

        with pytest.raises(ValueError, match="不匹配"):
            rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                                kb.embedding_model, NEW_EPOCH)


# ────────────────────────────── cutover / rollback / gc ──────────────────────────────

class TestCutover:
    def test_sets_pointer_and_recomputes_count(self, db, tmp_path, fake_io):
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        n = rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                                kb.embedding_model, NEW_EPOCH)
        fake_io._count = n

        rb.do_cutover(db, kb, "kb_kb-1_v2")

        assert kb.active_collection == "kb_kb-1_v2"
        assert kb.chunk_count == n
        # 切读把文档代次对齐到所服务的代次（与回滚对称）
        assert doc.active_chunk_epoch == rb.config.chunk_epoch
        # 旧代次行仍在（回滚窗口未关闭）
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_epoch != NEW_EPOCH).count() == 0  # 本夹具无旧代次行

    def test_cutover_does_not_invent_epoch_for_unrebuilt_documents(self, db, tmp_path, fake_io):
        """没被重建过的文档（没有当前代次的行）不得被写上当前代次"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400), epoch=OLD_EPOCH)
        db.add(KnowledgeChunk(tenant_id=kb.tenant_id, kb_id=kb.id, doc_id=doc.id,
                              content="旧块", chunk_index=0, chunk_epoch=OLD_EPOCH,
                              vector_id=vector_id_for(doc.id, 0, OLD_EPOCH)))
        db.commit()
        # 当前代次是 448-64，而该文档只有 1024-0 的行
        assert rb.config.chunk_epoch != OLD_EPOCH

        rb.do_cutover(db, kb, "kb_kb-1_v2")

        assert doc.active_chunk_epoch == OLD_EPOCH  # 未被编造


class TestRollback:
    def test_clears_pointer_and_restores_oldest_epoch(self, db, tmp_path, fake_io):
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        doc.active_chunk_epoch = OLD_EPOCH
        db.add(KnowledgeChunk(tenant_id=kb.tenant_id, kb_id=kb.id, doc_id=doc.id,
                              content="旧块", chunk_index=0, chunk_epoch=OLD_EPOCH,
                              vector_id=vector_id_for(doc.id, 0, OLD_EPOCH)))
        db.commit()
        rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                            kb.embedding_model, NEW_EPOCH)
        assert doc.active_chunk_epoch == NEW_EPOCH

        rb.do_rollback(db, kb, epoch=None)

        assert kb.active_collection is None
        assert doc.active_chunk_epoch == OLD_EPOCH  # 还原，避免列表与检索对不上
        assert kb.chunk_count == 1

    def test_explicit_epoch_is_honored_only_if_rows_exist(self, db, tmp_path, fake_io):
        """``--rollback-epoch`` 指向不存在的代次时不得凭空写上一个假代次"""
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                            kb.embedding_model, NEW_EPOCH)

        rb.do_rollback(db, kb, epoch="2030-1")

        assert doc.active_chunk_epoch == NEW_EPOCH  # 未变


class TestGcOldEpochs:
    def test_removes_only_non_current_generations(self, db, tmp_path, fake_io):
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        doc.active_chunk_epoch = OLD_EPOCH
        db.add(KnowledgeChunk(tenant_id=kb.tenant_id, kb_id=kb.id, doc_id=doc.id,
                              content="旧块", chunk_index=0, chunk_epoch=OLD_EPOCH,
                              vector_id=vector_id_for(doc.id, 0, OLD_EPOCH)))
        db.commit()
        rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                            kb.embedding_model, NEW_EPOCH)

        removed = rb.do_gc_old_epochs(db, kb, keep_epoch=NEW_EPOCH)

        assert removed == 1
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_epoch == OLD_EPOCH).count() == 0
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.chunk_epoch == NEW_EPOCH).count() > 0


# ────────────────────────────── main 的安全闸门 ──────────────────────────────

class TestMainSafetyGates:
    def test_dry_run_writes_nothing(self, db, tmp_path, fake_io, monkeypatch):
        """缺省（无 --execute）必须是只读：不写 MySQL、不写 Qdrant"""
        kb = _make_kb(db)
        _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)
        # 显式打桩，不依赖「本机 Qdrant 连不上」这一偶然事实
        monkeypatch.setattr(rb, "collection_exists", lambda name, client=None: False)
        monkeypatch.setattr(rb, "create_hybrid_collection",
                            lambda *a, **k: pytest.fail("干跑不应创建集合"))
        monkeypatch.setattr(rb, "get_qdrant_client", lambda: (_ for _ in ()).throw(
            AssertionError("干跑不应访问 Qdrant")))

        code = rb.main(["--kb-id", kb.id])

        assert code == 0
        assert db.query(KnowledgeChunk).count() == 0
        assert db.query(KnowledgeDocument).one().chunk_count == 0

    def test_execute_refuses_when_target_exists_without_recreate(self, db, tmp_path, fake_io, monkeypatch):
        """目标已存在时拒绝执行——半成品续写不会报错，只会留下点数少一半的集合"""
        kb = _make_kb(db)
        _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)
        monkeypatch.setattr(rb, "collection_exists", lambda name, client=None: True)
        monkeypatch.setattr(rb, "create_hybrid_collection",
                            lambda *a, **k: pytest.fail("不应创建集合"))

        with pytest.raises(SystemExit, match="目标集合已存在"):
            rb.main(["--kb-id", kb.id, "--execute"])

    def test_missing_kb_reports_actionable_error(self, db, monkeypatch):
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)
        with pytest.raises(SystemExit, match="知识库不存在"):
            rb.main(["--kb-id", "no-such-kb"])

    def test_parser_defaults_are_read_only(self):
        """``--execute`` / ``--cutover`` / ``--gc-old-epochs`` 默认必须为关"""
        args = rb.build_parser().parse_args(["--kb-id", "kb-1"])

        assert args.execute is False
        assert args.cutover is False
        assert args.rollback is False
        assert args.gc_old_epochs is False
        assert args.limit_docs is None


class TestActionSemantics:
    """切读 / 回滚 / 回收是三个互斥的运维动作，各自独立于重建"""

    def test_cutover_runs_without_execute(self, db, tmp_path, fake_io, monkeypatch):
        """``--cutover`` 单独执行必须真的切读

        回归守卫：曾把 cutover 判断放在 ``--execute`` 分支内部，于是单独执行
        ``--cutover`` 会**静默落入干跑分支**——打印一堆计划、什么都没做、
        退出码还是 0。这类「看起来成功」的失败最容易在生产上被忽略。
        """
        kb = _make_kb(db)
        doc = _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        n = rb.rebuild_document(db, doc, kb, "kb_kb-1_v2", rb.default_encoder(),
                                kb.embedding_model, NEW_EPOCH)
        fake_io._count = n
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)
        monkeypatch.setattr(rb, "collection_exists", lambda name, client=None: True)

        code = rb.main(["--kb-id", kb.id, "--cutover"])

        assert code == 0
        assert kb.active_collection == "kb_kb-1_v2"
        assert kb.chunk_count == n

    def test_cutover_requires_existing_target(self, db, tmp_path, fake_io, monkeypatch):
        """目标集合不存在时切读必须报错，而不是把指针指向一个空集合"""
        kb = _make_kb(db)
        _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)
        monkeypatch.setattr(rb, "collection_exists", lambda name, client=None: False)

        with pytest.raises(SystemExit, match="目标集合不存在"):
            rb.main(["--kb-id", kb.id, "--cutover"])

    def test_execute_cannot_be_combined_with_maintenance_actions(self, db, tmp_path, fake_io, monkeypatch):
        """``--execute --cutover`` 必须报错：先重建再切读是两步，混在一次调用里
        会让「重建完成」与「已切读」两件事无法分别验收"""
        kb = _make_kb(db)
        _make_doc(db, kb, _make_source(tmp_path, "内容。" * 400))
        monkeypatch.setattr(rb, "sessionLocal", lambda: db)

        with pytest.raises(SystemExit, match="--execute 只用于重建"):
            rb.main(["--kb-id", kb.id, "--execute", "--cutover"])

    def test_maintenance_actions_are_mutually_exclusive(self):
        """两个运维动作叠加会留下与预期不符的半成品状态，argparse 直接拒绝"""
        with pytest.raises(SystemExit):
            rb.build_parser().parse_args(["--kb-id", "kb-1", "--cutover", "--rollback"])
