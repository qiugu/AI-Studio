"""文档解析和分块工具

解析与分块分两层，中间用 :class:`TextSegment` 传递结构信息：

    DocumentParser.parse_segments()  →  [TextSegment(text, page, heading_path)]
    TextSplitter.split_segments()    →  [TextChunk(text, index, page, heading_path)]

分段的目的是让**元数据归属可精确断言**：一个块要么整块来自第 37 页，要么整块
不属于任何页，不会出现「标题在第 3 页、正文在第 4 页」的混合归属。因此分块是在
**每个段内部**独立进行的（见 :meth:`TextSplitter.split_segments`），块边界即段边界。

``DocumentParser.parse()`` / ``TextSplitter.split()`` 保持原有契约不变（返回纯文本 /
纯字符串列表），由分段接口**薄封装**实现——评测链路与既有单测依赖它们，改签名属
破坏性变更而收益仅为「少一个方法」。
"""
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class TextSegment:
    """解析后的一个连续文本段，自带其来源元数据

    ``page`` 与 ``heading_path`` 的**可得性因格式而异**，缺失时一律为 ``None``：
    不猜测、不用启发式（例如据字号推断 PDF 标题）把噪音写进元数据。

    * ``.pdf``： ``page`` 精确（逐页解析），``heading_path`` 恒为 ``None``
      ——``pypdf`` 只给文本流，无版式/结构信息；
    * ``.md``： ``heading_path`` 精确（ATX ``#`` 层级栈），``page`` 恒为 ``None``
      ——Markdown 无分页概念；
    * ``.docx``：``heading_path`` 精确（``paragraph.style.name``），``page`` 恒为
      ``None``——DOCX 无固定分页，同一段落在不同机器上落在不同页；
    * ``.txt``：两者恒为 ``None``。
    """

    text: str
    page: Optional[int] = None
    heading_path: Optional[str] = None


@dataclass(frozen=True)
class TextChunk:
    """分块结果，携带该块所属段的元数据"""

    text: str
    index: int
    page: Optional[int] = None
    heading_path: Optional[str] = None


#: Markdown ATX 标题（``#``~``######`` + 空格 + 标题文本）
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

#: DOCX 标题样式名：``Heading 2`` / ``标题 2``（Word 中文版）。
#: 样式名可能带修饰后缀（``Heading 1 Char``），故后续按前缀匹配。
_DOCX_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*(\d+)")


def _docx_heading_level(paragraph) -> Optional[int]:
    """从段落样式名解析标题层级；非标题返回 ``None``

    只认样式名这一**明确信号**，不按字号/加粗猜测（``Title`` 等样式也不当作标题）。
    """
    style = getattr(paragraph, "style", None)
    name = (getattr(style, "name", "") or "").strip()
    match = _DOCX_HEADING_RE.match(name)
    return int(match.group(1)) if match else None


