"""会话内临时文档的解析、额度校验与存取编排。

对应 Java 版 `ragcore/quickdocument/QuickDocumentService.java`。
复用 `DocumentParserFactory`(含 OCR 网关自动降级),不新写解析逻辑;
不切块、不向量化、不写入知识库索引。

字符预算超出会话已用额度时抛 `QuotaExceededException`,不写入任何数据
(无论 Redis 还是解析中间产物)。
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from app.core.config import Settings, settings as default_settings
from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser.factory import DocumentParserFactory
from app.ragcore.quickdocument.quick_document import QuickDocument
from app.ragcore.quickdocument.quick_document_store import QuickDocumentStore

logger = logging.getLogger(__name__)


class QuotaExceededException(ValueError):
    """会话临时文档总额度池已满,拒绝本次上传;继承 ValueError 复用现有 400 映射。"""

    def __init__(self, existing_characters: int, new_characters: int, max_total_characters: int) -> None:
        super().__init__(
            f"会话临时文档总额已满(已用 {existing_characters} + 本次 {new_characters} > 上限 "
            f"{max_total_characters} 字符),请先删除一个再上传"
        )


class QuickDocumentService:
    def __init__(
        self,
        parser_factory: DocumentParserFactory,
        store: QuickDocumentStore,
        cfg: Settings | None = None,
        max_total_characters: int | None = None,
    ) -> None:
        cfg = cfg or default_settings
        self._factory = parser_factory
        self._store = store
        self._max_total = max_total_characters or cfg.rag_quick_document_max_total_characters

    async def upload(self, session_id: UUID, file: "DocumentInputLike") -> QuickDocument:
        doc_id = uuid4()
        # 先在 async 方法里把完整字节内容读出来,再交给同步的 parser;不要在同步
        # 方法内部尝试把 asyncio 桥接成阻塞读取(会在已运行的事件循环里抛
        # RuntimeError,参见 default_pipeline.py 的 _DocumentInputAdapter 同类修法)。
        # 临时文档本就受 rag.quick-document.max-total-characters 额度限制,一次性
        # 读入内存可接受。
        raw_bytes = await file.read()
        parsed = await self._factory.parse(_to_parser_input(doc_id, file, raw_bytes))
        content = _join_sections(parsed)

        existing = sum(d.character_count for d in await self._store.find_all_by_session(session_id))
        new_chars = len(content)
        if existing + new_chars > self._max_total:
            raise QuotaExceededException(existing, new_chars, self._max_total)

        filename = file.filename or "unknown"
        document = QuickDocument(
            doc_id=doc_id,
            session_id=session_id,
            filename=filename,
            content=content,
            character_count=new_chars,
            created_at=datetime.now(tz=timezone.utc),
        )
        await self._store.save(document)
        return document

    async def list(self, session_id: UUID) -> list[QuickDocument]:
        return list(await self._store.find_all_by_session(session_id))

    async def delete(self, session_id: UUID, doc_id: UUID) -> None:
        await self._store.delete(session_id, doc_id)


# ---- 输入适配 --------------------------------------------------------

class DocumentInputLike(Protocol):
    """FastAPI `UploadFile` / Django `UploadedFile` 适配协议,只读所需字段。"""

    @property
    def filename(self) -> str | None: ...

    @property
    def content_type(self) -> str | None: ...

    async def read(self) -> bytes: ...


def _to_parser_input(doc_id: UUID, file: DocumentInputLike, content: bytes) -> DocumentInput:
    return _BytesDocumentInput(doc_id, file, content)


class _BytesDocumentInput(DocumentInput):
    """包装已异步读取完毕的字节内容,`open_stream()` 直接返回同步 BytesIO。

    不再需要惰性的异步转同步桥接(此前的 `_AsyncByteStreamAdapter` 在已运行的
    事件循环里调用 `run_until_complete()` 会抛 RuntimeError,详见 upload() 处注释)。
    """

    def __init__(self, document_id: UUID, file: DocumentInputLike, content: bytes) -> None:
        self._doc_id = document_id
        self._file = file
        self._content = content

    def document_id(self) -> UUID:
        return self._doc_id

    def filename(self) -> str:
        return self._file.filename or "unknown"

    def content_type(self) -> str | None:
        return self._file.content_type

    def source_path(self) -> str:
        return f"quickdoc/{self._doc_id}"

    def open_stream(self):
        return io.BytesIO(self._content)


def _join_sections(parsed: ParsedDocument) -> str:
    """把 ParsedDocument 的 sections 拼成一段纯文本;QuickDocument 不需要保留结构。"""
    parts: list[str] = []
    for section in parsed.sections:
        if isinstance(section, DocumentSection):
            text = section.text
        else:
            # 兼容 chunk.models.DocumentSection(同样有 text/heading_path/page_no 等字段)
            text = getattr(section, "text", None)
        if text:
            parts.append(text)
    return "\n\n".join(parts)
