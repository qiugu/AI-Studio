#!/usr/bin/env python
"""文档切分质量报告（只读）

为什么需要这个工具
------------------
分块质量是检索质量的上游：块边界切断了答案，检索再强也召不回。但「分块好不好」
长期无法被讨论，因为**没有可复现的数字**——只能靠人肉翻几块样本，结论随样本漂移。

本工具把「结构对齐」这件事量化成七个可复现的指标，为后续解析/分块改动提供同一把
尺子（改前跑一次、改后跑一次，差值即收益）。

指标与判据
----------
* ``double_newline`` / ``single_newline`` / ``paragraph_ratio``
  解析出的文本里 ``\\n\\n`` 与 ``\\n`` 的实际数量。``paragraph_ratio``（
  ``\\n\\n / \\n``）接近 0 说明**段落边界没有表现为空行**，层级最高的分隔符
  ``"\\n\\n"`` 在分块器中不可达——这是 PDF 分块退化为「按版面行装箱」的直接原因。
* ``sep_level_hist``
  每个段实际命中的分隔符级别（0 = ``"\\n\\n"``，1 = ``"\\n"``，2 = ``"。"``……）。
  关注点：**级别 0 是否可达**、以及级别 2（句号）是否从未被触发——后者意味着
  尺寸兜底从未在句子粒度生效。
* ``tiny_ratio``（< 50 字符）/ ``half_ratio``（< chunk_size/2）
  过短的块信息量不足：向量被少量词主导，与任意查询的相似度都容易虚高，等于往
  召回池里灌噪声。这两个比例是「块过碎」的量化形式。
* ``tail_sentence_ratio``
  块尾落在句末标点上的比例。**这是「块边界是否落在语义边界」最直接的指标**：
  比例低说明块在句子中间被切断，单块无法独立支撑答案，Recall 上限被压低。
* ``orphan_heading_chunks``
  整块只有标题行、没有任何正文的块。这类块必然过短且语义空泛，同时说明标题与
  其正文被切散了（社区 ``chunk_by_title`` 明确禁止的行为）。
* ``chunks_per_segment_hist``
  每个段产出多少块。若分布集中在 ``1``，说明段边界被当作硬块边界、**从未有过
  合并**，碎片化的根因在「段粒度」而非「段内切分」。

安全设计
--------
- **纯只读**：不写数据库、不调嵌入模型、不写 Qdrant、不联网。
- **可不依赖应用配置**：``--path`` 模式只导入 ``app.utils.document`` 的纯函数；
  仅 ``--kb`` 模式需要数据库连接。
- **基线可回归**：``--json-out`` 落盘指标，``--baseline`` 与历史基线逐项对比并
  打印差值，供 CI 或人工门禁使用。

用法
----
    # 单文件
    python scripts/chunking_quality_report.py --path /app/uploads/.../a.pdf

    # 目录内全部受支持文件（递归）
    python scripts/chunking_quality_report.py --dir /app/uploads

    # 按知识库（从 MySQL 取该库已完成的文档）
    python scripts/chunking_quality_report.py --kb <kb_id>

    # 固化基线并做对比
    python scripts/chunking_quality_report.py --dir /app/uploads --json-out base.json
    python scripts/chunking_quality_report.py --dir /app/uploads --baseline base.json

    # A/B 对比两种合并策略（0 = 关闭「短串并入下一串」）
    python scripts/chunking_quality_report.py --dir /app/uploads --min-fill 0

退出码
------
``0`` 正常；``1`` 有文档分析失败；``2`` 基线对比发现任一指标劣化。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# 允许以 ``python scripts/xxx.py`` 直接运行（脚本目录不在包内，需补项目根）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.document import (  # noqa: E402
    ATX_HEADING_RE,
    DocumentParser,
    HEADING_SEPARATOR,
    TextChunk,
    TextSegment,
    TextSplitter,
)

#: 目录条目（点线引导符）检测：``1. 引言........ 3`` / ``2.3 方法...... 12``。
#: 用于 ``toc_leak_ratio``——这类行若漏进块里，说明目录页抑制失效（S2 的污染根）。
#: 用三个弱条件组合而非一条长正则：长正则的贪婪回溯在点线场景下不稳定，
#: 这里改为「行首是编号 + 行内含 2+ 连续点 + 行尾是页码」分别判定，更鲁棒。
_TOC_LEAD_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_TOC_DOTS_RE = re.compile(r"\.{2,}")
_TOC_TAIL_RE = re.compile(r"\d+\s*$")


def _is_toc_leak_line(line: str) -> bool:
    """单行是否像目录条目（点线引导符 + 编号 + 页码）"""
    return bool(
        _TOC_LEAD_RE.match(line)
        and _TOC_DOTS_RE.search(line)
        and _TOC_TAIL_RE.search(line)
    )
from app.utils.text_structure import (  # noqa: E402
    SENTENCE_END,
    ends_sentence,
    starts_structural_block,
)

#: 「极短块」阈值（字符）。低于此长度的块几乎不承载可检索信息。
TINY_CHARS = 50

#: 分隔符级别的可读名称，用于报告输出。
_SEP_LEVEL_NAMES = {
    0: r"'\\n\\n'",
    1: r"'\\n'",
    2: r"'。'",
    3: r"'，'",
    4: r"' '",
    5: r"''",
}


# ────────────────────────────── 指标计算 ──────────────────────────────


def picked_separator_level(text: str, separators: Sequence[str]) -> int:
    """复刻 ``TextSplitter._split_recursive`` 的选择逻辑：返回**实际命中**的级别

    与分块器保持同一判定（「按顺序取第一个在文本中存在的分隔符」）是刻意的：
    报告要解释分块器的行为，就不能用一套自己的、更聪明的判定，否则数字与现象对不上。
    """
    for level, sep in enumerate(separators):
        if sep in text:
            return level
    return len(separators) - 1


def is_orphan_heading_chunk(text: str) -> bool:
    """整块是否只有标题行、没有正文

    仅对带标题标记的格式（Markdown ATX）可判定；DOCX/PDF 的标题在提取后不带标记，
    无法与短正文区分，故这些格式下不计算本指标（报告会标注 ``n/a``）。
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return False
    return all(ATX_HEADING_RE.match(ln) for ln in lines)