class DocumentParser:
    """文档解析器，支持多种格式"""

    # 根据文件扩展名确定解析方法
    PARSERS = {
        ".txt": "parse_text",
        ".md": "parse_markdown",
        ".pdf": "parse_pdf",
        ".docx": "parse_docx",
    }

    # 分段解析方法（返回 List[TextSegment]，带页码 / 标题路径）
    SEGMENT_PARSERS = {
        ".txt": "parse_text_segments",
        ".md": "parse_markdown_segments",
        ".pdf": "parse_pdf_segments",
        ".docx": "parse_docx_segments",
    }

    @staticmethod
    def parse(file_path: str, file_type: str) -> str:
        """
        解析文件并返回文本内容

        Args:
            file_path: 文件路径
            file_type: 文件类型 (txt, md, pdf, docx)

        Returns:
            解析后的文本内容
        """
        parser = DocumentParser.PARSERS.get(f".{file_type}")
        if not parser:
            raise ValueError(f"Unsupported file type: {file_type}")

        method = getattr(DocumentParser, parser)
        return method(file_path)

    @staticmethod
    def parse_segments(file_path: str, file_type: str) -> List[TextSegment]:
        """解析文件并返回**分段**结果，每段自带页码 / 标题路径

        与 :meth:`parse` 的关系是**严格**的：``parse()`` 的返回值必须等于
        ``"\\n".join(s.text for s in parse_segments(...))``——即分段只是把同一份文本
        切开，不增删任何字符。该不变量由 ``tests/test_document_segments.py`` 逐格式
        回归断言；否则「加元数据」会悄悄改变入库文本，且不会有任何报错。

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

    @staticmethod
    def parse_text(file_path: str) -> str:
        """解析纯文本文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def parse_markdown(file_path: str) -> str:
        """解析Markdown文件"""
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def parse_pdf(file_path: str) -> str:
        """
        解析PDF文件
        需要安装：pip install pypdf
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError("pypdf is required for PDF parsing. Install it with: pip install pypdf")

        text = []
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                text.append(page.extract_text())
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {str(e)}")

        return "\n".join(text)

    @staticmethod
    def parse_docx(file_path: str) -> str:
        """
        解析Word文档
        需要安装：python-docx
        """
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx is required for DOCX parsing. Install it with: pip install python-docx")

        text = []
        try:
            doc = Document(file_path)
            for para in doc.paragraphs:
                if para.text.strip():
                    text.append(para.text)
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX: {str(e)}")

        return "\n".join(text)

    # ── 分段解析 ──────────────────────────────────────────────────────────────

    @staticmethod
    def parse_text_segments(file_path: str) -> List[TextSegment]:
        """纯文本：整份文件作为**单一**段（无结构信息可提取）"""
        with open(file_path, "r", encoding="utf-8") as f:
            return [TextSegment(text=f.read())]

    @staticmethod
    def parse_markdown_segments(file_path: str) -> List[TextSegment]:
        """Markdown：按 ATX 标题层级切段，每段记录其标题栈路径

        行为细节（都为让 :meth:`parse_markdown` 仍能无损复原原文）：

        * **逐行分区**，每一行必须且只能属于一段——**包括空行**。空行若被丢弃，
          ``parse()`` 的返回值就不再与原文逐字符相等；
        * 标题行归属**紧随其后的那段**（标题即本节内容的一部分）：块文本自描述、
          标题本身可被检索命中，且元数据与实际内容不错位；
        * 层级回退用栈式归并：遇 ``##`` 时弹出所有 ``>= 2`` 的层级，故 ``# A``
          下的 ``### B`` 得到 ``"A > B"``，同级标题互不串味。

        标题路径形如 ``"3 原理 > 3.2 注意力"``（各级标题原文以 ``" > "`` 连接）。
        """
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")

        segments: List[TextSegment] = []
        stack: List[Tuple[int, str]] = []  # [(level, title)]
        run: List[str] = []
        current_path: Optional[str] = None

        def flush() -> None:
            if run:
                segments.append(TextSegment(text="\n".join(run), heading_path=current_path))
                run.clear()

        for line in lines:
            heading = _ATX_HEADING_RE.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                title = heading.group(2).strip().rstrip("#").strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, title))
                current_path = " > ".join(title for _, title in stack) or None
            run.append(line)

        flush()
        return segments

    @staticmethod
    def parse_pdf_segments(file_path: str) -> List[TextSegment]:
        """PDF：**一页一段**，页码为 1 基（与阅读器显示一致）

        ``heading_path`` 恒为 ``None``：``pypdf`` 只提供文本流，没有版式信息；
        用字号/加粗等启发式推断标题属于**猜测**，会把噪音写进「出处」这个本应
        可核对的字段。要做另立专项，以样本准确率作为验收。

        ``extract_text()`` 对空白页可能返回 ``None``，此处归一为 ``""``：旧实现
        直接把它塞进 ``"\\n".join``，遇到这类页面会以 ``TypeError`` 崩掉。
        """
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ImportError("pypdf is required for PDF parsing. Install it with: pip install pypdf")

        segments: List[TextSegment] = []
        try:
            reader = PdfReader(file_path)
            for page_no, page in enumerate(reader.pages, start=1):
                segments.append(TextSegment(text=page.extract_text() or "", page=page_no))
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {str(e)}")

        return segments

    @staticmethod
    def parse_docx_segments(file_path: str) -> List[TextSegment]:
        """DOCX：按段落样式名（``Heading N`` / ``标题 N``）切段

        空段落与 :meth:`parse_docx` 保持一致地过滤掉，保证 ``parse()`` 返回值不变。
        """
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx is required for DOCX parsing. Install it with: pip install python-docx")

        segments: List[TextSegment] = []
        stack: List[Tuple[int, str]] = []
        run: List[str] = []
        current_path: Optional[str] = None

        def flush() -> None:
            if run:
                segments.append(TextSegment(text="\n".join(run), heading_path=current_path))
                run.clear()

        try:
            doc = Document(file_path)
            for para in doc.paragraphs:
                text = para.text
                if not text.strip():
                    continue
                level = _docx_heading_level(para)
                if level is not None:
                    flush()
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    stack.append((level, text.strip()))
                    current_path = " > ".join(title for _, title in stack) or None
                run.append(text)
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


class TextSplitter:
    """文本分块器，基于递归字符分块"""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        separators: Optional[List[str]] = None,
    ):
        """
        初始化分块器

        Args:
            chunk_size: 分块大小（字符数）。``None`` 时取 ``config.chunk_size``。
            chunk_overlap: 分块之间的重叠（字符数）。``None`` 时取
                ``config.chunk_overlap``。
            separators: 分割符列表，优先级递减

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
        self.separators = separators or ["\n\n", "\n", "。", "，", " ", ""]

    def split(self, text: str) -> List[str]:
        """
        将文本分块

        Returns:
            分块文本列表
        """
        return self._split_recursive(text, self.separators)

    def split_segments(self, segments: List[TextSegment]) -> List[TextChunk]:
        """**段内切分**：在每个段内部独立分块，元数据随段下发

        为什么不做跨段合并：跨段合并会让块归属退化为「起始页」——一个块里可能同时
        含第 3 页尾与第 4 页头，``source_page`` 便无法再被断言为「这一块的页码」，
        而本项目的元数据是给人看、用于核实出处的（「出自第 37 页 §3.2」），归属必须
        精确。代价是页尾/节尾会多出一些短块（数量可量化，见方案 §2.1）。

        ``index`` 是**文档内全局序号**（从 0 开始，跨段连续），与入库的
        ``chunk_index`` 一致；它同时参与 ``vector_id`` 的推导，故必须稳定可复现。

        空段（如纯空白页）不产出块——否则会出现内容为空的分块并被向量化。
        """
        chunks: List[TextChunk] = []
        for segment in segments:
            for piece in self._split_recursive(segment.text, self.separators):
                chunks.append(
                    TextChunk(
                        text=piece,
                        index=len(chunks),
                        page=segment.page,
                        heading_path=segment.heading_path,
                    )
                )
        return chunks

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
