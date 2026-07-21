"""StructuredDataParser 测试。

对照 Java 版 `StructuredDataParser.java`：JSON/YAML 统一走树形展开，保留 `$.a.b` 形式的
jsonPath 元数据；大对象（>2048 字符）递归展开、小对象整体保留；XML 用简单标签正则展开。
纯字符串处理，直接构造 JSON/YAML/XML 文本输入。
"""

from __future__ import annotations

import json

from app.ragcore.parser.structured_data_parser import StructuredDataParser


class TestSupports:
    def test_supports_by_content_type(self):
        parser = StructuredDataParser()
        assert parser.supports("application/json", None) is True
        assert parser.supports("application/x-yaml", None) is True

    def test_supports_by_extension(self):
        parser = StructuredDataParser()
        assert parser.supports(None, "config.yaml") is True
        assert parser.supports(None, "config.yml") is True
        assert parser.supports(None, "data.json") is True
        assert parser.supports(None, "data.xml") is True

    def test_rejects_unrelated_extension(self):
        parser = StructuredDataParser()
        assert parser.supports(None, "report.pdf") is False


class TestJsonFlattening:
    def test_top_level_keys_recurse_with_json_path(self, make_document_input):
        payload = {"server": {"port": 8080, "host": "0.0.0.0"}, "name": "svc"}
        doc_input = make_document_input(json.dumps(payload).encode("utf-8"), "config.json")
        result = StructuredDataParser().parse(doc_input)

        json_paths = {s.metadata.get("jsonPath") for s in result.sections}
        assert "$.server" in json_paths
        assert "$.name" in json_paths

    def test_small_object_kept_as_single_compact_section(self, make_document_input):
        payload = {"server": {"port": 8080, "host": "0.0.0.0"}}
        doc_input = make_document_input(json.dumps(payload).encode("utf-8"), "config.json")
        result = StructuredDataParser().parse(doc_input)

        server_section = next(s for s in result.sections if s.heading_path == ("$.server",))
        assert "8080" in server_section.text
        assert "0.0.0.0" in server_section.text

    def test_large_object_recurses_into_children(self, make_document_input):
        # 构造一个 compact JSON 长度超过 2048 的大对象，逼迫按 key 递归展开。
        big_value = "x" * 2200
        payload = {"big": {"a": big_value, "b": "short"}}
        doc_input = make_document_input(json.dumps(payload).encode("utf-8"), "config.json")
        result = StructuredDataParser().parse(doc_input)

        json_paths = {s.metadata.get("jsonPath") for s in result.sections}
        # 大对象本身不该整体保留成一个 section，而是递归到子键。
        assert "$.big" not in json_paths
        assert "$.big.a" in json_paths
        assert "$.big.b" in json_paths

    def test_scalar_leaf_becomes_key_value_text(self, make_document_input):
        payload = {"version": "1.2.3"}
        doc_input = make_document_input(json.dumps(payload).encode("utf-8"), "config.json")
        result = StructuredDataParser().parse(doc_input)

        version_section = next(s for s in result.sections if s.heading_path == ("$.version",))
        assert version_section.text == "version: 1.2.3"

    def test_array_of_scalars_joined_by_newline(self, make_document_input):
        payload = {"tags": ["a", "b", "c"]}
        doc_input = make_document_input(json.dumps(payload).encode("utf-8"), "config.json")
        result = StructuredDataParser().parse(doc_input)

        tags_section = next(s for s in result.sections if s.heading_path == ("$.tags",))
        assert tags_section.text == "a\nb\nc"

    def test_empty_object_produces_no_sections(self, make_document_input):
        doc_input = make_document_input(b"{}", "empty.json")
        result = StructuredDataParser().parse(doc_input)
        assert result.sections == ()

    def test_metadata_format_is_json(self, make_document_input):
        doc_input = make_document_input(b'{"a": 1}', "data.json")
        result = StructuredDataParser().parse(doc_input)
        assert result.metadata["format"] == "json"


class TestYamlFlattening:
    def test_yaml_parsed_same_as_equivalent_json(self, make_document_input):
        yaml_text = "server:\n  port: 8080\n  host: 0.0.0.0\n"
        doc_input = make_document_input(yaml_text.encode("utf-8"), "config.yaml")
        result = StructuredDataParser().parse(doc_input)

        assert result.metadata["format"] == "yaml"
        server_section = next(s for s in result.sections if s.heading_path == ("$.server",))
        assert "8080" in server_section.text


class TestXmlFlattening:
    def test_tags_with_short_content_are_dropped(self, make_document_input):
        # 正则 `<(\w+)[^>]*>(.*?)</\1>` 非贪婪但不做真正的 XML 树解析（与 Java 版同款简化
        # 策略，详见模块 docstring：「不追求完整 XML 语义」）——用平铺、不嵌套的标签结构
        # 才能观察到"逐标签独立展开"的预期行为；嵌套标签会被最外层标签整体吃掉。
        xml_text = "<id>1</id><name>this is a long enough name value</name>"
        doc_input = make_document_input(xml_text.encode("utf-8"), "data.xml")
        result = StructuredDataParser().parse(doc_input)

        tags = {s.heading_path[0] for s in result.sections}
        # <id>1</id> 内容长度 <= 10，应该被丢弃；<name> 内容较长应保留。
        assert "id" not in tags
        assert "name" in tags

    def test_nested_tags_are_swallowed_by_outermost_match(self, make_document_input):
        """已知行为（非 bug）：嵌套标签只产生最外层一个 section，内层标签不会被单独展开。"""
        xml_text = "<root><id>1</id><name>this is a long enough name value</name></root>"
        doc_input = make_document_input(xml_text.encode("utf-8"), "data.xml")
        result = StructuredDataParser().parse(doc_input)

        tags = [s.heading_path[0] for s in result.sections]
        assert tags == ["root"]

    def test_tag_content_strips_nested_markup(self, make_document_input):
        xml_text = "<desc>hello <b>world</b> this has enough characters</desc>"
        doc_input = make_document_input(xml_text.encode("utf-8"), "data.xml")
        result = StructuredDataParser().parse(doc_input)

        desc_section = next(s for s in result.sections if s.heading_path == ("desc",))
        assert "<b>" not in desc_section.text
        assert "world" in desc_section.text

    def test_metadata_format_is_xml(self, make_document_input):
        xml_text = "<root><name>this is a long enough name value</name></root>"
        doc_input = make_document_input(xml_text.encode("utf-8"), "data.xml")
        result = StructuredDataParser().parse(doc_input)
        assert result.metadata["format"] == "xml"

    def test_no_matching_tags_falls_back_to_whole_document(self, make_document_input):
        # 没有 <tag>...</tag> 配对结构、但整体文本足够长时，回退成单个 section。
        xml_text = "just some plain text content without any xml tags at all here"
        doc_input = make_document_input(xml_text.encode("utf-8"), "data.xml")
        result = StructuredDataParser().parse(doc_input)

        assert len(result.sections) == 1
        assert result.sections[0].heading_path == ()
