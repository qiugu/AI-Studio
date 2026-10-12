"""文档解析和分块工具

两层结构，中间用 :class:`TextSegment` 传递结构信息：

    DocumentParser.parse_segments()  →  [TextSegment(text, page, heading_path)]
    TextSplitter.split_segments()    →  [TextChunk(text, index, page, heading_path)]

文本契约（解析层与分块层之间的唯一约定）
----------------------------------------

    ``\\n\\n`` = 结构边界（段落 / 列表项 / 节与节之间）
    ``\\n``    = 同一结构单元内的换行

分块器直接复用这份契约作为分隔符链的前两级，故**解析器必须先满足它**，否则分块只能
退化到句号、逗号一级。四种格式的达成情况：

* ``.txt``：原文即契约（空行分段），无需处理；
* ``.md``：原文即契约（空行分段），解析只需保证**不在代码围栏内部**识别标题；
* ``.docx``：段落之间以 ``\\n\\n`` 连接（段落样式是权威的段落边界），
  ``Heading N`` 段落同时构成节边界；
* ``.pdf``：``pypdf`` 的默认输出是**版面行流**，段内折行与段落边界同为 ``\\n``，
  故必须先经 :mod:`app.utils.text_structure` 做段落重建，才能让 ``\\n\\n`` 可达。
  这是历史缺陷的直接成因，详见该模块与 ``docs/plan-chunking-structure-alignment.md``。

分块的粒度：结构组（structural group）
------------------------------------

分块的最小单元不是「段」，而是**结构组**——连续若干个可合并的段（见
:meth:`TextSplitter._structural_groups`）。合并是必要的：段边界若直接充当块边界，
一份「每 100 字符一个小标题」的 Markdown 会切出等量的极短块（实测 5929 字符的文件
切出 52 块，均长 112，其中 **42.3% 不足 50 字符**，含 11 个只有一行标题的孤儿块）。

合并的**唯一硬约束**是不跨越「同级或更浅」的标题边界——只允许把更深的子节并入当前组
（``depth(候选) > depth(组首段)``）。无标题结构的格式（PDF / TXT）不受该约束，可自由
合并。合并后块的出处由 ``page`` / ``page_end`` 与 ``heading_path`` /
``heading_path_mixed`` 共同表达，语义仍是精确的（见 :class:`TextChunk`）。

无损性契约的变更（重要）
------------------------

旧契约要求 ``parse()`` **逐字符**等于 ``"\\n".join(seg.text)``，即分段只是把同一份文本
切开、不增删任何字符。PDF 段落重建必然打破它（需剔除页码/页眉等噪声行、并合并被
折行截断的行）。新契约改为：

1. ``parse()`` 由 ``parse_segments()`` **派生**（``"\\n".join(s.text for s in segments)``），
   两者永远一致——不再有两份可能漂移的实现；
2. 归一化**只做结构变换，不做内容改写**：除噪声行外，原文内容按原顺序保留；
3. 归一化是**确定性**的（同输入恒得同输出），这是 ``vector_id`` 可复现的前提。

由 ``tests/test_document_segments.py`` 逐格式回归断言。
"""
import logging
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from app.utils.text_structure import rebuild_pdf_pages

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextSegment:
    """解析后的一个连续文本段，自带其来源元数据

    ``page`` 与 ``heading_path`` 的**可得性因格式而异**，缺失时一律为 ``None``：
    不猜测、不用启发式（例如据字号推断 PDF 标题）把噪音写进元数据。

    * ``.pdf``： ``page`` 精确（逐页解析），``heading_path`` 由版式信号识别；
    * ``.md``： ``heading_path`` 精确（ATX ``#`` 层级栈），``page`` 恒为 ``None``
      ——Markdown 无分页概念；
    * ``.docx``：``heading_path`` 精确（``paragraph.style.name``），``page`` 恒为
      ``None``——DOCX 无固定分页，同一段落在不同机器上落在不同页；
    * ``.txt``：两者恒为 ``None``。

    ``kind`` / ``is_atomic`` 是 S5 引入的**块类型信号**：``table`` / ``code`` 块
    必须原子化（不可被分块器切碎，否则语义崩塌），``heading`` / ``title`` 块须避免
    成为「只有一行标题」的孤儿块。分块器据此调整合并与切分策略。
    """

    text: str
    page: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: Optional[str] = None
    kind: str = "paragraph"
    is_atomic: bool = False


@dataclass(frozen=True)
class TextChunk:
    """分块结果，携带该块的**出处区间**与**块类型**

    块可以跨页、跨小节（这是结构组合并的必然结果），故出处由「区间 + 混合标记」
    表达，而不是退化为一个近似值：

    * ``page`` / ``page_end``：块内容实际覆盖的页码范围（1 基，闭区间）。单页块
      两者相等；非 PDF 两者同为 ``None``。人工核对时就该显示成「第 37–38 页」。
    * ``heading_path``：块所覆盖各段的**最深公共标题前缀**。合并 ``# A`` 与其子节
      ``## B`` 时收敛为 ``"A"``——因为块确实同时属于 A 与 A 的子节。
    * ``heading_path_mixed``：``heading_path`` 是否**粗于**块的实际覆盖范围。仅当
      公共前缀**不是**组内任一段的完整路径时为 ``True``（例如块只含 ``A > B`` 与
      ``A > C`` 的内容，却只能标注成 ``A``）。为 ``True`` 时前端应把出处呈现为
      「A 等小节」而非断言「本块出自 A」，避免过度承诺。
    * ``kind`` / ``is_atomic``：沿用段的块类型信号。``table`` / ``code`` 块
      ``is_atomic=True``，分块器**不切碎**它；检索装配层可据此前缀 ``[表格]`` /
      ``[代码]`` 标记（见 P4 三键契约，不改 ``content``）。
    """

    text: str
    index: int
    page: Optional[int] = None
    page_end: Optional[int] = None
    heading_path: Optional[str] = None
    heading_path_mixed: bool = False
    kind: str = "paragraph"
    is_atomic: bool = False


#: 入库 ``knowledge_chunks.chunk_type`` 的**取值域**（列宽 ``String(16)``）。
#:
#: 它与 ``kind`` 是两件不同的事：``kind`` 是解析层的**内部标识**（十余种，随解析器
#: 演进），``chunk_type`` 是**对外契约**（决定前端走哪条渲染分支、检索装配加什么
#: 前缀）。对外契约必须少而稳定——把解析器的内部枚举直接落库，等于让数据库契约随
#: 解析器重构漂移，而调用方无从感知该列的含义已经变了。
CHUNK_TYPES = frozenset({"text", "table", "code", "title", "image"})

#: ``kind -> chunk_type`` 的显式映射（未列出的一律回落 ``text``）。
#:
#: * ``code`` / ``table`` / ``title`` 一对一：这三类在前端需要**不同的渲染分支**
#:   （代码保换行、表格按列渲染、标题加大字号），必须原样透传；
#: * ``heading`` 并入 ``title``：二者只差层级，渲染分支相同；层级信息已由
#:   ``heading_path`` 承担，不必再往类型列复制一份；
#: * ``list_item`` / ``caption`` / ``toc`` / ``paragraph`` 全部并入 ``text``：
#:   它们在界面上都只是正文段落，单独建值只会给前端添三个永不触发的分支；
#: * ``image`` 为 **P2-a 图片锚点预留**（解析层尚未产出该 ``kind``）：先占位，
#:   使 ``CHUNK_TYPES`` 与映射表口径一致，落地时无需再改列宽或迁移。
_KIND_TO_CHUNK_TYPE = {
    "code": "code",
    "table": "table",
    "title": "title",
    "heading": "title",
    "image": "image",
}


