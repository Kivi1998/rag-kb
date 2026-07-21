"""PdfParser 测试。

用 `pymupdf`(fitz) 现造最小 PDF 文档验证解析结果结构（不是逐字节对齐 Java 版）：
sections、page_no 正确、扫描件（文本量过低）触发 `NeedsMultimodalParsingException`、
启发式标题检测。

已知限制（模块 docstring 里也提到）：`page.insert_text()` 在同一页内多次调用时，
`get_text("text")` 提取结果只用单个 `\\n` 连接各行，不会产生 `\\n\\n` 段落分隔——因此
这里测试段落切分逻辑时，让"一页 = 一个段落"，用多页而不是同页多段来覆盖 page_no 和
段落级过滤行为，避免依赖 pymupdf 排版细节的脆弱断言。
"""

from __future__ import annotations

import fitz
import pytest

from app.ragcore.model import NeedsMultimodalParsingException
from app.ragcore.parser.pdf_parser import PdfParser
from tests.ragcore.parser.conftest import FakeDocumentInput


def _build_pdf(page_texts: list[str]) -> bytes:
    doc = fitz.open()
    try:
        for text in page_texts:
            page = doc.new_page(width=595, height=1600)
            # 默认内置字体(Helvetica)不含中文字形，写入中文会被静默替换成占位符（"·"），
            # 必须显式用内置 CJK 字体，否则提取出来的文本根本不是我们写入的中文。
            # 用 insert_textbox（而不是 insert_text）让长文本按页宽自动换行，
            # 否则 insert_text 遇到超出单行宽度的文字会被静默截断、丢字符。
            rect = fitz.Rect(72, 72, 523, 1500)
            page.insert_textbox(rect, text, fontsize=11, fontname="china-s")
        return doc.tobytes()
    finally:
        doc.close()


def _pdf_input(data: bytes, filename: str = "doc.pdf") -> FakeDocumentInput:
    return FakeDocumentInput(data, filename, content_type="application/pdf")


_FILLER = "这是用于填充字符数量的正文内容，需要足够长才能超过每页最少字符数阈值。" * 3


class TestSupports:
    def test_supports_by_content_type(self):
        assert PdfParser().supports("application/pdf", None) is True

    def test_supports_by_extension(self):
        assert PdfParser().supports(None, "report.pdf") is True

    def test_rejects_unrelated(self):
        assert PdfParser().supports(None, "report.docx") is False


class TestMultiPageParsing:
    def test_page_no_assigned_per_page_in_order(self):
        pages = [f"第{i}页 {_FILLER}" for i in range(1, 4)]
        data = _build_pdf(pages)
        result = PdfParser().parse(_pdf_input(data))

        page_numbers = [s.page_no for s in result.sections]
        assert page_numbers == sorted(page_numbers)
        assert set(page_numbers) == {1, 2, 3}

    def test_metadata_num_pages_matches_page_count(self):
        data = _build_pdf([_FILLER, _FILLER])
        result = PdfParser().parse(_pdf_input(data))
        assert result.metadata["numPages"] == "2"
        assert result.metadata["format"] == "pdf"

    def test_section_content_type_and_source_path_from_input(self):
        data = _build_pdf([_FILLER])
        doc_input = _pdf_input(data, filename="spec.pdf")
        result = PdfParser().parse(doc_input)
        assert result.content_type == "application/pdf"
        assert result.source_path == "spec.pdf"


class TestShortParagraphFiltering:
    def test_page_with_only_very_short_text_produces_no_section(self):
        # "hi" 长度 <5，即使这一页本身通过不了自己的密度阈值，只要整份文档的平均字符数
        # 达标（靠另一页 filler 撑住），这一页也不会因为扫描件判断被整体拒绝，
        # 但它的短段落应该被丢弃，不产生 section。
        data = _build_pdf(["hi", _FILLER * 4])
        result = PdfParser().parse(_pdf_input(data))
        assert all(s.text != "hi" for s in result.sections)


class TestHeadingDetection:
    def test_chapter_pattern_first_line_becomes_heading(self):
        text = f"第一章 引言\n{_FILLER}"
        data = _build_pdf([text])
        result = PdfParser().parse(_pdf_input(data))
        assert any(s.heading_path == ("第一章 引言",) for s in result.sections)

    def test_numbered_pattern_first_line_becomes_heading(self):
        text = f"一、概述\n{_FILLER}"
        data = _build_pdf([text])
        result = PdfParser().parse(_pdf_input(data))
        assert any(s.heading_path == ("一、概述",) for s in result.sections)

    def test_short_pure_chinese_first_line_is_treated_as_heading_too(self):
        """已知启发式弱点（非本次移植引入的 bug，Java 版同款逻辑）：

        `first_line == first_line.upper()` 对不含小写 ASCII 字母的字符串（纯中文/
        数字/标点）恒为真，所以任何 <=80 字符的中文首行都会被判成"标题"，不只是真正的
        全大写英文标题。这里显式记录这个行为，避免以后有人当成回归 bug 来"修"。
        """
        text = f"这是一段普通正文，不符合任何标题启发式规则。{_FILLER}"
        data = _build_pdf([text])
        result = PdfParser().parse(_pdf_input(data))
        assert any(s.heading_path != () for s in result.sections)

    def test_mixed_case_english_first_line_with_lowercase_has_no_heading(self):
        text = f"This is a plain paragraph in mixed Case, not a heading. {_FILLER}"
        data = _build_pdf([text])
        result = PdfParser().parse(_pdf_input(data))
        assert all(s.heading_path == () for s in result.sections)


class TestScannedPdfFallback:
    def test_low_text_density_raises_needs_multimodal_parsing(self):
        # 每页只放极少文字，平均每页字符数远低于 MIN_CHARS_PER_PAGE=100。
        data = _build_pdf(["x", "y", "z"])
        with pytest.raises(NeedsMultimodalParsingException):
            PdfParser().parse(_pdf_input(data))
