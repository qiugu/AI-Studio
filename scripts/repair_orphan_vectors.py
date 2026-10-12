#!/usr/bin/env python
"""MySQL 分块/文档计数与 Qdrant 向量的一致性校准工具（D9 存量数据处置）

背景
----
``KnowledgeBaseService.delete_document`` 历史上存在两个叠加缺陷：

1. **仅软删除文档，未级联软删除分块**——``knowledge_chunks.deleted_at`` 保持 NULL，
   而检索回表路径（``KnowledgeChunkRepository.list_by_vector_ids``）的过滤条件正是
   ``deleted_at IS NULL``。过滤逻辑本身正确，失效原因是写入侧从未把分块标记为已删除。
   后果：**已下架文档的分块仍会被检索命中并进入回答上下文**。
2. **向量删除静默失败**（缺陷编号 A2）——``points_selector`` 传入了裸字符串，
   qdrant-client 抛 ``ValueError``，而调用处 ``except Exception: pass`` 将其吞掉。
   后果：向量残留在 Qdrant 中，占用存储并污染召回池。

两者叠加使得「删除文档」在生产上**既不生效于召回、也不释放向量**。

缺陷 1 现已**在结构上不可能复现**：``knowledge_chunks`` 取消了软删列（分块是派生
数据，见 ``app/models/knowledge_chunk.py``），删除文档时级联**物理删除**分块，因此
不存在「文档已下架、分块仍存活」这一状态可被写入。但**历史遗留行仍可能存在**，
且缺陷 2 形态的残留（Qdrant 删除失败、人工直接改库、进程崩溃于两次写入之间）
与软删无关、会长期存在。故本工具保留，并作为一致性兜底定期运行。

P3-I 扩展｜冗余计数字段漂移
--------------------------
除上述两类「实体」不一致外，三个冗余计数字段也可能与真实存量脱节：

* ``knowledge_bases.document_count``
* ``knowledge_bases.chunk_count``
* ``knowledge_documents.chunk_count``

它们只用于前端展示与配额判断，不影响召回正确性，但会导致「界面上还有 12 个分块、
实际只有 3 个」这类误导，并让容量规划失真。本工具新增 ``collect_counter_drift``
做三方比对，并可通过 ``--execute`` 一并回写。

安全设计
--------
- **默认只读**：不加 ``--execute`` 时仅输出诊断报告，不产生任何写入。
- **幂等**：重复执行不会产生额外副作用（残留分块被删除后，再次诊断即不再命中）。
- **可审计**：执行前完整打印待处理清单与数量，便于人工核对。
- **纳管闸门（关键）**：只对「存在对应 ``knowledge_bases`` 记录」的 ``kb_*`` 集合
  做孤儿判定。**MySQL 中不存在同名知识库的集合一律跳过、绝不删除**，仅在报告中
  以「未纳管集合」列出。理由：``kb_rageval_t2r`` 这类 RAG 评测语料由
  ``scripts/index_rag_eval_corpus.py`` **直接写 Qdrant、从不写 MySQL**，其全部
  point 天然「无对应分块」。缺此闸门时，孤儿判定会把 28771 个评测向量全部判为
  孤儿并在 ``--execute`` 时删除，**评测索引被不可逆摧毁**。
- **计数修正始终后置且重新采样**：执行路径先完成「软删孤儿分块 + 删向量」，**再**
  重新采集真实存量回写计数字段。若沿用修复前采样的值，会把「修复前的正确值」
  写回去，在本轮修复改变了真实存量时反而制造新的偏差。
- **不越界**：只处理未软删的知识库；软删知识库的计数字段不再维护（无展示意义），
  但其集合仍参与向量清理（残留向量属真实垃圾）。

用法
----
    # 只读诊断（默认）
    python scripts/repair_orphan_vectors.py

    # 实际执行修复
    python scripts/repair_orphan_vectors.py --execute

    # 仅校准指定知识库
    python scripts/repair_orphan_vectors.py --kb-id <uuid> --execute

退出码
------
``0`` 正常（含「无需修复」）；``1`` 修复过程中出现错误；``2`` 参数或环境错误。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

COLLECTION_PREFIX = "kb_"
SCROLL_BATCH = 512

# 计数字段所在表：键为内部 scope，值为**代码内固定字面量**（绝不由外部输入拼接，
# 否则 UPDATE 语句的表名将成为注入面）。
COUNTER_TABLES: Dict[str, str] = {"kb": "knowledge_bases", "doc": "knowledge_documents"}


# ────────────────────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class StaleChunk:
    """已下架文档（``knowledge_documents.deleted_at`` 非空）之下、却仍有行存在的分块

    取消分块软删之后这类行只应来自**历史遗留**：新代码在删除文档时会一并物理删除
    分块。命中即说明是改造前留下的残留，或有人绕过服务层直接改库。
    """

    chunk_id: str
    vector_id: Optional[str]
    doc_id: str
    kb_id: str


@dataclass
class CounterDrift:
    """冗余计数字段与真实存量的偏差

    ``stored`` / ``actual`` 为**同构字典**，键即被校准表的计数字段名，
    便于统一渲染与统一回写：

    * ``scope="kb"``  → ``{"document_count": …, "chunk_count": …}``
    * ``scope="doc"`` → ``{"chunk_count": …}``
    """

    scope: str  # "kb" | "doc"
    target_id: str
    kb_id: str
    label: str  # 知识库名 / 文档名，仅用于人工核对
    stored: Dict[str, int]
    actual: Dict[str, int]

    @property
    def corrections(self) -> Dict[str, int]:
        """需要回写的字段 → 目标值（仅含确有偏差的字段）

        未偏差的字段不进入 UPDATE 语句：既缩小写入面，也让日志只呈现真实变化。
        """
        return {
            name: self.actual[name]
            for name, current in self.stored.items()
            if current != self.actual.get(name)
        }

    def describe(self) -> str:
        return "; ".join(
            f"{name}: {self.stored[name]} → {self.actual[name]}" for name in self.corrections
        )


@dataclass
class RepairPlan:
    """一次校准的全部待处理项"""

    stale_chunks: List[StaleChunk] = field(default_factory=list)
    #: ``{collection_name: [point_id, ...]}``
    orphan_points: Dict[str, List[str]] = field(default_factory=dict)
    counter_drifts: List[CounterDrift] = field(default_factory=list)
    #: Qdrant 中存在、但 MySQL 无对应知识库的 ``kb_*`` 集合。**只报告，不处理**——
    #: 它们可能是纯向量索引（如 RAG 评测语料），删除即数据丢失。
    unknown_collections: List[str] = field(default_factory=list)

    @property
    def n_stale_chunks(self) -> int:
        return len(self.stale_chunks)

    @property
    def n_orphan_points(self) -> int:
        return sum(len(ids) for ids in self.orphan_points.values())

    @property
    def n_counter_drifts(self) -> int:
        return len(self.counter_drifts)

    @property
    def is_clean(self) -> bool:
        """是否无需修复

        ``unknown_collections`` **不参与**判定：它们不是「待修复项」，
        而是「不可自动处置、需人工确认归属」的信息项。若纳入判定，
        工具会在每次都提示「不一致」，诱使运维对纯向量索引执行删除。
        """
        return not self.stale_chunks and not self.orphan_points and not self.counter_drifts

    def points_to_purge(self) -> Dict[str, List[str]]:
        """本次修复实际需要删除的向量，按 collection 分组

        **不能用 ``orphan_points`` 代替**：失效分块对应的向量在诊断阶段仍映射得到
        一条分块行，因此不会被判定为孤儿。若只删 ``orphan_points``，这些向量会被
        静默漏掉，MySQL 侧看似修好、Qdrant 侧依旧残留。故此处显式合并两类来源。
        """
        merged: Dict[str, List[str]] = {name: list(ids) for name, ids in self.orphan_points.items()}
        for chunk in self.stale_chunks:
            if not chunk.vector_id:
                continue
            collection = f"{COLLECTION_PREFIX}{chunk.kb_id}"
            bucket = merged.setdefault(collection, [])
            if chunk.vector_id not in bucket:
                bucket.append(chunk.vector_id)
        return merged


# ────────────────────────────────────────────────────────────────────────────
# 诊断｜实体不一致
# ────────────────────────────────────────────────────────────────────────────


def collect_stale_chunks(db: Session, kb_id: Optional[str] = None) -> List[StaleChunk]:
    """收集「文档已软删、分块行仍存在」的分块

    这类行是 D9 时代的遗留：当时分块只有软删列、且写入侧从未级联标记它。如今删除
    文档会级联物理删除分块，因此**新代码不会再产出**这类行；命中即说明是历史残留
    或被绕过的写入，处理方式是物理删除（连同其向量）。
    """
    sql = """
        SELECT c.id, c.vector_id, c.doc_id, c.kb_id
        FROM knowledge_chunks AS c
        JOIN knowledge_documents AS d ON c.doc_id = d.id
        WHERE d.deleted_at IS NOT NULL
    """
    params: Dict[str, str] = {}
    if kb_id:
        sql += " AND c.kb_id = :kb_id"
        params["kb_id"] = kb_id

    rows = db.execute(text(sql), params).fetchall()
    return [
        StaleChunk(chunk_id=row[0], vector_id=row[1], doc_id=row[2], kb_id=row[3])
        for row in rows
    ]


def _scroll_all_point_ids(client, collection_name: str) -> List[str]:
    """分批拉取 collection 内的全部 point id（只取 id，不取 payload/vector）"""
    ids: List[str] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=SCROLL_BATCH,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        ids.extend(str(point.id) for point in points)
        if offset is None:
            break
    return ids


def list_qdrant_collections(client) -> List[str]:
    """Qdrant 中全部 ``kb_*`` 集合名"""
    return [
        item.name
        for item in client.get_collections().collections
        if item.name.startswith(COLLECTION_PREFIX)
    ]


def collect_managed_collections(db: Session, kb_id: Optional[str] = None) -> Set[str]:
    """应用纳管的集合名集合：存在对应 ``knowledge_bases`` 记录的 ``kb_*`` 集合

    **软删知识库也计入纳管**：其残留向量是真实垃圾，应当清理；仅其计数字段不再维护。
    """
    sql = "SELECT id FROM knowledge_bases"
    params: Dict[str, str] = {}
    if kb_id:
        sql += " WHERE id = :kb_id"
        params["kb_id"] = kb_id
    return {
        f"{COLLECTION_PREFIX}{row[0]}" for row in db.execute(text(sql), params).fetchall()
    }


def find_unknown_collections(db: Session, client, kb_id: Optional[str] = None) -> List[str]:
    """Qdrant 中存在、但 MySQL 无对应知识库的 ``kb_*`` 集合

    典型实例：``kb_rageval_t2r``（RAG 评测语料，纯向量索引）。
    这些集合**不在孤儿清理范围内**，只作信息项报告，提醒人工确认归属。
    """
    managed = collect_managed_collections(db)
    if kb_id:
        candidates = [f"{COLLECTION_PREFIX}{kb_id}"]
    else:
        candidates = list_qdrant_collections(client)
    return sorted(name for name in candidates if name not in managed)


def collect_orphan_points(
    db: Session,
    client,
    kb_id: Optional[str] = None,
) -> Dict[str, List[str]]:
    """收集 Qdrant 中「无对应存活分块」的孤儿向量

    判定口径：Qdrant 的 point id 必须能映射到一条 ``knowledge_chunks`` 记录；
    否则即为孤儿。该定义天然覆盖三种来源：删除文档时向量清理失败、
    分块行被删除而向量未同步、以及历史遗留的残留向量。

    注意「文档已软删、分块行仍在」**不**在此处判定——那属于 :func:`collect_stale_chunks`
    的职责，两类来源在 :meth:`RepairPlan.points_to_purge` 中取并集，故不会漏删。

    **纳管闸门**：仅对 ``collect_managed_collections`` 认可的集合做判定。
    无对应 ``knowledge_bases`` 记录的集合（如纯向量评测索引）全部跳过——
    其 point 天然无分块，若纳入判定会在 ``--execute`` 时被整批误删。
    """
    # 分块表已无软删列：行存在即「非孤儿」，故不再有 deleted_at 条件。
    alive_sql = "SELECT vector_id FROM knowledge_chunks WHERE vector_id IS NOT NULL"
    params: Dict[str, str] = {}
    if kb_id:
        alive_sql += " AND kb_id = :kb_id"
        params["kb_id"] = kb_id

    alive: Set[str] = {row[0] for row in db.execute(text(alive_sql), params).fetchall()}

    managed = collect_managed_collections(db, kb_id)
    if kb_id:
        candidates = [f"{COLLECTION_PREFIX}{kb_id}"]
    else:
        candidates = list_qdrant_collections(client)

    orphans: Dict[str, List[str]] = {}
    for name in candidates:
        if name not in managed:
            # 静默跳过：可读性由 print_plan 的「未纳管集合」段落统一呈现，
            # 避免同一事实在诊断与报告两处重复输出。
            continue
        try:
            point_ids = _scroll_all_point_ids(client, name)
        except Exception as exc:  # noqa: BLE001 - 单个 collection 异常不应中断整体诊断
            print(f"[warn] 读取 collection {name} 失败，已跳过：{exc}")
            continue
        missing = [pid for pid in point_ids if pid not in alive]
        if missing:
            orphans[name] = missing
    return orphans


# ────────────────────────────────────────────────────────────────────────────
# 诊断｜计数字段漂移（P3-I 扩展）
# ────────────────────────────────────────────────────────────────────────────

# 「真实文档数」= 未软删文档；「真实分块数」= 分块属于**文档的当前代**
# （``chunk_epoch = active_chunk_epoch``）且其文档存活。
#
# 为什么必须带代次条件：重建期间新旧两代分块行会同时存活（旧行支撑回滚窗口），
# 不带代次的 ``COUNT(*)`` 会把两代一起算进去，于是每次重建后台账都会显示
# 「计数漂移」——一条永远修不掉、也永远不该修的假告警。
# 带条件后口径与 ``kb.chunk_count`` / ``doc.chunk_count`` 的维护语义一致
# （它们记录的都是「当前代」的块数）。
_LIVE_DOC_COUNT_SQL = """
    SELECT kb_id, COUNT(*) FROM knowledge_documents
    WHERE deleted_at IS NULL
    GROUP BY kb_id
