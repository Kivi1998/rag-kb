"""PPTX 技术演示文稿解析器。对应 PptxParser.java。

提取每页的可见文本，使用第一个短文本框作为页标题，并把页号写入结构化元数据。
图表、图片、扫描页中的文字由多模态解析网关补充，本解析器不伪造 OCR 结果。

**与 Java 版的已知差异**：Java 版用 Apache POI(poi-ooxml)。本移植改用
`python-pptx`(与 parser-gateway `_parse_pptx` 同一个库)。与 Java 版一致，
本解析器只抽文本框文字，不在本地做图片 OCR——图片文字识别统一交给
`NeedsMultimodalParsingException` 触发的多模态网关兜底（当页面完全没有文本
时），而不是像 parser-gateway 那样逐图内联 OCR。
"""

from __future__ import annotations

from pptx import Presentation

from app.ragcore.models import DocumentInput, DocumentSection, NeedsMultimodalParsingException, ParsedDocument
from app.ragcore.parser.base import DocumentParser

_SUPPORTED_TYPES = {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}


class PptxParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type and content_type.lower() in _SUPPORTED_TYPES:
            return True
        return bool(filename) and filename.lower().endswith(".pptx")

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        stream = document_input.open_stream()
        try:
            presentation = Presentation(stream)
        finally:
            stream.close()

        sections: list[DocumentSection] = []
        slide_no = 0
        for slide in presentation.slides:
            slide_no += 1
            lines: list[str] = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    text = (shape.text_frame.text or "").strip()
                    if text:
                        lines.append(text)
            if not lines:
                continue
            title = next((line for line in lines if len(line) <= 120), f"第 {slide_no} 页")
            sections.append(DocumentSection(
                text="\n".join(lines), heading_path=(title,), page_no=slide_no,
                line_start=None, line_end=None,
                metadata={"type": "slide", "slideNo": str(slide_no)},
            ))

        if not sections:
            raise NeedsMultimodalParsingException("PPTX 中未提取到可索引文本；需要 OCR 或版面解析服务")

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "pptx", "slideCount": str(len(presentation.slides))},
        )
