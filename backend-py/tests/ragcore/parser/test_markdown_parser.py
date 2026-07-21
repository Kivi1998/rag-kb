"""MarkdownParser 测试。

对照 Java 版 `MarkdownParser.java`：标题层级追踪（heading_path 随标题深度回退）、
代码围栏内容不被当作分段依据、按空行分段、行号区间记录。纯字符串处理，直接构造
markdown 文本输入。
"""

from __future__ import annotations

from app.ragcore.parser.markdown_parser import MarkdownParser


class TestSupports:
    def test_supports_markdown_content_type(self):
        parser = MarkdownParser()
        assert parser.supports("text/markdown", None) is True

    def test_supports_by_extension_when_no_content_type(self):
        parser = MarkdownParser()
        assert parser.supports(None, "readme.md") is True
        assert parser.supports(None, "notes.markdown") is True

    def test_rejects_unrelated_extension(self):
        parser = MarkdownParser()
        assert parser.supports(None, "report.pdf") is False

    def test_rejects_no_content_type_no_filename(self):
        parser = MarkdownParser()
        assert parser.supports(None, None) is False


class TestHeadingPathTracking:
    def test_single_level_heading_applies_to_following_paragraph(self, make_document_input):
        text = "# 标题一\n\n正文内容属于标题一。\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        body_sections = [s for s in result.sections if "正文内容" in s.text]
        assert len(body_sections) == 1
        assert body_sections[0].heading_path == ("标题一",)

    def test_nested_headings_build_path(self, make_document_input):
        # 注意：新标题出现时会 flush 上一个块，块内容里包含标题行本身 + 后续正文
        # （标题行不是纯元数据、也计入 section.text），所以这里用子串匹配而不是整段相等。
        text = "# 一级\n\n## 二级\n\n正文\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        body_sections = [s for s in result.sections if "正文" in s.text]
        assert len(body_sections) == 1
        assert body_sections[0].heading_path == ("一级", "二级")

    def test_heading_backtracks_to_correct_level(self, make_document_input):
        """### 之后出现 ## 时，heading_path 要回退到二级，而不是简单按栈长度处理。"""
        text = "# 一级\n\n## 二级A\n\n### 三级\n\n正文A\n\n## 二级B\n\n正文B\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        section_a = next(s for s in result.sections if "正文A" in s.text)
        section_b = next(s for s in result.sections if "正文B" in s.text)
        assert section_a.heading_path == ("一级", "二级A", "三级")
        assert section_b.heading_path == ("一级", "二级B")


class TestCodeFenceProtection:
    def test_code_fence_content_kept_in_single_block(self, make_document_input):
        text = "# 标题\n\n```python\ndef f():\n    pass\n```\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        code_sections = [s for s in result.sections if "def f()" in s.text]
        assert len(code_sections) == 1
        assert "```python" in code_sections[0].text
        assert "pass" in code_sections[0].text

    def test_blank_lines_inside_code_fence_do_not_split_block(self, make_document_input):
        text = "```text\n" + ("line\n\n" * 20) + "```\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        # 围栏内即使有很多空行也不应该被切成多个 section（不在围栏内才按空行分段）。
        assert len(result.sections) == 1


class TestBasicSectioning:
    def test_empty_document_produces_no_sections(self, make_document_input):
        doc_input = make_document_input(b"", "empty.md")
        result = MarkdownParser().parse(doc_input)
        assert result.sections == ()

    def test_sections_have_line_ranges(self, make_document_input):
        text = "# 标题\n\n正文第一行\n正文第二行\n"
        doc_input = make_document_input(text.encode("utf-8"), "doc.md")
        result = MarkdownParser().parse(doc_input)

        body = next(s for s in result.sections if "正文第一行" in s.text)
        assert body.line_start is not None
        assert body.line_end is not None
        assert body.line_end >= body.line_start

    def test_metadata_includes_format_and_filename(self, make_document_input):
        doc_input = make_document_input(b"hello", "doc.md")
        result = MarkdownParser().parse(doc_input)
        assert result.metadata["format"] == "markdown"
        assert result.metadata["filename"] == "doc.md"
