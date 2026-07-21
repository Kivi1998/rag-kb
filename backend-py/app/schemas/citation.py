"""引用 DTO,序列化 app.ragcore.model.Citation。供会话历史消息、SSE source 事件复用。
对应 Java 版 ragcore/model/Citation.java 被 Jackson 直接序列化时的字段形状。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.ragcore.model import Citation


class CitationOut(BaseModel):
    document_id: UUID | None = Field(default=None, alias="documentId")
    document_name: str = Field(..., alias="documentName")
    heading_path: tuple[str, ...] = Field(default_factory=tuple, alias="headingPath")
    snippet: str
    page_no: int | None = Field(default=None, alias="pageNo")
    line_start: int | None = Field(default=None, alias="lineStart")
    line_end: int | None = Field(default=None, alias="lineEnd")
    score: float | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @staticmethod
    def from_domain(citation: Citation) -> "CitationOut":
        return CitationOut(
            documentId=citation.document_id,
            documentName=citation.document_name,
            headingPath=citation.heading_path,
            snippet=citation.snippet,
            pageNo=citation.page_no,
            lineStart=citation.line_start,
            lineEnd=citation.line_end,
            score=citation.score,
        )
