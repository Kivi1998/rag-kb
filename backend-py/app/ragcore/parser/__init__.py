"""文档格式解析子包。对应 Java 版 `ragcore/parser/`。

公共 API:
    抽象接口: DocumentParser
    工厂: DocumentParserFactory, UnsupportedDocumentTypeException
    具体实现: MarkdownParser, CodeParser, DocxParser, PdfParser, PptxParser,
             TextParser, SubtitleParser, StructuredDataParser,
             LocalMultimodalDocumentParser(本地 OCR/ASR 兜底,由 base 之外的
             其他模块按需导入)

历史说明: `MultimodalDocumentParser` 这个签名不一致的历史 ABC(为已下线的
HTTP 网关适配层 `HttpMultimodalDocumentParser` 设计)已随该实现一并删除,
详见 `base.py` 和 `local_multimodal_parser.py` 的模块 docstring。
"""

from app.ragcore.parser.base import DocumentParser
from app.ragcore.parser.factory import (
    DocumentParserFactory,
    UnsupportedDocumentTypeException,
)
from app.ragcore.parser.local_multimodal_parser import LocalMultimodalDocumentParser
from app.ragcore.parser.subtitle_parser import SubtitleParser
from app.ragcore.parser.text_parser import TextParser

__all__ = [
    "DocumentParser",
    "DocumentParserFactory",
    "UnsupportedDocumentTypeException",
    "TextParser",
    "SubtitleParser",
    "LocalMultimodalDocumentParser",
]
