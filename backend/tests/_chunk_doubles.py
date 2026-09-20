"""``KnowledgeChunk`` 的测试替身工厂

为什么需要它
------------

``KnowledgeBaseService.search`` 会逐个读取出处字段（``source_page`` /
``source_page_end`` / ``heading_path`` / ``heading_path_mixed``）。此前四个检索测试
文件各自手写 ``SimpleNamespace`` 的字段列表，模型加列后**一定会静默过期**——
只有跑到读该列的用例才以 ``AttributeError`` 暴露，而且一次要改 N 个文件。

实测代价：新增 ``source_page_end`` 后，``test_knowledge_search_{rerank,hybrid,dedup,
diagnostics}.py`` 共 36 个用例同时失败，全部指向同一处替身缺字段。

因此这里把字段集**从 ORM 模型派生**（``KnowledgeChunk.__table__.columns``），
模型加列即自动跟随，不再需要逐个文件同步。

用法
----

    from tests._chunk_doubles import chunk_double

    chunk = chunk_double(vector_id="v1", id="chunk-v1", content="正文", chunk_index=0)

未显式覆盖的列一律为 ``None``；``heading_path_mixed`` 例外——它是 ``NOT NULL``，
故默认 ``False``（``None`` 会让「未覆盖」与「显式为 NULL」不可区分）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.models.knowledge_chunk import KnowledgeChunk


def chunk_double(**overrides: Any) -> SimpleNamespace:
    """构造一个分块替身，字段集从 ORM 模型派生

    Args:
        **overrides: 需要具体取值的字段。额外支持 ``document`` 键（关系字段，模型
            的列集合里没有它）：不传时补一个最小文档替身，让服务层读
            ``chunk.document.file_name`` 时不会炸；想模拟「孤立分块」可显式传
            ``document=None``。

    Returns:
        ``SimpleNamespace``：属性访问语义与 ORM 实例一致，但不触发任何数据库行为。
    """
    data: dict[str, Any] = {
        column.name: None for column in KnowledgeChunk.__table__.columns
    }
    # NOT NULL 且无服务端默认值的列必须给合理默认，否则服务层读到的 None 与实际
    # 语义不符（该列在库里不可能为 NULL）。
    data["heading_path_mixed"] = False
    data["document"] = SimpleNamespace(file_name="doc.pdf")
    data.update(overrides)
    return SimpleNamespace(**data)
