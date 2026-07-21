"""DOCX 文档解析器。对应 DocxParser.java。

提取段落正文、标题层级、表格文本；按标题/空行分节，每个节带 heading_path。

**与 Java 版的已知差异**：Java 版用 Apache POI(poi-ooxml)。本移植改用
`python-docx`(与 parser-gateway `_parse_docx` 同一个库，风格参考自那里)。
python-docx 不提供 POI `getAllPictures()` 那种"文档内嵌图片总表"的直接 API，
这里改为扫描 `document.part.rels` 里 reltype 为 IMAGE 的关系来判定"是否含内嵌
图片"，语义等价（POI 的 getAllPictures 底层也是遍历包内图片关系）。
"""

from __future__ import annotations

from docx import Document
from docx.document import Document as _DocumentType
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ragcore.models import DocumentInput, DocumentSection, NeedsMultimodalParsingException, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
_DOCX_EXTENSIONS = {"docx"}


def _iter_block_items(document: _DocumentType):
    """按文档正文顺序产出段落/表格对象，等价于 Java POI 的 IBodyElement 遍历。"""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


class DocxParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            return True
        if filename:
            return extension_of(filename) in _DOCX_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            document = Document(stream)
        finally:
            stream.close()

        # 技术文档中的报错截图、架构图和代码截图不能静默丢失；交给多模态网关统一抽正文、
        # 表格和图片 OCR。
        if self._has_embedded_pictures(document):
            raise NeedsMultimodalParsingException("DOCX 包含内嵌图片，需要 OCR 以保证内容完整性")

        sections: list[DocumentSection] = []
        heading_stack: list[str] = []
        current_block: list[str] = []

        def flush() -> None:
            nonlocal current_block
            text = "\n".join(current_block).strip()
            if text:
                sections.append(DocumentSection(text=text, heading_path=tuple(heading_stack),
                                                 page_no=None, line_start=None, line_end=None, metadata={}))
            current_block = []

        for element in _iter_block_items(document):
            if isinstance(element, Paragraph):
                style_id = element.style.style_id if element.style is not None else ""
                style_id = style_id or ""
                text = element.text

                if not text or not text.strip():
                    if len("\n".join(current_block)) > 50:
                        flush()
                    continue

                if self._is_heading_style(style_id):
                    flush()
                    level = self._extract_heading_level(style_id)
                    while len(heading_stack) >= level:
                        heading_stack.pop()
                    heading_stack.append(text.strip())
                    current_block.append(text.strip())
                    continue

                current_block.append(text)
            elif isinstance(element, Table):
                flush()
                table_text = self._extract_table(element)
                if table_text.strip():
                    sections.append(DocumentSection(text=table_text, heading_path=tuple(heading_stack),
                                                     page_no=None, line_start=None, line_end=None,
                                                     metadata={"type": "table"}))
        flush()

        if not sections:
            raise NeedsMultimodalParsingException("DOCX 中未提取到可索引文本，需要 OCR 或版面解析服务")

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "docx", "filename": document_input.filename() or ""},
        )

    def _has_embedded_pictures(self, document: _DocumentType) -> bool:
        for relationship in document.part.rels.values():
            if relationship.reltype == RT.IMAGE:
                return True
        return False

    def _is_heading_style(self, style_id: str) -> bool:
        return bool(style_id) and style_id.lower().startswith("heading") and style_id[7:].strip().isdigit()

    def _extract_heading_level(self, style_id: str) -> int:
        digits = "".join(ch for ch in style_id if ch.isdigit())
        try:
            return int(digits) if digits else 1
        except ValueError:
            return 1

    def _extract_table(self, table: Table) -> str:
        lines = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            lines.append(" | ".join(cells))
        return "\n".join(lines).strip()