def structure_boundaries(text: str) -> Tuple[Set[int], Set[int]]:
    """返回文本中所有**可安全落刀**的偏移位置

    Returns:
        ``(段落末偏移, 句末偏移)``，偏移是「末字符之后」的位置。

    段落末偏移来自 ``"\\n\\n"`` 切分的结果——这正是解析层与分块层约定的结构边界。
    句末偏移是段落内部的句子边界，是次优但同样可接受的落刀点。
    """
    paragraph_ends: Set[int] = set()
    sentence_ends: Set[int] = set()
    cursor = 0
    for paragraph in text.split("\n\n"):
        for index, char in enumerate(paragraph):
            if char in SENTENCE_END:
                sentence_ends.add(cursor + index + 1)
        cursor += len(paragraph)
        paragraph_ends.add(cursor)
        sentence_ends.add(cursor)
        cursor += 2  # 跨过 "\n\n"
    return paragraph_ends, sentence_ends


def paragraph_break_quality(text: str) -> Tuple[int, int]:
    """统计段落断点总数，以及其中落在句子/结构边界上的数量

    这是 :func:`measure_boundary_alignment` 的**护栏**。仅看「块尾落在 ``\\n\\n`` 边界
    上」的比例会被轻易刷高：只要把**每一行**都标成段落，对齐率立刻 100%，而块边界
    实际仍落在版面折行处——即改造前的病态状态。故必须同时看断点本身的来源：

    * 断点前一个字符是句末标点 → 句子驱动的断点，语义正确；
    * 断点后一行以列表项/章节标题开头 → 结构驱动的断点，语义正确；
    * 其余（前一行既未结束句子，后一行也不是新的结构单元）→ **版面驱动的断点**，
      说明段落重建把本属同段的内容切开了。

    Returns:
        ``(断点总数, 语义断点数)``
    """
    parts = text.split("\n\n")
    starts: List[int] = []
    position = 0
    for part in parts:
        starts.append(position)
        position += len(part) + 2

    total = 0
    aligned = 0
    for index in range(1, len(parts)):
        total += 1
        previous_end = starts[index] - 2  # 前一段末字符之后的偏移
        # 取末尾若干字符交给 ends_sentence：句末标点可能后跟 1~2 个收尾符号
        if previous_end > 0 and ends_sentence(text[max(0, previous_end - 4) : previous_end]):
            aligned += 1
            continue
        head = parts[index].lstrip().split("\n", 1)[0]
        if starts_structural_block(head):
            aligned += 1
    return total, aligned


