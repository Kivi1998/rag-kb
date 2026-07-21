"""会话内临时文档值对象。

对应 Java 版 `ragcore/quickdocument/QuickDocument.java`。
不写入知识库、不参与切块/向量化/索引,只在 Redis 里按 TTL 存活。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QuickDocument:
    doc_id: UUID
    session_id: UUID
    filename: str
    content: str
    character_count: int
    created_at: datetime

    def __post_init__(self) -> None:
        if self.doc_id is None:
            raise ValueError("doc_id 不能为空")
        if self.session_id is None:
            raise ValueError("session_id 不能为空")
        if not self.filename:
            raise ValueError("filename 不能为空")
        if self.content is None:
            raise ValueError("content 不能为空")
        if self.created_at is None:
            raise ValueError("created_at 不能为空")
        if self.character_count < 0:
            raise ValueError("character_count 不能为负数")
