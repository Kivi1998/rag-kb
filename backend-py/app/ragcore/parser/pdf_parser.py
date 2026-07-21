"""文本型 PDF 解析器。对应 PdfParser.java。

保留页码信息。仅在 PDF 可以提取足够文本时标记为成功；扫描型/纯图片 PDF 标记为
不能解析（通过检测提取文本量与文件页数的比例判断质量）。扫描 PDF 不静默成功：
文本量不足时抛出 `NeedsMultimodalParsingException` 交由多模态网关接管。

**与 Java 版的已知差异**：Java 版用 Apache PDFBox。本移植改用 `pymupdf`(fitz)，
与 parser-gateway `_parse_pdf` 同一个库、同样的原生文本提取路径(`page.get_text
("text")`)。**已知限制**：这条路径不做版面分析，多栏文本型 PDF 仍可能按行交叉
拼接（与 parser-gateway 文档里记录的限制一致，`docs/解析指南.md` 已知限制第一条）；
PDFBox 与 PyMuPDF 的文本提取顺序、换行/分段方式并非逐字节一致，因此本解析器的
"平均每页字符数"阈值判断、段落切分结果与 Java 版不保证完全相同，但判定逻辑
(MIN_CHARS_PER_PAGE=100、按空行分段、启发式标题检测)是等价移植。
"""

from __future__ import annotations

import re

import fitz  # pymupdf

from app.ragcore.models import DocumentInput, DocumentSection, NeedsMultimodalParsingException, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {"application/pdf"}
_PDF_EXTENSIONS = {"pdf"}

# 每页最少平均字符数，低于此值认为是扫描 PDF
_MIN_CHARS_PER_PAGE = 100

_HEADING_CHAPTER_RE = re.compile(r".*第[一二三四五六七八九十\d]+[章节条].*")
_HEADING_NUMBERED_RE = re.compile(r"^[一二三四五六七八九十\d]+[、.．].*$")


class PdfParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            return True
        if filename:
            return extension_of(filename) in _PDF_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            data = stream.read()
        finally:
            stream.close()

        document = fitz.open(stream=data, filetype="pdf")
        try:
            num_pages = document.page_count
            if num_pages == 0:
                raise IOError("PDF 文件无页面")

            page_texts = [page.get_text("text") for page in document]
            full_text = "\n".join(page_texts)
            avg_chars_per_page = len(full_text) / num_pages
            if avg_chars_per_page < _MIN_CHARS_PER_PAGE:
                raise NeedsMultimodalParsingException(
                    f"PDF 文本量过低（平均每页 {avg_chars_per_page:.0f} 字符），"
                    "可能为扫描件或纯图片 PDF，当前不支持解析"
                )

            sections: list[DocumentSection] = []
            for page_no, page_text in enumerate(page_texts, start=1):
                page_text = page_text.strip()
                if not page_text:
                    continue
                paragraphs = re.split(r"\n\n+", page_text)
                for para in paragraphs:
                    trimmed = para.strip()
                    if len(trimmed) < 5:
                        continue
                    heading_path = self._detect_heading(trimmed)
                    sections.append(DocumentSection(
                        text=trimmed, heading_path=heading_path, page_no=page_no,
                        line_start=None, line_end=None, metadata={},
                    ))

            return ParsedDocument(
                document_id=document_input.document_id(),
                content_type=document_input.content_type(),
                source_path=document_input.source_path(),
                sections=tuple(sections),
                metadata={"format": "pdf", "numPages": str(num_pages)},
            )
        finally:
            document.close()

    def _detect_heading(self, text: str) -> tuple[str, ...]:
        first_line = text.split("\n")[0].strip()
        if len(first_line) <= 80 and (
            first_line == first_line.upper()
            or _HEADING_CHAPTER_RE.fullmatch(first_line)
            or _HEADING_NUMBERED_RE.fullmatch(first_line)
        ):
            return (first_line,)
        return ()
