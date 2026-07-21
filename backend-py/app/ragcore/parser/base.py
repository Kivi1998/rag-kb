"""可插拔文档格式解析器的接口定义。对应 DocumentParser.java / MultimodalDocumentParser.java。"""

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


class MultimodalDocumentParser(ABC):
    """OCR、版面识别和语音转写的外部适配边界。

    对应 MultimodalDocumentParser.java：编排服务不绑定具体 OCR/ASR 实现，
    生产部署把它替换为独立 parser-gateway 服务，结果统一以 ParsedDocument 结构
    进入后续切块与索引链路。
    """

    @abstractmethod
    def supports(self, document_input: DocumentInput) -> bool:
        """是否支持该输入(通常按扩展名判断)。"""

    @abstractmethod
    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        """调用多模态网关完成解析。"""
