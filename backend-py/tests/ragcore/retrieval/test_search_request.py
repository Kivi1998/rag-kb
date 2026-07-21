"""SearchRequest / VectorSearchRequest 租户边界校验测试。

对应 Java 版 `ragcore/index/SearchRequest.java`、`ragcore/retrieval/VectorSearchRequest.java`。
这两个 dataclass 是 ES / Milvus 召回请求的统一入口,要求强制携带 org_id + kb_id,
且 top_k / query_vector 必填——任何"未带边界"或"空 query_vector"都直接 ValueError,
不允许落到下游(那会变成裸查全索引的越权路径)。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.ragcore.index.search_request import SearchRequest
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest


class TestSearchRequestValidation:
    def test_minimal_valid_request(self):
        req = SearchRequest(organization_id=uuid4(), knowledge_base_id=uuid4(), query="hello", top_k=10)
        assert req.organization_id is not None
        assert req.knowledge_base_id is not None
        assert req.query == "hello"
        assert req.top_k == 10
        assert req.document_ids == ()

    def test_rejects_zero_top_k(self):
        with pytest.raises(ValueError):
            SearchRequest(organization_id=uuid4(), knowledge_base_id=uuid4(), query="x", top_k=0)

    def test_rejects_negative_top_k(self):
        with pytest.raises(ValueError):
            SearchRequest(organization_id=uuid4(), knowledge_base_id=uuid4(), query="x", top_k=-1)

    def test_rejects_missing_organization_id(self):
        with pytest.raises(ValueError):
            SearchRequest(organization_id=None, knowledge_base_id=uuid4(), query="x", top_k=10)  # type: ignore[arg-type]

    def test_rejects_missing_knowledge_base_id(self):
        with pytest.raises(ValueError):
            SearchRequest(organization_id=uuid4(), knowledge_base_id=None, query="x", top_k=10)  # type: ignore[arg-type]

    def test_document_ids_normalized_to_tuple(self):
        req = SearchRequest(
            organization_id=uuid4(), knowledge_base_id=uuid4(), query="x", top_k=10, document_ids=[uuid4()]
        )
        assert isinstance(req.document_ids, tuple)


class TestVectorSearchRequestValidation:
    def test_minimal_valid_request(self):
        req = VectorSearchRequest(
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            query_vector=[0.1, 0.2, 0.3],
            top_k=5,
        )
        assert req.query_vector == [0.1, 0.2, 0.3]
        assert req.top_k == 5

    def test_rejects_empty_query_vector(self):
        """空 query_vector 在 Milvus/ES 侧会变成非法请求,这里必须 fail-fast。"""
        with pytest.raises(ValueError):
            VectorSearchRequest(
                organization_id=uuid4(), knowledge_base_id=uuid4(), query_vector=[], top_k=5
            )

    def test_rejects_zero_top_k(self):
        with pytest.raises(ValueError):
            VectorSearchRequest(
                organization_id=uuid4(),
                knowledge_base_id=uuid4(),
                query_vector=[0.1],
                top_k=0,
            )

    def test_rejects_missing_org_id(self):
        with pytest.raises(ValueError):
            VectorSearchRequest(
                organization_id=None,  # type: ignore[arg-type]
                knowledge_base_id=uuid4(),
                query_vector=[0.1],
                top_k=5,
            )

    def test_rejects_missing_kb_id(self):
        with pytest.raises(ValueError):
            VectorSearchRequest(
                organization_id=uuid4(),
                knowledge_base_id=None,  # type: ignore[arg-type]
                query_vector=[0.1],
                top_k=5,
            )

    def test_query_vector_is_copied(self):
        original = [0.1, 0.2, 0.3]
        req = VectorSearchRequest(
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            query_vector=original,
            top_k=5,
        )
        original.append(0.99)
        assert req.query_vector == [0.1, 0.2, 0.3]

    def test_document_ids_normalized_to_tuple(self):
        req = VectorSearchRequest(
            organization_id=uuid4(),
            knowledge_base_id=uuid4(),
            query_vector=[0.1],
            top_k=5,
            document_ids=[uuid4(), uuid4()],
        )
        assert isinstance(req.document_ids, tuple)
        assert len(req.document_ids) == 2
