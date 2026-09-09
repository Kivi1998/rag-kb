"""本地多模态解析兜底实现。取代已下线的 `HttpMultimodalDocumentParser`。

背景:parser-gateway 最初被拆成独立 HTTP 微服务,是因为主编排后端历史上是 Java,
Java 没有好用的 OCR 生态。现在主后端(backend-py)本身也是 Python 了,
deepdoc(OCR + 版面识别 + 表格结构识别,见 `app.ragcore.parser.deepdoc`)已经
下沉为进程内模块,不再需要跨进程 HTTP 往返、也不再需要网关那套 multipart 契约。

**2026-09 已移除音视频(ASR)支持**:当前业务不再需要音视频转写能力,原
`app.ragcore.parser.asr`(faster-whisper 封装)模块、`mp3/wav/mp4/mov/mkv`
扩展名的分发分支与对应上传校验规则一并删除。`ParseError`/`ParserUnavailableError`
两个异常原定义在 `asr.py` 里,但语义上一直是"多模态实现执行失败"的通用异常
(OCR 侧同样在用),随 `asr.py` 一起删除会破坏 OCR 路径,因此改为直接定义在本
文件里,不再从已删除的模块导入。

**设计决策 1 —— 不再实现 `MultimodalDocumentParser` 这个历史 ABC**:
`MultimodalDocumentParser.supports(document_input)` 的签名和 `DocumentParser.
supports(content_type, filename)` 不一致,是当年专门为 HTTP 网关适配层设计的
接口。现在唯一的多模态实现就是本类,网关已经不存在,继续维护两套不同签名的
抽象契约只会让 `DocumentParserFactory` 需要用 `isinstance` 特判两种 parser。
因此 `LocalMultimodalDocumentParser` 直接继承 `DocumentParser`,和其余 8 个
本地解析器共用同一套 `supports(content_type, filename)` / `parse(document_input)`
契约,`DocumentParserFactory` 不需要再区分"是不是多模态 parser"。`base.py` 里的
`MultimodalDocumentParser` ABC 本身也一并删除(全仓库唯一实现已删除,没有代码
再引用它)。

**设计决策 2 —— 各扩展名的分发逻辑**(逐个移植自
`parser-gateway/app/parsers.py` 的 `_parse_pdf`/`_parse_docx`/`_parse_pptx`/
`_parse_image`/`_parse_media`,只是把返回值从裸 dict 换成
`app.ragcore.model.ParsedDocument`/`DocumentSection`,并把所有同步阻塞调用
包一层 `asyncio.to_thread`):
    - pdf: 逐页用 PyMuPDF 提取原生文本,≥100 字符的页直接用原生文本;否则渲染
      成图片交给 `deepdoc.pipeline.parse_page()` 做 OCR + 版面分析 + 表格识别。
      与本地 `PdfParser` 的"整份文档平均字符数"判定不同,这里按页判定,因为
      能走到这里的 PDF 已经被 `PdfParser` 判定为整体低文本量,按页处理能让
      混排扫描页/文字页的文档也拿到尽量高质量的结果。
    - docx: 复用 `docx_parser.py` 的 `_iter_block_items()` 做段落/表格遍历
      (标题层级、表格拼接风格与本地 `DocxParser` 保持一致),额外对
      `document.part.rels` 里 reltype 为 IMAGE 的内嵌图片逐张跑纯文字 OCR
      (不需要版面/表格分析,直接调 `deepdoc.pipeline._ocr()` 单例,比整页
      `parse_page()` 更快,同 parser-gateway `_ocr_bytes()` 的取舍)。
    - pptx: 逐页取文本框文字(风格对齐本地 `PptxParser`),对
      `MSO_SHAPE_TYPE.PICTURE` 类型的图片形状同样跑纯文字 OCR。
    - png/jpg/jpeg/tif/tiff: 整张图片直接跑 `deepdoc.pipeline.parse_page()`。

**异常语义**:`ParseError`(执行失败,如 OCR 均未产出任何文本)和
`ParserUnavailableError`(OCR 底层模型不可用)定义在本文件里,不新增一套平行的
异常类——这两个异常描述的是"多模态实现自身失败了",不是
`NeedsMultimodalParsingException` 那种"移交决策"信号。
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import numpy as np
from PIL import Image

from app.core.config import settings
from app.ragcore.model import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser
from app.ragcore.parser.deepdoc import pipeline as deepdoc_pipeline
from app.ragcore.parser.docx_parser import _iter_block_items

logger = logging.getLogger(__name__)


class ParseError(RuntimeError):
    """多模态解析执行失败(如 OCR 未产生任何文本片段)。"""


class ParserUnavailableError(RuntimeError):
    """OCR 运行时未安装,或模型加载失败,导致解析能力当前不可用。"""


_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff"}
_SUPPORTED_EXTENSIONS = {"pdf", "docx", "pptx", *_IMAGE_EXTENSIONS}

# 文本型 PDF 逐页判定阈值:与 parser-gateway `_parse_pdf` 一致的经验值。
_MIN_CHARS_PER_PAGE = 100


class LocalMultimodalDocumentParser(DocumentParser):
    """OCR(deepdoc)的本地多模态兜底解析器。

    在 `DocumentParserFactory` 的解析器列表里应放在最后一位:本地格式解析器
    (`PdfParser`/`DocxParser`/`PptxParser` 等)判定"需要 OCR"时抛出
    `NeedsMultimodalParsingException`,factory 捕获后继续尝试列表里的下一个
    candidate,自然落到这里对整份文档重新完整解析。
    """

    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if not settings.rag_multimodal_parser_enabled:
            return False
        if not filename:
            return False
        return extension_of(filename) in _SUPPORTED_EXTENSIONS

    async def parse(self, document_input: DocumentInput) -> ParsedDocument:
        filename = document_input.filename() or ""
        ext = extension_of(filename)

        stream = document_input.open_stream()
        try:
            content = stream.read()
        finally:
            stream.close()

        if ext == "pdf":
            sections, metadata = await asyncio.to_thread(_parse_pdf_bytes, content)
        elif ext == "docx":
            sections, metadata = await asyncio.to_thread(_parse_docx_bytes, content)
        elif ext == "pptx":
            sections, metadata = await asyncio.to_thread(_parse_pptx_bytes, content)
        elif ext in _IMAGE_EXTENSIONS:
            sections, metadata = await asyncio.to_thread(_parse_image_bytes, content, ext)
        else:
            # supports() 已经把关,理论上不会走到这里;保留 fail-fast 兜底
            # 避免未来扩展 _SUPPORTED_EXTENSIONS 时忘记同步分发分支。
            raise ParseError(f"本地多模态解析器不支持的扩展名: {ext!r}")

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# 各格式的同步实现:全部是纯 CPU/IO 阻塞调用,只应在 asyncio.to_thread 里执行。
# ---------------------------------------------------------------------------


def _parse_pdf_bytes(content: bytes) -> tuple[list[DocumentSection], dict[str, str]]:
    import fitz  # pymupdf

    document = fitz.open(stream=content, filetype="pdf")
    try:
        sections: list[DocumentSection] = []
        ocr_pages = 0
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            if len(text) >= _MIN_CHARS_PER_PAGE:
                sections.append(DocumentSection(
                    text=text, page_no=index + 1, metadata={"type": "page", "ocr": "false"},
                ))
                continue

            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            page_sections = _safe_parse_page(image)
            ocr_pages += 1
            for sec in page_sections:
                sec_text = (sec.get("text") or "").strip()
                if not sec_text:
                    continue
                sections.append(DocumentSection(
                    text=sec_text, page_no=index + 1,
                    metadata={"type": sec.get("layout_type") or "page", "ocr": "true"},
                ))

        if not sections:
            raise ParseError("PDF 未提取到任何可索引文本(本地多模态 OCR 兜底仍未产出内容)")

        return sections, {
            "format": "pdf",
            "pageCount": str(document.page_count),
            "ocrPageCount": str(ocr_pages),
            "parser": "local-multimodal",
        }
    finally:
        document.close()


def _parse_docx_bytes(content: bytes) -> tuple[list[DocumentSection], dict[str, str]]:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(content))
    sections: list[DocumentSection] = []
    heading_stack: list[str] = []
    current_block: list[str] = []

    def flush() -> None:
        nonlocal current_block
        text = "\n".join(current_block).strip()
        if text:
            sections.append(DocumentSection(
                text=text, heading_path=tuple(heading_stack), metadata={"type": "paragraph"},
            ))
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

            if _is_heading_style(style_id):
                flush()
                level = _extract_heading_level(style_id)
                while len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(text.strip())
                current_block.append(text.strip())
                continue

            current_block.append(text)
        elif isinstance(element, Table):
            flush()
            table_text = _extract_table_text(element)
            if table_text.strip():
                sections.append(DocumentSection(
                    text=table_text, heading_path=tuple(heading_stack), metadata={"type": "table"},
                ))
    flush()

    ocr_images = 0
    seen_parts: set[str] = set()
    for relationship in document.part.rels.values():
        if relationship.reltype != RT.IMAGE:
            continue
        part_name = str(relationship.target_part.partname)
        if part_name in seen_parts:
            continue
        seen_parts.add(part_name)
        image_text = _ocr_bytes(relationship.target_part.blob)
        if image_text:
            ocr_images += 1
            sections.append(DocumentSection(text=image_text, metadata={"type": "image", "ocr": "true"}))

    if not sections:
        raise ParseError("DOCX 未提取到任何可索引文本(含内嵌图片 OCR 兜底后仍为空)")

    return sections, {"format": "docx", "ocrImageCount": str(ocr_images), "parser": "local-multimodal"}


def _parse_pptx_bytes(content: bytes) -> tuple[list[DocumentSection], dict[str, str]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    presentation = Presentation(io.BytesIO(content))
    sections: list[DocumentSection] = []
    ocr_images = 0
    for slide_no, slide in enumerate(presentation.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = (shape.text_frame.text or "").strip()
                if text:
                    lines.append(text)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                image_text = _ocr_bytes(shape.image.blob)
                if image_text:
                    lines.append(image_text)
                    ocr_images += 1
        if not lines:
            continue
        title = next((line for line in lines if len(line) <= 120), f"第 {slide_no} 页")
        sections.append(DocumentSection(
            text="\n".join(lines), heading_path=(title,), page_no=slide_no,
            metadata={"type": "slide", "slideNo": str(slide_no)},
        ))

    if not sections:
        raise ParseError("PPTX 未提取到任何可索引文本(含图片 OCR 兜底后仍为空)")

    return sections, {
        "format": "pptx",
        "slideCount": str(len(presentation.slides)),
        "ocrImageCount": str(ocr_images),
        "parser": "local-multimodal",
    }


def _parse_image_bytes(content: bytes, ext: str) -> tuple[list[DocumentSection], dict[str, str]]:
    image = Image.open(io.BytesIO(content))
    page_sections = _safe_parse_page(image)
    sections: list[DocumentSection] = []
    for sec in page_sections:
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        sections.append(DocumentSection(
            text=text, page_no=1, metadata={"type": sec.get("layout_type") or "image", "ocr": "true"},
        ))

    if not sections:
        raise ParseError("图片 OCR 未产出任何文字")

    return sections, {"format": ext, "ocrPageCount": "1", "parser": "local-multimodal"}


# ---------------------------------------------------------------------------
# deepdoc OCR 调用的小工具:模型不可用统一收敛为 ParserUnavailableError,
# 单张内嵌图片解码/识别失败则跳过(不拖垮整份文档),与 parser-gateway
# `ensure_ocr_ready()`/`_ocr_bytes()` 的取舍一致。
# ---------------------------------------------------------------------------


def _safe_parse_page(image: Image.Image) -> list[dict[str, Any]]:
    try:
        return deepdoc_pipeline.parse_page(image)
    except Exception as exc:  # noqa: BLE001 - OCR/版面/表格模型底层任意异常统一收敛
        raise ParserUnavailableError("OCR/版面分析模型不可用") from exc


def _ocr_bytes(data: bytes) -> str:
    """给 DOCX/PPTX 内嵌的单张图片做纯文字识别,不跑版面/表格分析(更快)。"""
    try:
        deepdoc_pipeline.ensure_models_ready()
    except Exception as exc:  # noqa: BLE001
        raise ParserUnavailableError("OCR/版面分析模型不可用") from exc

    try:
        np_image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
        raw_boxes = deepdoc_pipeline._ocr(np_image)
    except Exception:
        # 单张图片解码/识别失败(如老式 WMF/EMF 矢量图 Pillow 无法解码)不该
        # 拖垮整份文档的解析——按"这张图没有可识别文字"处理,跳过继续。
        logger.warning("跳过一张无法解码或识别的内嵌图片", exc_info=True)
        return ""
    if not raw_boxes:
        return ""
    return "\n".join(text.strip() for _, (text, _score) in raw_boxes if text and text.strip())


# ---------------------------------------------------------------------------
# DOCX 标题层级/表格抽取:与 `docx_parser.py::DocxParser` 里的同名逻辑保持一致
# 风格,但这里是独立的模块级函数(不复用 DocxParser 实例方法,避免耦合到另一个
# parser 类的私有实现细节)。
# ---------------------------------------------------------------------------


def _is_heading_style(style_id: str) -> bool:
    return bool(style_id) and style_id.lower().startswith("heading") and style_id[7:].strip().isdigit()


def _extract_heading_level(style_id: str) -> int:
    digits = "".join(ch for ch in style_id if ch.isdigit())
    try:
        return int(digits) if digits else 1
    except ValueError:
        return 1


def _extract_table_text(table: Any) -> str:
    lines = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        lines.append(" | ".join(cells))
    return "\n".join(lines).strip()
