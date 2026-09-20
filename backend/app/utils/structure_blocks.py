"""文档结构解析：把「版面行流」还原为「带类型的块流」（S1 + S2）

问题
----
PDF 侧的解析此前止步于「版面行流 → 段落流」（:mod:`app.utils.text_structure`），
于是分块器可用的结构边界**只有段落**：标题、表格、代码块的位置全都不可知。
实测后果——``knowledge_chunks.heading_path`` 在 PDF 上 **1414/1414 全为 NULL**，
且「识别表格」这一步在本仓库从未存在（``app/`` 下 ``find_tables`` /
``extract_table`` / ``pdfplumber`` 零命中）。

本模块补上两件事：**识别标题**（S2）与**产出带类型的块**（S1）。表格识别（S3）
另开模块，共用本模块的片段/行基础设施。

两条被实测确立的判据
--------------------
1. **文本来源必须是默认模式，不是回调片段**
   ``pypdf`` 的 ``extract_text(visitor_text=f)`` 能给出 ``f(text, cm, tm, font_dict,
   font_size)``，但**含插图的页面**其片段文本与默认模式**不是同一个文本集**：实测
   ``AI-Agents-in-Depth`` 的 p10/p16，visitor 模式多出图内标签（``Agent（智能体）
   Harness（模型运行与交互层）上下文观察·历史``），默认模式则含图题注
   （``图1-1 Agent 与 Environment 的闭环交互``）。二者差异达该页 15–19% 的字符。
   故：**默认模式取权威文本**（与既有行为一致、不引入图标签噪声），
   **visitor 只取版式信号**，两者按「去空白后文本相等」对齐。
   **对不上信号的行一律按普通段落处理**——绝不猜测（这是本模块的保守原则）。

2. **真实字号要自己还原**
   ``visitor_text`` 的 ``font_size`` **恒为 1.0**（内容流用 ``Tf`` 设 1 倍、真实缩放
   落在文本矩阵 ``Tm`` 里），故 **有效字号 = ``font_size × hypot(tm[0], tm[1])``**。
   另外 ``visitor_operand_before`` 的真实签名是 ``(operator, operands, cm, tm)``
   ——**``operator`` 在第一位**（写成 ``(operands, operator, ...)`` 会抛
   ``TypeError: unhashable type: 'list'``）。

为什么必须做「文档级归一」而非固定阈值
--------------------------------------
实测三条反例（同一套阈值在另一份文档上必然失效）：

* ``Happy-LLM-0727.pdf``（PPT 导出）**等宽字体占 60.5%** ⇒「等宽＝代码」会误判一半
  正文，必须按**文档级等宽基率**归一后才可用；
* 目录页的「编号 + 点线 + 页码」会被误判为标题 ⇒ 需 TOC 抑制；
* 同文档 ``x0`` 出现 ``-15.3`` / ``0.0``（版面溢出）⇒ 坐标类判据一律用**相对位置**
  （行宽 / 页宽），不用绝对磅值。

确定性
------
本模块的判定逻辑全部为纯函数：同一输入恒得同一输出，不含随机、时间、IO、环境依赖。
分块结果参与 ``vector_id`` 推导，故确定性是可复现性的前提。IO 只集中在
:func:`read_pdf` 一处（``pypdf`` 惰性导入）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from app.utils.text_structure import (
    ends_sentence,
    is_noise_line,
    join_wrapped,
    starts_structural_block,
    normalize_for_dedup,
)

# ────────────────────────────── 类型 ──────────────────────────────

BlockKind = Literal[
    "title",      # 文档主标题（封面）
    "heading",    # 章节标题（带 level）
    "paragraph",  # 正文段落
    "list_item",  # 列表项
    "table",      # 表格（S3 产出）
    "code",       # 代码块
    "caption",    # 图/表题注
    "toc",        # 目录条目（标记而非删除）
]


@dataclass(frozen=True)
class Fragment:
    """一个文本片段（``visitor_text`` 的产物），只取版式信号，**不作为文本来源**"""

    page: int
    text: str
    size: float          # 有效字号 = font_size × hypot(tm[0], tm[1])
    font: str
    x: float
    y: float
    bold: bool
    mono: bool


@dataclass(frozen=True)
class LayoutLine:
    """同一 y 上的片段聚合而成的一「行」，携带该行的版式信号"""

    page: int
    text: str
    size: float          # 该行**最大**有效字号（标题通常是行内最大者）
    x0: float
    x1: float
    y: float
    bold: bool
    mono_share: float    # 该行等宽片段的占比


@dataclass(frozen=True)
class DocLine:
    """权威文本的一行 + 其**可能缺失**的版式信号

    ``signal is None`` 表示该行在 visitor 通道中找不到对应行（含图页的图题注、
    被默认模式以不同方式拼接的行）。此时一切与版式有关的判据都不可用，该行
    按普通段落处理。
    """

    page: int
    text: str
    signal: Optional[LayoutLine] = None


@dataclass(frozen=True)
class Block:
    """带类型的块，是解析层交给分块层的**唯一**中间表示"""

    kind: BlockKind
    text: str
    page: Optional[int] = None
    page_end: Optional[int] = None
    level: Optional[int] = None       # heading 层级（1 基）
    heading_path: Optional[str] = None  # 该块所属的标题路径（含自身若为标题）
    bold: bool = False
    mono_share: float = 0.0
    meta: Dict[str, object] = field(default_factory=dict)


# ────────────────────────────── 可调判据 ──────────────────────────────

#: 行聚合的纵向容差（相对字号）。同一行的片段 y 会因基线/上标略有差异，
#: 用「字号的比例」而非绝对磅值，才能同时适配 9 磅正文与 36 磅封面标题。
Y_TOL_RATIO = 0.5

#: 标题判定的**加权和**阈值。低于阈值一律判普通段落——误判标题会把噪音写进
#: ``heading_path`` 这个本应可核对的字段，并经由检索层的 Contextual header
#: 注入到喂给 LLM 的文本里，代价不对称，故取保守侧。
HEADING_MIN_SCORE = 2.0

#: 「短行」判据（字符数）。标题通常短；正文行会折到行长上限。
SHORT_LINE_CHARS = 40

#: 标题层级上限（与 Markdown 的 ``#``~``######`` 对齐）。
MAX_HEADING_LEVEL = 6

#: 字号比值 → 层级的分档。用**相对正文的比值**而非绝对字号，才能跨文档复用。
LEVEL_RATIO_TIERS: Tuple[Tuple[float, int], ...] = (
    (2.00, 1),
    (1.50, 2),
    (1.30, 3),
    (1.20, 4),
    (1.12, 5),
)

#: 各信号的权重。
W_SIZE_STRONG = 3.0
W_SIZE_MEDIUM = 2.5
W_SIZE_WEAK = 1.5
W_SIZE_MARGINAL = 0.5
W_BOLD = 1.0
W_SHORT = 0.5
W_NUMBERED = 0.5

#: 判定「本行是代码」所需的等宽占比，以及「等宽已不稀奇」的文档级基率。
#:
#: 后者**不再充当整篇门禁**，只用于**抬高单行的等宽阈值**（文档级归一）。
#: 实测 PPT 导出的 ``Happy-LLM`` 全篇等宽占 60.03%，但分页统计显示 p1–p7 为 0%、
#: p8 起才 22–30%——等宽恰恰是**代码页的特有信号**。原实现按整篇基率否决判据，
#: 等于把「代码多」误判成「等宽不可信」，方向反了（实测 code 块 475 → 0）。
LINE_MONO_SHARE = 0.6
DOC_MONO_DISABLE = 0.5

# ── 代码行判据（多信号加权，见 docs/plan-parse-coverage-fix.md §2 P0-a） ──
#
# 为何不用「字体单信号」：是否等宽取决于文档制作者，PPT 导出、扫描件、部分中文
# 排版都不保证；而代码的**词法特征**与文档无关，可跨文档复用。社区实践
# （Docling / Unstructured）同样以「代码关键字 + token + 缩进/括号」为主信号。

#: 行首代码关键字：命中即该行几乎必然属于代码（Python / JS / Java / C 系）。
_CODE_KEYWORD_RE = re.compile(
    r"^(def|class|import|from|return|elif|else|for|while|with|try|except|finally|"
    r"async|await|yield|lambda|raise|assert|global|nonlocal|pass|break|continue|"
    r"package|public|private|protected|static|void|function|struct|enum|interface|"
    r"switch|case|default|do|new|delete|let|const|var|this|super)\b"
)
#: 行内代码 token：调用式、属性访问、赋值、比较运算符、装饰器、注释符、
#: 独占一行的括号。``\.\w+\(`` 用**通用方法调用**而非枚举 ``.append\(`` 等具体方法——
#: 后者会漏掉 ``nn.Linear(`` / ``xq.transpose(`` 这类主力形态。
_CODE_TOKEN_RE = re.compile(
    r"(self\.|cls\.|print\(|\w+\([^)]*\)\s*[:=]|==|!=|>=|<=|->|::|"
    r"\.\w+\(|\|\||&&|"
    r"^\s*@\w+|^\s*[{}()\[\]]\s*$|#\s|\b\w+\s*=\s*[\[{('\"]|;\s*$)"
)

#: 行首/行内注释符。在 PDF 里以 ``# `` 起行的独立行几乎必然是代码注释——正文段落
#: 不会以井号起行，故给强权重。这也是**中文注释**（``# 输出权重矩阵。``）唯一可依赖
#: 的特征：它既可能不等宽、又以句末标点收尾，靠其余信号都会漏判（实测落到
#: ``list_item`` 后成为 9 字符碎片块）。
_COMMENT_LINE_RE = re.compile(r"(^#\s|\s#\s|^//\s|^/\*|\*/$)")

#: 多信号加权阈值。各项权重按「证据强度」赋值：等宽、关键字、注释符是强证据
#: （可单独定案），token 是弱证据（需配合）；中文句末标点是**否证**（正文特征）。
W_CODE_MONO_STRONG = 2.0
W_CODE_MONO_WEAK = 0.8
#: 行首关键字本身就是**足以定案**的强证据：以 ``return `` / ``import `` / ``def ``
#: 起行的文本在 PDF 里没有第二种解释。（初版给的 1.5 分会让 ``import torch`` 这类
#: 无其他信号的行判不出来，而它恰恰是代码的主力形态。）
W_CODE_KEYWORD = 2.0
W_CODE_COMMENT = 2.0
W_CODE_TOKEN = 1.0
W_CODE_SENTENCE_END = -1.5
CODE_MIN_SCORE = 2.0

#: 标题允许偏离正文左边界的容差（相对正文字号）。取 2 倍字号（10 磅正文 ⇒ 20 磅）
#: 是为了容纳**缩进式的下级标题**，同时远小于插图内文字块的偏移量（实测 ≥ 90 磅）。
MARGIN_TOLERANCE_RATIO = 2.0

#: 估计左边界所需的最少正文字符数。低于此值众数不可靠，判据整体跳过。
MARGIN_MIN_BODY_CHARS = 200


# ────────────────────────────── IO（唯一的非纯函数入口） ──────────────────────────────

def read_pdf(file_path: str) -> Tuple[List[str], List[Fragment], List[GeometryLine]]:
    """读取 PDF：返回**默认模式**逐页文本、visitor 版式信号、与矢量线几何

    三次采集是刻意的，各司其职：

    * 默认模式 ``extract_text()`` 负责**文本**（含 pypdf 自己的词间空格处理）；
    * ``visitor_text`` 负责**版式信号**（字号/字体/坐标）；
    * ``visitor_operand_before`` 负责**矢量线框**（表格识别用）。

    三者可从同一次内容流遍历中获取，但调用方分别消费。几何只在 S3 表格识别时需要，
    不影响既有标题/段落判定。

    Returns:
        ``(pages, fragments, geom)``；``pages[i]`` 为第 ``i+1`` 页默认文本（空白页归一
        为 ``""``），``fragments`` 为全部页的片段，``geom`` 为全部页的矢量线段。

    Raises:
        ImportError: 缺少 ``pypdf``
        ValueError: 解析失败
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError(
            "pypdf is required for PDF parsing. Install it with: pip install pypdf"
        )

    try:
        reader = PdfReader(file_path)
        pages: List[str] = []
        fragments: List[Fragment] = []
        geom: List[GeometryLine] = []
        for page_no, page in enumerate(reader.pages, start=1):
            pages.append(page.extract_text() or "")

            def visitor(text, cm, tm, font_dict, font_size, _p=page_no):
                collected = collect_fragment(text, cm, tm, font_dict, font_size, _p)
                if collected is not None:
                    fragments.append(collected)

            state: dict = {"x": 0.0, "y": 0.0}

            def visitor_op(operator, operands, cm, tm, _p=page_no):
                collect_geometry(state, geom, operator, operands, cm, tm, _p)

            try:
                page.extract_text(visitor_text=visitor, visitor_operand_before=visitor_op)
            except TypeError:
                # 旧版 pypdf 或测试桩不支持 operator visitor：退回不带几何的解析，
                # 表格识别因此跳过，但标题/段落判定不受影响（geom 为空）。
                page.extract_text(visitor_text=visitor)
    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {str(e)}")

    return pages, fragments, geom