def measure_boundary_alignment(
    segments: List[TextSegment], splitter: TextSplitter
) -> Dict[str, object]:
    """量化「块尾是否落在文档结构块的边缘」

    这是本报告回答的核心问题。判据是把每个块尾映射为它在所属段内的字符偏移，
    再看该偏移是否属于结构边界：

    * ``at_paragraph``——落在 ``\\n\\n`` 段落边界上（最优）；
    * ``at_sentence``——落在段落内部的句末标点上（次优，句子完整）；
    * ``inside``——两者都不是，即**把一个句子从中间切开**（缺陷）。

    ``unresolved`` 是块文本无法在段内定位的数量（理论上为 0；非 0 说明块的
    ``strip`` 改动或重叠回溯改变了内容，属实现异常，须排查而非忽略）。
    """
    at_paragraph = at_sentence = inside = unresolved = 0
    # 按**结构组**遍历（与分块器同一套分组与文本）：块是在组内切出来的，
    # 用「段」为单位度量会与实现漂移。
    for _group, group_text in splitter.iter_group_texts(segments):
        # 归一掉尾部空白再算边界：组文本常以空行结尾，而块是 ``strip()`` 过的，
        # 直接比对偏移会把「本就落在段落末尾的块」误判为「切在段落内部」——
        # 这是纯度量假象，必须先消除。
        text = group_text.rstrip()
        if not text:
            continue
        paragraph_ends, sentence_ends = structure_boundaries(text)
        cursor = 0
        for piece in splitter._split_recursive(text, splitter.separators):
            start = text.find(piece, cursor)
            if start < 0:
                start = text.find(piece)
            if start < 0:
                unresolved += 1
                continue
            cursor = start
            end = start + len(piece)
            if end in paragraph_ends:
                at_paragraph += 1
            elif end in sentence_ends:
                at_sentence += 1
            else:
                inside += 1

    total = at_paragraph + at_sentence + inside
    return {
        "boundary_total": total,
        "boundary_paragraph_ratio": round(at_paragraph / total, 4) if total else 0.0,
        "boundary_sentence_ratio": round(at_sentence / total, 4) if total else 0.0,
        "boundary_inside_ratio": round(inside / total, 4) if total else 0.0,
        "boundary_unresolved": unresolved,
    }


