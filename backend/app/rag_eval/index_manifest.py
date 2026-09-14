"""索引清单：分块级索引与段落级标准答案之间的映射

评测体系里有两套 id，必须显式分开：

======================  ====================================================
id                      含义
======================  ====================================================
``point_id``            索引中的检索单元（Qdrant point），一个段落可能对应多个
``passage_id``          基准的标准答案单元（段落）
======================  ====================================================

映射在**索引构建期**确定并落盘（``chunks.jsonl``），而不是评测时按分块参数重新
推导。原因是推导逻辑一旦与写入逻辑不一致（分块器版本差异、参数差异），指标就会
失真，而且这种失真不会有任何显式报错——只会表现为「召回率莫名下降」。

除了映射，本模块还提供分块原文：精排必须对**分块文本**打分（线上就是这样做的），
若评测侧改用整段文本，测出的精排增益无法外推到线上。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from app.rag_eval.dataset import load_jsonl

__all__ = ["ChunkRecord", "IndexManifest", "load_index_manifest"]

CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "index_manifest.json"


@dataclass(frozen=True)
class ChunkRecord:
    """一个索引分块"""

    point_id: str
    passage_id: str
    chunk_index: int
    text: str


@dataclass
class IndexManifest:
    """索引清单：映射关系 + 索引参数（可复现性凭证）"""

    collection: str
    chunks: List[ChunkRecord]
    params: Dict[str, object]
    # 派生索引：由 chunks 在 __post_init__ 中构建，不参与构造签名。
    _text_by_point: Dict[str, str] = field(init=False, repr=False, default_factory=dict)

    # ── 映射查询 ────────────────────────────────────────────────────────────

    @property
    def id_map(self) -> Dict[str, str]:
        """``{point_id: passage_id}``"""
        return {chunk.point_id: chunk.passage_id for chunk in self.chunks}

    def chunk_text(self, point_id: str) -> Optional[str]:
        """分块原文（精排输入）；未知 id 返回 ``None``

        返回 ``None`` 而不是空串：空串会被精排当成「一段空文档」并给出一个分数，
        而 ``None`` 能让调用方区分「没有这段文本」与「这段文本是空的」。
        """
        return self._text_by_point.get(point_id)

    def chunks_per_passage(self) -> Dict[str, int]:
        """``{passage_id: 分块数}``，用于切断检测"""
        counts: Dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.passage_id] = counts.get(chunk.passage_id, 0) + 1
        return counts

    # ── 内部索引 ────────────────────────────────────────────────────────────

    def __post_init__(self) -> None:
        self._text_by_point = {chunk.point_id: chunk.text for chunk in self.chunks}

    @property
    def n_passages(self) -> int:
        return len({chunk.passage_id for chunk in self.chunks})

    @property
    def n_chunks(self) -> int:
        return len(self.chunks)

    def summary(self) -> Dict[str, object]:
        return {
            "collection": self.collection,
            "n_passages": self.n_passages,
            "n_chunks": self.n_chunks,
            **self.params,
        }


def load_index_manifest(data_dir: str | Path) -> IndexManifest:
    """从数据目录读取索引清单（``chunks.jsonl`` + ``index_manifest.json``）"""
    directory = Path(data_dir)
    chunks_path = directory / CHUNKS_FILE
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"未找到 {chunks_path}；请先运行 scripts/index_rag_eval_corpus.py 构建索引"
        )

    records: List[ChunkRecord] = []
    for row in load_jsonl(chunks_path):
        records.append(
            ChunkRecord(
                point_id=str(row["point_id"]),
                passage_id=str(row["passage_id"]),
                chunk_index=int(row["chunk_index"]),
                text=str(row["text"]),
            )
        )

    manifest_path = directory / MANIFEST_FILE
    params: Dict[str, object] = {}
    collection = ""
    if manifest_path.exists():
        params = json.loads(manifest_path.read_text(encoding="utf-8"))
        collection = str(params.get("collection", ""))

    if not collection:
        raise ValueError(f"{manifest_path} 缺少 collection 字段，无法确定待评测的集合")

    return IndexManifest(collection=collection, chunks=records, params=params)
