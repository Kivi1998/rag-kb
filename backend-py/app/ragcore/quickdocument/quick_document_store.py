"""会话内临时文档的存取端口。

对应 Java 版 `ragcore/quickdocument/QuickDocumentStore.java`。
实现负责 TTL 与过期清理,调用方不感知底层存储细节。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from app.ragcore.quickdocument.quick_document import QuickDocument


@runtime_checkable
class QuickDocumentStore(Protocol):
    async def save(self, document: QuickDocument) -> None: ...

    async def find_all_by_session(self, session_id: UUID) -> list[QuickDocument]: ...

    async def delete(self, session_id: UUID, doc_id: UUID) -> None: ...

    async def touch(self, session_id: UUID, doc_ids: list[UUID]) -> None: ...
