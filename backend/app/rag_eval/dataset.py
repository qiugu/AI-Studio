"""评测数据集：金标准集与语料的 schema、加载与校验

数据以 JSONL 存放（每行一个 JSON 对象），便于流式读取、逐行 diff 与人工审阅——
评测资产一旦进入版本管理，评审人需要能看懂每次改动命中了哪一条查询。

两类资产：

* ``corpus.jsonl``  —— 采样语料（``CorpusEntry``），Phase 2 由公开基准采样得到；
* ``golden.jsonl``  —— 金标准查询与相关结果（``GoldenQuery``）。

**关于「检索单元」的口径**：``RelevantItem.id`` 指向**索引中真实存在、可被检索到的
单元**（即 Qdrant point id / 分块 id），而不是原始基准里的段落 id。原因是语料入库时
会经过真实的 ``TextSplitter`` 分块，一个段落可能变成多个分块、也可能被边界切断。
若在金标准里直接用段落 id，评测就必须在运行时再做一层映射，一旦映射逻辑与写入
逻辑不一致，指标即失真。因此映射关系在**数据集构建期**固化，``passage_id`` 字段
仅用于溯源与派生文档级指标。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "CorpusEntry",
    "RelevantItem",
    "GoldenQuery",
    "GoldenSet",
    "load_jsonl",
    "dump_jsonl",
]


class CorpusEntry(BaseModel):
    """采样语料中的一段文本"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="语料单元 ID（同时作为溯源用的 passage_id）")
    text: str = Field(..., description="原文文本")

    @field_validator("id", "text")
    @classmethod
    def _not_blank(cls, value: str, info: Any) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value


class RelevantItem(BaseModel):
    """一条相关结果标注"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="检索单元 ID（索引中可被检索到的 point id）")
    grade: int = Field(1, ge=1, description="分级相关度，>=1；二值场景恒为 1")
    passage_id: Optional[str] = Field(
        None, description="来源语料段落 ID，用于溯源与分块切断检测"
    )

    @field_validator("id")
    @classmethod
    def _id_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("relevant.id must be non-empty")
        return value


class GoldenQuery(BaseModel):
    """一条金标准查询

    字段说明：

    * ``relevant`` 必须非空——没有标准答案的查询无法参与评测，指标无定义。
      这类查询应在数据集构建期剔除或补齐标注，而不是在运行时静默跳过。
      不变量由校验器强制，避免「看似全绿的评测」掩盖标注缺失。
    * ``query_type`` 为自由文本分组键（建议：``fact`` / ``exact_term`` /
      ``paraphrase`` / ``multi_doc``），用于分类型观察各阶段增益来源。
    """

    model_config = ConfigDict(extra="forbid")

    query_id: str
    query: str
    relevant: List[RelevantItem] = Field(..., min_length=1)
    query_type: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("query_id", "query")
    @classmethod
    def _not_blank(cls, value: str, info: Any) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must be non-empty")
        return value

    @model_validator(mode="after")
    def _no_duplicate_relevant_ids(self) -> "GoldenQuery":
        ids = [item.id for item in self.relevant]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"relevant contains duplicate ids: {duplicates[:5]}")
        return self

    @property
    def relevant_ids(self) -> List[str]:
        """完整相关集 ``R``（**不要截断**——它是 Recall 的分母）"""
        return [item.id for item in self.relevant]

    @property
    def gains(self) -> Dict[str, int]:
        """``{检索单元 id: 增益}``，供 nDCG 使用"""
        return {item.id: item.grade for item in self.relevant}

    @property
    def passage_ids(self) -> List[str]:
        """涉及的全部来源段落 ID（去重，忽略未标注项）"""
        seen: Dict[str, None] = {}
        for item in self.relevant:
            if item.passage_id:
                seen.setdefault(item.passage_id, None)
        return list(seen)


class GoldenSet(BaseModel):
    """金标准集合

    构造方式：``GoldenSet(queries=[...])`` 或 :meth:`GoldenSet.load` 从 JSONL 读取。
    ``manifest`` 记录采样参数与随机种子，随报告一同落盘，作为可复现性凭证。
    """

    model_config = ConfigDict(extra="forbid")

    queries: List[GoldenQuery] = Field(default_factory=list)
    manifest: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def _no_duplicate_query_ids(self) -> "GoldenSet":
        ids = [q.query_id for q in self.queries]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate query_id across golden set: {duplicates[:5]}")
        return self

    # ── 构造 ────────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> "GoldenSet":
        """从 JSONL 加载并校验金标准集；同名目录下的 ``manifest.json`` 会自动带上"""
        records = load_jsonl(path)
        queries = [GoldenQuery.model_validate(record) for record in records]
        manifest_path = Path(path).with_name("manifest.json")
        manifest = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return cls(queries=queries, manifest=manifest)

    # ── 查询 ────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.queries)

    def __iter__(self) -> Iterator[GoldenQuery]:  # type: ignore[override]
        return iter(self.queries)

    @property
    def groups(self) -> Dict[str, str]:
        """``{query_id: query_type}``，供分类型聚合使用"""
        return {q.query_id: (q.query_type or "unknown") for q in self.queries}

    @property
    def relevant_id_pool(self) -> List[str]:
        """全部查询涉及的检索单元 ID（去重）——用于校验索引覆盖率"""
        seen: Dict[str, None] = {}
        for q in self.queries:
            for item in q.relevant:
                seen.setdefault(item.id, None)
        return list(seen)

    def stats(self) -> Dict[str, Any]:
        """数据集统计（写入报告，作为可复现性凭证的一部分）"""
        type_counts: Dict[str, int] = {}
        for q in self.queries:
            key = q.query_type or "unknown"
            type_counts[key] = type_counts.get(key, 0) + 1

        sizes = [len(q.relevant) for q in self.queries]
        return {
            "n_queries": len(self.queries),
            "query_type_distribution": dict(sorted(type_counts.items())),
            "n_relevant_total": sum(sizes),
            "n_relevant_per_query": {
                "min": min(sizes) if sizes else 0,
                "max": max(sizes) if sizes else 0,
                "mean": round(sum(sizes) / len(sizes), 3) if sizes else 0.0,
            },
            "n_unique_relevant_units": len(self.relevant_id_pool),
            "provenance": self._provenance_mix(),
        }

    def _provenance_mix(self) -> Dict[str, int]:
        """统计标注是否携带来源段落 ID，用于确认切断检测是否已执行"""
        with_passage = sum(1 for q in self.queries for it in q.relevant if it.passage_id)
        total = sum(len(q.relevant) for q in self.queries)
        return {
            "relevant_with_passage_id": with_passage,
            "relevant_without_passage_id": total - with_passage,
        }


# ── JSONL 读写 ──────────────────────────────────────────────────────────────


def load_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    """逐行读取 JSONL；空行忽略，格式错误时报出具体行号

    解析失败必须**立即报错并带上行号**——评测资产是人工维护的，静默跳过坏行
    会导致「数据集悄悄变小、指标悄悄变好看」。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"dataset file not found: {file_path}")

    records: List[Dict[str, Any]] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{file_path}:{lineno} invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{file_path}:{lineno} expected a JSON object, got {type(record).__name__}")
            records.append(record)
    return records


def dump_jsonl(records: Sequence[BaseModel | Dict[str, Any]], path: str | Path) -> Path:
    """写出 JSONL（``ensure_ascii=False``，保留中文可读性）"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        for record in records:
            payload = (
                record.model_dump(exclude_none=True)
                if isinstance(record, BaseModel)
                else record
            )
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return file_path
