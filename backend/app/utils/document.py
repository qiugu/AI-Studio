"""文档解析和分块工具"""
import re
from typing import List
from pathlib import Path


class DocumentParser:
    """文档解析器，支持多种格式"""

    # 根据文件扩展名确定解析方法
    PARSERS = {
        ".txt": "parse_text",
        ".md": "parse_markdown",
        ".pdf": "parse_pdf",
        ".docx": "parse_docx",
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
        需要安装：pip install python-docx
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


class TextSplitter:
    """文本分块器，基于递归字符分块"""

    def __init__(
        self,
        chunk_size: int = 1024,
        chunk_overlap: int = 128,
        separators: List[str] = None,
    ):
        """
        初始化分块器

        Args:
            chunk_size: 分块大小（字符数）
            chunk_overlap: 分块之间的重叠（字符数）
            separators: 分割符列表，优先级递减
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", "。", "，", " ", ""]

    def split(self, text: str) -> List[str]:
        """
        将文本分块

        Returns:
            分块文本列表
        """
        return self._split_recursive(text, self.separators)

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
        """合并短分块"""
        separator_len = len(separator)
        good_splits = []
        current = ""

        for s in splits:
            if len(current) + len(s) + separator_len <= self.chunk_size:
                current += separator + s if current else s
            else:
                if current:
                    good_splits.append(current)
                current = s

        if current:
            good_splits.append(current)

        return good_splits
