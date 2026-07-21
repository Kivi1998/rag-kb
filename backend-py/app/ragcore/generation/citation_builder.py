"""将最终参与回答的 chunk 转为前端可定位的服务端引用。

对应 Java 版 `ragcore/generation/CitationBuilder.java`。
"""

from __future__ import annotations

from uuid import UUID

from app.ragcore.model import Citation, RetrievedChunk

MAX_SNIPPET_CHARS = 500


def build(chunks: list[RetrievedChunk], document_names: dict[UUID, str]) -> list[Citation]:
    return [_build_one(item, document_names) for item in chunks]


def _build_one(item: RetrievedChunk, document_names: dict[UUID, str]) -> Citation:
    chunk = item.chunk
    content = chunk.content
    snippet = content if len(content) <= MAX_SNIPPET_CHARS else content[:MAX_SNIPPET_CHARS] + "…"
    document_name = document_names.get(chunk.document_id, "已删除或不可访问的文档")
    return Citation(
        document_id=chunk.document_id,
        document_name=document_name,
        heading_path=chunk.heading_path,
        snippet=snippet,
        page_no=chunk.page_no,
        line_start=chunk.line_start,
        line_end=chunk.line_end,
        score=item.final_score,
    )