"""

_LIVE_CHUNK_COUNT_SQL = """
    SELECT d.kb_id, COUNT(*)
    FROM knowledge_chunks AS c
    JOIN knowledge_documents AS d ON d.id = c.doc_id AND d.deleted_at IS NULL
    WHERE c.chunk_epoch = d.active_chunk_epoch
    GROUP BY d.kb_id
"""

_KB_COUNTER_SQL = """
    SELECT kb.id, kb.name, kb.document_count, kb.chunk_count
    FROM knowledge_bases AS kb
    WHERE kb.deleted_at IS NULL
"""

_DOC_COUNTER_SQL = """
    SELECT d.id, d.kb_id, d.file_name, d.chunk_count, COALESCE(cnt.n, 0) AS actual_chunks
    FROM knowledge_documents AS d
    LEFT JOIN (
        SELECT c.doc_id, COUNT(*) AS n
        FROM knowledge_chunks AS c
        JOIN knowledge_documents AS dd ON dd.id = c.doc_id
        WHERE c.chunk_epoch = dd.active_chunk_epoch
        GROUP BY c.doc_id
    ) AS cnt ON cnt.doc_id = d.id
    WHERE d.deleted_at IS NULL
"""


def collect_kb_counter_drift(db: Session, kb_id: Optional[str] = None) -> List[CounterDrift]:
    """知识库级计数字段（``document_count`` / ``chunk_count``）漂移

    统计口径为全表聚合，再用字典查表取值：``--kb-id`` 只用于收窄**输出**范围，
    不改变聚合的语义，避免「收窄查询」与「全量口径」两套实现产生分歧。
    """
    sql = _KB_COUNTER_SQL
    params: Dict[str, str] = {}
    if kb_id:
        sql += " AND kb.id = :kb_id"
        params["kb_id"] = kb_id

    live_docs = {row[0]: row[1] for row in db.execute(text(_LIVE_DOC_COUNT_SQL)).fetchall()}
    live_chunks = {row[0]: row[1] for row in db.execute(text(_LIVE_CHUNK_COUNT_SQL)).fetchall()}

    drifts: List[CounterDrift] = []
    for row in db.execute(text(sql), params).fetchall():
        target_id, name = row[0], row[1]
        stored = {"document_count": row[2] or 0, "chunk_count": row[3] or 0}
        actual = {
            "document_count": live_docs.get(target_id, 0),
            "chunk_count": live_chunks.get(target_id, 0),
        }
        if stored != actual:
            drifts.append(CounterDrift("kb", target_id, target_id, name, stored, actual))
    return drifts


def collect_doc_counter_drift(db: Session, kb_id: Optional[str] = None) -> List[CounterDrift]:
    """文档级计数字段（``chunk_count``）漂移"""
    sql = _DOC_COUNTER_SQL
    params: Dict[str, str] = {}
    if kb_id:
        sql += " AND d.kb_id = :kb_id"
        params["kb_id"] = kb_id

    drifts: List[CounterDrift] = []
    for row in db.execute(text(sql), params).fetchall():
        target_id, row_kb_id, file_name = row[0], row[1], row[2]
        stored = {"chunk_count": row[3] or 0}
        actual = {"chunk_count": row[4] or 0}
        if stored != actual:
            drifts.append(
                CounterDrift("doc", target_id, row_kb_id, file_name, stored, actual)
            )
    return drifts


def collect_counter_drift(db: Session, kb_id: Optional[str] = None) -> List[CounterDrift]:
    """三方比对：KB 文档数、KB 分块数、文档分块数"""
    return collect_kb_counter_drift(db, kb_id) + collect_doc_counter_drift(db, kb_id)


def build_plan(db: Session, client, kb_id: Optional[str] = None) -> RepairPlan:
    return RepairPlan(
        stale_chunks=collect_stale_chunks(db, kb_id),
        orphan_points=collect_orphan_points(db, client, kb_id),
        counter_drifts=collect_counter_drift(db, kb_id),
        unknown_collections=find_unknown_collections(db, client, kb_id),
    )


# ────────────────────────────────────────────────────────────────────────────
# 执行
# ────────────────────────────────────────────────────────────────────────────


def _apply_counter_drift(db: Session, drift: CounterDrift) -> int:
    """回写单个计数字段漂移，返回被修正的字段数

    表名取自 ``COUNTER_TABLES`` 固定映射，字段名取自本模块构造的 ``corrections``
    键集合，二者均非外部输入，故字符串拼接不构成注入面。
    """
    corrections = drift.corrections
    if not corrections:
        return 0
    table = COUNTER_TABLES[drift.scope]
    assignments = ", ".join(f"{name} = :{name}" for name in corrections)
    db.execute(
        text(f"UPDATE {table} SET {assignments} WHERE id = :target_id"),
        {**corrections, "target_id": drift.target_id},
    )
    print(f"  [mysql] {drift.scope}={drift.target_id[:8]}… {drift.describe()}")
    return len(corrections)


def execute_plan(
    db: Session,
    client,
    plan: RepairPlan,
    kb_id: Optional[str] = None,
) -> None:
    """执行修复：先删除残留分块行，再删除孤儿向量，最后重新采样并回写计数字段

    顺序说明：

    1. 先删分块行使 MySQL 侧立即一致，同时释放其 ``vector_id`` 唯一索引占用；
    2. 随后删除向量；两步均基于已固定的待处理清单，不受中途状态变化影响；
    3. 计数字段**必须最后处理且重新采样**——前两步改变了真实存量，
       沿用诊断阶段的采样值会把过期数值写回去。

    分块行是**物理删除**（``knowledge_chunks`` 已无软删列）：留着软删行只会让
    ``vector_id`` 永远被占，且让「某文档有多少分块」的统计持续偏离事实。
    """
    from qdrant_client.models import PointIdsList

    # 1) 按 doc_id 分组批量删除残留分块行
    doc_ids = sorted({chunk.doc_id for chunk in plan.stale_chunks})
    for doc_id in doc_ids:
        result = db.execute(
            text("DELETE FROM knowledge_chunks WHERE doc_id = :doc_id"),
            {"doc_id": doc_id},
        )
        print(f"  [mysql] doc={doc_id[:8]}… 删除残留分块 {result.rowcount} 条")

    # 2) 删除向量：既含诊断阶段已判定的孤儿，也含本次删除分块对应的向量。
    #    务必用 points_to_purge() 而非 orphan_points——后者会漏掉「因本次删除
    #    分块才成为孤儿」的向量（它们在前一步之前仍能映射到分块行）。
    for collection_name, point_ids in plan.points_to_purge().items():
        client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=point_ids),
        )
        print(f"  [qdrant] {collection_name} 删除向量 {len(point_ids)} 个")

    db.commit()

    # 3) 计数字段：重新采样后回写（见函数 docstring 顺序说明第 3 点）
    refreshed = collect_counter_drift(db, kb_id)
    fixed_fields = 0
    for drift in refreshed:
        fixed_fields += _apply_counter_drift(db, drift)
    if refreshed:
        db.commit()
        print(f"  [mysql] 计数字段修正 {len(refreshed)} 处（{fixed_fields} 个字段）")


# ────────────────────────────────────────────────────────────────────────────
# 呈现
# ────────────────────────────────────────────────────────────────────────────


def print_plan(plan: RepairPlan, execute: bool) -> None:
    print("=" * 66)
    print("一致性校准诊断报告")
    print("=" * 66)
    print(f"残留分块（文档已下架、分块行仍在）：{plan.n_stale_chunks} 条")
    print(f"孤儿向量（Qdrant 有、MySQL 无有效分块）：{plan.n_orphan_points} 个")
    print(f"计数字段漂移（冗余计数与实际存量不符）：{plan.n_counter_drifts} 处")
    if plan.unknown_collections:
        print(
            f"未纳管集合（Qdrant 有、MySQL 无对应知识库）：{len(plan.unknown_collections)} 个"
            " —— 不参与清理，请人工确认归属"
        )
        for name in plan.unknown_collections:
            print(f"    - {name}")
    if plan.stale_chunks:
        by_doc: Dict[str, int] = {}
        for chunk in plan.stale_chunks:
            by_doc[chunk.doc_id] = by_doc.get(chunk.doc_id, 0) + 1
        for doc_id, count in sorted(by_doc.items()):
            print(f"    - doc={doc_id[:8]}…: {count} 条")
    for drift in plan.counter_drifts:
        scope_label = "知识库" if drift.scope == "kb" else "文档"
        print(f"    - {scope_label} {drift.target_id[:8]}…（{drift.label}）{drift.describe()}")
    purge = plan.points_to_purge()
    if purge:
        total = sum(len(ids) for ids in purge.values())
        print(f"本次将删除的向量合计：{total} 个")
        for collection_name, point_ids in purge.items():
            print(f"    - {collection_name}: {len(point_ids)} 个")
    print("-" * 66)
    if plan.is_clean:
        print("结论：数据一致，无需修复。")
    elif execute:
        print("结论：将执行上述修复（--execute 已启用）。")
    else:
        print("结论：存在不一致。当前为**只读诊断**，未做任何修改。")
        print("      确认无误后加 --execute 执行修复。")
    print("=" * 66)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repair_orphan_vectors",
        description=(
            "校准 MySQL 分块/文档计数与 Qdrant 向量的一致性（D9 存量数据处置 + P3-I 计数对齐）"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--execute", action="store_true", help="实际执行修复（默认只读诊断）")
    parser.add_argument("--kb-id", default=None, help="仅校准指定知识库；缺省则扫描全部 kb_* collection")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    from app.core.database import sessionLocal
    from app.core.vector_db import get_qdrant_client

    db = sessionLocal()
    try:
        client = get_qdrant_client()
        plan = build_plan(db, client, args.kb_id)
        print_plan(plan, execute=args.execute)
        if plan.is_clean or not args.execute:
            return 0
        execute_plan(db, client, plan, kb_id=args.kb_id)
    except Exception as exc:  # noqa: BLE001 - CLI 顶层需给出明确错误与退出码
        db.rollback()
        print(f"[error] 修复失败已回滚：{exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    # 修复后复检
    print()
    print("修复后复检：")
    db = sessionLocal()
    try:
        client = get_qdrant_client()
        remaining = build_plan(db, client, args.kb_id)
        print_plan(remaining, execute=False)
        return 0 if remaining.is_clean else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
