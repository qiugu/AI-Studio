"""``KnowledgeBaseService.upload_document`` 的同库重复检测契约

「检索结果一半重复」的**源头**在写入侧：每次上传都会创建新的 ``doc_id``，而向量
id 由 ``uuid5(doc.id + index)`` 派生，副本之间互不覆盖，会各自在 Qdrant 中占一份
向量。检索侧去重只是对存量数据的兜底，堵源头必须靠上传拦截。因此这里断言三件事：

* 同名同大小的再次上传被**拒绝**，且消息给出已有文档 ID 与处置建议；
* 拒绝发生在任何写入之前（不建文档行、不搬文件、不派发异步任务）；
* 首次上传照常放行并派发处理任务——拦截不能误伤正常路径。

另有一条固化**已知局限**的用例：判定键只有 (kb_id, file_name, file_size)，
改名后重传同一份文件不会被识别。把它写成断言而非注释，是为了让日后引入内容哈希
时成为一次显式改动。

全部依赖以替身注入，不连 MySQL、不连 Celery。
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.exceptions import ValidationException
from app.services.knowledge import KnowledgeBaseService

KB_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "tenant-1"
#: 与下面写入临时文件的字节数严格一致，重复判定键包含 size
PDF_BYTES = b"%PDF-1.4 dummy"


def _build_service(duplicates, created, captured=None) -> KnowledgeBaseService:
    """构造只依赖替身的服务实例

    Args:
        duplicates: ``doc_repo.list`` 的返回值（模拟同库已存在的同名同大小文档）
        created: ``doc_repo.create`` 的返回值（模拟新建出的文档行）
        captured: 可选，用于回收传给 ``doc_repo.list`` 的过滤条件
    """

    def fake_list(**kwargs):
        if captured is not None:
            captured["filters"] = kwargs
        return duplicates

    service = KnowledgeBaseService(db=MagicMock(), tenant_id=TENANT)
    service.get_knowledge_base = lambda _kb_id: SimpleNamespace(
        id=KB_ID, tenant_id=TENANT, document_count=1, embedding_model="fake/model", active_collection=None
    )
    service.doc_repo = SimpleNamespace(list=fake_list, create=lambda **_kwargs: created)
    service.kb_repo = SimpleNamespace(update=lambda *_args, **_kwargs: None)
    return service


@pytest.fixture
def upload_env(monkeypatch, tmp_path):
    """把上传落盘目录指向临时目录，并拦掉 Celery 派发（不连 broker）"""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.config, "upload_dir", str(tmp_path / "uploads"), raising=False
    )
    dispatched: list[dict] = []
    monkeypatch.setattr(
        "app.services.knowledge.process_document_task",
        SimpleNamespace(delay=lambda **kwargs: dispatched.append(kwargs)),
    )
    return {"tmp_path": tmp_path, "dispatched": dispatched}


class TestDuplicateUploadRejected:
    def test_same_name_and_size_is_rejected_with_actionable_message(
        self, upload_env, tmp_path
    ):
        """同名同大小的再次上传必须被拒绝，并告知已有文档与处置方式"""
        src = tmp_path / "Happy-LLM-0727.pdf"
        src.write_bytes(PDF_BYTES)
        created = SimpleNamespace(id="doc-new")
        service = _build_service(
            duplicates=[SimpleNamespace(id="doc-existing")], created=created
        )

        with pytest.raises(ValidationException) as exc:
            service.upload_document(KB_ID, str(src), "Happy-LLM-0727.pdf", "pdf")

        detail = exc.value.detail
        assert "Happy-LLM-0727.pdf" in detail
        assert "doc-existing" in detail
        assert "删除" in detail  # 必须给出可执行的下一步，而非只说「重复」

    def test_rejection_happens_before_any_write(self, upload_env, tmp_path):
        """拒绝必须发生在建行 / 搬文件 / 派发任务之前，避免留下孤儿记录或文件"""
        src = tmp_path / "dup.pdf"
        src.write_bytes(PDF_BYTES)
        service = _build_service(
            duplicates=[SimpleNamespace(id="doc-existing")],
            created=SimpleNamespace(id="doc-new"),
        )
        create_calls: list[dict] = []
        service.doc_repo.create = lambda **kwargs: (
            create_calls.append(kwargs) or SimpleNamespace(id="doc-new")
        )

        with pytest.raises(ValidationException):
            service.upload_document(KB_ID, str(src), "dup.pdf", "pdf")

        assert create_calls == []
        assert upload_env["dispatched"] == []
        assert src.exists()  # 源文件未被搬走


class TestNormalUploadUnaffected:
    def test_first_upload_passes_and_dispatches_task(self, upload_env, tmp_path):
        """首次上传放行，并照常派发异步处理任务"""
        src = tmp_path / "new.pdf"
        src.write_bytes(PDF_BYTES)
        created = SimpleNamespace(id="doc-new")
        service = _build_service(duplicates=[], created=created)

        doc = service.upload_document(KB_ID, str(src), "new.pdf", "pdf")

        assert doc is created
        assert upload_env["dispatched"] == [
            {"doc_id": "doc-new", "file_path": doc.file_url, "tenant_id": TENANT}
        ]

    def test_duplicate_lookup_keys_on_kb_name_and_size(self, upload_env, tmp_path):
        """固化判定键为 (kb_id, file_name, file_size)

        这三项是「已知局限」的边界：改名后重传同一份文件不会被拦截。用断言锁住
        查询参数，使引入内容哈希成为一次显式改动，而不是悄悄扩大判定范围。
        """
        src = tmp_path / "new.pdf"
        src.write_bytes(PDF_BYTES)
        captured: dict = {}
        service = _build_service(
            duplicates=[], created=SimpleNamespace(id="doc-new"), captured=captured
        )

        service.upload_document(KB_ID, str(src), "new.pdf", "pdf")

        assert captured["filters"] == {
            "page": 1,
            "page_size": 1,
            "kb_id": KB_ID,
            "file_name": "new.pdf",
            "file_size": len(PDF_BYTES),
        }
