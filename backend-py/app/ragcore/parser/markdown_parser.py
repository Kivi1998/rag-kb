"""Markdown 文档解析器。对应 MarkdownParser.java。

保留标题层级（heading_path）、代码围栏、列表结构和段落边界，按空行分段，
追踪标题栈构建 heading_path。
"""

from __future__ import annotations

import re

from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {"text/markdown", "text/x-markdown"}
_MARKDOWN_EXTENSIONS = {"md", "markdown", "mdown", "mkd"}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")


class MarkdownParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            return True
        if filename:
            return extension_of(filename) in _MARKDOWN_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            raw = stream.read()
        finally:
            stream.close()
        all_lines = raw.decode("utf-8").splitlines()

        sections: list[DocumentSection] = []
        heading_stack: list[str] = []
        heading_levels: list[int] = []
        current_block: list[str] = []
        block_start_line = 1
        in_code_fence = False

        def flush(line_end: int) -> None:
            nonlocal current_block, block_start_line
            text = "\n".join(current_block).strip()
            if text:
                path = tuple(heading_stack)
                sections.append(DocumentSection(text=text, heading_path=path, page_no=None,
                                                 line_start=block_start_line, line_end=line_end, metadata={}))
            current_block = []

        for i, line in enumerate(all_lines):
            line_no = i + 1

            if _CODE_FENCE_RE.match(line.strip()):
                in_code_fence = not in_code_fence
                current_block.append(line)
                continue

            if in_code_fence:
                current_block.append(line)
                continue

            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush(line_no - 1)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                # 以标题真实层级回退；不能仅按栈长度判断（例如 ### 后出现 ##）。
                while heading_levels and heading_levels[-1] >= level:
                    heading_levels.pop()
                    heading_stack.pop()
                heading_levels.append(level)
                heading_stack.append(title)

                block_start_line = line_no
                current_block.append(line)
                continue

            if not line.strip():
                current_block.append("")
                # Java 版按"字符长度 > 50"判断是否已有实质内容再 flush；
                # join 后的长度近似 Java 里 StringBuilder 长度。
                if len("\n".join(current_block)) > 50:
                    flush(line_no)
                    block_start_line = line_no + 1
                continue

            current_block.append(line)

        flush(len(all_lines))

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "markdown", "filename": document_input.filename() or ""},
        )
