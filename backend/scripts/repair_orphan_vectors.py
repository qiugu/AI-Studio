#!/usr/bin/env python
"""MySQL 分块与 Qdrant 向量的一致性校准工具（D9 存量数据处置）

背景
----
``KnowledgeBaseService.delete_document`` 在修复前存在两个叠加缺陷：

1. **仅软删除文档，未级联软删除分块**——``knowledge_chunks.deleted_at`` 保持 NULL，
   而检索回表路径（``KnowledgeChunkRepository.list_by_vector_ids``）的过滤条件正是
   ``deleted_at IS NULL``。过滤逻辑本身正确，失效原因是写入侧从未把分块标记为已删除。
   后果：**已下架文档的分块仍会被检索命中并进入回答上下文**。
2. **向量删除静默失败**（缺陷编号 A2）——``points_selector`` 传入了裸字符串，
   qdrant-client 抛 ``ValueError``，而调用处 ``except Exception: pass`` 将其吞掉。
   后果：向量残留在 Qdrant 中，占用存储并污染召回池。

两者叠加使得「删除文档」在生产上**既不生效于召回、也不释放向量**。代码侧已修复；
本工具用于修复**修复前遗留的存量数据**，并可长期作为一致性兜底工具定期运行。

安全设计
--------
- **默认只读**：不加 ``--execute`` 时仅输出诊断报告，不产生任何写入。
- **幂等**：重复执行不会产生额外副作用（已软删的分块不会被二次处理）。
- **可审计**：执行前完整打印待处理清单与数量，便于人工核对。
- **不碰 KB 计数**：``knowledge_bases`` 的 ``document_count`` / ``chunk_count``
  在删除时已由业务代码维护，本工具不介入，避免重复扣减。

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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

COLLECTION_PREFIX = "kb_"
SCROLL_BATCH = 512


# ────────────────────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class StaleChunk:
    """已下架文档之下、却仍存活（``deleted_at IS NULL``）的分块"""

    chunk_id: str
    vector_id: Optional[str]
    doc_id: str
    kb_id: str


@dataclass
class RepairPlan:
    """一次校准的全部待处理项"""

    stale_chunks: List[StaleChunk] = field(default_factory=list)
    #: ``{collection_name: [point_id, ...]}``
    orphan_points: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def n_stale_chunks(self) -> int:
        return len(self.stale_chunks)

    @property
    def n_orphan_points(self) -> int:
        return sum(len(ids) for ids in self.orphan_points.values())

    @property
    def is_clean(self) -> bool:
        return not self.stale_chunks and not self.orphan_points

    def points_to_purge(self) -> Dict[str, List[str]]:
        """本次修复实际需要删除的向量，按 collection 分组

        **不能用 ``orphan_points`` 代替**：失效分块对应的向量在诊断阶段
        仍能映射到「存活」分块（正因为它们尚未被软删），因此不会被判定为孤儿。
        它们要在软删**之后**才成为孤儿——若只删 ``orphan_points``，这些向量会被
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
# 诊断
# ────────────────────────────────────────────────────────────────────────────


