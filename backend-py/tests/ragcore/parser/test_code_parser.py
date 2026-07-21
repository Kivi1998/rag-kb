"""CodeParser 测试。

对照 Java 版 `CodeParser.java`：语言探测（按扩展名/特殊文件名）、package/import 跳过、
顶层定义（类/函数）识别与代码块边界（Python 按缩进、花括号语言按配对计数）、
heading_path 记录当前定义名称。纯字符串处理，直接构造源码文本输入。
"""

from __future__ import annotations

from app.ragcore.parser.code_parser import CodeParser


class TestSupports:
    def test_supports_known_extension(self):
        parser = CodeParser()
        assert parser.supports(None, "Main.java") is True
        assert parser.supports(None, "app.py") is True

    def test_supports_dockerfile_by_filename(self):
        parser = CodeParser()
        assert parser.supports(None, "Dockerfile") is True
        assert parser.supports(None, "backend.Dockerfile") is True

    def test_supports_makefile_by_filename(self):
        parser = CodeParser()
        assert parser.supports(None, "Makefile") is True

    def test_rejects_unrelated_extension(self):
        parser = CodeParser()
        assert parser.supports(None, "report.docx") is False

    def test_rejects_no_filename_no_content_type(self):
        parser = CodeParser()
        assert parser.supports(None, None) is False


class TestLanguageDetection:
    def test_detects_python(self, make_document_input):
        doc_input = make_document_input(b"x = 1\n", "script.py")
        result = CodeParser().parse(doc_input)
        assert result.metadata["language"] == "Python"

    def test_detects_java(self, make_document_input):
        doc_input = make_document_input(b"public class A {}\n", "A.java")
        result = CodeParser().parse(doc_input)
        assert result.metadata["language"] == "Java"

    def test_detects_dockerfile(self, make_document_input):
        doc_input = make_document_input(b"FROM python:3.13\n", "Dockerfile")
        result = CodeParser().parse(doc_input)
        assert result.metadata["language"] == "Dockerfile"


class TestPythonParsing:
    def test_import_lines_are_skipped_as_sections(self, make_document_input):
        source = "import os\nfrom typing import Any\n\ndef foo():\n    return 1\n"
        doc_input = make_document_input(source.encode("utf-8"), "mod.py")
        result = CodeParser().parse(doc_input)

        joined = "\n".join(s.text for s in result.sections)
        assert "import os" not in joined
        assert "from typing import Any" not in joined

    def test_top_level_function_becomes_its_own_section(self, make_document_input):
        source = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
        doc_input = make_document_input(source.encode("utf-8"), "mod.py")
        result = CodeParser().parse(doc_input)

        foo_section = next(s for s in result.sections if "def foo" in s.text)
        bar_section = next(s for s in result.sections if "def bar" in s.text)
        assert foo_section.heading_path == ("foo",)
        assert bar_section.heading_path == ("bar",)
        assert "return 1" in foo_section.text
        assert "return 2" not in foo_section.text

    def test_function_body_ends_at_dedent(self, make_document_input):
        source = "def foo():\n    return 1\n\nx = 2\n"
        doc_input = make_document_input(source.encode("utf-8"), "mod.py")
        result = CodeParser().parse(doc_input)

        foo_section = next(s for s in result.sections if "def foo" in s.text)
        assert "return 1" in foo_section.text
        assert "x = 2" not in foo_section.text


class TestJavaParsing:
    def test_class_block_bounded_by_braces(self, make_document_input):
        source = "package com.example;\n\npublic class Foo {\n    void bar() {\n        int x = 1;\n    }\n}\n"
        doc_input = make_document_input(source.encode("utf-8"), "Foo.java")
        result = CodeParser().parse(doc_input)

        joined = "\n".join(s.text for s in result.sections)
        assert "package com.example;" not in joined

        foo_section = next(s for s in result.sections if "class Foo" in s.text)
        assert foo_section.heading_path == ("Foo",)
        assert "int x = 1;" in foo_section.text
        # 花括号配对结束后不应该把下一段无关内容纳入同一个 section。
        assert foo_section.text.strip().endswith("}")


class TestSectionsCarryLanguageMetadata:
    def test_each_section_metadata_has_language(self, make_document_input):
        source = "def foo():\n    return 1\n"
        doc_input = make_document_input(source.encode("utf-8"), "mod.py")
        result = CodeParser().parse(doc_input)
        assert all(s.metadata.get("language") == "Python" for s in result.sections)
