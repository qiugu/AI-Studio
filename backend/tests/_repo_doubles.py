"""``KnowledgeChunkRepository`` 的测试替身工厂

**为什么需要它**（与 ``_chunk_doubles.py`` 同源的问题，只是换了一层）

检索路径每新增一个仓储方法，各测试文件里手写的 ``SimpleNamespace`` / ``MagicMock``
替身就会整体失效。P4 新增 ``list_neighbors`` 后，4 个检索测试文件共 34 个用例同时
失败——失败形态是 ``AttributeError`` / ``TypeError``，与真正的业务断言失败混在
一起，定位成本远高于修复成本。

把替身收敛到一处后，新增仓储方法只需在这里实现一次；``_chunk_doubles.py`` 管
「一行长什么样」，本模块管「仓储怎么答」。

用法::

    from tests._repo_doubles import chunk_repo_double

    service.chunk_repo = chunk_repo_double([c1, c2])                  # 只答查询
    calls = []
    service.chunk_repo = chunk_repo_double([c1, c2], calls=calls)     # 顺带记录调用
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, List, Optional, Sequence


def chunk_repo_double(
    chunks: Iterable[Any] = (),
    *,
    calls: Optional[List[dict]] = None,
    neighbor_rows: Optional[Sequence[Any]] = None,
) -> SimpleNamespace:
    """构造 KnowledgeChunkRepository 替身（纯内存，不连数据库）

    Args:
        chunks: 可见的分块行。替身对象或 ORM 实例均可，只需具备 ``vector_id`` /
            ``doc_id`` / ``chunk_epoch`` / ``chunk_index`` 属性。
        calls: 传入一个列表即可记录每次 ``list_neighbors`` 的实参——用于断言
            「按 (文档, 代次) 归组」「代次取自命中块」这类**实现约定**。
        neighbor_rows: 覆写邻块查询的返回（模拟「邻块行已被清理/软删」）。
            缺省时按 ``chunks`` 过滤，语义与真实仓储一致：
            **文档 + 代次 + 下标集合**三个条件都必须满足。

    Returns:
        ``SimpleNamespace``，含 ``list_by_vector_ids`` 与 ``list_neighbors``。

    Note:
        ``neighbor_rows`` 走参数而非事后改属性：闭包在构造时即绑定实参，事后改
        ``harness.neighbor_rows`` 不会生效——这类「改了没反应」在测试里会伪装成
        「功能没实现」。
    """
    rows: List[Any] = list(chunks)

    def list_by_vector_ids(vector_ids):
        wanted = set(vector_ids)
        return [row for row in rows if row.vector_id in wanted]

    def list_neighbors(doc_id: str, chunk_epoch: str, chunk_indexes):
        if calls is not None:
            calls.append(
                {
                    "doc_id": doc_id,
                    "chunk_epoch": chunk_epoch,
                    "chunk_indexes": list(chunk_indexes),
                }
            )
        if neighbor_rows is not None:
            return list(neighbor_rows)
        wanted_indexes = set(chunk_indexes)
        return sorted(
            [
                row
                for row in rows
                if row.doc_id == doc_id
                and row.chunk_epoch == chunk_epoch
                and row.chunk_index in wanted_indexes
            ],
            key=lambda row: row.chunk_index,
        )

    return SimpleNamespace(
        list_by_vector_ids=list_by_vector_ids,
        list_neighbors=list_neighbors,
    )