def collect_fragment(text, cm, tm, font_dict, font_size, page: int) -> Optional[Fragment]:
    """把 ``visitor_text`` 的回调参数归一为一个 :class:`Fragment`

    独立成函数是为了可测：调用方（:func:`read_pdf`）依赖 pypdf 的 IO，而本函数
    只做参数到数据结构的纯映射。

    **坐标必须复合 ``cm``（CTM）**，不能直接用 ``tm``：实测 ``AI-Agents-in-Depth``
    的正文片段其 ``tm[4]`` 落在 ``-15`` 附近（负值，显然不是页坐标），而同一页的
    其他文本落在 ``37`` / ``183``；复合后正文才归到同一个左边界 ``≈57``
    （该页 ``cm = (1,0,0,1,72,769.89)``，``72 + (-15.3) = 56.7``）。
    用未复合的 ``tm`` 做任何位置判据都会得出矛盾结论。

    渲染矩阵按行向量约定为 ``Tm × CTM``，故::

        page_x = tm[4]*cm[0] + tm[5]*cm[2] + cm[4]
        page_y = tm[4]*cm[1] + tm[5]*cm[3] + cm[5]

    有效字号同理需乘上 ``cm`` 的缩放（``hypot(cm[0], cm[1])``；观察到的 CTM 缩放
    多为 1，偶尔为 0.71）。``cm`` 缺失时退回只用 ``tm``——桩测试与异常内容流会走到
    这条路径，必须不抛异常。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None

    font = ""
    try:
        if font_dict:
            font = str(font_dict.get("/BaseFont", "") or "")
    except Exception:
        font = ""

    tm_scale = _matrix_scale(tm)
    cm_scale = _matrix_scale(cm)
    try:
        eff = float(font_size or 1.0) * tm_scale * cm_scale
    except (TypeError, ValueError):
        eff = tm_scale * cm_scale

    x = _page_coord(cm, tm, 0)
    y = _page_coord(cm, tm, 1)
    if x is None:
        x = _opt_float(tm, 4) or 0.0
    if y is None:
        y = _opt_float(tm, 5) or 0.0

    return Fragment(
        page=page,
        text=stripped,
        size=round(eff, 3),
        font=font,
        x=x,
        y=y,
        bold=is_bold_font(font),
        mono=is_mono_font(font),
    )


def _matrix_scale(matrix) -> float:
    """矩阵的 x 轴缩放（``hypot(a, b)``）；不可用时为 1.0"""
    if not matrix or len(matrix) < 2:
        return 1.0
    try:
        a, b = float(matrix[0]), float(matrix[1])
    except (TypeError, ValueError):
        return 1.0
    return (a * a + b * b) ** 0.5 or 1.0


def _page_coord(cm, tm, axis: int) -> Optional[float]:
    """``Tm × CTM`` 复合后的页坐标（``axis`` 0 = x，1 = y）"""
    if tm is None or len(tm) < 6:
        return None
    if cm is None or len(cm) < 6:
        return _opt_float(tm, 4 + axis)
    try:
        a, b, c, d, e, f = (float(v) for v in cm[:6])
        e2, f2 = float(tm[4]), float(tm[5])
    except (TypeError, ValueError):
        return _opt_float(tm, 4 + axis)
    if axis == 0:
        return e2 * a + f2 * c + e
    return e2 * b + f2 * d + f


def _opt_float(seq, index: int) -> Optional[float]:
    try:
        return float(seq[index])
    except (TypeError, ValueError, IndexError):
        return None


def is_bold_font(font: str) -> bool:
    """字体名是否指示加粗（``Bold`` / ``Semibold`` / ``Heavy`` / ``Black`` / ``Medium``）

    这是**辅助**信号，不单独定案：实测 ``Happy-LLM`` 有 189 个加粗片段落在正文行上。
    """
    name = (font or "").lower()
    return any(h in name for h in ("bold", "semibold", "heavy", "black", "medium"))


def is_mono_font(font: str) -> bool:
    """字体名是否指示等宽（代码）——须先过文档级基率判据才可用，见 :data:`DOC_MONO_DISABLE`"""
    name = (font or "").lower()
    return any(h in name for h in ("courier", "mono", "consol", "menlo"))


# ────────────────────────────── 行聚合（纯函数） ──────────────────────────────

def fragments_to_lines(
    fragments: Sequence[Fragment],
    y_tol_ratio: float = Y_TOL_RATIO,
) -> List[LayoutLine]:
    """把片段按「页 + y」聚成行

    排序键 ``(page, -y, x)``：PDF 的 y 轴向上，故对 y 取负即得「自上而下、自左而右」
    的阅读顺序。同一行内以**首个片段的 y 为锚**，容差取 ``y_tol_ratio × 该组最大字号``
    ——用字号比例而非绝对磅值，才能同时适配 9 磅正文与 36 磅封面标题。

    行内片段拼接复用 :func:`join_wrapped` 的规则（两边都是 ASCII 字母数字才补空格）：
    与段落重建**同一套**粘连判据，避免两处行为漂移。
    """
    if not fragments:
        return []

    ordered = sorted(fragments, key=lambda f: (f.page, -f.y, f.x))
    lines: List[LayoutLine] = []
    group: List[Fragment] = []
    anchor_y = 0.0
    max_size = 0.0

    def flush() -> None:
        if not group:
            return
        text = ""
        for frag in group:
            text = join_wrapped(text, frag.text)
        lines.append(
            LayoutLine(
                page=group[0].page,
                text=text,
                size=max_size,
                x0=min(f.x for f in group),
                x1=max(f.x for f in group),
                y=group[0].y,
                bold=any(f.bold for f in group),
                mono_share=sum(1 for f in group if f.mono) / len(group),
            )
        )
        group.clear()

    for frag in ordered:
        tol = y_tol_ratio * max(max_size, frag.size)
        if group and (group[0].page != frag.page or abs(frag.y - anchor_y) > tol):
            flush()
        if not group:
            anchor_y = frag.y
            max_size = 0.0
        group.append(frag)
        max_size = max(max_size, frag.size)
    flush()
    return lines


def match_signals(
    pages: Sequence[str],
    fragments: Sequence[Fragment],
) -> List[DocLine]:
    """把权威文本行与版式信号对齐，返回逐行的 :class:`DocLine`

    对齐分两条路，**由页面级一致性检查决定**（见 :func:`_align_page`）：

    1. 两个通道的**字符序列相同** ⇒ 按归一化字符**偏移区间求交**。这是必需的第二条
       路：同一页内容在两条通道里可能被切成**不同数量的行**（实测默认模式把章节标题
       拆成「第 1 章」+「AI Agent 入门」两行、visitor 合成一行），此时按文本精确匹配
       会**整页失配**——表现是章标题全部漏检，而图内标签因为恰好单行而对得上，
       于是「标签被当成标题、真标题被忽略」。
    2. 序列不同（含插图的页面必然如此）⇒ 退回按「去空白后文本相等」精确匹配，
       对不上的行 ``signal=None``，**不猜测**。

    两种路径都可能产出 ``signal=None``，调用方一律按普通段落处理。
    """
    visitor_by_page: Dict[int, List[LayoutLine]] = {}
    for line in fragments_to_lines(fragments):
        visitor_by_page.setdefault(line.page, []).append(line)

    result: List[DocLine] = []
    for page_no, page_text in enumerate(pages, start=1):
        raw_lines = [raw.strip() for raw in (page_text or "").split("\n") if raw.strip()]
        signals = _align_page(raw_lines, visitor_by_page.get(page_no, []))
        for text, signal in zip(raw_lines, signals):
            result.append(DocLine(page=page_no, text=text, signal=signal))
    return result


def _align_page(
    raw_lines: Sequence[str],
    visitor_lines: Sequence[LayoutLine],
) -> List[Optional[LayoutLine]]:
    """单页对齐：按两条通道的字符序列是否一致选择策略"""
    if not visitor_lines:
        return [None] * len(raw_lines)

    plain_norm = "".join(normalize_for_dedup(t) for t in raw_lines)
    visitor_norm = "".join(normalize_for_dedup(l.text) for l in visitor_lines)
    if plain_norm and plain_norm == visitor_norm:
        return _align_by_offset(raw_lines, visitor_lines)
    return _align_by_text(raw_lines, visitor_lines)


def _align_by_text(
    raw_lines: Sequence[str],
    visitor_lines: Sequence[LayoutLine],
) -> List[Optional[LayoutLine]]:
    """按「去空白后文本相等」精确匹配

    同一归一化文本在一页里可能出现多次（如重复的列表项），故每个键维护**有序队列**
    并按序消费，避免同一段信号被两行复用。
    """
    by_key: Dict[str, List[LayoutLine]] = {}
    for line in visitor_lines:
        by_key.setdefault(normalize_for_dedup(line.text), []).append(line)

    out: List[Optional[LayoutLine]] = []
    for text in raw_lines:
        queue = by_key.get(normalize_for_dedup(text))
        out.append(queue.pop(0) if queue else None)
    return out


def _align_by_offset(
    raw_lines: Sequence[str],
    visitor_lines: Sequence[LayoutLine],
) -> List[Optional[LayoutLine]]:
    """按归一化字符**偏移区间**对齐（对「行数不同」免疫）

    两条通道的字符序列已由调用方校验为相同，故同一段内容在两者中的字符偏移一致。
    对每个文本行取 ``[c, d)``，在 visitor 行中找**重叠最多**者作为其信号来源。
    于是「一行被拆成两行」时两行都能拿到同一段信号，「两行被并成一行」时按重叠择优。

    游标 ``ptr`` 单调前移：文本行按序处理，已结束于当前行之前的 visitor 行对后续行
    必然无交集，无需回看，整体只需扫一遍。
    """
    starts: List[int] = []
    position = 0
    for line in visitor_lines:
        starts.append(position)
        position += len(normalize_for_dedup(line.text))
    total = position

    out: List[Optional[LayoutLine]] = []
    cursor = 0
    ptr = 0
    for text in raw_lines:
        start = cursor
        cursor += len(normalize_for_dedup(text))
        end = cursor

        best: Optional[LayoutLine] = None
        best_overlap = 0
        index = ptr
        while index < len(visitor_lines) and starts[index] < end:
            stop = starts[index + 1] if index + 1 < len(visitor_lines) else total
            overlap = min(end, stop) - max(start, starts[index])
            if overlap > best_overlap:
                best, best_overlap = visitor_lines[index], overlap
            index += 1
        out.append(best)

        while ptr < len(visitor_lines):
            stop = starts[ptr + 1] if ptr + 1 < len(visitor_lines) else total
            if stop <= end:
                ptr += 1
            else:
                break
    return out


# ────────────────────────────── 文档级统计（纯函数） ──────────────────────────────

@dataclass(frozen=True)
class DocStats:
    """整篇文档的归一化基准——所有相对判据都建立在这上面"""

    body_size: float          # 正文主字号（按字符数加权的众数）
    mono_share: float         # 全文档等宽片段占比（决定「等宽＝代码」是否可用）

    @property
    def mono_usable(self) -> bool:
        """等宽在本文档是否**稀有到足以单独作为证据**

        .. deprecated:: 2026-09-16
           该属性已**不再充当整篇门禁**（见 :func:`looks_like_code` 的动态阈值）。
           保留仅为兼容既有诊断脚本与回归用例；新代码不应据此禁用代码判定。
           历史教训：按整篇基率否决会把「代码多」误判成「等宽不可信」——
           实测 ``Happy-LLM`` 的 code 块因此从 475 个归零。
        """
        return self.mono_share < DOC_MONO_DISABLE


def estimate_stats(lines: Sequence[DocLine], fragments: Sequence[Fragment]) -> DocStats:
    """估计正文主字号与全文档等宽基率

    正文主字号用**按字符数加权的众数**而非简单平均：标题/页眉的字号是长尾，
    平均会被拉偏；而正文行承载了绝大多数字符。字号按 0.1 取整分桶，避免浮点抖动。

    **平票时取更小的字号**（``-kv[0]``）：短文档（如只有几行的小节）里标题与正文的
    字符数可能正好持平，此时若取更大者会把标题当成正文基准，导致**全篇标题都判不出**
    （标题与「正文」字号相同 ⇒ 比值 1.0 ⇒ 得分 0）。正文在排版上总是更小、更常见的
    那一档，这个方向的偏向是安全的。
    """
    weight: Dict[float, int] = {}
    for line in lines:
        if line.signal is None:
            continue
        bucket = round(line.signal.size, 1)
        weight[bucket] = weight.get(bucket, 0) + len(line.text)

    body = max(weight.items(), key=lambda kv: (kv[1], -kv[0]))[0] if weight else 10.0

    mono = sum(1 for f in fragments if f.mono)
    share = mono / len(fragments) if fragments else 0.0
    return DocStats(body_size=body, mono_share=share)


def page_left_margin(lines: Sequence[DocLine], stats: DocStats) -> Optional[float]:
    """估计本页正文的**左边界**（x0 的按字符加权众数，仅统计正文尺寸的行）

    这条判据的必要性来自实测：``AI-Agents-in-Depth`` 用大量**流程图**承载内容，
    图内文字块（``user.input``、``⚡ user.interrupt: "停止!"``、``思考题`` 等）字号
    不小、常常加粗、又很短，仅靠「字号 + 加粗 + 短行」会被判成标题，实测污染了
    上百条 ``heading_path``。而**章节标题永远与正文同一个左边界**，图内文字块则由
    版面决定起点（同页矩形算子实测落在 x=175.5 / 230.2 / 436.5）。

    Returns:
        左边界（磅）；页内正文样本不足时返回 ``None``——此时调用方**跳过**该判据
        （宁可放过，不可误杀）。
    """
    weight: Dict[int, int] = {}
    for line in lines:
        if line.signal is None:
            continue
        if abs(line.signal.size - stats.body_size) > 0.15 * stats.body_size:
            continue
        bucket = int(round(line.signal.x0))
        weight[bucket] = weight.get(bucket, 0) + len(line.text)

    # 样本太少时众数不可靠（一整页正文通常有数百到上千字符）
    if sum(weight.values()) < MARGIN_MIN_BODY_CHARS:
        return None
    return float(max(weight.items(), key=lambda kv: (kv[1], -kv[0]))[0])


def level_for_size(size: float, body_size: float) -> int:
    """字号比值 → 标题层级（1..:data:`MAX_HEADING_LEVEL`）

    用**相对正文的比值**分档，故同一套阈值可跨文档复用（实测两份真实 PDF 的
    正文分别为 9.96 与 9.3，标题阶梯都落在同样的比值区间）。
    """
    if body_size <= 0:
        return MAX_HEADING_LEVEL
    ratio = size / body_size
    for threshold, level in LEVEL_RATIO_TIERS:
        if ratio >= threshold:
            return level
    return MAX_HEADING_LEVEL


# ────────────────────────────── 行分类（纯函数） ──────────────────────────────

@dataclass(frozen=True)
class Verdict:
    """一行的判定结果：类型 + 标题得分 + 层级"""

    kind: BlockKind
    score: float
    level: Optional[int] = None

    @property
    def is_heading(self) -> bool:
        return self.kind in ("title", "heading")


def looks_like_code(text: str, signal: LayoutLine, stats: DocStats) -> bool:
    """该行是否为代码（多信号加权，不依赖字体是否等宽）

    三个信号源互补，任一单独都不足以定案：

    1. **等宽**（强）——但阈值随文档**归一**：等宽在全篇越普遍，单行等宽的证据
       越弱。这是对旧「整篇门禁」的修正（见 :data:`DOC_MONO_DISABLE` 的说明）。
    2. **代码关键字 / token**（强 + 弱）——与文档无关，覆盖无等宽字体的场景，
       也是中文注释行（``# 输出权重矩阵。``）能被认出的唯一途径。
    3. **否证**——以中文句末标点结尾的行是正文特征，扣分。

    判据只在**单行**上成立（本函数无上下文），故宁可漏检：漏检退回普通段落，
    而误判会把正文行按代码处理（缩进/换行被当作语义）并污染后续切分。
    """
    stripped = text.strip()
    if not stripped:
        return False

    return _code_score(text, signal.mono_share, stats) >= CODE_MIN_SCORE


def _code_score(text: str, mono_share: float, stats: DocStats) -> float:
    """代码行的加权得分（:func:`looks_like_code` 与表格检测**共用**同一判据）

    抽出来是为了让「跳过代码行」与「判定代码行」用同一份语义——两处若各写一套，
    必然漂移。参数只保留文本与等宽占比，故调用方无需构造 :class:`LayoutLine`。
    """
    stripped = text.strip()
    if not stripped:
        return 0.0

    score = 0.0

    # 信号 1：等宽（归一后的动态阈值）
    mono_floor = 0.85 if stats.mono_share >= DOC_MONO_DISABLE else LINE_MONO_SHARE
    if mono_share >= mono_floor:
        score += W_CODE_MONO_STRONG
    elif mono_share >= mono_floor * 0.5:
        score += W_CODE_MONO_WEAK

    # 信号 2：词法特征
    if _CODE_KEYWORD_RE.match(stripped):
        score += W_CODE_KEYWORD
    if _COMMENT_LINE_RE.search(stripped):
        score += W_CODE_COMMENT
    token_hits = len(_CODE_TOKEN_RE.findall(stripped))
    if token_hits:
        # 按**命中数**加权（封顶 2）：单个 token 是弱证据，两个同时出现才足以定案
        # ——``self.wq = nn.Linear(dim, dim)`` 的 ``self.`` + ``.Linear(`` 即属此列。
        score += W_CODE_TOKEN * min(token_hits, 2)

    # 信号 3：否证——中文句末标点结尾是正文特征。
    # **注释行例外**：中文注释同样以「。」收尾（``# 输出权重矩阵。``），若一并扣分
    # 会让这类行落到 :func:`is_list_item_line`，成为碎片块。
    if stripped[-1] in "。！？；" and not _COMMENT_LINE_RE.search(stripped):
        score += W_CODE_SENTENCE_END

    return score


def classify_line(
    line: DocLine,
    stats: DocStats,
    *,
    toc_page: bool = False,
    page_margin: Optional[float] = None,
) -> Verdict:
    """判定一行的类型

    判定顺序是**先排除、再打分**：目录页 / 题注 / 代码这些「看起来像标题」的行先被
    摘出去，剩下的才参与标题打分。顺序不能反——目录条目的字号往往与章标题相同。

    打分过阈值后还要过**左边界**判据（:func:`is_at_left_margin`）：插图内的文字块
    同样字号大、加粗、且短，只有位置能把它们与章节标题区分开。
    """
    text = line.text
    signal = line.signal

    # 目录页上的结构起点不是真标题——它是目录条目。
    if toc_page and starts_structural_block(text):
        return Verdict(kind="toc", score=0.0)

    if is_caption_line(text):
        return Verdict(kind="caption", score=0.0)

    if signal is None:
        # 无信号 ⇒ 无判据可用 ⇒ 保守回落为普通段落。
        return Verdict(kind="paragraph", score=0.0)

    # 代码判定**前置于**标题打分与列表项判定。顺序不能反：Python 注释
    # ``# 输出权重矩阵。`` 在 :func:`is_list_item_line` 眼里是「结构起点」，
    # 会先被摘成 ``list_item``，进而切成 9 字符的碎片块（实测）。判据本身已放宽
    # 到多信号（:func:`looks_like_code`），故不再需要「整篇门禁」这一层。
    if looks_like_code(text, signal, stats):
        return Verdict(kind="code", score=0.0)

    score = score_heading(text, signal, stats)
    if score >= HEADING_MIN_SCORE and is_at_left_margin(signal, stats, page_margin):
        level = level_for_size(signal.size, stats.body_size)
        kind: BlockKind = "title" if level == 1 else "heading"
        return Verdict(kind=kind, score=score, level=level)

    if is_list_item_line(text):
        return Verdict(kind="list_item", score=score)
    return Verdict(kind="paragraph", score=score)


def is_at_left_margin(
    signal: LayoutLine,
    stats: DocStats,
    page_margin: Optional[float],
) -> bool:
    """该行是否起于正文左边界附近（标题的位置判据）

    ``page_margin is None``（本页正文样本不足，或调用方未提供）时**不做该判据**并
    返回 ``True``——宁可放过一个误判，也不误杀真实标题。
    """
    if page_margin is None:
        return True
    tolerance = max(stats.body_size, 1.0) * MARGIN_TOLERANCE_RATIO
    return signal.x0 <= page_margin + tolerance


def score_heading(text: str, signal: LayoutLine, stats: DocStats) -> float:
    """标题的加权和打分（各权重见模块常量）

    刻意**不用**单一阈值（如「字号 > 14 就算标题」）：实测两份文档的正文分别为
    9.96 与 9.3，绝对阈值无法同时适用；而比值 + 加粗 + 短行 + 编号的组合在两者
    上都能给出稳定排序。
    """
    score = 0.0
    ratio = signal.size / stats.body_size if stats.body_size > 0 else 1.0

    if ratio >= 1.60:
        score += W_SIZE_STRONG
    elif ratio >= 1.30:
        score += W_SIZE_MEDIUM
    elif ratio >= 1.15:
        score += W_SIZE_WEAK
    elif ratio >= 1.05:
        score += W_SIZE_MARGINAL

    if signal.bold:
        score += W_BOLD
    if len(text) <= SHORT_LINE_CHARS:
        score += W_SHORT
    if is_numbered_heading(text):
        score += W_NUMBERED
    return score


def is_caption_line(text: str) -> bool:
    """图/表题注：``图2.3`` / ``表 3-1`` / ``Figure 2.1`` / ``Table 3``

    题注与标题的字号/加粗往往相同，必须单独摘出，否则会污染 ``heading_path``。
    """
    stripped = text.lstrip()
    for prefix in ("图", "表", "Figure", "Fig.", "Table", "Chart"):
        if stripped.startswith(prefix):
            rest = stripped[len(prefix):].lstrip()
            digits = 0
            while digits < len(rest) and (rest[digits].isdigit() or rest[digits] in ".-–—"):
                digits += 1
            if digits > 0 and any(ch.isdigit() for ch in rest[:digits]):
                return True
    return False


def is_list_item_line(text: str) -> bool:
    """列表项：``- x`` / ``• x`` / ``1. x`` / ``（1）x`` / ``一、x``

    与 :func:`app.utils.text_structure.starts_structural_block` 的口径一致，但
    **不含**章节编号（``3.2``）——后者是标题而非列表项。故此处单独实现，先排除
    编号标题的形状。
    """
    stripped = text.lstrip()
    if not stripped:
        return False
    if starts_structural_block(stripped) and is_numbered_heading(stripped):
        return False
    if stripped[0] in "-*+•·▪◦":
        return True
    return starts_structural_block(stripped)


def is_numbered_heading(text: str) -> bool:
    """编号型标题：``第 3 章`` / ``3.2 标题`` / ``3.2.1`` / ``附录 A``

    ``1.1 Agent = LLM + 上下文 + 工具`` 这类行只靠字号（比值 1.44）得分不足，
    编号是压过阈值的补充信号。
    """
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith("第") and len(stripped) > 1:
        return True
    if stripped.startswith("附录"):
        return True
    head = stripped.split(" ", 1)[0]
    parts = head.split(".")
    if len(parts) >= 2 and all(p.isdigit() for p in parts if p):
        return sum(1 for p in parts if p) >= 2
    return False


def is_toc_page(lines: Sequence[DocLine], min_entries: int = 5, min_ratio: float = 0.4) -> bool:
    """整页是否为目录页

    判据：**带页码引导点线的行**占比达到阈值，或「结构起点行 + 行尾为页码」的行数
    达到 ``min_entries``。目录页的字号与章标题相同，只能靠这个版面特征区分。

    以页为单位而非行：单看一行无法区分「目录条目」与「真标题」——「第 7 章 工具」
    在目录页与正文页的外观几乎一致。
    """
    if not lines:
        return False
    dot_leaders = sum(1 for l in lines if has_dot_leader(l.text))
    if dot_leaders >= min_entries and dot_leaders / len(lines) >= min_ratio:
        return True

    entries = sum(
        1
        for l in lines
        if starts_structural_block(l.text) and ends_with_page_number(l.text)
    )
    return entries >= min_entries


def has_dot_leader(text: str) -> bool:
    """是否含目录引导点线（``....`` / ``. . . .`` / ``……``）"""
    run = 0
    for ch in text:
        if ch in ".·…⋯":
            run += 1
            if run >= 4:
                return True
        elif ch.isspace():
            continue
        else:
            run = 0
    return False


def ends_with_page_number(text: str) -> bool:
    """行尾是否为页码（目录条目的第二个特征）"""
    stripped = text.rstrip()
    digits = 0
    while digits < len(stripped) and stripped[-1 - digits].isdigit():
        digits += 1
    return 1 <= digits <= 4


# ────────────────────────────── 块装配（纯函数） ──────────────────────────────

#: 标题路径的层级分隔符，必须与 ``app.utils.document.HEADING_SEPARATOR`` **完全一致**
#: ——若不一致，PDF 与 MD/DOCX 的 ``heading_path`` 会无法互相比较（P4 的
#: ``section_scope_share`` 判据正是按它计深度）。此处不 import 是为了避免
#: ``document`` ↔ ``structure_blocks`` 的循环依赖；一致性由单元测试断言。
HEADING_SEPARATOR = " > "

#: 这些类型的块**按行**保留结构（用 ``\n`` 连接），不做折行合并：
#: 代码块换行即语义，目录条目一行一条。
KINDS_PRESERVING_LINES = frozenset({"code", "toc"})


def build_blocks(
    pages: Sequence[str],
    fragments: Sequence[Fragment],
    geom: Optional[Sequence[GeometryLine]] = None,
) -> List[Block]:
    """主入口：逐页文本 + 版式信号（+ 可选矢量线框）→ 带类型的块序列

    产出粒度是**语义单元**（一个段落 / 一个标题 / 一个代码块 / 一条目录条目 /
    **一个表格**），而不是「节」——节由 :func:`to_sections` 组装。分两层是因为后续的
    块类型驱动分块规则（S5）需要看到表格、代码这些**节内**单元，而分块器的段接口只
    需要节。

    S3 接入点：若提供 ``geom``（来自 :func:`read_pdf` 的矢量线），先识别表格区域，
    把表格片段从默认文本里**抹掉**以免重复进入段落/标题流，再把识别出的表格作为
    独立的 ``kind="table"`` 原子块插入阅读顺序——这正是消除 S2 表格行污染的那一步。

    页边界是**硬边界**（每页独立装配）：这与既有行为一致，且使每个块的 ``page``
    精确为单页——跨页块仍由分块器的结构组合并产生（实测当前 206 个），不在此处
    引入新的跨页语义。

    标题层级栈**跨页存活**：一章跨多页，路径必须延续；表格是原子单元，不触碰栈。
    """
    from app.utils.text_structure import detect_running_lines

    page_count = len(pages)
    # 始终跑 detect_tables：``geom`` 为空列表（无矢量线）时仍要做**无线框**
    # （列对齐）检测；旧实现写 ``if geom else []``，会把无线框表整张漏掉。
    tables = detect_tables(geom or [], fragments, page_count)
    pages_clean = _blank_table_text(pages, tables, fragments) if tables else list(pages)

    all_lines = match_signals(pages_clean, fragments)
    stats = estimate_stats(all_lines, fragments)
    running = detect_running_lines(pages_clean)

    by_page: Dict[int, List[DocLine]] = {}
    for line in all_lines:
        by_page.setdefault(line.page, []).append(line)

    blocks: List[Block] = []
    stack: List[Tuple[int, str]] = []

    for page_no in sorted(by_page):
        raw_lines = by_page[page_no]
        # 目录页判定必须在剔除噪声之前——目录条目的点线正是判据本身，
        # 先剔噪声会把判据一起删掉。
        toc_page = is_toc_page(raw_lines)
        kept = [
            l
            for l in raw_lines
            if not is_noise_line(l.text, running, keep_dot_leaders=toc_page)
        ]
        # 左边界在**剔除噪声之后**估计：页眉/页脚也可能与正文同宽，
        # 但它们的位置不代表正文排版。
        margin = page_left_margin(kept, stats)
        # _build_page_blocks_with_anchor 返回 (Block, anchor) 元组，anchor 供
        # _interleave_blocks 把表格块插回正确阅读顺序；无表格的页只需解开元组。
        page_blocks = _build_page_blocks_with_anchor(
            kept, stats, toc_page, stack, page_no, margin
        )
        page_tables = [t for t in tables if t.page == page_no]
        if page_tables:
            blocks.extend(_interleave_blocks(page_blocks, page_tables))
        else:
            blocks.extend(block for block, _ in page_blocks)
    return blocks


def _interleave_blocks(
    page_blocks: Sequence[Block],
    page_tables: Sequence[TableBox],
) -> List[Block]:
    """把表格原子块按阅读顺序插回本页的非表格块之间

    锚点：非表格块用其首个片段的 y（已由 :func:`_build_page_blocks_with_anchor`
    给出）；表格块用其包围盒顶部 y（``bbox[3]``，y 向上，越大越靠上）。按 y 降序
    排列即得「自上而下」的阅读顺序。表格块 ``heading_path`` 留 ``None``——它是原子
    节，不并入任何标题的小节树，且不影响标题栈（栈在 :func:`build_blocks` 里只随
    非表格块推进）。
    """
    events: List[Tuple[float, int, Block]] = []
    for block, anchor in page_blocks:
        events.append((anchor, 0, block))
    for table in page_tables:
        tb = Block(
            kind="table",
            text=table.markdown,
            page=table.page,
            page_end=table.page,
            heading_path=None,
            meta={"n_rows": table.n_rows, "n_cols": table.n_cols},
        )
        events.append((table.bbox[3], 1, tb))
    events.sort(key=lambda e: (-e[0], e[1]))
    return [block for _, _, block in events]


def _build_page_blocks(
    lines: Sequence[DocLine],
    stats: DocStats,
    toc_page: bool,
    stack: List[Tuple[int, str]],
    page_no: int,
    page_margin: Optional[float] = None,
) -> List[Block]:
    """装配单页的块（:func:`build_blocks` 的内层；``stack`` 被就地更新）

    返回 ``List[Block]``（见 :func:`_build_page_blocks_with_anchor`）。
    """
    return [block for block, _ in _build_page_blocks_with_anchor(
        lines, stats, toc_page, stack, page_no, page_margin)]


def _build_page_blocks_with_anchor(
    lines: Sequence[DocLine],
    stats: DocStats,
    toc_page: bool,
    stack: List[Tuple[int, str]],
    page_no: int,
    page_margin: Optional[float] = None,
) -> List[Tuple[Block, float]]:
    """装配单页的块，并附带每个块的阅读顺序锚点（首个片段的 y）

    锚点仅供 :func:`_interleave_blocks` 把表格块插回正确位置；标题栈跨页存活。
    """
    out: List[Tuple[Block, float]] = []
    group: List[DocLine] = []
    group_kind: Optional[BlockKind] = None
    group_anchor: float = 0.0

    def path_now() -> Optional[str]:
        return HEADING_SEPARATOR.join(title for _, title in stack) or None

    def flush() -> None:
        nonlocal group, group_kind, group_anchor
        if group:
            out.append((_make_block(group, group_kind, page_no, path_now()), group_anchor))
        group = []
        group_kind = None

    for line in lines:
        verdict = classify_line(line, stats, toc_page=toc_page, page_margin=page_margin)
        anchor_y = line.signal.y if line.signal is not None else 0.0

        if verdict.is_heading:
            flush()
            level = verdict.level or MAX_HEADING_LEVEL
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, line.text))
            out.append(
                (
                    Block(
                        kind=verdict.kind,
                        text=line.text,
                        page=page_no,
                        page_end=page_no,
                        level=level,
                        heading_path=path_now(),
                        bold=bool(line.signal and line.signal.bold),
                        mono_share=line.signal.mono_share if line.signal else 0.0,
                    ),
                    anchor_y,
                )
            )
            continue

        if not group:
            group_anchor = anchor_y
        if group and not _same_group(group_kind, group[-1], line, verdict.kind):
            flush()
            group_anchor = anchor_y
        if not group:
            group_kind = verdict.kind
        group.append(line)

    flush()
    return out


def _same_group(
    group_kind: Optional[BlockKind],
    last: DocLine,
    current: DocLine,
    current_kind: BlockKind,
) -> bool:
    """``current`` 是否应并入正在累积的同一块

    * 类型不同 ⇒ 断开（标题、表格、代码天然是独立单元）；
    * 代码/目录 ⇒ 连续同类一律并入（换行即语义）；
    * 段落/列表项 ⇒ 仅当**上行未结句且本行不是新结构起点**时并入——这正是
      :func:`app.utils.text_structure.rebuild_paragraphs` 的折行判据，
      两者必须一致，否则「段落」在两条代码路径上会有不同边界。
    """
    if group_kind != current_kind:
        return False
    if current_kind in KINDS_PRESERVING_LINES:
        return True
    if ends_sentence(last.text):
        return False
    return not starts_structural_block(current.text)


def _make_block(
    group: Sequence[DocLine],
    kind: Optional[BlockKind],
    page_no: int,
    heading_path: Optional[str],
) -> Block:
    """把一组同类文本行折叠成一个块"""
    assert kind is not None
    if kind in KINDS_PRESERVING_LINES:
        text = "\n".join(l.text for l in group)
    else:
        text = group[0].text
        for nxt in group[1:]:
            text = join_wrapped(text, nxt.text)

    mono = sum((l.signal.mono_share if l.signal else 0.0) for l in group) / len(group)
    return Block(
        kind=kind,
        text=text,
        page=page_no,
        page_end=page_no,
        heading_path=heading_path,
        bold=any(bool(l.signal and l.signal.bold) for l in group),
        mono_share=mono,
    )


# ────────────────────────────── 节组装（纯函数） ──────────────────────────────

@dataclass(frozen=True)
class Section:
    """一节：标题与其后继正文的同属单元——分块器的段接口正是这一粒度

    与 DOCX 的 :func:`app.utils.document._assemble_docx_section` 同构：这段文本
    才是 ``TextSegment.text``。
    """

    text: str
    page: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: Optional[str] = None
    kind: BlockKind = "paragraph"


#: 节内「标题与其正文」的连接符。刻意**不用**空行：空白会让分块器最优先的切点
#: 落在标题与正文之间，切出孤儿标题块（实测旧分块器 42.3% 的块不足 50 字符，
#: 其中 11 块只有一行标题）。与 DOCX 的 ``_DOCX_HEADING_BODY_SEP`` 同值同因。
HEADING_BODY_SEP = "\n"

#: 节内相邻正文块之间的连接符。用空行——它正是分块器**最优先**的切点，
#: 从而让段边界在合并成节之后依然是块边界的首选位置。
SECTION_BODY_SEP = "\n\n"


def to_sections(blocks: Sequence[Block]) -> List[Section]:
    """把语义单元块组装为「节」

    规则：标题开启新的一节，其后继的非标题块并入该节，直到下一个标题。
    标题与**首个**正文块之间用 :data:`HEADING_BODY_SEP`（单换行），
    其余相邻正文块之间用 :data:`SECTION_BODY_SEP`（空行）。

    **页边界是硬边界**：跨页时先 `flush`，故一节的 ``page`` 恒等于 ``page_end``。
    这样既让出处页码**精确**（无需扩展 :class:`~app.utils.document.TextSegment`
    与分块器的 ``_segment_bounds``/``_page_range`` 契约），又不损失跨页能力——
    跨页块仍由分块器的结构组合并产生（实测当前 206 个）。截断发生在页边界而非
    段落中间，与旧实现「一页一段」的截断位置完全一致，故不引入新的劣化。
    """
    sections: List[Section] = []
    parts: List[Block] = []

    def flush() -> None:
        nonlocal parts
        if not parts:
            return
        pages = [b.page for b in parts if b.page is not None]
        text = parts[0].text
        for index, block in enumerate(parts[1:], start=1):
            # 只有「标题 + 紧随其后的第一个正文块」之间用单换行；
            # 其余相邻正文块之间用空行（分块器最优先的切点）。
            sep = HEADING_BODY_SEP if (index == 1 and _is_heading(parts[0])) else SECTION_BODY_SEP
            text += sep + block.text
        sections.append(
            Section(
                text=text,
                page=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                heading_path=parts[0].heading_path,
                kind=parts[0].kind,
            )
        )
        parts = []

    for block in blocks:
        if parts and parts[-1].page != block.page:
            flush()
        if _is_heading(block):
            # 标题开启新的一节，并**留在该节内**与其正文同属——若在此处提前
            # flush，标题就会成为只有一行标题的孤儿块。
            flush()
            parts.append(block)
            continue
        if block.kind == "table":
            # 表格是自成一节的原子单元，不与相邻正文合并。
            flush()
            parts.append(block)
            flush()
            continue
        if block.kind == "code":
            # 代码同样自成一节，但**连续 code 块要合并**——一个函数常被页内的
            # 分组规则切成多个 Block，合并后才完整。
            # 不这么做会退化为：``kind`` 取 ``parts[0].kind``（见 flush），代码被
            # 并入前一个标题/段落节，``is_atomic`` 随 ``section.kind`` 一起丢失，
            # 随后被 ``chunk_size`` 机械切碎。实测 475 个 code Block 只活下来 51 个。
            if parts and parts[-1].kind != "code":
                flush()
            parts.append(block)
            continue
        if parts and parts[-1].kind == "code":
            # 正文块紧接代码节 ⇒ 先封住代码节，避免混节导致 kind 退化。
            flush()
        parts.append(block)
    flush()
    return sections


def _is_heading(block: Block) -> bool:
    return block.kind in ("title", "heading")


# ────────────────────────────── S3：PDF 表格识别（零依赖） ──────────────────────────────
#
# 零依赖的线框表格重建：用 ``visitor_operand_before`` 采集矢量线/矩形算子，聚类成横/竖
# 线，再用「闭合矩形网格」判定表格区域；单元格文本由片段坐标归属。该路径不引入任何
# 第三方库（pypdf 已在 PDF 解析中依赖），与 D1 的零依赖决策一致。
#
# 表格块对上游 S2 的污染有直接修复作用：实测 ``AI-Agents-in-Depth`` 的标题误判几乎全部
# 来自**表格行**（「字号大 + 左边距 + 短行」与章节标题在纯文本特征上不可分），而表格行
# 正落在左边距、左边界判据对它无效。识别表格并把其片段从标题/段落流里剔除，污染即消除。

@dataclass(frozen=True)
class GeometryLine:
    """一条矢量线段（已复合 CTM，页坐标，y 向上）"""

    x0: float
    y0: float
    x1: float
    y1: float
    page: int


@dataclass(frozen=True)
class TableBox:
    """一个识别出的表格区域"""

    page: int
    bbox: Tuple[float, float, float, float]  # x0, y0, x1, y1（y 向上）
    markdown: str  # GFM 表示（表头 + 分隔行 + 表体）
    n_rows: int
    n_cols: int
    #: 非空单元格数 / 单元格内文本总字符数——供 :func:`_table_is_credible`
    #: 做质量守卫。默认 0 以兼容既有构造点：守卫会将其视为不可信。
    filled_cells: int = 0
    text_chars: int = 0


#: 横/竖线判据：线段在另一轴上的投影 < 该阈值即视为水平/垂直。
_LINE_DIR_TOL = 2.0
#: 线聚类容差（磅）：同一网格线的多次绘制会有亚磅抖动。
_GRID_TOL = 3.0
#: 表格最小列数/行数（单列/单行的线框是图形边框，不是表格）。
_MIN_TABLE_COLS = 2
_MIN_TABLE_ROWS = 2

#: **无线框**表格的独立门槛——比线框路径更严。
#:
#: 线框路径有物理网格线作证，无线框路径只有「列起点一致」这一个信号，故必须收紧：
#: 等宽字体的代码行天然满足它——同一段代码的各行 token 位置逐行对齐，且 `self.wq =
#: nn.Linear(...)` 这类行会被拆成 20+ 列。实测旧门槛（2 行 / 容差 8 磅）下，88 张
#: 产出里 72 张只有 2 行、11 张列数超过 18，内容全部是代码 token 或中文正文。
#:
#: 取 3 行的依据：真表格极少只有「表头 + 1 行」，而 2 行恰是列对齐最易偶然成立的规模。
_MIN_BORDERLESS_ROWS = 3
#: 无线框表格的列数上限：真表格极少超过该值（线框路径另有 :data:`_MAX_TABLE_COLS`）。
_MAX_BORDERLESS_COLS = 12
#: 单元格归属容差：片段中心须落在网格带内（带略放大以容纳基线偏移）。
_CELL_TOL = 4.0
#: 装饰图形过滤：小于该尺寸的线框矩形不视为表格（PPT 装饰形状）。
_MIN_TABLE_SPAN = 12.0

# ── 表格质量守卫与规模上界（见 docs/plan-table-rendering-fix.md §2 P0） ──
#
# 背景：PPT 导出的 PDF 里，每页的**装饰性矢量矩形**（版式底框、色块、页脚条）
# 都能自证「四边被网格线覆盖」，从而被判成表格；实测 171 页每页恰好产出 1 张，
# 单元格非空率仅 4.2%，最大 145 列。这些伪表格后续会经 :func:`_blank_table_text`
# 把整页正文抹成空格，导致 ``heading_path`` 覆盖率归零。

#: 线框检测的规模上界：单页横/竖网格线数超过该值时放弃线框路径。
#: 候选矩形数随 ``H²V²`` 增长，无上界时第 26 页内存以 ~12 MB/s 无界增长
#: （实测把 backend 容器跑成重启）。正常表格页远低于该值。
_MAX_GRID_LINES = 60
#: 候选矩形容量上界：超出即放弃该页（宁可漏检，不可耗尽内存）。
_MAX_TABLE_RECTS = 2000
#: 列数上界：真实表格极少超过该值，伪表格实测达 145 列。
_MAX_TABLE_COLS = 30
#: 单元格填充率下限：低于此值说明是「装饰线围成的空框」而非表格。
_MIN_CELL_FILL_RATIO = 0.30
#: 单元格平均字符数下限：整表都是 1~2 字符碎片时不是真表格。
_MIN_MEAN_CELL_CHARS = 2.0
#: 抹除保护：表格区域占本页内容范围超过该比例时视为版式背景，不抹除正文。
_BLANK_PAGE_AREA_RATIO = 0.6


def _to_page_point(cm, tm, x: float, y: float) -> Optional[Tuple[float, float]]:
    """把文本空间里的点 ``(x, y)`` 复合 ``Tm × CTM`` 映射到页坐标（y 向上）"""
    if tm is None or len(tm) < 6:
        return None
    if cm is None or len(cm) < 6:
        return (float(x), float(y))
    try:
        a, b, c, d, e, f = (float(v) for v in cm[:6])
        tm0, tm1, tm2, tm3, tm4, tm5 = (float(v) for v in tm[:6])
    except (TypeError, ValueError):
        return None
    tx = tm0 * x + tm2 * y + tm4
    ty = tm1 * x + tm3 * y + tm5
    return (a * tx + c * ty + e, b * tx + d * ty + f)


def collect_geometry(
    state: dict,
    geom: List[GeometryLine],
    operator,
    operands,
    cm,
    tm,
    page: int,
) -> None:
    """``visitor_operand_before`` 的回调：把线/矩形算子归一成 :class:`GeometryLine`

    ``m``（moveto）/ ``l``（lineto）给出线段端点；``re``（矩形）展开成四条边。当前点
    在 ``state`` 中维护——``l`` 连的是上一次 ``m``/``l`` 的点，与 PDF 内容流语义一致。
    任何异常都吞掉并返回 ``None``：几何只是表格判定的辅助信号，绝不可因一处畸形算子
    让整页解析崩溃。
    """
    try:
        if isinstance(operator, (bytes, bytearray)):
            op = operator.strip().decode("latin-1", "ignore")
        else:
            op = str(operator).strip()
        if op == "m" and len(operands) >= 2:
            p = _to_page_point(cm, tm, float(operands[0]), float(operands[1]))
            if p:
                state["x"], state["y"] = p
        elif op == "l" and len(operands) >= 2:
            p = _to_page_point(cm, tm, float(operands[0]), float(operands[1]))
            if p:
                geom.append(GeometryLine(state["x"], state["y"], p[0], p[1], page))
                state["x"], state["y"] = p
        elif op == "re" and len(operands) >= 4:
            x, y, w, h = (float(operands[0]), float(operands[1]),
                          float(operands[2]), float(operands[3]))
            c0 = _to_page_point(cm, tm, x, y)
            c1 = _to_page_point(cm, tm, x + w, y)
            c2 = _to_page_point(cm, tm, x + w, y + h)
            c3 = _to_page_point(cm, tm, x, y + h)
            if c0 and c1 and c2 and c3:
                geom.append(GeometryLine(c0[0], c0[1], c1[0], c1[1], page))
                geom.append(GeometryLine(c1[0], c1[1], c2[0], c2[1], page))
                geom.append(GeometryLine(c2[0], c2[1], c3[0], c3[1], page))
                geom.append(GeometryLine(c3[0], c3[1], c0[0], c0[1], page))
    except Exception:
        return None


def _merge_axis(lines: Sequence[GeometryLine], is_h: bool) -> List[Tuple[float, float, float]]:
    """把同向线段聚成「网格线」：返回 ``(坐标, 另一轴_起点, 另一轴_终点)``

    按坐标聚类（容差 :data:`_GRID_TOL`），同一簇取坐标均值、另一轴取并集跨度——
    这样一条贯穿整表的横线（可能被拆成数段）会合并成一条全覆盖的网格线。
    """
    groups: Dict[int, List[float]] = {}
    for l in lines:
        c = l.y0 if is_h else l.x0
        a0 = min(l.x0, l.x1) if is_h else min(l.y0, l.y1)
        a1 = max(l.x0, l.x1) if is_h else max(l.y0, l.y1)
        key = int(round(c / _GRID_TOL))
        g = groups.setdefault(key, [c, a0, a1])
        g[0] = (g[0] + c) / 2.0
        g[1] = min(g[1], a0)
        g[2] = max(g[2], a1)
    return [(g[0], g[1], g[2]) for g in groups.values()]


def _axis_covers(
    spans: Sequence[Tuple[float, float, float]],
    coord: float,
    a: float,
    b: float,
    is_h: bool,
) -> bool:
    """在 ``spans`` 里是否存在一条位于 ``coord``（容差内）、且沿另一轴覆盖 ``[a, b]`` 的网格线"""
    for c, a0, a1 in spans:
        if abs(c - coord) > _GRID_TOL:
            continue
        if is_h:
            if a0 <= a + _GRID_TOL and a1 >= b - _GRID_TOL:
                return True
        else:
            if a0 <= a + _GRID_TOL and a1 >= b - _GRID_TOL:
                return True
    return False


def _union_rects(rects: List[Tuple[float, float, float, float]]) -> List[Tuple[float, float, float, float]]:
    """贪心合并相交的矩形（表格的若干候选子矩形收敛成一个区域）"""
    rects = sorted(rects)
    merged: List[List[float]] = []
    for x0, y0, x1, y1 in rects:
        hit = False
        for m in merged:
            if not (x1 < m[0] - _GRID_TOL or x0 > m[2] + _GRID_TOL
                    or y1 < m[1] - _GRID_TOL or y0 > m[3] + _GRID_TOL):
                m[0] = min(m[0], x0)
                m[1] = min(m[1], y0)
                m[2] = max(m[2], x1)
                m[3] = max(m[3], y1)
                hit = True
                break
        if not hit:
            merged.append([x0, y0, x1, y1])
    return [(m[0], m[1], m[2], m[3]) for m in merged]


def _detect_ruled_tables(
    page: int,
    lines: Sequence[GeometryLine],
    frags: Sequence[Fragment],
) -> List[TableBox]:
    """线框表格：从横/竖线中找闭合矩形网格，再把片段归入单元格

    判定是「闭合」而非「有边框」：一个矩形要成为表格，其四条边必须由网格线覆盖，
    否则只是装饰形状（如 PPT 整页背景 ``[0,0,595,842]``、单格图标边框）。
    """
    h = [l for l in lines if abs(l.y0 - l.y1) <= _LINE_DIR_TOL
         and abs(l.x1 - l.x0) >= _MIN_TABLE_SPAN]
    v = [l for l in lines if abs(l.x1 - l.x0) <= _LINE_DIR_TOL
         and abs(l.y1 - l.y0) >= _MIN_TABLE_SPAN]
    if len(h) < 2 or len(v) < 2:
        return []
    hspans = _merge_axis(h, is_h=True)
    vspans = _merge_axis(v, is_h=False)
    # 安全阀：候选矩形数是 O(H²V²)，而 PPT 单页装饰线可达数百条。
    # 无上界时检测会在「整页背景矩形」上组合爆炸——实测第 26 页起内存以
    # ~12 MB/s 增长直到容器被 OOM 重启。正常表格页远低于阈值。
    if len(hspans) > _MAX_GRID_LINES or len(vspans) > _MAX_GRID_LINES:
        return []

    rects: List[Tuple[float, float, float, float]] = []
    for yT, xaT, xbT in hspans:
        for yB, xaB, xbB in hspans:
            if yB >= yT:
                continue
            X0, X1 = max(xaT, xaB), min(xbT, xbB)
            if X1 - X0 < _MIN_TABLE_SPAN:
                continue
            for xC, yc0, yc1 in vspans:
                for xD, yd0, yd1 in vspans:
                    if xD <= xC:
                        continue
                    Y0, Y1 = max(yc0, yd0), min(yc1, yd1)
                    if Y1 - Y0 < _MIN_TABLE_SPAN:
                        continue
                    if not (
                        _axis_covers(hspans, yT, X0, X1, True)
                        and _axis_covers(hspans, yB, X0, X1, True)
                        and _axis_covers(vspans, xC, Y0, Y1, False)
                        and _axis_covers(vspans, xD, Y0, Y1, False)
                    ):
                        continue
                    rects.append((X0, Y0, X1, Y1))
                    if len(rects) > _MAX_TABLE_RECTS:
                        # 兜底：网格线数在阈值内也可能组合出巨量候选矩形。
                        return []
    if not rects:
        return []
    out: List[TableBox] = []
    for x0, y0, x1, y1 in _union_rects(rects):
        tb = _build_table_from_grid(page, x0, y0, x1, y1, hspans, vspans, frags)
        if tb:
            out.append(tb)
    return out


def _build_table_from_grid(
    page: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    hspans: Sequence[Tuple[float, float, float]],
    vspans: Sequence[Tuple[float, float, float]],
    frags: Sequence[Fragment],
) -> Optional[TableBox]:
    """用落在区域内的横/竖网格线切出单元格，把片段归属进去，产出 GFM 表格"""
    # 网格线必须**横跨整个表格区域**才配切分单元格。仅「坐标落在 bbox 内」是不够的：
    # 伪表格的 bbox 被 :func:`_union_rects` 并成整页后，页面上每条装饰线都落进
    # 包围盒，列数于是等于「该页竖线数 − 1」（实测最大 145 列）。该判据与
    # :func:`_axis_covers` 同源——构成候选矩形的线本就满足全覆盖。
    rows = sorted(
        (c for c, a0, a1 in hspans
         if y0 - _GRID_TOL <= c <= y1 + _GRID_TOL
         and a0 <= x0 + _GRID_TOL and a1 >= x1 - _GRID_TOL),
        reverse=True,  # y 向下排：第一行在顶部
    )
    cols = sorted(
        (c for c, a0, a1 in vspans
         if x0 - _GRID_TOL <= c <= x1 + _GRID_TOL
         and a0 <= y0 + _GRID_TOL and a1 >= y1 - _GRID_TOL)
    )
    n_rows = len(rows) - 1
    n_cols = len(cols) - 1
    if n_rows < _MIN_TABLE_ROWS or n_cols < _MIN_TABLE_COLS:
        return None

    # 行带 / 列带：相邻网格线之间。
    row_bands = [(rows[i + 1], rows[i]) for i in range(n_rows)]  # (y_bottom, y_top)
    col_bands = [(cols[j], cols[j + 1]) for j in range(n_cols)]  # (x_left, x_right)

    grid: Dict[Tuple[int, int], str] = {}
    for frag in frags:
        if not (x0 - _CELL_TOL <= frag.x <= x1 + _CELL_TOL
                and y0 - _CELL_TOL <= frag.y <= y1 + _CELL_TOL):
            continue
        r = _band_index(row_bands, frag.y, 1)
        c = _band_index(col_bands, frag.x, 0)
        if r is None or c is None:
            continue
        prev = grid.get((r, c))
        grid[(r, c)] = join_wrapped(prev, frag.text) if prev else frag.text

    # 至少要有表头 + 一行有内容的表体，才判定为表格；否则退回普通段落
    # （避免把「带边框的单段说明文字」误吞）。
    has_body = any((r, c) in grid for r in range(1, n_rows) for c in range(n_cols))
    if not has_body:
        return None

    markdown = _grid_to_markdown(grid, n_rows, n_cols)
    if not markdown:
        return None
    return TableBox(page=page, bbox=(x0, y0, x1, y1), markdown=markdown,
                    n_rows=n_rows, n_cols=n_cols,
                    filled_cells=len(grid),
                    text_chars=sum(len(v) for v in grid.values()))


def _band_index(bands: Sequence[Tuple[float, float]], value: float, axis: int) -> Optional[int]:
    """``value`` 落在第几个带里（带为闭区间 ``[bands[i][0], bands[i][1]]``）"""
    for i, (lo, hi) in enumerate(bands):
        if axis == 1:  # 行带：y 落在 [y_bottom, y_top]
            if lo - _CELL_TOL <= value <= hi + _CELL_TOL:
                return i
        else:  # 列带：x 落在 [x_left, x_right]
            if lo - _CELL_TOL <= value <= hi + _CELL_TOL:
                return i
    return None


def _grid_to_markdown(grid: Dict[Tuple[int, int], str], n_rows: int, n_cols: int) -> str:
    """把单元格字典渲染成 GFM 表格（首行作表头）"""
    def cell(r: int, c: int) -> str:
        return (grid.get((r, c)) or "").replace("\n", " ").replace("|", "\\|").strip()

    header = "| " + " | ".join(cell(0, c) for c in range(n_cols)) + " |"
    sep = "| " + " | ".join("---" for _ in range(n_cols)) + " |"
    body = []
    for r in range(1, n_rows):
        row_text = "| " + " | ".join(cell(r, c) for c in range(n_cols)) + " |"
        body.append(row_text)
    if not body:
        return ""
    return "\n".join([header, sep] + body)


def _group_fragments_by_row(
    frags: Sequence[Fragment], y_tol_ratio: float = Y_TOL_RATIO
) -> List[List[Fragment]]:
    """把片段按 y 聚成行（复用行聚类的思路，但直接在片段上做，不经信号对齐）"""
    if not frags:
        return []
    ordered = sorted(frags, key=lambda f: (-f.y, f.x))
    rows: List[List[Fragment]] = []
    group: List[Fragment] = []
    anchor_y = 0.0
    max_size = 0.0
    for frag in ordered:
        tol = y_tol_ratio * max(max_size, frag.size)
        if group and abs(frag.y - anchor_y) > tol:
            rows.append(group)
            group = []
        if not group:
            anchor_y = frag.y
            max_size = 0.0
        group.append(frag)
        max_size = max(max_size, frag.size)
    if group:
        rows.append(group)
    return rows


def _detect_borderless_tables(
    page: int,
    frags: Sequence[Fragment],
    ruled: Sequence[TableBox],
    stats: Optional[DocStats] = None,
) -> List[TableBox]:
    """无线框表格：靠**列对齐**识别（同一组行共享一致的列 x 起点，且连续 >=3 行）

    这是线框检测的补充——线框检测对「纯文字、靠留白分列」的表格天然失效（见 §2.4）。
    判据保守：要求 >=3 行、每行 >=2 个片段、且各行**列起点集合一致**（每列起点偏差
    < 5 磅）。正文段落即使偶然折成多列对齐，也很难满足「连续三行、列数相同、列起点一致」，
    故误报率低；代价是漏掉不规则无线框表，但漏报只是退回普通段落、不影响正确性。

    **代码行必须排除**（``stats`` 提供归一基准）：等宽代码的 token 位置逐行对齐，
    天然满足列对齐判据——实测 ``self.n_kv_heads = n_kv_heads``、``import random``
    都被切成 2~10 列的「表格」。这也是线框路径修复前该缺陷被掩盖的原因：伪表格
    的整页 bbox 让所有片段都被 ``inside`` 排除，无线框路径于是产出恒为 0。
    """
    def inside(f: Fragment) -> bool:
        return any(
            b.bbox[0] - _CELL_TOL <= f.x <= b.bbox[2] + _CELL_TOL
            and b.bbox[1] - _CELL_TOL <= f.y <= b.bbox[3] + _CELL_TOL
            for b in ruled
        )

    rows = _group_fragments_by_row([f for f in frags if not inside(f)])
    # 每行：片段按 x 排序后记录列起点集合（仅取 >=2 片段的行）。
    row_cols: List[Tuple[float, List[float]]] = []  # (anchor_y, [col_x0...])
    for row in rows:
        if len(row) < 2:
            continue
        if stats is not None and _row_is_code_like(row, stats):
            continue
        xs = sorted(f.x for f in row)
        row_cols.append((row[0].y, xs))

    out: List[TableBox] = []
    i = 0
    while i < len(row_cols):
        # 找从 i 起、列数相同且列起点对齐的连续行序列。
        base_n = len(row_cols[i][1])
        if base_n < _MIN_TABLE_COLS:
            i += 1
            continue
        j = i
        group_rows: List[Tuple[float, List[float]]] = [row_cols[i]]
        while j + 1 < len(row_cols):
            nxt_n = len(row_cols[j + 1][1])
            if nxt_n != base_n:
                break
            if not _cols_aligned(group_rows[-1][1], row_cols[j + 1][1]):
                break
            group_rows.append(row_cols[j + 1])
            j += 1
        if len(group_rows) >= _MIN_BORDERLESS_ROWS:
            tb = _build_borderless_table(page, group_rows, frags, ruled)
            if tb:
                out.append(tb)
            i = j + 1
        else:
            i += 1
    return out


def _row_is_code_like(row: Sequence[Fragment], stats: DocStats) -> bool:
    """该行是否像代码（供无线框表格检测排除）

    PDF 的片段边界不等同于词边界（``self.wq = nn.Linear(...)`` 会被拆成 20+ 个片段），
    故对**紧拼**与**空隔拼**两种还原各判一次，任一命中即视为代码——宁可少检一张
    表，也不把代码 token 写成 GFM 表格（后者会污染 ``content`` 与检索）。
    """
    for text in (" ".join(f.text for f in row), "".join(f.text for f in row)):
        if not text.strip():
            continue
        mono = sum(1 for f in row if f.mono) / len(row)
        if _code_score(text, mono, stats) >= CODE_MIN_SCORE:
            return True
    return False


def _cols_aligned(a: Sequence[float], b: Sequence[float], tol: float = 5.0) -> bool:
    """两组列起点是否逐列对齐（列数已相等）

    容差 5 磅（≈半个正文字符宽）：旧值 8 磅会让「刚好差不多的两行」判为同表，
    而等宽代码行的 token 起点抖动可达 6~7 磅，正是误检来源。
    """
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _build_borderless_table(
    page: int,
    group_rows: Sequence[Tuple[float, List[float]]],
    frags: Sequence[Fragment],
    ruled: Sequence[TableBox],
) -> Optional[TableBox]:
    """用对齐的列起点把片段聚成单元格，产出 GFM 表格"""
    col_edges = sorted({x for _, xs in group_rows for x in xs})
    # 列起点即各列左边界；N 列有 N 个互异起点，故列数 = 起点数（不再减一）。
    # 旧实现写 ``len(col_edges) - 1`` 会把 2 列误判成 1 列整张丢弃，末列片段也因
    # 落在所有列带之外而丢失。
    n_cols = len(col_edges)
    if not _MIN_TABLE_COLS <= n_cols <= _MAX_BORDERLESS_COLS:
        return None
    y_top = max(y for y, _ in group_rows)
    y_bot = min(y for y, _ in group_rows)
    x0 = min(col_edges)
    x1 = max(col_edges)

    # 收集属于该区域、且不在已识别线框表内的片段。
    region_frags = [
        f for f in frags
        if x0 - _CELL_TOL <= f.x <= x1 + _CELL_TOL
        and y_bot - _CELL_TOL <= f.y <= y_top + _CELL_TOL
        and not any(
            b.bbox[0] - _CELL_TOL <= f.x <= b.bbox[2] + _CELL_TOL
            and b.bbox[1] - _CELL_TOL <= f.y <= b.bbox[3] + _CELL_TOL
            for b in ruled
        )
    ]
    if not region_frags:
        return None

    n_rows = len(group_rows)
    # 无线框表无列边界线，片段按 x 对齐到**最近的列起点**即所在列（列起点互异）。
    # 不能用闭区间列带：首列带的上界恰好等于第二列起点，落在边界的片段会被误归首列。
    grid: Dict[Tuple[int, int], str] = {}
    for r, (anchor_y, _) in enumerate(group_rows):
        for frag in region_frags:
            if abs(frag.y - anchor_y) > max(6.0, frag.size * Y_TOL_RATIO):
                continue
            c = min(range(n_cols), key=lambda k: abs(frag.x - col_edges[k]))
            prev = grid.get((r, c))
            grid[(r, c)] = join_wrapped(prev, frag.text) if prev else frag.text

    has_body = any((r, c) in grid for r in range(1, n_rows) for c in range(n_cols))
    if not has_body:
        return None
    markdown = _grid_to_markdown(grid, n_rows, n_cols)
    if not markdown:
        return None
    return TableBox(page=page, bbox=(x0, y_bot, x1, y_top), markdown=markdown,
                    n_rows=n_rows, n_cols=n_cols,
                    filled_cells=len(grid),
                    text_chars=sum(len(v) for v in grid.values()))


def detect_tables(
    geom: Sequence[GeometryLine],
    fragments: Sequence[Fragment],
    page_count: int,
) -> List[TableBox]:
    """PDF 表格总入口：线框 + 无线框两路，按页识别后合并且按阅读顺序返回"""
    geom_by_page: Dict[int, List[GeometryLine]] = {}
    for line in geom:
        geom_by_page.setdefault(line.page, []).append(line)
    frag_by_page: Dict[int, List[Fragment]] = {}
    for f in fragments:
        frag_by_page.setdefault(f.page, []).append(f)

    # 简化文档统计：无线框路径的代码行排除需要「等宽基率」这一归一基准。
    # 此处只用 ``mono_share``（``body_size`` 不参与该判据），故无需完整
    # :func:`estimate_stats`（它还要行信号，而本函数在行装配**之前**执行）。
    mono_total = sum(1 for f in fragments if f.mono)
    stats = DocStats(
        body_size=10.0,
        mono_share=mono_total / len(fragments) if fragments else 0.0,
    )

    tables: List[TableBox] = []
    for page in range(1, page_count + 1):
        lines = geom_by_page.get(page, [])
        frags = frag_by_page.get(page, [])
        ruled = [t for t in _detect_ruled_tables(page, lines, frags)
                 if _table_is_credible(t)]
        tables.extend(ruled)
        tables.extend(t for t in _detect_borderless_tables(page, frags, ruled, stats)
                      if _table_is_credible(t))
    tables.sort(key=lambda t: (t.page, -t.bbox[3]))
    return tables


def _table_is_credible(table: TableBox) -> bool:
    """表格质量守卫：把「装饰线围成的空框」挡在表格流之外

    三条判据都取保守侧（宁可漏检、不可错位）：错位文本会同时污染 ``content``、
    ``heading_path`` 与喂给 LLM 的 ``llm_content``；而漏检只是退回普通段落流。

    实测支撑：伪表格的单元格非空率仅 4.2%、最大 145 列、单元格多为一两个字符。
    """
    if table.n_cols > _MAX_TABLE_COLS:
        return False
    total = table.n_rows * table.n_cols
    if total <= 0 or table.filled_cells <= 0:
        return False
    if table.filled_cells / total < _MIN_CELL_FILL_RATIO:
        return False
    if table.text_chars / table.filled_cells < _MIN_MEAN_CELL_CHARS:
        return False
    return True


def _covers_page(bbox: Tuple[float, float, float, float],
                 page_frags: Sequence[Fragment],
                 ratio: float = _BLANK_PAGE_AREA_RATIO) -> bool:
    """该表格区域是否覆盖了整页内容的绝大部分（⇒ 更可能是版式背景）

    页面尺寸不取自 ``mediabox``（该信息不在此层），而用本页**片段坐标范围**作代理：
    抹除的风险只与「正文实际占用的区域」有关，与纸张边界无关。
    """
    if len(page_frags) < 4:
        return False
    xs = [f.x for f in page_frags]
    ys = [f.y for f in page_frags]
    px0, px1 = min(xs), max(xs)
    py0, py1 = min(ys), max(ys)
    page_w = max(px1 - px0, 1.0)
    page_h = max(py1 - py0, 1.0)

    x0, y0, x1, y1 = bbox
    ix0, ix1 = max(x0, px0), min(x1, px1)
    iy0, iy1 = max(y0, py0), min(y1, py1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    return (ix1 - ix0) * (iy1 - iy0) / (page_w * page_h) > ratio


def _blank_table_text(
    pages: Sequence[str],
    tables: Sequence[TableBox],
    fragments: Sequence[Fragment],
) -> List[str]:
    """把表格区域里的片段文本从默认模式逐页文本中抹掉（替换为等长空格）

    为何要抹：表格片段同时存在于默认文本与 visitor 通道；若不抹，表格文本会作为
    普通行进入段落/标题流，与表格块**重复**。抹掉后 :func:`match_signals` 自然不再
    为这些行产出 ``DocLine``（对齐失败的行被保守忽略），表格只由其专用块承载。
    等长空格保持行结构不变，避免错位。
    """
    frags_by_page: Dict[int, List[Fragment]] = {}
    for f in fragments:
        frags_by_page.setdefault(f.page, []).append(f)

    by_page: Dict[int, List[str]] = {}
    for t in tables:
        if _covers_page(t.bbox, frags_by_page.get(t.page, [])):
            # 表格区域几乎等于整页内容范围 ⇒ 更可能是版式背景/装饰底框。
            # 抹除它会把整页正文（含代码块与标题）一并抹成等长空格——实测该情况下
            # ``heading_path`` 覆盖率归零、代码块完全消失。宁可让表格文本重复一次，
            # 也不能吃掉正文。
            continue
        for f in fragments:
            if f.page == t.page and (
                t.bbox[0] - _CELL_TOL <= f.x <= t.bbox[2] + _CELL_TOL
                and t.bbox[1] - _CELL_TOL <= f.y <= t.bbox[3] + _CELL_TOL
            ):
                by_page.setdefault(t.page, []).append(f.text)
    out = list(pages)
    for page_no, texts in by_page.items():
        if page_no - 1 < 0 or page_no - 1 >= len(out):
            continue
        text = out[page_no - 1]
        for frag_text in set(texts):
            if frag_text and frag_text in text:
                text = text.replace(frag_text, " " * len(frag_text))
        out[page_no - 1] = text
    return out
