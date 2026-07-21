"""CitationBuilder 测试。

对照 Java 版 `CitationBuilder.java`：验证从 chunk/RetrievedChunk 正确提取字段构造
Citation，snippet 超过 500 字符截断并补省略号，文档名缺失时回退成"已删除或不可访问的文档"。
"""

from __future__ import annotations

from uuid import uuid4

from app.ragcore.generation.citation_builder import MAX_SNIPPET_CHARS, build
from app.ragcore.model import Chunk, RetrievedChunk


def _chunk(**overrides) -> Chunk:
    defaults = dict(
        id="chunk-1",
        organization_id=None,
        knowledge_base_id=None,
        document_id=uuid4(),
        ordinal=0,
        content="正文内容",
        heading_path=("第一章", "第一节"),
        page_no=3,
        line_start=10,
        line_end=20,
    )
    defaults.update(overrides)
    return Chunk(**defaults)


class TestCitationFieldMapping:
    def test_extracts_all_fields_from_chunk(self):
        document_id = uuid4()
        chunk = _chunk(document_id=document_id, content="短内容", page_no=5, line_start=1, line_end=2)
        candidate = RetrievedChunk(chunk=chunk, final_score=0.87)

        citations = build([candidate], {document_id: "需求文档.docx"})

        assert len(citations) == 1
        citation = citations[0]
        assert citation.document_id == document_id
        assert citation.document_name == "需求文档.docx"
        assert citation.heading_path == ("第一章", "第一节")
        assert citation.snippet == "短内容"
        assert citation.page_no == 5
        assert citation.line_start == 1
        assert citation.line_end == 2
        assert citation.score == 0.87

    def test_missing_document_name_falls_back_to_placeholder(self):
        document_id = uuid4()
        chunk = _chunk(document_id=document_id)
        candidate = RetrievedChunk(chunk=chunk, final_score=0.5)

        citations = build([candidate], {})

        assert citations[0].document_name == "已删除或不可访问的文档"

    def test_preserves_order_of_input_list(self):
        c1 = RetrievedChunk(chunk=_chunk(id="a"), final_score=0.1)
        c2 = RetrievedChunk(chunk=_chunk(id="b"), final_score=0.9)

        citations = build([c1, c2], {})

        assert [c.score for c in citations] == [0.1, 0.9]

    def test_empty_list_returns_empty(self):
        assert build([], {}) == []


class TestSnippetTruncation:
    def test_short_content_not_truncated(self):
        chunk = _chunk(content="a" * 100)
        citation = build([RetrievedChunk(chunk=chunk)], {})[0]
        assert citation.snippet == "a" * 100

    def test_content_at_exact_limit_not_truncated(self):
        chunk = _chunk(content="a" * MAX_SNIPPET_CHARS)
        citation = build([RetrievedChunk(chunk=chunk)], {})[0]
        assert citation.snippet == "a" * MAX_SNIPPET_CHARS
        assert "…" not in citation.snippet

    def test_content_over_limit_truncated_with_ellipsis(self):
        chunk = _chunk(content="a" * (MAX_SNIPPET_CHARS + 50))
        citation = build([RetrievedChunk(chunk=chunk)], {})[0]
        assert citation.snippet == "a" * MAX_SNIPPET_CHARS + "…"
        assert len(citation.snippet) == MAX_SNIPPET_CHARS + 1