def measure(
    segments: List[TextSegment],
    chunks: List[TextChunk],
    splitter: TextSplitter,
    heading_markup: bool = False,
) -> Dict[str, object]:
    """把「解析 + 分块」结果折算为一组结构指标

    入参只用纯数据结构，不触碰数据库或配置，便于单测直接构造。

    Args:
        heading_markup: 源格式是否**在文本里保留标题标记**（仅 Markdown 为真）。
            只有此时「孤儿标题块」才能被可靠识别——PDF/DOCX 提取后的标题不带标记，
            用同一条判据会在 PDF 上产生大量误报。
    """
    full_text = "\n".join(s.text for s in segments)
    double_newline = full_text.count("\n\n")
    single_newline = full_text.count("\n")

    lengths = sorted(len(c.text) for c in chunks)
    chunk_count = len(chunks)

    def _percentile(p: float) -> int:
        if not lengths:
            return 0
        return lengths[min(chunk_count - 1, int(chunk_count * p))]

    sep_hist = Counter(
        picked_separator_level(s.text, splitter.separators) for s in segments
    )

    # 每组产出块数：分布集中在 1 说明组边界即硬块边界、从未合并过
    per_group: Counter = Counter()
    group_texts = list(splitter.iter_group_texts(segments))
    for _group, group_text in group_texts:
        per_group[len(splitter._split_recursive(group_text, splitter.separators))] += 1

    metrics: Dict[str, object] = {
        "segments": len(segments),
        "chars": len(full_text),
        "double_newline": double_newline,
        "single_newline": single_newline,
        "paragraph_ratio": round(double_newline / single_newline, 4)
        if single_newline
        else 0.0,
        "sep_level_hist": {str(k): v for k, v in sorted(sep_hist.items())},
        "sep_level_top": max(sep_hist.items(), key=lambda kv: kv[1])[0]
        if sep_hist
        else None,
        "chunks": chunk_count,
        "chunk_len_min": lengths[0] if lengths else 0,
        "chunk_len_p50": _percentile(0.5),
        "chunk_len_p90": _percentile(0.9),
        "chunk_len_max": lengths[-1] if lengths else 0,
        "chunk_len_avg": round(sum(lengths) / chunk_count, 1) if chunk_count else 0.0,
        "chunks_per_segment_hist": {str(k): v for k, v in sorted(per_group.items())},
    }
    if not chunk_count:
        metrics.update(
            {
                "tiny_ratio": 0.0,
                "half_ratio": 0.0,
                "tail_sentence_ratio": 0.0,
                "size_utilisation": 0.0,
                "l0_segment_ratio": round(sep_hist.get(0, 0) / len(segments), 4)
                if segments
                else 0.0,
                "boundary_total": 0,
                "boundary_paragraph_ratio": 0.0,
                "boundary_sentence_ratio": 0.0,
                "boundary_inside_ratio": 0.0,
                "boundary_unresolved": 0,
                "paragraph_breaks": 0,
                "paragraph_break_aligned_ratio": 0.0,
                "cross_page_chunks": 0,
                "mixed_heading_chunks": 0,
                "table_chunks": 0,
                "code_chunks": 0,
                "atomic_chunks": 0,
                "orphan_heading_ratio": 0.0,
                "toc_leak_ratio": 0.0,
                "heading_precision": 1.0,
            }
        )
        if heading_markup:
            metrics["orphan_heading_chunks"] = 0
        return metrics

    tiny = sum(1 for length in lengths if length < TINY_CHARS)
    half = sum(1 for length in lengths if length < splitter.chunk_size / 2)
    tail_sentence = sum(1 for c in chunks if ends_sentence(c.text))

    metrics["tail_sentence_ratio"] = round(tail_sentence / chunk_count, 4)
    metrics["tiny_ratio"] = round(tiny / chunk_count, 4)
    metrics["half_ratio"] = round(half / chunk_count, 4)
    # 平均块长占 chunk_size 的比例：过低说明尺寸预算被浪费
    metrics["size_utilisation"] = round(
        (sum(lengths) / chunk_count) / splitter.chunk_size, 4
    )
    # 命中最外层分隔符 ``"\n\n"`` 的段占比。近 0 说明解析层没有产出段落结构，
    # 分块只能退到「行」一级——这是块边界错位的机制性指标。
    metrics["l0_segment_ratio"] = (
        round(sep_hist.get(0, 0) / len(segments), 4) if segments else 0.0
    )
    metrics.update(measure_boundary_alignment(segments, splitter))

    # 段落断点质量：护栏指标，防止用「把每行都标成段落」刷高对齐率
    break_total = break_aligned = 0
    for _group, group_text in group_texts:
        group_total, group_aligned = paragraph_break_quality(group_text.rstrip())
        break_total += group_total
        break_aligned += group_aligned
    metrics["paragraph_breaks"] = break_total
    metrics["paragraph_break_aligned_ratio"] = (
        round(break_aligned / break_total, 4) if break_total else 0.0
    )

    # 结构组合并的直接观测量：跨页块与覆盖多个小节的块。
    # 它们不是「缺陷」，而是块出处升级为区间之后的正常形态，故只观测、不判优劣。
    # ``mixed_heading_chunks`` 只统计 ``heading_path`` **粗于**实际覆盖范围的块
    # （见 ``TextSplitter._group_heading``），合并常态（父节 + 其子节）不计入。
    metrics["cross_page_chunks"] = sum(
        1 for c in chunks if c.page_end is not None and c.page_end != c.page
    )
    metrics["mixed_heading_chunks"] = sum(1 for c in chunks if c.heading_path_mixed)

    # ── S3/S4/S5 新增指标：块类型与结构泄漏 ──────────────────────────────
    # 表格 / 代码原子块计数：直接量化「表格污染是否已被切成独立原子块」。
    table_chunks = sum(1 for c in chunks if c.kind == "table")
    code_chunks = sum(1 for c in chunks if c.kind == "code")
    metrics["table_chunks"] = table_chunks
    metrics["code_chunks"] = code_chunks
    metrics["atomic_chunks"] = table_chunks + code_chunks
    # 孤儿标题块占比（绝对计数见 orphan_heading_chunks）。
    orphan = sum(1 for c in chunks if is_orphan_heading_chunk(c.text)) if heading_markup else 0
    metrics["orphan_heading_ratio"] = (
        round(orphan / chunk_count, 4) if heading_markup else 0.0
    )
    # 目录泄漏率：含点线引导符（``1. 引言.... 3``）的块占比。>0 说明目录页抑制失效。
    toc_leak = sum(1 for c in chunks if any(_is_toc_leak_line(ln) for ln in c.text.split("\n")))
    metrics["toc_leak_ratio"] = round(toc_leak / chunk_count, 4)
    # 标题路径精度：块的 heading_path 是否真能对应到某个真实标题小节。
    # 以 heading 类型段的 heading_path 为地面真值；若块被错挂到不存在的章节，
    # 精度下降（这正是 S2 把表格行误判标题的症状）。
    real_headings = {s.heading_path for s in segments if s.kind == "heading" and s.heading_path}
    if real_headings:
        ok = 0
        total = 0
        for c in chunks:
            if not c.heading_path:
                continue
            total += 1
            if any(
                c.heading_path == h
                or h.startswith(c.heading_path + HEADING_SEPARATOR)
                for h in real_headings
            ):
                ok += 1
        metrics["heading_precision"] = round(ok / total, 4) if total else 1.0
    else:
        metrics["heading_precision"] = 1.0

    if heading_markup:
        metrics["orphan_heading_chunks"] = sum(
            1 for c in chunks if is_orphan_heading_chunk(c.text)
        )
    return metrics


