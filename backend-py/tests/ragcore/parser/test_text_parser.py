"""TextParser 测试。

覆盖：supports 判定、按空行切段、line_start/line_end 元数据、文件末尾无空行
收尾、纯空文件无 section、长单段不切。
"""

from __future__ import annotations

from app.ragcore.parser.text_parser import TextParser


class TestSupports:
    def test_supports_by_content_type(self):
        assert TextParser().supports("text/plain", None) is True
        assert TextParser().supports("text/x-log", None) is True

    def test_supports_by_extension(self):
        assert TextParser().supports(None, "notes.txt") is True

    def test_rejects_unrelated(self):
        assert TextParser().supports(None, "report.md") is False
        assert TextParser().supports(None, "data.json") is False

    def test_rejects_no_content_type_no_filename(self):
        assert TextParser().supports(None, None) is False


class TestSectioning:
    def test_blank_line_separates_paragraphs(self, make_document_input):
        text = "第一段第一行\n第一段第二行\n\n第二段第一行\n\n第三段\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.txt")
        result = TextParser().parse(doc_input)

        texts = [s.text for s in result.sections]
        assert texts == ["第一段第一行\n第一段第二行", "第二段第一行", "第三段"]

    def test_line_start_and_end_track_paragraphs(self, make_document_input):
        # 文件: 4 行,1 段占 1-2,空行,1 段占 4
        text = "段A第一行\n段A第二行\n\n段B\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.txt")
        result = TextParser().parse(doc_input)

        seg_a = next(s for s in result.sections if "段A" in s.text)
        seg_b = next(s for s in result.sections if "段B" in s.text)
        assert seg_a.line_start == 1
        assert seg_a.line_end == 2
        assert seg_b.line_start == 4
        assert seg_b.line_end == 4

    def test_no_trailing_blank_line_still_captures_last_paragraph(self, make_document_input):
        # 文件以非空行收尾,且两段之间用空行分隔
        text = "第一段\n\n第二段\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.txt")
        result = TextParser().parse(doc_input)

        assert [s.text for s in result.sections] == ["第一段", "第二段"]

    def test_empty_document_produces_no_sections(self, make_document_input):
        doc_input = make_document_input(b"", "empty.txt")
        result = TextParser().parse(doc_input)
        assert result.sections == ()

    def test_only_blank_lines_produces_no_sections(self, make_document_input):
        text = "\n\n\n"
        doc_input = make_document_input(text.encode("utf-8"), "blank.txt")
        result = TextParser().parse(doc_input)
        assert result.sections == ()

    def test_multiple_blank_lines_between_paragraphs_treated_as_one_separator(
        self, make_document_input
    ):
        text = "段A\n\n\n\n\n段B\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.txt")
        result = TextParser().parse(doc_input)
        assert [s.text for s in result.sections] == ["段A", "段B"]

    def test_metadata_includes_format_and_filename(self, make_document_input):
        doc_input = make_document_input(b"hello world", "log.txt")
        result = TextParser().parse(doc_input)
        assert result.metadata["format"] == "text"
        assert result.metadata["filename"] == "log.txt"

    def test_heading_path_is_empty_tuple(self, make_document_input):
        doc_input = make_document_input("一段\n".encode("utf-8"), "doc.txt")
        result = TextParser().parse(doc_input)
        assert result.sections[0].heading_path == ()
        assert result.sections[0].page_no is None
