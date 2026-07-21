"""可插拔文档格式解析器的接口定义。对应 DocumentParser.java。

历史说明:曾经还有一个 `MultimodalDocumentParser` ABC(对应 Java 版
`MultimodalDocumentParser.java`),`supports(document_input)` 签名与本文件的
`DocumentParser.supports(content_type, filename)` 不一致——那是当年专门为
"把 OCR/ASR 转发给独立 parser-gateway HTTP 服务"这个适配层设计的接口。现在
OCR(deepdoc)/ASR(faster-whisper)都已经下沉为进程内模块,`LocalMultimodalDocument
Parser`(见 `app.ragcore.parser.local_multimodal_parser`)直接实现本文件的
`DocumentParser` 接口即可,不再需要这个签名不一致的历史 ABC,已删除。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.ragcore.models import DocumentInput, ParsedDocument


class DocumentParser(ABC):
    """单一文档格式的本地解析器。"""

    @abstractmethod
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        """是否支持该 contentType/文件名组合。"""

    @abstractmethod
    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        """解析文档；解析器判断需要 OCR/ASR 时应抛出 NeedsMultimodalParsingException。"""
