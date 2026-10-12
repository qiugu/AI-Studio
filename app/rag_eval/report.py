"""评测报告输出：JSON（机器可读）+ Markdown（人可读）+ 回归门禁

两种格式各有不可替代的用途，必须同时产出：

* **JSON** —— 回归门禁的基线快照、跨版本逐项 diff、后续可视化数据源；
* **Markdown** —— 评审人阅读的正文，用于说明「结论是在什么口径下、基于哪份数据集得出的」。

报告的完整性要求：任何一项指标都必须能追溯到数据集 + 采样清单 + 检索器实现。
缺少其中任一环，指标就只是数字，不能支撑决策。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.rag_eval.runner import EvalRun

__all__ = [
    "RegressionCheck",
    "check_regression",
    "load_baseline",
    "render_markdown",
    "render_comparison_markdown",
    "write_json",
    "write_markdown",
]

_METRIC_ORDER = ("recall", "hit", "precision", "mrr", "map", "ndcg")


def _fmt(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _fmt_ms(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.1f}"


def write_json(run: EvalRun, path: str | Path) -> Path:
    """写出指标 JSON（回归基线与跨版本对照的统一格式）"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(run.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def load_baseline(path: str | Path) -> Dict[str, Any]:
    """读取基线 JSON（由 :func:`write_json` 产出）"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── 回归门禁 ────────────────────────────────────────────────────────────────


@dataclass
class RegressionCheck:
    """单项回归门禁结果"""

    metric: str
    baseline: Optional[float]
    current: Optional[float]
    delta_pp: Optional[float]
    max_drop_pp: float
    passed: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "baseline": self.baseline,
            "current": self.current,
            "delta_pp": self.delta_pp,
            "max_drop_pp": self.max_drop_pp,
            "passed": self.passed,
            "note": self.note,
        }


def check_regression(
    current: EvalRun,
    baseline: Dict[str, Any],
    metric: str = "recall@5",
    max_drop_pp: float = 1.0,
) -> RegressionCheck:
    """回归门禁：断言 ``metric`` 相对基线下降不超过 ``max_drop_pp`` 个百分点

    以「百分点（percentage point）」而非相对百分比作为阈值——相对百分比在
    基线本身很低时过于宽松（0.10 → 0.09 是 10% 的相对下降，却只有 1pp）。
    指标内部以 0~1 归一，故 1pp = 0.01。

    基线缺失或当前指标缺失时**不判定通过**：无法验证与「验证通过」是两回事，
    把缺失当成通过会让门禁在数据不全时静默失效。
    """
    baseline_value = (baseline.get("aggregate") or {}).get(metric)
    current_value = current.metric(metric)

    if baseline_value is None:
        return RegressionCheck(
            metric=metric,
            baseline=None,
            current=current_value,
            delta_pp=None,
            max_drop_pp=max_drop_pp,
            passed=False,
            note=f"基线中不存在指标 {metric}，无法判定",
        )
    if current_value is None:
        return RegressionCheck(
            metric=metric,
            baseline=baseline_value,
            current=None,
            delta_pp=None,
            max_drop_pp=max_drop_pp,
            passed=False,
            note=f"本次运行未产出指标 {metric}，无法判定",
        )

    delta_pp = (current_value - baseline_value) * 100.0
    passed = delta_pp >= -max_drop_pp
    return RegressionCheck(
        metric=metric,
        baseline=baseline_value,
        current=current_value,
        delta_pp=round(delta_pp, 4),
        max_drop_pp=max_drop_pp,
        passed=passed,
        note="通过" if passed else f"下降 {abs(delta_pp):.2f}pp，超过允许的 {max_drop_pp}pp",
    )


# ── Markdown 渲染 ───────────────────────────────────────────────────────────


def render_markdown(run: EvalRun, checks: Sequence[RegressionCheck] = ()) -> str:
    """渲染单次运行报告"""
    lines: List[str] = []
    lines.append(f"# 检索评测报告 — {run.name}")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|----|----|")
    lines.append(f"| 检索器 | `{run.retriever_name}` |")
    lines.append(f"| 截断位置 k | {', '.join(str(k) for k in run.k_values)} |")
    lines.append(f"| 参与评测查询数 | {run.n_scored} |")
    lines.append(f"| 失败查询数 | {run.n_failed} |")
    lines.append(f"| 唯一相关单元数 | {run.dataset_stats.get('n_unique_relevant_units', '—')} |")
    lines.append("")

    lines.extend(_render_metric_table(run))
    lines.extend(_render_stage_section(run))
    lines.extend(_render_type_table(run))
    lines.extend(_render_latency_table(run))
    lines.extend(_render_dataset_section(run))

    if checks:
        lines.append("## 回归门禁")
        lines.append("")
        lines.append("| 指标 | 基线 | 本次 | Δ (pp) | 允许下降 (pp) | 结论 |")
        lines.append("|------|------|------|--------|---------------|------|")
        for check in checks:
            lines.append(
                f"| `{check.metric}` | "
                f"{_fmt(check.baseline, 4)} | "
                f"{_fmt(check.current, 4)} | "
                f"{'—' if check.delta_pp is None else f'{check.delta_pp:+.2f}'} | "
                f"{check.max_drop_pp} | "
                f"{'✅ 通过' if check.passed else '❌ 不通过'} — {check.note} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def _render_metric_table(run: EvalRun) -> List[str]:
    lines = ["## 总体指标（单查询宏观平均）", ""]
    header = ["指标"] + [f"@{k}" for k in run.k_values]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "------|" * len(header))
    for metric in _METRIC_ORDER:
        row = [metric.upper()]
        for k in run.k_values:
            row.append(_fmt(run.metric(f"{metric}@{k}")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def _render_stage_section(run: EvalRun) -> List[str]:
    """召回损失 vs 排序损失：只有提供宽召回候选集时才有意义"""
    if run.metric("candidate_recall") is None:
        return []

    smallest_k = run.k_values[0]
    candidate_recall = run.metric("candidate_recall")
    final_recall = run.metric(f"recall@{smallest_k}")
    lines = [
        "## 召回损失 vs 排序损失",
        "",
        f"- 宽召回候选集内的召回率（`candidate_recall`）：**{_fmt(candidate_recall)}**",
        f"- 排序截断后的召回率（`recall@{smallest_k}`）：**{_fmt(final_recall)}**",
        "",
    ]
    if candidate_recall is not None and final_recall is not None:
        gap = (candidate_recall - final_recall) * 100
        lines.append(
            f"两者相差 **{gap:.2f}pp**：这部分差距完全由排序造成——候选集中已经存在"
            "相关结果，只是没能排进前 "
            f"{smallest_k}。该差额越大，精排（reranker）的收益空间越大；"
            "若 `candidate_recall` 本身就低，则应优先补召回而非精排。"
        )
        lines.append("")
    return lines


def _render_type_table(run: EvalRun) -> List[str]:
    """按查询类型分组展示 @5 指标

    只看总体均值会掩盖「某类查询变好、另一类变坏」的结构性变化，
    因此分类型视图是必需项而非可选装饰。
    """
    if not run.by_query_type:
        return []
    lines = ["## 分查询类型指标", ""]
    header = ["查询类型", "查询数", "recall@5", "mrr@5", "ndcg@5"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "------|" * len(header))
    for type_name, metrics in run.by_query_type.items():
        row = [type_name, str(run.type_counts.get(type_name, "—"))]
        for metric in ("recall", "mrr", "ndcg"):
            row.append(_fmt(metrics.get(f"{metric}@5")))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return lines


def _render_latency_table(run: EvalRun) -> List[str]:
    if not run.latency:
        return []
    lines = ["## 延迟（毫秒）", ""]
    lines.append("| 阶段 | p50 | p95 | mean |")
    lines.append("|------|-----|-----|------|")
    for stage in ("retrieve", "rerank", "total"):
        stats = run.latency.get(stage)
        if not stats:
            continue
        lines.append(
            f"| {stage} | {_fmt_ms(stats.get('p50'))} | "
            f"{_fmt_ms(stats.get('p95'))} | {_fmt_ms(stats.get('mean'))} |"
        )
    lines.append("")
    return lines


def _render_dataset_section(run: EvalRun) -> List[str]:
    lines = ["## 数据集与可复现性", ""]
    lines.append("```json")
    lines.append(
        json.dumps(
            {"dataset": run.dataset_stats, "manifest": run.manifest},
            ensure_ascii=False,
            indent=2,
        )
    )
    lines.append("```")
    lines.append("")
    return lines


def render_comparison_markdown(
    baseline: Dict[str, Any],
    current: EvalRun,
    title: str = "before / after 对照",
) -> str:
    """渲染基线 vs 本次运行的逐项对照表（Phase 4 的主要交付物）"""
    baseline_aggregate: Dict[str, Optional[float]] = baseline.get("aggregate") or {}
    keys = sorted(set(baseline_aggregate) | set(current.aggregate))

    lines = [f"# {title}", ""]
    lines.append(f"- 基线：`{baseline.get('name', 'baseline')}`（检索器 `{baseline.get('retriever', '—')}`）")
    lines.append(f"- 本次：`{current.name}`（检索器 `{current.retriever_name}`）")
    lines.append("")
    lines.append("| 指标 | 基线 | 本次 | Δ (pp) | 变化 |")
    lines.append("|------|------|------|--------|------|")
    for key in keys:
        before = baseline_aggregate.get(key)
        after = current.aggregate.get(key)
        if before is None or after is None:
            delta = "—"
            trend = "—"
        else:
            delta_pp = (after - before) * 100
            delta = f"{delta_pp:+.2f}"
            trend = "↑" if delta_pp > 1e-9 else ("↓" if delta_pp < -1e-9 else "=")
        lines.append(f"| `{key}` | {_fmt(before)} | {_fmt(after)} | {delta} | {trend} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_markdown(content: str, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