def chunk_type_for(kind: str) -> str:
    """把解析层的块类型 ``kind`` 映射为入库用的 ``chunk_type``

    返回值**必然**落在 :data:`CHUNK_TYPES` 内——未知 ``kind`` 回落为 ``text``，
    因此调用方无需再做合法性校验（这正是不直接写 ``chunk_type=chunk.kind`` 的
    原因：``String(16)`` 不会拒绝 ``toc`` 这类合法 ``kind``，却会让一个从未被
    前端适配过的值静默入库）。
    """
    return _KIND_TO_CHUNK_TYPE.get(kind, "text")


#: Markdown ATX 标题（``#``~``######`` + 空格 + 标题文本）。
#: 公开导出：诊断脚本需要与解析器使用**完全相同**的标题判据，否则报告里的
#: 「孤儿标题块」计数与解析器行为对不上。
ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

#: Markdown 围栏代码块的开/闭标记（最多 3 个前导空格，至少 3 个 `` ` `` 或 ``~``）
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

#: DOCX 标题样式名：``Heading 2`` / ``标题 2``（Word 中文版）。
#: 样式名可能带修饰后缀（``Heading 1 Char``），故后续按前缀匹配。
DOCX_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*(\d+)")

#: GFM 管道表的分隔行（``|---|---|``）：由 ``|`` 分隔、单元格内只含 ``- : .`` 与空格，
#: 且至少含一个 ``-``。用于 MD 解析时把管道表从普通段落里摘出来。
_MD_SEP_RE = re.compile(r"^\s*\|?[\s:\-.]+\|[\s:\-.]+\|?\s*$")


