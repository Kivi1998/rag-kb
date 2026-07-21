"""纯文本 / 日志解析器。对应 TextParser.java。

按空行分块；连续非空行聚为一节。`heading_path=()`、`page_no=None`，每节带
`line_start` / `line_end` 元数据，便于在引用定位时回溯原始行号。

**与 Java 版的差异**：Java 版还做了超长段（>4096 字符）按句末标点的二次切分；
本移植先聚焦"按空行切段"的核心契约（与 MarkdownParser 风格一致），把超长段
二次切分留给后续针对超大日志/纯文本的优化任务；二次切分逻辑可作为内部
helper 在不破坏现有契约的前提下补回来。
"""

from __future__ import annotations

from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {"text/plain", "text/x-log"}
_TEXT_EXTENSIONS = {"txt"}


class TextParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            return True
        if filename:
            return extension_of(filename) in _TEXT_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            raw = stream.read().decode("utf-8")
        finally:
            stream.close()

        sections: list[DocumentSection] = []
        all_lines = raw.splitlines()
        n = len(all_lines)

        # 收集每个非空段(连续非空行聚合)。先扫一遍记录 (start, end) 区间(均为 1-based，
        # start 是段内第一行行号,end 是段内最后一行行号),再生成 section;这样 line 元数据
        # 稳定对应原始文件行号,引用定位不会因为空行丢字符。
        segments: list[tuple[int, int, str]] = []
        seg_start: int | None = None
        seg_buf: list[str] = []

        def flush(end_line: int) -> None:
            nonlocal seg_start, seg_buf
            if seg_start is None or not seg_buf:
                seg_start = None
                seg_buf = []
                return
            text = "\n".join(seg_buf).strip()
            if text:
                segments.append((seg_start, end_line, text))
            seg_start = None
            seg_buf = []

        for i, line in enumerate(all_lines):
            line_no = i + 1
            if line.strip():
                if seg_start is None:
                    seg_start = line_no
                seg_buf.append(line)
            else:
                if seg_start is not None:
                    flush(line_no - 1)
        # 文件末尾若以非空行收尾,补一次 flush
        if seg_start is not None and seg_buf:
            flush(n)

        for start, end, text in segments:
            sections.append(DocumentSection(
                text=text,
                heading_path=(),
                page_no=None,
                line_start=start,
                line_end=end,
                metadata={},
            ))

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "text", "filename": document_input.filename() or ""},
        )