def analyze_file(path: str, file_type: str, splitter: Optional[TextSplitter] = None) -> Dict[str, object]:
    """解析并分块单个文件，返回其指标（失败时抛出，由调用方收集）"""
    splitter = splitter or TextSplitter()
    segments = DocumentParser.parse_segments(path, file_type)
    chunks = splitter.split_segments(segments)
    result: Dict[str, object] = {"path": path, "file_type": file_type}
    result.update(
        measure(segments, chunks, splitter, heading_markup=(file_type == "md"))
    )
    return result


def analyze_directory(root: str, splitter: Optional[TextSplitter] = None) -> List[Dict[str, object]]:
    """递归分析目录下所有受支持格式的文件

    同名同大小的文件只分析一次。上传目录会为每份文档复制一份原件，同一本 PDF
    在库中被重复上传 N 次就有 N 份**内容相同**的副本，逐个分析会把同一行结果刷屏，
    使报告失去可读性。判重键取 ``(文件名, 字节数)``，与上传去重键
    ``(kb_id, file_name, file_size)`` 同构；命中的副本数记在 ``copies`` 里，
    以便区分「只传了一份」与「传了 8 份」。

    ``splitter`` 必须由调用方传入并**透传**给 :func:`analyze_file`：否则
    ``--chunk-size`` / ``--min-fill`` 这类覆盖参数在 ``--dir`` 模式下会静默失效，
    让人以为「改了参数指标没动」。
    """
    supported = set(DocumentParser.SEGMENT_PARSERS)
    paths = sorted(
        p for p in Path(root).rglob("*") if p.is_file() and p.suffix.lower() in supported
    )

    rows: List[Dict[str, object]] = []
    seen: Dict[Tuple[str, int], Dict[str, object]] = {}
    for path in paths:
        key = (path.name, path.stat().st_size)
        existing = seen.get(key)
        if existing is not None:
            existing["copies"] = int(existing.get("copies", 1)) + 1
            continue
        row = analyze_file(str(path), path.suffix.lower().lstrip("."), splitter)
        row["copies"] = 1
        seen[key] = row
        rows.append(row)
    return rows


