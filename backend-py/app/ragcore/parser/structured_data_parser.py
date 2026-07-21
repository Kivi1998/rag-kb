"""YAML / JSON / XML 结构化配置解析器。对应 StructuredDataParser.java。

将结构化内容展开为带键路径（如 `server.port`）的可检索平铺文本节，每个顶层键或
语义配置节作为一个 DocumentSection。JSON/YAML 统一走同一套树形展开逻辑
（YAML 先解析成 Python 原生结构，与 JSON 解析结果同构处理）；XML 用简单的
标签正则展开（不追求完整 XML 语义，只保证标签内文本可检索，逐字对应 Java 版
同款正则策略）。
"""

from __future__ import annotations

import json
import re

import yaml

from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser.base import DocumentParser

_STRUCT_EXTENSIONS = {"json", "yaml", "yml", "xml"}
_STRUCT_TYPES = {
    "application/json", "application/xml", "text/xml",
    "application/x-yaml", "text/yaml", "text/x-yaml", "application/yaml",
}

_XML_TAG_RE = re.compile(r"<(\w+)[^>]*>(.*?)</\1>", re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

_JsonScalar = str | int | float | bool | None


class StructuredDataParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _STRUCT_TYPES:
            return True
        if filename:
            ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
            return ext in _STRUCT_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            raw = stream.read().decode("utf-8").strip()
        finally:
            stream.close()
        fmt = self._detect_format(document_input.filename())

        if fmt == "xml":
            return self._parse_xml(document_input, raw)

        if fmt in ("yaml", "yml"):
            tree = yaml.safe_load(raw)
        else:
            tree = json.loads(raw) if raw else {}

        sections: list[DocumentSection] = []
        # 始终从根节点递归，保证中间键（如 $.server）出现在 jsonPath 元数据里。
        if isinstance(tree, dict):
            for key, value in tree.items():
                self._flatten(value, f"$.{key}", sections)
        else:
            self._flatten(tree, "$", sections)

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": fmt, "filename": document_input.filename() or ""},
        )

    def _parse_xml(self, document_input: DocumentInput, raw: str) -> ParsedDocument:
        sections: list[DocumentSection] = []
        line_no = 1
        for m in _XML_TAG_RE.finditer(raw):
            tag = m.group(1)
            content = _WHITESPACE_RE.sub(" ", _TAG_STRIP_RE.sub(" ", m.group(2))).strip()
            matched_lines = m.group(0).count("\n")
            if len(content) > 10:
                sections.append(DocumentSection(
                    text=content, heading_path=(tag,), page_no=None,
                    line_start=line_no, line_end=line_no + matched_lines,
                    metadata={"xpath": f"/{tag}"},
                ))
            line_no += matched_lines

        if not sections and len(raw) > 10:
            stripped = _WHITESPACE_RE.sub(" ", _TAG_STRIP_RE.sub(" ", raw)).strip()
            if len(stripped) > 10:
                sections.append(DocumentSection(
                    text=stripped, heading_path=(), page_no=None,
                    line_start=1, line_end=raw.count("\n") + 1, metadata={"format": "xml"},
                ))

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "xml", "filename": document_input.filename() or ""},
        )

    def _flatten(self, node: object, path: str, sections: list[DocumentSection]) -> None:
        """把一棵 JSON/YAML 树展开成 DocumentSection 列表，保留 $.a.b 形式的键路径。"""
        if isinstance(node, dict):
            compact = self._compact_json(node)
            if len(compact) <= 2048:
                sections.append(DocumentSection(text=compact, heading_path=(path,), page_no=None,
                                                 line_start=None, line_end=None, metadata={"jsonPath": path}))
                return
            for key, value in node.items():
                self._flatten(value, f"{path}.{key}", sections)
        elif isinstance(node, list):
            lines: list[str] = []
            for item in node:
                if isinstance(item, dict):
                    lines.append(self._compact_json(item))
                elif isinstance(item, list):
                    lines.append(self._compact_json(item))
                else:
                    lines.append(self._as_text(item))
            text = "\n".join(lines).strip()
            if text:
                sections.append(DocumentSection(text=text, heading_path=(path,), page_no=None,
                                                 line_start=None, line_end=None, metadata={"jsonPath": path}))
        else:
            text = self._as_text(node)
            if text.strip():
                key = path.rsplit(".", 1)[-1]
                kv = f"{key}: {text}"
                sections.append(DocumentSection(text=kv, heading_path=(path,), page_no=None,
                                                 line_start=None, line_end=None, metadata={"jsonPath": path}))

    def _compact_json(self, node: object) -> str:
        return json.dumps(node, ensure_ascii=False, separators=(",", ":"))

    def _as_text(self, value: _JsonScalar) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _detect_format(self, filename: str | None) -> str:
        if not filename:
            return "json"
        lower = filename.lower()
        if lower.endswith(".yaml") or lower.endswith(".yml"):
            return "yaml"
        if lower.endswith(".xml"):
            return "xml"
        return "json"
