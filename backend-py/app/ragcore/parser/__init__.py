"""文档格式解析子包。对应 Java 版 `ragcore/parser/`。

公共 API:
    抽象接口: DocumentParser, MultimodalDocumentParser
    工厂: DocumentParserFactory, UnsupportedDocumentTypeException
    具体实现: MarkdownParser, CodeParser, DocxParser, PdfParser, PptxParser,
             TextParser, SubtitleParser, StructuredDataParser,
             HttpMultimodalDocumentParser(由 base 之外的其他模块按需导入)
"""

from app.ragcore.parser.base import DocumentParser, MultimodalDocumentParser
from app.ragcore.parser.factory import (
    DocumentParserFactory,
    UnsupportedDocumentTypeException,
)
from app.ragcore.parser.multimodal_parser import HttpMultimodalDocumentParser
from app.ragcore.parser.subtitle_parser import SubtitleParser
from app.ragcore.parser.text_parser import TextParser

__all__ = [
    "DocumentParser",
    "MultimodalDocumentParser",
    "DocumentParserFactory",
    "UnsupportedDocumentTypeException",
    "TextParser",
    "SubtitleParser",
    "HttpMultimodalDocumentParser",
]