def analyze_knowledge_base(kb_id: str) -> List[Dict[str, object]]:
    """分析某个知识库下所有已完成文档（需数据库连接）

    直接对 ``knowledge_documents.file_url`` 指向的落盘原件重新解析，**不读库里的
    分块内容**——目的是回答「按当前代码重新切会得到什么」，而不是「库里现在是什么」。
    """
    from app.core.database import sessionLocal
    from app.models.knowledge_document import DocumentStatus, KnowledgeDocument

    session = sessionLocal()
    try:
        docs = (
            session.query(KnowledgeDocument)
            .filter(
                KnowledgeDocument.kb_id == kb_id,
                KnowledgeDocument.status == DocumentStatus.COMPLETED,
            )
            .all()
        )
        results: List[Dict[str, object]] = []
        for doc in docs:
            path = doc.file_url
            if not path or not Path(path).exists():
                results.append(
                    {"path": f"<missing:{doc.file_name}>", "file_type": doc.file_type}
                )
                continue
            try:
                item = analyze_file(path, doc.file_type)
            except Exception as exc:  # 单文档失败不应中断整份报告
                item = {
                    "path": path,
                    "file_type": doc.file_type,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            item["document_id"] = doc.id
            item["file_name"] = doc.file_name
            item["active_chunk_epoch"] = doc.active_chunk_epoch
            results.append(item)
        return results
    finally:
        session.close()


# ────────────────────────────── 报告渲染 ──────────────────────────────


def _pct(value: object) -> str:
    return f"{float(value):.1%}" if isinstance(value, (int, float)) else "n/a"


def _short(path: str, limit: int = 38) -> str:
    name = Path(path).name
    return name if len(name) <= limit else name[: limit - 1] + "…"


def render_report(rows: Iterable[Dict[str, object]], splitter: TextSplitter) -> str:
    """把指标渲染成便于人工阅读的分块表"""
    lines: List[str] = []
    lines.append(
        f"分块参数: chunk_size={splitter.chunk_size} "
        f"chunk_overlap={splitter.chunk_overlap} "
        f"min_fill_chars={splitter.min_fill_chars} "
        f"separators={splitter.separators!r}"
    )
    lines.append("")

    double_newline_label = "\\n\\n"
    header = (
        f"{'文档':<40}{'类型':<6}{'段':>5}{'字符':>9}{double_newline_label:>7}{'块':>6}{'均长':>6}"
        f"{'极短':>7}{'半空':>7}{'段界':>7}{'句界':>7}{'切断':>7}{'孤儿':>6}"
        f"{'表':>5}{'码':>5}{'目录漏':>7}{'标题精':>7}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for row in rows:
        if "error" in row:
            lines.append(f"{_short(str(row['path'])):<40}解析失败: {row['error']}")
            continue
        if row.get("chunks") is None:
            lines.append(f"{_short(str(row['path'])):<40}原件缺失")
            continue
        lines.append(
            f"{_short(str(row['path'])):<40}"
            f"{str(row.get('file_type', '')):<6}"
            f"{row.get('segments', 0):>5}"
            f"{row.get('chars', 0):>9}"
            f"{row.get('double_newline', 0):>7}"
            f"{row.get('chunks', 0):>6}"
            f"{row.get('chunk_len_avg', 0):>6}"
            f"{_pct(row.get('tiny_ratio', 0)):>7}"
            f"{_pct(row.get('half_ratio', 0)):>7}"
            f"{_pct(row.get('boundary_paragraph_ratio', 0)):>7}"
            f"{_pct(row.get('boundary_sentence_ratio', 0)):>7}"
            f"{_pct(row.get('boundary_inside_ratio', 0)):>7}"
            f"{str(row.get('orphan_heading_chunks', 'n/a')):>6}"
            f"{row.get('table_chunks', 0):>5}"
            f"{row.get('code_chunks', 0):>5}"
            f"{_pct(row.get('toc_leak_ratio', 0)):>7}"
            f"{_pct(row.get('heading_precision', 1.0)):>7}"
        )

    lines.append("")
    lines.append(
        "列说明: 极短=块长<50字符  半空=块长<chunk_size/2  "
        "段界=块尾落在段落边界上  句界=块尾落在句末标点上  切断=块尾两不沾（句子被切开）  "
        "孤儿=整块只有标题行（仅 md 可判定）"
    )
    lines.append("")

    for row in rows:
        if "error" in row or row.get("chunks") is None:
            continue
        sep_names = {
            _SEP_LEVEL_NAMES.get(int(k), k): v
            for k, v in (row.get("sep_level_hist") or {}).items()
        }
        lines.append(
            f"  {_short(str(row['path']), 34):<34} "
            f"段落比={row.get('paragraph_ratio', 0):.3f}  "
            f"L0可达={_pct(row.get('l0_segment_ratio', 0))}  "
            f"分隔符命中={sep_names or '{}'}  "
            f"每组块数={row.get('chunks_per_segment_hist', {})}  "
            f"尺寸利用={_pct(row.get('size_utilisation', 0))}  "
            f"跨页块={row.get('cross_page_chunks', 0)}  "
            f"跨小节块={row.get('mixed_heading_chunks', 0)}  "
            f"断点语义率={_pct(row.get('paragraph_break_aligned_ratio', 0))}"
        )
    return "\n".join(lines)


# ────────────────────────────── 基线对比 ──────────────────────────────

#: 值越小越好的指标（其余指标越大越好，或仅作观测量不参与判劣）
_LOWER_IS_BETTER = (
    "tiny_ratio",
    "half_ratio",
    "orphan_heading_chunks",
    "orphan_heading_ratio",
    "toc_leak_ratio",
    "boundary_inside_ratio",
    "boundary_unresolved",
)

#: 值越大越好的指标
_HIGHER_IS_BETTER = (
    "tail_sentence_ratio",
    "size_utilisation",
    "boundary_paragraph_ratio",
    "boundary_sentence_ratio",
    "paragraph_break_aligned_ratio",
    "heading_precision",
)


def compare_with_baseline(
    current: List[Dict[str, object]], baseline: List[Dict[str, object]]
) -> Tuple[List[str], bool]:
    """与基线逐文档对比，返回（报告行，是否存在劣化）

    匹配键用 ``path``。基线中缺失的文档视为「新增」，不参与劣化判定——否则每加
    一份文档都会让门禁失败。基线中**缺失的指标**同样跳过：指标集会随工具演进而
    增加，把「基线里没有这一项」当成 0 会把新指标一律误判为劣化。
    """
    by_path = {str(r["path"]): r for r in baseline if "error" not in r}
    report: List[str] = []
    degraded = False

    for row in current:
        if "error" in row or row.get("chunks") is None:
            continue
        base = by_path.get(str(row["path"]))
        if not base:
            report.append(f"  [新增] {_short(str(row['path']))}")
            continue

        deltas: List[str] = []
        for keys, worse in ((_LOWER_IS_BETTER, lambda a, b: a > b),
                            (_HIGHER_IS_BETTER, lambda a, b: a < b - 1e-9)):
            for key in keys:
                before, after = base.get(key), row.get(key)
                if not isinstance(before, (int, float)) or not isinstance(
                    after, (int, float)
                ):
                    continue
                if worse(after, before):
                    degraded = True
                    deltas.append(f"{key} 劣化 {before} → {after}")
        report.append(
            f"  {'[劣化]' if deltas else '[持平]'} {_short(str(row['path']))}"
            + ("  " + "; ".join(deltas) if deltas else "")
        )
    return report, degraded


# ────────────────────────────── CLI ──────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chunking_quality_report",
        description="文档切分质量报告（只读）：量化块边界与文档结构边界的对齐程度",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    source = parser.add_argument_group("分析对象（三选一）")
    source.add_argument("--path", action="append", help="单个文件路径，可重复")
    source.add_argument("--dir", help="递归分析该目录下所有受支持格式的文件")
    source.add_argument("--kb", help="知识库 ID：分析其下所有已完成文档")

    out = parser.add_argument_group("输出与门禁")
    out.add_argument("--json-out", help="把指标写为 JSON，供后续 --baseline 对比")
    out.add_argument("--baseline", help="历史指标 JSON：逐文档对比并标记劣化")
    out.add_argument("--chunk-size", type=int, help="覆盖 chunk_size（默认取配置）")
    out.add_argument("--chunk-overlap", type=int, help="覆盖 chunk_overlap（默认取配置）")
    out.add_argument(
        "--min-fill",
        type=int,
        help="覆盖可合并串的最小填充长度（默认 chunk_size×0.5）；传 0 可关闭合并以做 A/B 对比",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not any((args.path, args.dir, args.kb)):
        build_parser().print_help()
        return 1

    splitter = TextSplitter(
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        min_fill_chars=args.min_fill,
    )

    rows: List[Dict[str, object]] = []
    failures = 0
    if args.path:
        for path in args.path:
            suffix = Path(path).suffix.lower().lstrip(".")
            try:
                rows.append(analyze_file(path, suffix, splitter))
            except Exception as exc:
                failures += 1
                rows.append({"path": path, "file_type": suffix, "error": f"{type(exc).__name__}: {exc}"})
    if args.dir:
        rows.extend(analyze_directory(args.dir, splitter))
    if args.kb:
        rows.extend(analyze_knowledge_base(args.kb))

    failures += sum(1 for r in rows if "error" in r)
    print(render_report(rows, splitter))

    if args.json_out:
        payload = {
            "chunk_size": splitter.chunk_size,
            "chunk_overlap": splitter.chunk_overlap,
            "min_fill_chars": splitter.min_fill_chars,
            "documents": rows,
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n指标已写入 {args.json_out}")

    degraded = False
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        report, degraded = compare_with_baseline(rows, baseline.get("documents", []))
        print("\n与基线对比：")
        print("\n".join(report) if report else "  （无可比文档）")

    if degraded:
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
