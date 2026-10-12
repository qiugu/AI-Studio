#!/usr/bin/env python
"""Phase 2.1–2.3：从公开中文基准采样评测语料与金标准查询。

本脚本产出评测体系的两份**基础资产**，二者全部由「固定基准版本 + 固定种子」推导，
因此可完整复现；这也是报告结论能被追溯到原始数据的前提。

产出（默认 ``backend/data/rag_eval/``）::

    corpus.jsonl         采样语料，每行 ``{"id", "text"}``
    golden.jsonl         金标准查询，每行 ``{"query_id", "query", "relevant", ...}``
    manifest.json        采样参数与种子（可复现性凭证，随报告一同落盘）

设计要点
--------

1. **为什么不用 ``datasets.load_dataset``**：镜像源对 ``/resolve`` 之外的部分接口
   支持不完整，``get_dataset_config_names`` 在 ``datasets>=5`` 下会失败。基准的
   parquet 文件布局（``corpus/`` ``queries/`` ``data/``）是稳定的，直接按文件拉取
   更可控，也便于固定到具体 revision。

2. **为什么必须绕过代理访问 HF 域名**：镜像站按来源 IP 分流——境外 IP 会被 302
   重定向回 ``huggingface.co``，而本机代理出口在境外，于是下载必然失败且报错信息
   具有误导性（"Distant resource does not seem to be on huggingface.co"）。
   解除方法不是换镜像，而是把 HF 域名加入 ``NO_PROXY``。

3. **段落文本清洗**：基准语料 65.7% 含 ``<br>`` ``<img>`` 等标签（网页抓取残留）。
   不清洗会让向量化与重排都看到噪声，进而低估或错估真实检索能力。清洗仅作用于
   本评测语料，不改动线上文档解析链路。

4. **查询筛选口径**：只保留「全部相关段落都落在采样语料内」的查询。否则相关段落
   缺席会人为压低 Recall 上限，而指标本身不会暴露这一点——报告只会显示「召回率低」，
   让人误判为检索算法的问题。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 本脚本只需配置默认值（Qdrant 默认 localhost、无需数据库凭据），
# 因此默认跳过 backend/.env 的读取——否则在任何无凭据环境（含 CI）都会因
# 读取被拒而无法运行。显式设置了 AI_STUDIO_SKIP_ENV_FILE 的调用方不受影响。
os.environ.setdefault("AI_STUDIO_SKIP_ENV_FILE", "1")

from app.rag_eval.dataset import CorpusEntry, GoldenQuery, RelevantItem, dump_jsonl  # noqa: E402

# ── 默认参数 ────────────────────────────────────────────────────────────────

DEFAULT_REPO = "mteb/T2Retrieval"
# 固定 revision：同一种子 + 同一 revision ⇒ 逐行可复现的语料。
# 不固定则会随上游更新而漂移，历史报告将无法复算。
DEFAULT_REVISION = "921dd3af6e78d1ae7ee0368aa8d7eaee02c8f08e"
DEFAULT_FILES = {
    "corpus": "corpus/dev-00000-of-00001.parquet",
    "queries": "queries/dev-00000-of-00001.parquet",
    "qrels": "data/dev-00000-of-00001.parquet",
}
DEFAULT_OUT_DIR = BACKEND_DIR / "data" / "rag_eval"
DEFAULT_HF_ENDPOINT = "https://hf-mirror.com"
# 需绕过代理的 HF 相关域名：镜像站按来源 IP 分流，代理出口在境外会被重定向回
# 不可达的 huggingface.co；xethub 是镜像 302 之后的实际文件 CDN。
HF_DIRECT_DOMAINS = ("hf-mirror.com", "hf.co", "xethub.hf.co")

DEFAULT_M = 20_000          # 采样语料规模（段落数）
DEFAULT_Q = 100             # 金标准查询数
DEFAULT_SEED = 42
DEFAULT_MIN_CHARS = 10      # 清洗后短于此长度的段落不进入采样域

# ── 文本清洗 ────────────────────────────────────────────────────────────────

_HTML_BREAK = re.compile(r"<\s*(?:br|/p|/div|/tr|/li)\s*/?\s*>", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]{0,200}>")
_INLINE_SPACE = re.compile(r"[ \t\u00a0\u3000]+")
_MULTI_NEWLINE = re.compile(r"\n{2,}")


def clean_passage_text(raw: str) -> str:
    """把基准语料中的网页残留清洗为纯文本。

    处理顺序有讲究：先把换行类标签替换成真正的换行（保留段落结构，这对分块
    质量有直接影响），再兜底删除其余标签。若先删标签会把 ``<br>`` 一并删掉并
    使原本分行的内容粘连成一行。
    """
    text = _HTML_BREAK.sub("\n", raw or "")
    text = _HTML_TAG.sub(" ", text)
    text = html.unescape(text)
    text = _INLINE_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n", text)
    return text.strip()


def configure_hf_environment(endpoint: str = DEFAULT_HF_ENDPOINT) -> str:
    """配置 HF 端点与代理绕过，返回最终生效的端点。

    仅在调用方未显式设置时兜底，避免覆盖用户自己的镜像/代理配置。
    """
    os.environ.setdefault("HF_ENDPOINT", endpoint)
    for domain in HF_DIRECT_DOMAINS:
        for key in ("NO_PROXY", "no_proxy"):
            current = os.environ.get(key, "")
            parts = [p.strip() for p in current.split(",") if p.strip()]
            if domain not in parts:
                parts.append(domain)
            os.environ[key] = ",".join(parts)
    return os.environ["HF_ENDPOINT"]


# ── 基准文件读取 ────────────────────────────────────────────────────────────


def download_benchmark_files(repo: str, revision: str) -> Dict[str, Path]:
    """拉取基准的三份 parquet，返回 ``{kind: 本地路径}``"""
    from huggingface_hub import hf_hub_download

    paths: Dict[str, Path] = {}
    for kind, filename in DEFAULT_FILES.items():
        paths[kind] = Path(
            hf_hub_download(repo_id=repo, filename=filename, revision=revision, repo_type="dataset")
        )
    return paths


def iter_rows(path: Path, columns: Sequence[str]) -> Iterator[dict]:
    """按 row group 流式读取 parquet，避免把 15 万行一次性载入内存"""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    for group in range(parquet.metadata.num_row_groups):
        table = parquet.read_row_group(group, columns=list(columns))
        for row in table.to_pylist():
            yield row


def reservoir_sample(
    stream: Iterable[Tuple[str, str]],
    size: int,
    seed: int,
) -> List[Tuple[str, str]]:
    """对单遍流做 reservoir 采样（确定性、内存占用与语料总量无关）。

    返回值按**原始出现顺序**排列：水塘算法的内部顺序依赖替换历史，虽然同样确定，
    但把结果按出现顺序归一化后，``corpus.jsonl`` 的 diff 才能反映真实变化，
    而不是随机替换导致的整体重排。
    """
    if size < 1:
        raise ValueError("size must be >= 1")

    rng = random.Random(seed)
    reservoir: List[Tuple[int, str, str]] = []
    for index, (doc_id, text) in enumerate(stream):
        if index < size:
            reservoir.append((index, doc_id, text))
        else:
            victim = rng.randint(0, index)
            if victim < size:
                reservoir[victim] = (index, doc_id, text)
    # 位置信息只用于稳定排序；按 id 数值排序在 id 非纯数字时不可用。
    reservoir.sort(key=lambda item: item[0])
    return [(doc_id, text) for _, doc_id, text in reservoir]


def build_corpus_stream(corpus_path: Path, min_chars: int) -> Iterator[Tuple[str, str]]:
    """产出 (id, 清洗后文本)，并过滤清洗后过短的段落"""
    for row in iter_rows(corpus_path, columns=["_id", "text"]):
        cleaned = clean_passage_text(row["text"])
        if len(cleaned) >= min_chars:
            yield str(row["_id"]), cleaned


def load_qrels(qrels_path: Path) -> Dict[str, List[str]]:
    """读取相关性判定，返回 ``{query_id: [相关段落 id, ...]}``（仅保留正相关）"""
    relevant: Dict[str, List[str]] = {}
    for row in iter_rows(qrels_path, columns=["query-id", "corpus-id", "score"]):
        if int(row["score"]) > 0:
            relevant.setdefault(str(row["query-id"]), []).append(str(row["corpus-id"]))
    return relevant


def load_queries(queries_path: Path) -> Dict[str, str]:
    """读取查询文本，返回 ``{query_id: text}``"""
    return {
        str(row["_id"]): str(row["text"]).strip()
        for row in iter_rows(queries_path, columns=["_id", "text"])
    }


# ── 金标准构造 ──────────────────────────────────────────────────────────────

#: 查询分组键。基准未提供查询类型标注，与其用启发式猜测语义类型（不可验证），
#: 不如用**客观可复算**的相关段落数分档——它恰好也是判断「精排增益是否集中
#: 在相关项较多的查询上」所需的分组维度。
def classify_query(n_relevant: int) -> str:
    if n_relevant <= 1:
        return "rel1"
    if n_relevant == 2:
        return "rel2"
    return "rel3plus"


def select_queries(
    qrels: Dict[str, List[str]],
    queries: Dict[str, str],
    sampled_ids: set,
    quota: int,
    seed: int,
) -> List[str]:
    """挑选「全部相关段落均在采样语料内」的查询，并确定性抽取 ``quota`` 条。

    返回查询 id 列表。选择的是**确定性随机子集**而非「前 quota 条」：
    基准的 id 顺序与主题存在相关性（同一批抓取的内容相邻），直接取前 N 条
    会引入难以量化的主题偏斜。
    """
    eligible = sorted(
        (
            query_id
            for query_id, relevant in qrels.items()
            if query_id in queries
            and relevant
            and all(doc_id in sampled_ids for doc_id in relevant)
        ),
        key=lambda value: (len(value), value),
    )
    if len(eligible) < quota:
        raise SystemExit(
            f"合格查询仅 {len(eligible)} 条，少于所需的 {quota} 条。"
            f"请增大 --m（当前采样比的平方量级）或减小 --q。"
        )
    rng = random.Random(seed)
    return sorted(rng.sample(eligible, quota))


def build_golden_records(
    selected: Sequence[str],
    qrels: Dict[str, List[str]],
    queries: Dict[str, str],
) -> List[GoldenQuery]:
    """构造金标准查询对象（含 schema 校验）"""
    records: List[GoldenQuery] = []
    for query_id in selected:
        relevant_ids = qrels[query_id]
        records.append(
            GoldenQuery(
                query_id=query_id,
                query=queries[query_id],
                relevant=[
                    # id 与 passage_id 同为段落 id：本评测在**段落粒度**上打分
                    # （见 docs/rag-eval/PLAN.md 的粒度说明），索引中的 chunk
                    # 通过 index_manifest.json 映射回段落，故此处两者一致。
                    RelevantItem(id=doc_id, grade=1, passage_id=doc_id)
                    for doc_id in relevant_ids
                ],
                query_type=classify_query(len(relevant_ids)),
                meta={
                    "source_repo": DEFAULT_REPO,
                    "query_char_len": len(queries[query_id]),
                    "n_relevant_in_source": len(relevant_ids),
                },
            )
        )
    return records


# ── 主流程 ──────────────────────────────────────────────────────────────────


def build_manifest(
    *,
    repo: str,
    revision: str,
    endpoint: str,
    seed: int,
    requested_m: int,
    actual_m: int,
    quota: int,
    min_chars: int,
    pool_size: int,
    eligible: int,
    records: Sequence[GoldenQuery],
) -> Dict[str, object]:
    """采样清单：把「结论基于哪一份语料」固化为可复核的记录"""
    rel_counts = [len(record.relevant) for record in records]
    group_counts: Dict[str, int] = {}
    for record in records:
        key = record.query_type or "unknown"
        group_counts[key] = group_counts.get(key, 0) + 1

    return {
        "source_repo": repo,
        "source_revision": revision,
        "hf_endpoint": endpoint,
        "seed": seed,
        "requested_m": requested_m,
        "actual_m": actual_m,
        "quota": quota,
        "min_chars": min_chars,
        "pool_size": pool_size,
        "sampling_ratio": round(actual_m / pool_size, 6) if pool_size else None,
        "eligible_queries": eligible,
        "n_queries": len(records),
        "query_group_distribution": dict(sorted(group_counts.items())),
        "relevant_per_query": {
            "min": min(rel_counts) if rel_counts else 0,
            "max": max(rel_counts) if rel_counts else 0,
            "mean": round(statistics.fmean(rel_counts), 3) if rel_counts else 0.0,
        },
        "relevance_grading": "binary",
        # 采样偏差必须显式披露：语料是基准的子集，非相关干扰项同比例减少，
        # 绝对 Recall 会高于全量场景。主结论限定为「基线 vs 增强」的相对增益。
        "sampling_bias_note": (
            "语料为基准的子集，干扰项同比例减少，绝对 Recall 高于全量场景；"
            "结论仅用于比较基线与其他检索配置的相对增益。"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从公开中文基准采样评测语料与金标准查询",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="HuggingFace 数据集 id")
    parser.add_argument("--revision", default=DEFAULT_REVISION, help="固定的 commit revision")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="产出目录")
    parser.add_argument("--m", type=int, default=DEFAULT_M, help="采样段落数")
    parser.add_argument("--q", type=int, default=DEFAULT_Q, help="金标准查询数")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS,
                        help="清洗后段落的最小字符数")
    parser.add_argument("--endpoint", default=DEFAULT_HF_ENDPOINT, help="HF 镜像端点")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    endpoint = configure_hf_environment(args.endpoint)
    print(f"[1/5] 拉取基准 {args.repo}@{args.revision[:8]} (endpoint={endpoint})")
    files = download_benchmark_files(args.repo, args.revision)
    for kind, path in files.items():
        print(f"      {kind:8s} {path.stat().st_size/1e6:8.1f} MB  {path.name}")

    print(f"[2/5] reservoir 采样：seed={args.seed}, M={args.m}")
    pool_size = 0
    sampled: List[Tuple[str, str]] = []

    def counting_stream() -> Iterator[Tuple[str, str]]:
        nonlocal pool_size
        for item in build_corpus_stream(files["corpus"], args.min_chars):
            pool_size += 1
            yield item

    sampled = reservoir_sample(counting_stream(), args.m, args.seed)
    sampled_ids = {doc_id for doc_id, _ in sampled}
    print(f"      可采样域 {pool_size} 段 → 采样 {len(sampled)} 段 "
          f"(覆盖率 {len(sampled)/max(pool_size,1)*100:.1f}%)")

    print("[3/5] 加载 qrels 与 queries，筛选「相关段落全部命中」的查询")
    qrels = load_qrels(files["qrels"])
    queries = load_queries(files["queries"])
    eligible = [
        query_id
        for query_id, relevant in qrels.items()
        if query_id in queries and relevant and all(d in sampled_ids for d in relevant)
    ]
    print(f"      基准查询 {len(queries)} 条 → 合格 {len(eligible)} 条")

    print(f"[4/5] 抽取 {args.q} 条金标准查询")
    selected = select_queries(qrels, queries, sampled_ids, args.q, args.seed)
    records = build_golden_records(selected, qrels, queries)

    print("[5/5] 写出资产")
    corpus_path = dump_jsonl(
        [CorpusEntry(id=doc_id, text=text) for doc_id, text in sampled],
        out_dir / "corpus.jsonl",
    )
    golden_path = dump_jsonl(records, out_dir / "golden.jsonl")

    manifest = build_manifest(
        repo=args.repo, revision=args.revision, endpoint=endpoint, seed=args.seed,
        requested_m=args.m, actual_m=len(sampled), quota=args.q,
        min_chars=args.min_chars, pool_size=pool_size, eligible=len(eligible),
        records=records,
    )
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"      {corpus_path}  ({corpus_path.stat().st_size/1e6:.1f} MB)")
    print(f"      {golden_path}  ({len(records)} 条查询)")
    print(f"      {manifest_path}")
    print()
    print("查询分组分布:", manifest["query_group_distribution"])
    print("每查询相关段落数:", manifest["relevant_per_query"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
