"""文档解析器工厂: 按 content_type / 文件名扩展名路由到对应 DocumentParser。

对应 Java 版 `ragcore/parser/impl/DocumentParserFactory.java`。
Python 侧没有现成 factory,这次新写一个轻量路由器,统一供 `DefaultDocumentIngestionPipeline`
与 `QuickDocumentService` 使用,避免每个调用方各自手写 if/elif 链。
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.ragcore.models import DocumentInput, ParsedDocument
from app.ragcore.parser.base import DocumentParser

logger = logging.getLogger(__name__)


class UnsupportedDocumentTypeException(ValueError):
    """没有可用 Parser 时抛出,QuickDocumentService 等调用方决定是否降级到多模态网关。"""


def _extension_of(filename: str | None) -> str:
    if not filename:
        return ""
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot + 1 :].lower()


class DocumentParserFactory:
    def __init__(self, parsers: Iterable[DocumentParser]) -> None:
        self._parsers = list(parsers)

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        content_type = document_input.content_type()
        filename = document_input.filename()
        for parser in self._parsers:
            try:
                if parser.supports(content_type, filename):
                    return parser.parse(document_input)
            except Exception:  # noqa: BLE001 - 单个 Parser 失败不应阻塞其他候选
                logger.debug(
                    "Parser 抛异常,跳过: %s, filename=%s", type(parser).__name__, filename
                )
        raise UnsupportedDocumentTypeException(
            f"找不到支持 content_type={content_type!r} / filename={filename!r} 的解析器"
        )

    def find(self, content_type: str | None, filename: str | None) -> DocumentParser | None:
        for parser in self._parsers:
            if parser.supports(content_type, filename):
                return parser
        return None

    @staticmethod
    def extension_of(filename: str | None) -> str:
        return _extension_of(filename)