def _split_md_row(line: str) -> List[str]:
    """把一行 GFM 表格按 ``|`` 拆成单元格（去掉首尾的管道与每格空白）"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_separator(line: str) -> bool:
    """是否 GFM 管道表的分隔行（``|---|---|``）"""
    s = line.strip()
    if "|" not in s:
        return False
    return bool(_MD_SEP_RE.match(line)) and "-" in s


def _is_md_table_start(lines: Sequence[str], i: int) -> bool:
    """第 ``i`` 行是否是一个 GFM 管道表的表头起点（表头 + 下一行是分隔行）"""
    n = len(lines)
    if i + 1 >= n:
        return False
    header = lines[i].strip()
    return "|" in header and _is_md_separator(lines[i + 1])


def _collect_md_table(lines: Sequence[str], i: int) -> Tuple[List[List[str]], int]:
    """从 ``i`` 起收集一个 GFM 管道表：表头 + 分隔 + 连续的表体行

    Returns:
        ``(rows, 消费行数)``；``rows[0]`` 为表头单元格列表。遇到首行不含 ``|`` 或非同列
        数的行即停止（空行也终止）。
    """
    n = len(lines)
    header = _split_md_row(lines[i])
    rows = [header]
    j = i + 2
    while j < n:
        s = lines[j].strip()
        if not s or "|" not in s:
            break
        cells = _split_md_row(lines[j])
        if len(cells) != len(header):
            break
        rows.append(cells)
        j += 1
    return rows, j - i


def _rows_to_markdown(rows: Sequence[Sequence[str]]) -> str:
    """把「单元格二维表」渲染成 GFM（首行作表头，需至少一行表体）

    表格作为原子块入库：``content`` 存 GFM 而非纯文本，表头与行内文本都保留，
    使 BM25 与向量都能命中（比图/纯文本好）；同时 GFM 是人/LLM 都可读的中间形态。
    """
    if not rows or len(rows) < 2:
        return ""
    ncols = len(rows[0])

    def fmt(cells: Sequence[str]) -> str:
        return "| " + " | ".join((c or "").replace("\n", " ").replace("|", "\\|").strip()
                                 for c in cells) + " |"

    body = [fmt(r) for r in rows[1:]]
    if not body:
        return ""
    header = fmt(rows[0])
    sep = "| " + " | ".join("---" for _ in range(ncols)) + " |"
    return "\n".join([header, sep] + body)

#: DOCX **同级**段落之间的连接符。段落样式是权威的段落边界，故用空行表达，
#: 使 ``\\n\\n`` 在 DOCX 上可达（旧实现一律用单个 ``\\n``，导致段落、列表项、
#: 标题三者不可区分，分块器第一级分隔符永远命不中）。
_DOCX_PARAGRAPH_SEP = "\n\n"

#: DOCX **标题与其正文**之间的连接符。刻意不用空行，见
#: :func:`_assemble_docx_section`。
_DOCX_HEADING_BODY_SEP = "\n"

#: 标题路径的层级分隔符（``"A > B > C"`` 中的 ``" > "``）。
#: 层级深度 = 该分隔符出现次数 + 1，是「是否跨越同级标题边界」判定的依据。
HEADING_SEPARATOR = " > "

#: 顶层标题的深度。顶层标题是**可合并串内部的硬边界**（见
#: :meth:`TextSplitter._can_merge`）：它保证同一串内的成员必然同属一个顶层小节，
#: 于是 ``# A`` 永远不会与 ``# B`` 出现在同一串里。
ROOT_HEADING_DEPTH = 1

#: 结构组内各段之间的连接符。用空行是刻意的：它正是分块器**最优先**的切点，
#: 从而让「段边界」在合并成组之后依然是块边界的首选位置。
_GROUP_SEPARATOR = "\n\n"

#: 「最小填充」比例：短于 ``chunk_size × 该比例`` 的可合并串，会被并入**下一串**。
#:
#: 这一参数存在的唯一理由是消除**碎片块**，其语义等价于社区 ``chunk_by_title`` 的
#: ``combine_text_under_n_chars``：小节太短时不该独占一个块，而应与相邻小节合成
#: 一个尺寸正常的块。
#:
#: 为什么必须允许它跨越顶层标题边界：顶层小节本身就是短小节时（课程大纲类文档里
#: 的 ``# 学习规则`` 只有 159 字符），任何「不跨顶层」的规则都无法给它找到同块
#: 伙伴，只能留一个半空块。实测（5929 字符 / 52 小节的 Markdown）：硬边界策略的
#: 半空块占比 23.8%，本策略降到 5.6%。代价是块可能覆盖两个相邻小节——如实由
#: ``TextChunk.heading_path_mixed`` 标记，不隐瞒。
GROUP_MIN_FILL_RATIO = 0.5


def heading_depth(path: Optional[str]) -> Optional[int]:
    """标题路径的层级深度；``None`` 表示该段没有标题结构（PDF / TXT / 前言）

    ``"A"`` → 1，``"A > B"`` → 2。用它比较「谁在谁下面」，而不是比较字符串。
    """
    return None if path is None else path.count(HEADING_SEPARATOR) + 1


def common_heading_prefix(paths: Sequence[str]) -> Optional[str]:
    """多个标题路径的**最深公共标题前缀**

    按**层级分量**比较，不按字符比较：字符比较会把 ``"A > BC"`` 与 ``"A > BD"``
    的公共前缀判成 ``"A > B"``——一个并不存在的章节名。分量比较才是正确语义。

    Returns:
        公共前缀；无公共分量时返回 ``None``
    """
    if not paths:
        return None
    components = [path.split(HEADING_SEPARATOR) for path in paths]
    prefix: List[str] = []
    for column in zip(*components):
        if len(set(column)) != 1:
            break
        prefix.append(column[0])
    return HEADING_SEPARATOR.join(prefix) or None


def _docx_heading_level(paragraph) -> Optional[int]:
    """从段落样式名解析标题层级；非标题返回 ``None``

    只认样式名这一**明确信号**，不按字号/加粗猜测（``Title`` 等样式也不当作标题）。
    """
    style = getattr(paragraph, "style", None)
    name = (getattr(style, "name", "") or "").strip()
    match = DOCX_HEADING_RE.match(name)
    return int(match.group(1)) if match else None


def _assemble_docx_section(run: List[Tuple[str, bool]]) -> str:
    """把一节的段落序列拼成文本

    两类边界用不同连接符，原因是它们在分块器里的优先级不同：

    * **同级**（正文段之间、列表项之间）用 ``\\n\\n``——它是分块器的**最高优先级**
      切点，正对应「结构边界」；
    * **父子**（标题与紧随其后的正文）用 ``\\n``。标题与正文之间**不能**用空行：
      一旦标成最高优先级切点，长小节就会被切成「只有标题」的孤儿块——块过短、
      语义空泛，且标题与正文被拆散（社区 ``chunk_by_title`` 明确禁止的行为）。

    ``run`` 的不变量：**只有第一个元素可能是标题**。标题段落会触发 ``flush()``，
    故它不会与前一小节混进同一个 ``run``；这也意味着「连续标题」不可能出现在同一个
    ``run`` 里，空小节各自成为独立的段（由其 ``heading_path`` 携带出处信息），
    消除这类孤儿块是分块层「结构组合并」的职责，不在解析层。

    Args:
        run: 本节内按原文顺序排列的 ``(段落文本, 是否标题)``
    """
    head_text, head_is_heading = run[0]
    parts: List[str] = [head_text]
    for index, (text, _is_heading) in enumerate(run[1:], start=1):
        binds_to_heading = index == 1 and head_is_heading
        parts.append(
            (_DOCX_HEADING_BODY_SEP if binds_to_heading else _DOCX_PARAGRAPH_SEP) + text
        )
    return "".join(parts)


class DocumentParser:
    """文档解析器，支持多种格式"""

    # 分段解析方法（返回 List[TextSegment]，带页码 / 标题路径）
    SEGMENT_PARSERS = {
        ".txt": "parse_text_segments",
        ".md": "parse_markdown_segments",
        ".pdf": "parse_pdf_segments",
        ".docx": "parse_docx_segments",
    }

    @staticmethod
    def parse(file_path: str, file_type: str) -> str:
        """解析文件并返回**归一化后的全文**

        ``= "\\n".join(seg.text for seg in parse_segments(...))``。由分段结果派生而非
        另写一份实现，是为了让「入库文本」与「块拼接结果」在结构上不可能不一致——
        两份实现各自演化正是历史上元数据与正文错位的来源。

        Args:
            file_path: 文件路径
            file_type: 文件类型 (txt, md, pdf, docx)

        Returns:
            归一化文本（结构边界为 ``\\n\\n``，见模块文档的文本契约）
        """
        return "\n".join(
            segment.text for segment in DocumentParser.parse_segments(file_path, file_type)
        )

    @staticmethod
    def parse_segments(file_path: str, file_type: str) -> List[TextSegment]:
        """解析文件并返回**分段**结果，每段自带页码 / 标题路径

        Args:
            file_path: 文件路径
            file_type: 文件类型 (txt, md, pdf, docx)

        Returns:
            按原文顺序排列的文本段列表
        """
        parser = DocumentParser.SEGMENT_PARSERS.get(f".{file_type}")
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")

        method = getattr(DocumentParser, parser)
        return method(file_path)

    # ── 各格式的简便入口（等价于 parse()，保留以兼容既有调用） ────────────────

    @staticmethod
    def parse_text(file_path: str) -> str:
        """解析纯文本文件"""
        return DocumentParser.parse(file_path, "txt")

    @staticmethod
    def parse_markdown(file_path: str) -> str:
        """解析 Markdown 文件"""
        return DocumentParser.parse(file_path, "md")

    @staticmethod
    def parse_pdf(file_path: str) -> str:
        """解析 PDF 文件（需 ``pip install pypdf``）"""
        return DocumentParser.parse(file_path, "pdf")

    @staticmethod
    def parse_docx(file_path: str) -> str:
        """解析 Word 文档（需 ``pip install python-docx``）"""
        return DocumentParser.parse(file_path, "docx")

    # ── 分段解析 ──────────────────────────────────────────────────────────────

    @staticmethod
    def parse_text_segments(file_path: str) -> List[TextSegment]:
        """纯文本：整份文件作为**单一**段（无结构信息可提取）"""
        with open(file_path, "r", encoding="utf-8") as f:
            return [TextSegment(text=f.read())]

    @staticmethod
    def parse_markdown_segments(file_path: str) -> List[TextSegment]:
        """Markdown：按 ATX 标题层级切段，每段记录其标题栈路径

        行为细节：

        * **逐行分区**，每一行必须且只能属于一段——**包括空行**。空行若被丢弃，
          段落边界（``\\n\\n``）就被抹掉了；
        * 标题行归属**紧随其后的那段**（标题即本节内容的一部分）：块文本自描述、
          标题本身可被检索命中，且元数据与实际内容不错位；
        * 层级回退用栈式归并：遇 ``##`` 时弹出所有 ``>= 2`` 的层级，故 ``# A``
          下的 ``### B`` 得到 ``"A > B"``，同级标题互不串味；
        * **围栏代码块内的 ``#`` 不是标题**。``shell`` 片段里的注释行（``# 安装依赖``）
          与文本文件示例，在旧实现中会被当成 ATX 标题并在此**切断分段**，凭空造出
          一个不存在的章节与错误的 ``heading_path``（代码块被劈成两段，且后半段
          挂着一个伪装标题）。此处维护围栏状态，仅在第一行起始处匹配标题；
        * **GFM 管道表**与**围栏代码块**作为 ``kind="table"`` / ``kind="code"`` 的
          **原子块**独立成段（S4 + S5）：表格被切碎后语义崩塌、代码换行即语义，
          二者都不可并入相邻段落或被分块器切分。

        标题路径形如 ``"3 原理 > 3.2 注意力"``（各级标题原文以 ``" > "`` 连接）。
        """
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")

        segments: List[TextSegment] = []
        stack: List[Tuple[int, str]] = []  # [(level, title)]
        run: List[str] = []
        current_path: Optional[str] = None
        fence_char: Optional[str] = None  # 当前围栏的标记字符（`` ` `` 或 ``~``）
        fence_len = 0
        code_buffer: List[str] = []  # 围栏内的累积行

        def flush_run() -> None:
            if run:
                kind = "heading" if ATX_HEADING_RE.match(run[0]) else "paragraph"
                segments.append(
                    TextSegment(text="\n".join(run), heading_path=current_path, kind=kind)
                )
                run.clear()

        def flush_code() -> None:
            if code_buffer:
                # 代码块是原子单元：独立成段、不并入标题树（heading_path=None）。
                segments.append(
                    TextSegment(text="\n".join(code_buffer), kind="code", is_atomic=True,
                                heading_path=None)
                )
                code_buffer.clear()

        n = len(lines)
        i = 0
        while i < n:
            line = lines[i]
            fence = FENCE_RE.match(line)
            if fence:
                marker, rest = fence.group(1), fence.group(2)
                if fence_char is None:
                    flush_run()
                    fence_char, fence_len = marker[0], len(marker)
                    code_buffer = [line]
                elif marker[0] == fence_char and len(marker) >= fence_len and not rest.strip():
                    code_buffer.append(line)
                    flush_code()
                    fence_char, fence_len = None, 0
                else:
                    code_buffer.append(line)
                i += 1
                continue

            if fence_char is not None:
                code_buffer.append(line)
                i += 1
                continue

            # GFM 管道表：表头 + 分隔行 + 连续表体，作为原子表格块。
            if _is_md_table_start(lines, i):
                flush_run()
                rows, consumed = _collect_md_table(lines, i)
                gfm = _rows_to_markdown(rows)
                if gfm:
                    segments.append(
                        TextSegment(text=gfm, kind="table", is_atomic=True,
                                    heading_path=current_path)
                    )
                i += consumed
                continue

            heading = ATX_HEADING_RE.match(line)
            if heading:
                flush_run()
                level = len(heading.group(1))
                title = heading.group(2).strip().rstrip("#").strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                current_path = " > ".join(title for _, title in stack) or None
            run.append(line)
            i += 1

        flush_run()
        flush_code()
        return segments

    @staticmethod
    def parse_pdf_segments(file_path: str) -> List[TextSegment]:
        """PDF：**按结构块分段**（段 = 一节），页码精确，``heading_path`` 由版式信号识别

        与 MD/DOCX 的分段口径对齐——段 = 「标题 + 其后继正文」，而**不是**「一页」。
        这是本次改造的核心：旧的「一页一段」使分块器在 PDF 上只能看到段落边界，
        标题 / 表格 / 代码的位置全都不可知（实测旧数据 ``heading_path`` 在 PDF 上
        **1414/1414 全为 NULL**）。

        版式信号（字号 / 字体 / 坐标）取自 ``pypdf`` 的 ``visitor_text`` 回调，
        **文本**则取自默认模式——两个通道按「去空白后文本相等」对齐。为何不能只
        用一个通道，见 :mod:`app.utils.structure_blocks` 的模块文档。

        关于「用启发式推断标题会不会把噪音写进出处」——旧注释的顾虑是成立的，
        故本实现把误判代价压到最低：多信号加权过阈值才判标题，**取不到信号的行
        一律按普通段落处理**（绝不猜测），且准确率以真实 PDF 的**抽样人工核对**
        作为验收（见 ``docs/plan-structure-pipeline.md`` §6）。

        切不成节的页（封面、纯图页）仍产出段，故不丢内容；``extract_text()`` 对
        空白页可能返回 ``None``，由 :func:`app.utils.structure_blocks.read_pdf`
        归一为 ``""``——旧实现直接把它塞进 ``"\\n".join``，遇到这类页面会以
        ``TypeError`` 崩掉。
        """
        from app.utils.structure_blocks import build_blocks, read_pdf, to_sections

        pages, fragments, geom = read_pdf(file_path)
        sections = to_sections(build_blocks(pages, fragments, geom))
        return [
            TextSegment(
                text=section.text,
                page=section.page,
                heading_path=section.heading_path,
                kind=section.kind,
                is_atomic=section.kind in ("table", "code"),
            )
            for section in sections
            if section.text.strip()
        ]

    @staticmethod
    def parse_docx_segments(file_path: str) -> List[TextSegment]:
        """DOCX：按段落样式名（``Heading N`` / ``标题 N``）切段，并补 ``doc.tables``

        **段落之间以空行连接**（而非单个 ``\\n``）：DOCX 的段落样式是权威的段落边界，
        用空行表达它才能让分块器的第一级分隔符 ``"\\n\\n"`` 命中，进而按段落边界
        （而不是任意位置）落刀；列表项同样以段落身份参与，故列表项之间也会形成结构
        边界。标题与其正文之间则用单个 ``\\n``，避免切出孤儿标题块——理由见
        :func:`_assemble_docx_section`。

        **表格（S4）**：``python-docx`` 的 ``doc.paragraphs`` **不含**表格单元格内的段落
        （实测全仓无任何 ``.tables`` 引用，表格内容此前被静默丢弁）。此处改用
        ``doc.iter_inner_content()`` 按文档顺序遍历段落与表格，把表格渲染成 GFM 原子块
        （``kind="table"``、``is_atomic=True``）——表格被切碎后语义崩塌，且必须先于
        相邻段落 flush，否则会被并入正文段。

        空段落与旧实现保持一致地过滤掉（空段落不承载内容，保留只会产生连续空行）。
        """
        try:
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError:
            raise ImportError("python-docx is required for DOCX parsing. Install it with: pip install python-docx")

        segments: List[TextSegment] = []
        stack: List[Tuple[int, str]] = []
        run: List[Tuple[str, bool]] = []  # [(段落文本, 是否为标题)]
        current_path: Optional[str] = None

        def flush() -> None:
            if run:
                kind = "heading" if run[0][1] else "paragraph"
                segments.append(
                    TextSegment(text=_assemble_docx_section(run), heading_path=current_path,
                                kind=kind)
                )
                run.clear()

        def add_table(table: "Table") -> None:
            flush()
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            gfm = _rows_to_markdown(rows)
            if gfm:
                segments.append(
                    TextSegment(text=gfm, kind="table", is_atomic=True,
                                heading_path=current_path)
                )

        try:
            doc = Document(file_path)
            if hasattr(doc, "iter_inner_content"):
                items = list(doc.iter_inner_content())
            else:  # 旧版 python-docx：退回「只遍历段落」的旧行为（表格仍被忽略）
                items = list(doc.paragraphs)

            for item in items:
                if isinstance(item, Paragraph):
                    text = item.text
                    if not text.strip():
                        continue
                    level = _docx_heading_level(item)
                    if level is not None:
                        flush()
                        while stack and stack[-1][0] >= level:
                            stack.pop()
                        stack.append((level, text.strip()))
                        current_path = " > ".join(title for _, title in stack) or None
                    run.append((text, level is not None))
                elif isinstance(item, Table):
                    add_table(item)
                # 其它内联内容（如含表格的单元格）跳过：S4 只覆盖顶层表格。
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX: {str(e)}")

        flush()
        return segments


#: 分块参数的兜底默认值。真实取值来自 ``config.chunk_size`` /
#: ``config.chunk_overlap``（见 ``app/core/config.py`` 中关于 512 token 硬约束的
#: 说明）；此常量仅在「配置不可用」时生效——例如只导入本模块做纯文本处理的
#: 离线脚本或单元测试。
DEFAULT_CHUNK_SIZE = 448
DEFAULT_CHUNK_OVERLAP = 64


def _resolve_chunk_defaults() -> Tuple[int, int]:
    """在**调用期**解析分块参数：优先配置，配置不可用则回退到模块常量。

    为什么不用 ``def __init__(self, chunk_size=config.chunk_size)``：Python 的
    默认参数在**函数定义时**求值一次，会把导入那一刻的配置永久固化；而配置既可
    被环境变量在启动后覆盖，评测脚本也需要在运行期改参。用 ``None`` 哨兵 + 调用期
    解析，才能让「改配置即生效」成立。

    为什么吞掉异常：``TextSplitter`` 是纯工具类，会被评测脚本与离线脚本单独导入，
    这些场景不一定装配了完整的 pydantic 配置。缺配置时不该让**纯文本处理**失败。
    """
    try:
        from app.core.config import config

        return (
            int(getattr(config, "chunk_size", DEFAULT_CHUNK_SIZE)),
            int(getattr(config, "chunk_overlap", DEFAULT_CHUNK_OVERLAP)),
        )
    except Exception:  # pragma: no cover - 仅在配置不可用时走此分支
        return DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP


#: 原子块长度上界的默认倍数（相对 ``chunk_size``）。取 2 倍是为「函数级完整」留
#: 余量：实测代码块长度中位 330、p90 约 800，取 1×（448）会让正常函数频繁降级。
ATOMIC_MAX_CHARS_RATIO = 2

#: 超长原子块的**语义单元**边界：函数/类/装饰器定义行。代码块内部最自然的切分点。
_ATOMIC_BLOCK_START_RE = re.compile(r"^\s*(def|class|async\s+def|@\w+|function)\b")


def _split_atomic_units(text: str) -> List[str]:
    """按**语义单元**切分原子文本（函数/类定义行是单元边界）

    「单元」是切分的优先单位——装箱时尽量整单元放入，放不下才整体换到下一块，
    从而避免把函数从中间劈开。
    """
    units: List[str] = []
    buf: List[str] = []
    for line in text.split("\n"):
        if buf and _ATOMIC_BLOCK_START_RE.match(line):
            units.append("\n".join(buf))
            buf = []
        buf.append(line)
    if buf:
        units.append("\n".join(buf))
    return units


def _hard_split_lines(text: str, limit: int) -> List[str]:
    """按行贪心硬切：保证每个输出块长度 ≤ ``limit``

    单行本身超限时（压缩过的 JS 等）无边界可用，按字符切——这是唯一的例外，
    否则该行永远放不进任何块。
    """
    out: List[str] = []
    buf: List[str] = []
    size = 0

    def flush() -> None:
        nonlocal size
        if buf:
            out.append("\n".join(buf))
            buf.clear()
            size = 0

    for line in text.split("\n"):
        if len(line) > limit:
            flush()
            out.extend(line[k:k + limit] for k in range(0, len(line), limit))
            continue
        if buf and size + len(line) + 1 > limit:
            flush()
        buf.append(line)
        size += len(line) + 1
    flush()
    return out


#: GFM 表分隔行（``| --- | :--: |``）允许出现的字符。
#:
#: 判据比 :data:`_MD_SEP_RE` 更宽（后者要求**至少两列**，单列表判不出来）：
#: 这里问的是「要不要给后续片重复这行」，判错的代价是结构保真度损失，而不是
#: 数据错误，因此宁可放宽也不漏判。
_TABLE_SEPARATOR_CHARS = frozenset("|-: ")


def _is_table_separator_line(line: str) -> bool:
    """该行是否是 GFM 表的分隔行

    「表头 + 分隔行」正是让一段文本在 Markdown 中**成立为表**的充分条件，
    因此它决定了超长表降级时能否靠重复表头保住结构。
    """
    stripped = line.strip()
    return bool(stripped) and "-" in stripped and set(stripped) <= _TABLE_SEPARATOR_CHARS


def _resolve_atomic_max_chars(chunk_size: int) -> int:
    """原子块（表格 / 代码）的长度上界：超限即放弃原子性、降级为普通切分

    ``is_atomic`` 的语义是「不切碎」，但它与嵌入模型的 ``max_seq_length=512``
    （中文 ≈476 字）直接冲突，而后者是**静默截断**——超出部分从不进入向量，也
    从不进入精排。两者不可兼得时正确性优先：宁可切分，也不能让内容消失。
    """
    try:
        from app.core.config import config

        override = getattr(config, "atomic_max_chars", None)
        if override:
            return int(override)
    except Exception:  # pragma: no cover - 配置不可用时走默认
        pass
    return max(1, ATOMIC_MAX_CHARS_RATIO * chunk_size)


class TextSplitter:
    """文本分块器，基于递归字符分块"""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separators: Optional[List[str]] = None,
        min_fill_chars: Optional[int] = None,
    ):
        """
        初始化分块器

        Args:
            chunk_size: 分块大小（字符数）。``None`` 时取 ``config.chunk_size``。
            chunk_overlap: 分块之间的重叠（字符数）。``None`` 时取
                ``config.chunk_overlap``。
            separators: 分割符列表，优先级递减
            min_fill_chars: 可合并串的**最小填充长度**。短于此长度的串会并入下一串，
                以消除碎片块；显式传 ``0`` 可关闭该行为（用于 A/B 对比与回归定位）。
                ``None`` 时取 ``chunk_size × GROUP_MIN_FILL_RATIO``。

        Raises:
            ValueError: ``chunk_overlap > chunk_size``（重叠比块还长时，「重叠」
                会退化为「整块复制」，语义不成立，且块数会随重叠线性膨胀）
        """
        default_size, default_overlap = _resolve_chunk_defaults()
        self.chunk_size = default_size if chunk_size is None else int(chunk_size)
        self.chunk_overlap = (
            default_overlap if chunk_overlap is None else int(chunk_overlap)
        )
        if self.chunk_overlap > self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must not exceed "
                f"chunk_size ({self.chunk_size})"
            )
        if min_fill_chars is None:
            min_fill_chars = int(self.chunk_size * GROUP_MIN_FILL_RATIO)
        self.min_fill_chars = max(0, int(min_fill_chars))
        self.atomic_max_chars = _resolve_atomic_max_chars(self.chunk_size)
        self.separators = separators or ["\n\n", "\n", "。", "，", " ", ""]

    def split(self, text: str) -> List[str]:
        """
        将文本分块

        Returns:
            分块文本列表
        """
        return self._split_recursive(text, self.separators)

    def split_segments(self, segments: List[TextSegment]) -> List[TextChunk]:
        """把段序列切成块：**先分组，再在组内切分**

        为什么必须先分组：若以段为单元独立切分，段边界就成了硬块边界。后果实测如下——

        * Markdown（段 = 标题小节）：5929 字符的文件切出 52 块，均长 112（只用掉
          ``chunk_size`` 的 25%），**42.3% 的块不足 50 字符**，其中 11 块只有一行标题；
        * PDF（段 = 页）：段尾残块使半空块占比从 8.8% 升到 18.9%。

        合并把这两类残块收回去，同时**不牺牲出处精度**：块的出处从「某一页的第几块」
        升级为**区间**——``page``/``page_end`` 是内容真实覆盖的页码范围，
        ``heading_path`` 取合并集的最深公共前缀，``heading_path_mixed`` 标记「覆盖了
        多个小节」。人工核对时看到的是「第 37–38 页 §3.2」，比一个被切碎的单页片段
        更有用。

        ``index`` 是**文档内全局序号**（从 0 开始，跨组连续），与入库的
        ``chunk_index`` 一致；它同时参与 ``vector_id`` 的推导，故必须稳定可复现。

        空段（如纯空白页）不产出块——否则会出现内容为空的分块并被向量化。
        """
        chunks: List[TextChunk] = []
        for group, group_text in self.iter_group_texts(segments):
            # 原子块（表格 / 代码）：**整段作为一个块**，既不切碎、也不并入邻组。
            # 表格被切碎后语义崩塌、代码块的换行即语义，二者都必须保持完整——
            # 这是 S5「块类型驱动规则」的核心约束。
            if len(group) == 1 and group[0].is_atomic:
                seg = group[0]
                if len(seg.text) <= self.atomic_max_chars:
                    chunks.append(
                        TextChunk(
                            text=seg.text,
                            index=len(chunks),
                            page=seg.page,
                            page_end=seg.page_end,
                            heading_path=seg.heading_path,
                            heading_path_mixed=False,
                            kind=seg.kind,
                            is_atomic=True,
                        )
                    )
                    continue
                # 超长原子块降级：``is_atomic`` 承诺「不切碎」，但嵌入模型的
                # ``max_seq_length=512``（中文 ≈476 字）是**静默截断**，超限部分
                # 从不进入向量。实测 51 个 code chunk 中 23 个（45%）超限、最长
                # 1840 字符。取舍明确：宁可切分，也不能让内容永不参与检索。
                chunks.extend(self._split_oversized_atomic(seg, len(chunks)))
                continue

            heading_path, heading_mixed = self._group_heading(group)
            # 段边界一次性预计算 + 单调游标：结构组可能是整份 PDF（数千段），
            # 逐块重新累加会让出处解析退化成「块数 × 段数」的二次复杂度。
            bounds = self._segment_bounds(group)
            cursor = 0
            pointer = 0
            group_kind = group[0].kind if group else "paragraph"
            for piece in self._split_recursive(group_text, self.separators):
                start = self._locate(group_text, piece, cursor)
                # 推进到本次起点之后，而不是停在起点：相同文本重复出现时，
                # 下一块必须从后续位置继续查找。这里只推进一个字符而非整块长度，
                # 因为 chunk_overlap > 0 时下一块的起点可能仍落在当前块内部。
                cursor = start + 1
                page, page_end, pointer = self._page_range(
                    # overlap 允许下一块从当前块内部开始，因此回看一个段，
                    # 但仍由 _page_range 返回递进后的游标保持整体线性扫描。
                    bounds, start, start + len(piece), max(0, pointer - 1)
                )
                chunks.append(
                    TextChunk(
                        text=piece,
                        index=len(chunks),
                        page=page,
                        page_end=page_end,
                        heading_path=heading_path,
                        heading_path_mixed=heading_mixed,
                        kind=group_kind,
                    )
                )
        return chunks

    def _split_oversized_atomic(self, seg: TextSegment, base_index: int) -> List[TextChunk]:
        """超长原子块的**降级切分**：按类型选择切法

        * ``table`` ⇒ :meth:`_split_table_text`：**每片重复表头**，切完仍是多张合法表；
        * 其余（``code``）⇒ :meth:`_split_atomic_text`：切点落在行边界、优先在
          函数/类定义行断。

        两者都不能用 :meth:`_split_recursive`：它的末级分隔符是中文句末标点 ``。``，
        会从中文注释或表格单元格中间落刀；而代码与表格的换行即语义。
        """
        if seg.kind == "table":
            pieces = self._split_table_text(seg.text, self.atomic_max_chars)
        else:
            pieces = self._split_atomic_text(seg.text, self.atomic_max_chars)
        return [
            TextChunk(
                text=piece,
                index=base_index + offset,
                page=seg.page,
                page_end=seg.page_end,
                heading_path=seg.heading_path,
                heading_path_mixed=False,
                kind=seg.kind,
                # 已降级：不再承诺原子性，否则下游会继续按「不可切」处理
                is_atomic=False,
            )
            for offset, piece in enumerate(pieces)
            if piece.strip()
        ]

    @staticmethod
    def _split_table_text(text: str, limit: int) -> List[str]:
        """超长 GFM 表的降级切分：**每一片都重复表头**（且每片 ≤ ``limit``）

        表格的语义由「表头 + 分隔行 + 数据行」共同构成。按行切完不给后续片补表头，
        那些片在 Markdown 里就不成立为表，前端只能显示成「一堆竖线」——正是本次要
        修掉的显示缺陷，会在超长表上原样复现（实测 60 行 × 8 列的表切出 5 片，
        只有第 1 片还是合法表）。重复表头让每一片都能独立成立。

        预算是**先扣掉表头再装箱**的：每片 = ``表头 + 分隔行 + 若干数据行`` ≤
        ``limit``。上界是这个功能的全部意义（超过嵌入上限的部分被静默截断、永不
        参与检索），所以结构保真让位于上界——病态的超预算单行按字符硬切，那一行
        确实会碎，但它本来也不可能被完整检索到。
        """
        lines = text.split("\n")
        if len(lines) < 3 or not _is_table_separator_line(lines[1]):
            # 不是「表头 + 分隔行 + 数据行」的形态：重复表头无从谈起，退回通用降级
            return TextSplitter._split_atomic_text(text, limit)

        prefix = f"{lines[0]}\n{lines[1]}\n"
        budget = limit - len(prefix)
        if budget <= 0:
            # 表头本身已超限（病态宽表）：重复它只会让每片都超限，再重复就没有意义
            return TextSplitter._split_atomic_text(text, limit)

        out: List[str] = []
        buf: List[str] = []
        size = 0

        def flush() -> None:
            nonlocal size
            if buf:
                out.append(prefix + "\n".join(buf))
                buf.clear()
                size = 0

        for row in lines[2:]:
            if len(row) > budget:
                flush()
                out.extend(prefix + piece for piece in _hard_split_lines(row, budget))
                continue
            if buf and size + len(row) + 1 > budget:
                flush()
            size = size + len(row) + 1 if buf else len(row)
            buf.append(row)
        flush()
        # 只有表头、没有数据行（或原本就没有数据行）：原文即合法表，原样返回
        return out or [text]

    @staticmethod
    def _split_atomic_text(text: str, limit: int) -> List[str]:
        """把超长原子文本切到 ``limit`` 以内（语义单元装箱，切点落在行边界）

        两阶段：① 按函数/类定义行切出**语义单元**；② 对单元做贪心装箱。
        这样「不把函数从中间劈开」与「每块 ≤ limit」两个目标同时成立——
        而后者是这个功能的全部意义（长度上界决定内容会不会被嵌入模型静默截断）。

        为何不用 :meth:`_split_recursive`：那个切分器的末级分隔符是中文句末标点
        ``。``，会从中文注释中间落刀；而代码的换行即语义。
        """
        out: List[str] = []
        buf = ""
        for unit in _split_atomic_units(text):
            # 单元本身超限 ⇒ 无法整放，退化为按行硬切
            if len(unit) > limit:
                if buf:
                    out.append(buf)
                    buf = ""
                out.extend(_hard_split_lines(unit, limit))
                continue
            merged = f"{buf}\n{unit}" if buf else unit
            if len(merged) > limit:
                out.append(buf)
                buf = unit
            else:
                buf = merged
        if buf:
            out.append(buf)
        return out

    def iter_group_texts(
        self, segments: List[TextSegment]
    ) -> Iterator[Tuple[List[TextSegment], str]]:
        """按**结构组**遍历，产出 ``(组成员, 组文本)``

        公开此视图是专为诊断工具（``scripts/chunking_quality_report.py``）而设：
        它必须与分块器使用**完全相同**的分组与文本，否则报告测的就不是线上跑的逻辑，
        而报告的全部价值正在于二者同源。
        """
        for group in self._structural_groups(segments):
            yield group, _GROUP_SEPARATOR.join(segment.text for segment in group)

    def _structural_groups(self, segments: List[TextSegment]) -> List[List[TextSegment]]:
        """把段序列切成若干可独立切分的**结构组**

        两阶段，顺序不可交换：

        1. :meth:`_mergeable_runs`——只按**标题规则**切出「最大可合并串」。此阶段
           **不看长度**。这一点是修复碎片化的关键：若在这里就用 ``chunk_size``
           贪心截断，「当前组快满、下一段放不进来」会立刻收组，收出来的残组又无法
           与再下一组配对（两者相加仍超限），于是一路产生半空块。实测 5929 字符的
           Markdown 被切成 268 / 209 / 253 三个组，而**整串**交付递归切分只会得到
           448 / 350 两块。
        2. :meth:`_combine_undersized`——长度**不达标**的串并入下一串，消除
           「短小节独占一块」的碎片（社区 ``combine_text_under_n_chars`` 语义）。
        """
        return self._combine_undersized(self._mergeable_runs(segments))

    def _mergeable_runs(self, segments: List[TextSegment]) -> List[List[TextSegment]]:
        """**最大可合并串**：仅由标题边界决定切分，不受长度影响

        串内所有成员同属一个顶层小节；串内长度可能远超 ``chunk_size``，超出部分由
        递归切分器以真正的重叠语义处理。
        """
        runs: List[List[TextSegment]] = []
        current: List[TextSegment] = []

        for segment in segments:
            if not segment.text.strip():
                continue  # 空段不参与分组，也不产出内容
            # 原子段（表格 / 代码）：独占一组，前后都断开——它既不能并入邻段，
            # 也不许邻段并入它（否则会被切碎或把不相关的正文绑进同一块）。
            if segment.is_atomic:
                if current:
                    runs.append(current)
                    current = []
                runs.append([segment])
                continue
            if current and not self._can_merge(current[0], segment):
                runs.append(current)
                current = []
            current.append(segment)

        if current:
            runs.append(current)
        return runs

    def _combine_undersized(
        self, runs: List[List[TextSegment]]
    ) -> List[List[TextSegment]]:
        """把**长度不达标**的串并入下一串，消除碎片块

        判据是「串自身长度 < ``min_fill_chars``」——而不是「合并后是否超限」。后者会
        让短串找不到伙伴：``# 学习规则``（159 字符）与相邻的 Phase 0 小节（734 字符）
        合并后必然超过 ``chunk_size``，纯按上限判定就只能放弃合并、留下一个半空块。
        正确做法是**先合并再切分**：合并后的 895 字符由递归切分器切成两块约 448 的
        正常块，这正是社区 ``chunk_by_title`` 的行为。

        ``min_fill_chars == 0`` 时直接返回原串，便于 A/B 对比两种策略。

        尾部的残余串没有「下一串」可并，改为**并入前一串**（不超上限时）；仍放不下
        则独立成组——此时它确实是文档末尾的短收尾，无从消除。
        """
        if self.min_fill_chars <= 0:
            return runs

        merged: List[List[TextSegment]] = []
        pending: List[TextSegment] = []
        for run in runs:
            # 含原子段的串不参与「碎片合并」：原子块长度可能远小于 min_fill，
            # 若并入邻串会被切碎（违背原子性），故强制独立成组。
            if any(s.is_atomic for s in run):
                if pending:
                    merged.append(pending)
                    pending = []
                merged.append(run)
                continue
            candidate = pending + run if pending else list(run)
            pending = []
            if self._run_length(candidate) < self.min_fill_chars:
                pending = candidate
                continue
            merged.append(candidate)

        if pending:
            # 末尾残余串绝不并入**原子组**（否则表格/代码会被粘上无关正文而破坏
            # 原子性）：上一组合法且非原子、且合并后不超限时才并入，否则独立成组。
            if (
                merged
                and not any(s.is_atomic for s in merged[-1])
                and self._run_length(merged[-1])
                + len(_GROUP_SEPARATOR)
                + self._run_length(pending)
                <= self.chunk_size
            ):
                merged[-1] = merged[-1] + pending
            else:
                merged.append(pending)
        return merged

    @staticmethod
    def _run_length(run: List[TextSegment]) -> int:
        """串按 :data:`_GROUP_SEPARATOR` 拼接后的长度（与喂给切分器的文本同源）"""
        if not run:
            return 0
        return sum(len(s.text) for s in run) + len(_GROUP_SEPARATOR) * (len(run) - 1)

    @staticmethod
    def _can_merge(first: TextSegment, candidate: TextSegment) -> bool:
        """候选段能否并入以 ``first`` 为首段的**可合并串**

        规则：**顶层（深度 1）标题是串的硬边界**——候选段本身是顶层小节时必须另起
        一串；其余情况一律并入。

        为什么「候选是顶层即断开」恰好等价于「不跨越同级标题边界」：顶层标题总会先
        断开一次，因此任何串的成员都必然属于**同一个顶层小节**，串内不存在跨章合并。
        于是 ``# A`` 永远不会与 ``# B`` 进入同一串（社区 ``chunk_by_title`` 的核心
        约束），而 ``# A`` 内部的 ``## B`` ``## C`` ``### D`` 可以自由合成一块——
        块边界仍落在标题边界上。

        为什么串**内**允许同级兄弟合并：这是消除碎片化的前提。实测（5929 字符、
        52 个标题小节的 Markdown）若只允许「向更深层并入」，半空块占比 36.4%；
        允许顶层小节内部自由合并后，再配合 :meth:`_combine_undersized` 降到 5.6%。
        代价是块可能覆盖多个小节，由 ``heading_path_mixed`` 如实标记，
        ``heading_path`` 收敛为它们的公共祖先。

        两侧标题可得性不同时不合并（例如 DOCX 的前置正文与第一个 ``Heading 1``）：
        它们分属不同的结构域，混在一起会让 ``heading_path`` 无法自述。
        """
        first_depth = heading_depth(first.heading_path)
        candidate_depth = heading_depth(candidate.heading_path)
        if first_depth is None and candidate_depth is None:
            return True  # 无标题结构的格式（PDF / TXT）：可自由合并
        if first_depth is None or candidate_depth is None:
            return False
        return candidate_depth > ROOT_HEADING_DEPTH

    @staticmethod
    def _group_heading(group: List[TextSegment]) -> Tuple[Optional[str], bool]:
        """组的最深公共标题前缀，以及「该前缀是否**粗于**组的实际覆盖范围」

        ``mixed`` 的判据是「公共前缀**不在**组成员的路径集合里」，而不是「成员路径
        多于一个」。后者会把 ``{A, A>B}``（父节 + 其子节，合并的常态）也标成 mixed，
        于是本标记在真实语料上 100% 为真、彻底失去区分度——实测 Markdown 19/19 全为
        ``True``。

        按当前判据：

        * ``{A}`` / ``{A, A>B}`` → 前缀 ``A`` 就在集合里，``mixed=False``：标注 ``A``
          是**精确**的，块确实含 A 自身的内容；
        * ``{A>B, A>C}`` → 前缀 ``A`` 不在集合里，``mixed=True``：块只含 B、C 的内容，
          标注 ``A`` 是**粗化**的，前端应呈现为「A 等小节」；
        * ``{A, C}``（跨顶层小节的合并）→ 无公共分量，返回 ``(None, True)``。

        宁可不给标题，也不谎报一个不属于本块的章节名：``heading_path`` 是给人核对
        出处用的，写错比留空更糟。
        """
        paths = {s.heading_path for s in group if s.heading_path is not None}
        if not paths:
            return None, False
        prefix = common_heading_prefix(sorted(paths))
        return prefix, prefix not in paths

    @staticmethod
    def _locate(text: str, piece: str, cursor: int) -> int:
        """定位块在组文本中的起始偏移

        用 ``find`` 而不是「逐块累加长度」：块是 ``separator.join(片段)`` 再 ``strip``
        的结果，其长度不等于原文占位（块边界处的分隔符被丢弃、首尾空白被剥掉），
        累加会与真实偏移越差越远。
        """
        start = text.find(piece, cursor)
        if start < 0:
            start = text.find(piece)
        if start < 0:
            # 理论上不可达：块必是原文的连续子串。真发生说明分块器改写了内容，
            # 属实现异常，故降级为「沿用上一个游标」并留下告警，不静默返回 0。
            logger.warning(
                "chunk text not located in group text; page range may be approximate"
            )
            return cursor
        return start

    @staticmethod
    def _segment_bounds(
        group: List[TextSegment],
    ) -> List[Tuple[int, int, Optional[int]]]:
        """组内各段在**组文本**中的 ``(起始偏移, 结束偏移, 页码)``，一次性预计算

        偏移由同一份 ``_GROUP_SEPARATOR.join`` 累加得到，因而与块的偏移**同源**、
        无需再做文本查找，也就不会出现「页码与内容错位」。
        """
        bounds: List[Tuple[int, int, Optional[int]]] = []
        position = 0
        for segment in group:
            end = position + len(segment.text)
            bounds.append((position, end, segment.page))
            position = end + len(_GROUP_SEPARATOR)
        return bounds

    @staticmethod
    def _page_range(
        bounds: List[Tuple[int, int, Optional[int]]],
        start: int,
        end: int,
        pointer: int = 0,
    ) -> Tuple[Optional[int], Optional[int], int]:
        """块 ``[start, end)`` 实际覆盖的页码范围（1 基，闭区间）

        Args:
            bounds: :meth:`_segment_bounds` 的产物
            start / end: 块在组文本中的区间
            pointer: 调用方持有的**单调游标**。块在组内按序推进，故上一块扫过的
                段对后续块必然无交集，可直接跳过——整体只需扫一遍 ``bounds``。

        Returns:
            ``(起始页, 结束页, 新游标)``；无页码（MD / DOCX / TXT）时前两项为 ``None``
        """
        while pointer < len(bounds) and bounds[pointer][1] <= start:
            pointer += 1

        first: Optional[int] = None
        last: Optional[int] = None
        index = pointer
        while index < len(bounds) and bounds[index][0] < end:
            page = bounds[index][2]
            if page is not None:
                first = page if first is None else min(first, page)
                last = page if last is None else max(last, page)
            index += 1
        return first, last, index

    def _split_recursive(self, text: str, separators: List[str]) -> List[str]:
        """递归分块算法"""
        final_chunks = []
        separator = separators[-1]

        for sep in separators:
            if sep in text:
                separator = sep
                break

        if separator:
            splits = text.split(separator)
        else:
            splits = list(text)

        good_splits = []
        for s in splits:
            if len(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    merged = self._merge_splits(good_splits, separator)
                    final_chunks.extend(merged)
                    good_splits = []

                other_info = self._split_recursive(s, separators[separators.index(separator) + 1 :])
                final_chunks.extend(other_info)

        if good_splits:
            merged = self._merge_splits(good_splits, separator)
            final_chunks.extend(merged)

        return [c.strip() for c in final_chunks if c.strip()]

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:
        """合并短分块，并按 ``chunk_overlap`` 产生真实重叠（标准回溯算法）。

        与旧实现的关键差异
        ------------------
        旧实现只在 ``len(current) + len(s) + separator_len`` 超过 ``chunk_size``
        时换块，**从不回退已累积内容**，因此 ``chunk_overlap`` 参数只被读取、
        从未参与计算，声明的重叠实际恒为 0 —— 跨块边界的答案会被一刀两断，
        任何单块都无法独立支撑答案（D11，直接压低 Recall 上限）。

        本实现对齐 LangChain ``RecursiveCharacterTextSplitter._merge_splits``：
        换块时从 ``current_doc`` **头部弹出片段**，直到剩余长度不再超过
        ``chunk_overlap``（且新片段有机会落入本块），从而让新块以前一块的
        尾部片段开头，形成真实重叠。两个条件缺一不可：前者控制重叠上限，
        后者防止重叠区把块占满、导致新片段永远放不进去而死循环。

        保持的不变量
        ------------
        - 每个返回块长度 ≤ ``chunk_size``（片段自身超限时除外；上游
          ``_split_recursive`` 已保证喂入片段均 < ``chunk_size``，故不会发生）；
        - 每个返回块仍是原文的**连续子串**：块由 ``separator.join(片段)`` 还原，
          而片段来自 ``text.split(separator)``，拼接后可无损复原原文。
        """
        separator_len = len(separator)
        docs: List[str] = []
        current_doc: List[str] = []
        total = 0  # 恒等于 len(separator.join(current_doc))，避免重复拼接测长

        for d in splits:
            d_len = len(d)
            # 「已累积内容 + 新片段 + 分隔符」将超出块上限 → 先结算当前块
            if total + d_len + (separator_len if current_doc else 0) > self.chunk_size:
                if current_doc:
                    docs.append(separator.join(current_doc))
                    # 从头部弹出片段：直到 (a) 剩余长度 ≤ chunk_overlap，且
                    # (b) 新片段能落进本块（否则光有重叠、放不下新内容）
                    while total > self.chunk_overlap or (
                        total + d_len + (separator_len if current_doc else 0) > self.chunk_size
                        and total > 0
                    ):
                        total -= len(current_doc[0]) + (
                            separator_len if len(current_doc) > 1 else 0
                        )
                        current_doc = current_doc[1:]

            current_doc.append(d)
            total += d_len + (separator_len if len(current_doc) > 1 else 0)

        if current_doc:
            docs.append(separator.join(current_doc))

        return docs