def collect_stale_chunks(db: Session, kb_id: Optional[str] = None) -> List[StaleChunk]:
    """收集「文档已软删、分块仍存活」的分块

    这是 D9 的直接体现：分块的 ``deleted_at`` 未被级联标记，
    导致检索侧 ``deleted_at IS NULL`` 过滤无法将其排除。
    """
    sql = """
        SELECT c.id, c.vector_id, c.doc_id, c.kb_id
        FROM knowledge_chunks AS c
        JOIN knowledge_documents AS d ON c.doc_id = d.id
        WHERE d.deleted_at IS NOT NULL
          AND c.deleted_at IS NULL
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


def collect_orphan_points(
    db: Session,
    client,
    kb_id: Optional[str] = None,
) -> Dict[str, List[str]]:
    """收集 Qdrant 中「无对应存活分块」的孤儿向量

    判定口径：Qdrant 的 point id 必须能映射到一条
    ``knowledge_chunks.deleted_at IS NULL`` 的记录；否则即为孤儿。
    该定义天然覆盖三种来源：软删文档的残留向量、删除后未清理的向量、
    以及分块被硬删但向量未同步的情形。
    """
    alive_sql = "SELECT vector_id FROM knowledge_chunks WHERE deleted_at IS NULL AND vector_id IS NOT NULL"
    params: Dict[str, str] = {}
    if kb_id:
        alive_sql += " AND kb_id = :kb_id"
        params["kb_id"] = kb_id

    alive: Set[str] = {row[0] for row in db.execute(text(alive_sql), params).fetchall()}

    if kb_id:
        collections = [f"{COLLECTION_PREFIX}{kb_id}"]
    else:
        collections = [
            item.name
            for item in client.get_collections().collections
            if item.name.startswith(COLLECTION_PREFIX)
        ]

    orphans: Dict[str, List[str]] = {}
    for name in collections:
        try:
            point_ids = _scroll_all_point_ids(client, name)
        except Exception as exc:  # noqa: BLE001 - 单个 collection 异常不应中断整体诊断
            print(f"[warn] 读取 collection {name} 失败，已跳过：{exc}")
            continue
        missing = [pid for pid in point_ids if pid not in alive]
        if missing:
            orphans[name] = missing
    return orphans


def build_plan(db: Session, client, kb_id: Optional[str] = None) -> RepairPlan:
    return RepairPlan(
        stale_chunks=collect_stale_chunks(db, kb_id),
        orphan_points=collect_orphan_points(db, client, kb_id),
    )


# ────────────────────────────────────────────────────────────────────────────
# 执行
# ────────────────────────────────────────────────────────────────────────────


def execute_plan(db: Session, client, plan: RepairPlan, deleted_at: Optional[datetime] = None) -> None:
    """执行修复：先软删分块，再删除孤儿向量

    顺序说明：先软删分块可使 MySQL 侧立即一致（检索不再命中）；
    随后删除向量。两步均基于已固定的待处理清单，不受中途状态变化影响。
    """
    from qdrant_client.models import PointIdsList

    stamp = deleted_at or datetime.utcnow()

    # 1) 按 doc_id 分组批量软删分块
    doc_ids = sorted({chunk.doc_id for chunk in plan.stale_chunks})
    for doc_id in doc_ids:
        result = db.execute(
            text(
                "UPDATE knowledge_chunks SET deleted_at = :stamp "
                "WHERE doc_id = :doc_id AND deleted_at IS NULL"
            ),
            {"stamp": stamp, "doc_id": doc_id},
        )
        print(f"  [mysql] doc={doc_id[:8]}… 软删分块 {result.rowcount} 条")

    # 2) 删除向量：既含诊断阶段已判定的孤儿，也含本次软删分块对应的向量。
    #    务必用 points_to_purge() 而非 orphan_points——后者会漏掉「因本次软删
    #    才成为孤儿」的向量（它们在前一步之前仍能映射到存活分块）。
    for collection_name, point_ids in plan.points_to_purge().items():
        client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=point_ids),
        )
        print(f"  [qdrant] {collection_name} 删除向量 {len(point_ids)} 个")

    db.commit()


# ────────────────────────────────────────────────────────────────────────────
# 呈现
# ────────────────────────────────────────────────────────────────────────────


def print_plan(plan: RepairPlan, execute: bool) -> None:
    print("=" * 66)
    print("一致性校准诊断报告")
    print("=" * 66)
    print(f"失效分块（文档已下架、分块未软删）：{plan.n_stale_chunks} 条")
    print(f"孤儿向量（Qdrant 有、MySQL 无有效分块）：{plan.n_orphan_points} 个")
    if plan.stale_chunks:
        by_doc: Dict[str, int] = {}
        for chunk in plan.stale_chunks:
            by_doc[chunk.doc_id] = by_doc.get(chunk.doc_id, 0) + 1
        for doc_id, count in sorted(by_doc.items()):
            print(f"    - doc={doc_id[:8]}…: {count} 条")
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
        description="校准 MySQL 分块与 Qdrant 向量的一致性（D9 存量数据处置）",
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
        execute_plan(db, client, plan)
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
