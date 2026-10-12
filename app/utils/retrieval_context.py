"""检索结果的「上下文装配」纯函数（P4）

**为什么需要这一层**：分块尺寸与「喂给 LLM 的文本」是两个互相矛盾的目标。

* 检索希望块**小**——块越小，向量越聚焦于单一语义，命中精度越高，也让 top_k
  能覆盖更多不同位置；
* 生成希望块**大**——一段被截断在句子中间、且不说明自己出自哪里的文本，既有
  指代缺失（「它的默认值是 0」中的「它」），也无法核对（缺出处）。

把块整体调大只能同时牺牲两者（块变大 → 命中变糊；块仍会被截断）。正确做法是
**写入侧保持小块，读取侧做装配**：检索命中后再把上下文补回来。本模块承担装配
中**不依赖数据库**的部分，因此可以脱离 Qdrant / MySQL 单独测试。

装配由两个**相互独立**的开关控制（见 ``app/core/config.py`` 的检索段）：

1. **上下文头**：把「文件名 / 小节路径 / 页码范围」前置为一行出处标记；
2. **邻块扩展**：把 ``chunk_index ± N`` 的同代邻块按顺序拼成窗口。

两者都只写入新增的 ``llm_content`` 字段，**绝不修改 ``content``**。这一点是刻意
的：``content`` 同时是去重键、前端展示文本与既有调用方的取值处，一旦被注入就会被
重复计数、被显示成带标记的脏文本。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

__all__ = [
    "PAGE_RANGE_SEP",
    "CHUNK_TYPE_LABELS",
    "format_page_range",
    "format_heading_scope",
    "format_chunk_type",
    "build_context_header",
    "trim_overlap",
    "join_window",
]

#: 页码范围连接符。用 en dash（U+2013）而非连字符，与前端 ``citation.ts`` 保持一致——
#: 连字符在「第 3-4 页」里会被误读为负号或编号的一部分，中文排版惯例亦为短横。
PAGE_RANGE_SEP = "\u2013"

#: ``chunk_type`` -> 出处标记里显示的中文标签。
#:
#: **只给需要让模型换一种读法的类型加标签**：
#:
#: * ``table``——表格是二维的，按纯文本单行读会把行与列串味（「第 3 列的值」
#:   在纯文本里根本没有载体）；
#: * ``code``——代码逐字敏感，模型不应改写、压缩或"顺手修正"它；
#: * ``image``——该块是图片占位，正文本身没有语义，须提示模型按图理解。
#:
#: ``text`` / ``title`` **刻意不加**：给正文标一个 ``[正文]`` 是零信息量的噪音，
#: 而上下文预算是稀缺资源——用零信息前缀去挤占它，等于用检索质量换形式完整。
CHUNK_TYPE_LABELS = {
    "table": "表格",
    "code": "代码",
    "image": "图片",
}


def format_chunk_type(chunk_type: Optional[str]) -> Optional[str]:
    """把块类型格式化为出处标记里的标签

    未知类型（含 ``None``、``text``、``title``）一律返回 ``None``：出处标记按需
    出现，返回空串会让调用方写出 ``if label:`` 之外的分支逻辑，而「没有标签」与
    「标签为空」是同一件事，不该有两种表示。
    """
    if not chunk_type:
        return None
    return CHUNK_TYPE_LABELS.get(chunk_type)


def format_page_range(page: Optional[int], page_end: Optional[int]) -> Optional[str]:
    """把闭区间页码格式化为 ``p.37`` / ``p.37–38``

    ``source_page`` / ``source_page_end`` 是**闭区间**：块可以跨页（结构组合并的
    必然结果）。只显示起始页会让「块里含第 38 页内容」变成沉默的错答，因此区间
    一致时也必须走同一条格式化路径（而不是"两个值相等就退化成单值"的隐式分支）。
    """
    if page is None:
        return None
    if page_end is None or page_end == page:
        return f"p.{page}"
    return f"p.{page}{PAGE_RANGE_SEP}{page_end}"


def format_heading_scope(heading_path: Optional[str], mixed: bool = False) -> Optional[str]:
    """把标题路径格式化为 ``§ A > B`` / ``§ A 等小节``

    ``mixed`` 为真表示该路径只标到了若干兄弟子节的**公共祖先**，块内并无该祖先
    自身的内容。此时必须显式声明「等小节」，否则引用会断言「本块出自 A」，而 A
    恰好是块里唯一没有的那一节——这是把粗化标记当装饰品用的典型错法。
    """
    if not heading_path:
        return None
    return f"§ {heading_path} 等小节" if mixed else f"§ {heading_path}"


def build_context_header(
    doc_name: Optional[str] = None,
    heading_path: Optional[str] = None,
    heading_path_mixed: bool = False,
    page: Optional[int] = None,
    page_end: Optional[int] = None,
    chunk_type: Optional[str] = None,
) -> Optional[str]:
    """构造一行出处标记，例如 ``[《手册.pdf》 | 表格 | § 3.2 | p.37–38]``

    各成分（文件名 / 块类型 / 小节 / 页码）**按需出现**，用 ``" | "``（两侧留空）
    连接，全部缺失时返回 ``None``——返回空串会让调用方写 `if header:` 之外的判断
    逻辑，而 ``None`` 与「没有可标注的出处」是同一件事，不应该有两种表示。

    可得性因格式而异：PDF 有页码无标题路径（pypdf 只给文本流），md/docx 反之。
    因此这里不做「三者齐全才输出」的限制，否则 md 与 PDF 会有一方永远拿不到标记。

    ``chunk_type`` 给的是**命中块自身**的类型标签（表格 / 代码 / 图片），不是整段
    ``llm_content`` 的类型：开启邻块扩展后，标记行后面跟的是含前后邻块的窗口，
    而邻块可能是别的类型。把类型放进方括号内、与标题路径和页码并列，正是为了让
    「它描述的是被引用的那一块」在形式上成立——把 ``[表格]`` 写成窗口的独立前缀，
    在本块是段落、邻块是表格时会给出错误的暗示。

    成分顺序固定为 **文件 → 类型 → 小节 → 页码**：先「哪份文件」建立身份，再
    「这是什么形态的内容」确定读法，最后才是位置。顺序固定使标记可被机械解析，
    也让同一份文档的标记在多次检索中逐字一致（便于比对与去重）。
    """
    parts: List[str] = []
    if doc_name:
        parts.append(f"《{doc_name}》")
    label = format_chunk_type(chunk_type)
    if label:
        parts.append(label)
    scope = format_heading_scope(heading_path, mixed=heading_path_mixed)
    if scope:
        parts.append(scope)
    page_label = format_page_range(page, page_end)
    if page_label:
        parts.append(page_label)
    if not parts:
        return None
    return "[" + " | ".join(parts) + "]"


def trim_overlap(prev_text: str, next_text: str, max_overlap: int) -> str:
    """裁掉 ``next_text`` 开头与 ``prev_text`` 末尾重合的部分

    分块器带 ``chunk_overlap`` 字符重叠：相邻两块的尾部/首部是同一段文字的副本。
    直接拼接会把这段文字在 LLM 上下文里重复一遍——重复内容既浪费预算，也会让
    模型把同一句当成两条独立证据。

    实现是**有界**的：只比较最长 ``max_overlap`` 个字符，故复杂度与重叠长度相关
    而与文本长度无关（PDF 整份成组时文本可达数万字符，用 ``find`` 扫描整串会让
    每对相邻块都变成全串搜索）。

    只裁「整段重合」这一种情形；重叠处若被上游块边界改写（例如块尾加了标题行），
    则不裁——宁可留下少量重复，也不做模糊匹配去猜裁多少字符。
    """
    if max_overlap <= 0 or not prev_text or not next_text:
        return next_text
    limit = min(max_overlap, len(prev_text), len(next_text))
    for size in range(limit, 0, -1):
        if prev_text.endswith(next_text[:size]):
            return next_text[size:]
    return next_text


def join_window(texts: Sequence[str], overlap: int, separator: str = "\n\n") -> str:
    """把一串相邻块拼成窗口文本，并裁掉相邻处重叠

    Args:
        texts: 按 ``chunk_index`` 升序排列的块内容
        overlap: 分块时的重叠字符数（``config.chunk_overlap``）
        separator: 块间连接符。用空行而非单换行：结构分块的边界本身就落在段落
            边界上，用单换行会让「两块内容」读起来像一段连续文字，模型更易把
            跳行后的内容误接。

    Returns:
        窗口文本。裁重叠后为空的块（块内容完全被前一块尾部覆盖）直接跳过，
        不留空段——否则窗口里会出现连续空行，让模型以为中间省略了内容。
    """
    if not texts:
        return ""

    kept: List[str] = []
    previous_raw: Optional[str] = None
    for text in texts:
        body = (
            text if previous_raw is None else trim_overlap(previous_raw, text, overlap)
        )
        if body.strip():
            kept.append(body)
        # 重叠参照的是**上一块原文**而非裁剩的部分：裁剩文本可能短于真实重叠长度
        # （前一块被裁得较多时），而检测窗口上限含 len(prev)，用裁剩文本会让上限
        # 收缩、漏掉本应裁掉的重复。
        previous_raw = text
    return separator.join(kept)


def collect_window_indexes(
    center: int,
    radius: int,
    floor: int = 0,
) -> List[int]:
    """返回以 ``center`` 为中心、半径 ``radius`` 的闭区间下标列表

    独立成函数是为了让「邻块窗口到底包含哪些下标」这一约定可被直接断言——
    它是 ``chunk_index ± N`` 的唯一定义处，散落在服务层内联计算时无法被测试覆盖
    （边界、负数、radius=0 三种情形都曾各写一遍）。
    """
    start = max(floor, center - radius)
    return [index for index in range(start, center + radius + 1)]


def iter_unique(rows: Iterable) -> List:
    """按首次出现顺序去重（保持确定性输出）

    仅用于把「多个命中块请求的邻块下标」合并成一次查询，去重顺序不影响正确性，
    但固定的顺序让日志与测试断言稳定。
    """
    seen = set()
    ordered = []
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        ordered.append(row)
    return ordered
