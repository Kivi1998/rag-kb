"""ES chunk `_source` 投影反序列化测试。

对照 Java 版 `ragcore/retrieval/ElasticsearchChunkDocumentMapper.java`。
负责把 ES `hits.hits[]._source` 还原为 Chunk;任何字段缺失/类型错误都该被识别为
ElasticsearchIndexException,而不是悄悄给 None 透传到下游(那会让 ChunkHydrator 把
越权 chunk 当合法数据补回).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.retrieval.es_chunk_document_mapper import SOURCE_FIELDS, to_chunk


def _valid_source(**overrides) -> dict:
    org_id = uuid4()
    kb_id = uuid4()
    document_id = uuid4()
    base = {
        "chunk_id": "chunk-1",
        "org_id": str(org_id),
        "kb_id": str(kb_id),
        "document_id": str(document_id),
        "ordinal": 3,
        "content": "正文片段",
        "heading_path": ["第一章", "第一节"],
        "source_path": "doc.md",
        "page_no": 7,
        "line_start": 10,
        "line_end": 12,
        "language": "python",
        "content_hash": "deadbeef",
        "metadata": {"key": "value"},
    }
    base.update(overrides)
    return base


class TestSourceFieldsContract:
    """SOURCE_FIELDS 是 ES 召回与补齐路径必须完全一致的字段集合,改了就破坏了
    chunk 投影兼容性,让其他模块拿不到全字段。"""

    def test_required_fields_present(self):
        for field in [
            "chunk_id", "org_id", "kb_id", "document_id", "ordinal", "content",
        ]:
            assert field in SOURCE_FIELDS

    def test_is_tuple_immutable(self):
        """SOURCE_FIELDS 是 tuple,任何修改会改变下游所有 ES 查询的 _source 投影。"""
        assert isinstance(SOURCE_FIELDS, tuple)


class TestHappyPath:
    def test_full_source_round_trips(self):
        source = _valid_source()
        chunk = to_chunk(source)
        assert chunk.id == "chunk-1"
        assert isinstance(chunk.organization_id, UUID)
        assert chunk.heading_path == ("第一章", "第一节")
        assert chunk.metadata == {"key": "value"}
        assert chunk.page_no == 7
        assert chunk.line_start == 10
        assert chunk.line_end == 12
        assert chunk.language == "python"
        assert chunk.content_hash == "deadbeef"

    def test_optional_fields_default_to_none(self):
        source = _valid_source()
        # 移除所有可选字段
        for optional in ("heading_path", "source_path", "page_no", "line_start", "line_end",
                        "language", "content_hash", "metadata"):
            source.pop(optional, None)
        chunk = to_chunk(source)
        assert chunk.heading_path == ()
        assert chunk.source_path is None
        assert chunk.page_no is None
        assert chunk.line_start is None
        assert chunk.line_end is None
        assert chunk.language is None
        assert chunk.content_hash is None
        assert chunk.metadata == {}


class TestRequiredFieldValidation:
    @pytest.mark.parametrize("missing", [
        "chunk_id", "org_id", "kb_id", "document_id", "ordinal", "content",
    ])
    def test_missing_required_field_raises(self, missing: str):
        source = _valid_source()
        source.pop(missing)
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)

    def test_blank_chunk_id_rejected(self):
        """空 chunk_id 会被误判为 ES 投影字段缺失,直接抛错而不是给个空字符串。"""
        source = _valid_source(chunk_id="   ")
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)

    def test_blank_content_rejected(self):
        source = _valid_source(content="")
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)

    def test_non_uuid_org_id_rejected(self):
        """org_id/kb_id/document_id 必须是合法 UUID,否则下游 ES 过滤拿不到匹配。"""
        source = _valid_source(org_id="not-a-uuid")
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)

    def test_bool_ordinal_rejected(self):
        """bool 是 int 子类,必须显式排除——否则 Python 把 True/False 当成 1/0 透传。"""
        source = _valid_source(ordinal=True)
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)

    def test_non_integer_ordinal_rejected(self):
        source = _valid_source(ordinal="three")
        with pytest.raises(ElasticsearchIndexException):
            to_chunk(source)
