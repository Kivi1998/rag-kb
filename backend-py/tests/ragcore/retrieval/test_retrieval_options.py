"""RetrievalOptions 数据契约与权重工厂测试。

对应 Java 版 `ragcore/retrieval/RetrievalOptions.java`。
校验 candidate_limit / result_limit 关系、权重非负校验、precomputed_query_vector 透传
与 with_* 工厂方法不变量——HybridRetriever 的早退阈值、限流逻辑都直接依赖这套契约。
"""

from __future__ import annotations

import pytest

from app.ragcore.retrieval.retrieval_options import RetrievalOptions


class TestDefaults:
    def test_defaults_match_java_contract(self):
        """默认值 50 候选/8 结果/开启重排/等权重,跨语言对照测试依赖这套数字。"""
        opts = RetrievalOptions.defaults()
        assert opts.candidate_limit == 50
        assert opts.result_limit == 8
        assert opts.rerank is True
        assert opts.bm25_weight == 1.0
        assert opts.vector_weight == 1.0
        assert opts.precomputed_query_vector is None
        assert opts.document_ids == ()


class TestConstructionValidation:
    def test_rejects_zero_candidate_limit(self):
        with pytest.raises(ValueError):
            RetrievalOptions(candidate_limit=0, result_limit=0, rerank=False)

    def test_rejects_zero_result_limit(self):
        with pytest.raises(ValueError):
            RetrievalOptions(candidate_limit=10, result_limit=0, rerank=False)

    def test_rejects_result_greater_than_candidate(self):
        with pytest.raises(ValueError):
            RetrievalOptions(candidate_limit=5, result_limit=10, rerank=False)

    def test_rejects_negative_bm25_weight(self):
        with pytest.raises(ValueError):
            RetrievalOptions(candidate_limit=10, result_limit=5, rerank=False, bm25_weight=-0.1)

    def test_rejects_negative_vector_weight(self):
        with pytest.raises(ValueError):
            RetrievalOptions(candidate_limit=10, result_limit=5, rerank=False, vector_weight=-0.1)

    def test_result_equal_to_candidate_accepted(self):
        """result_limit == candidate_limit 在"全收"路径下合法,等于号不算违反。"""
        opts = RetrievalOptions(candidate_limit=10, result_limit=10, rerank=False)
        assert opts.candidate_limit == 10
        assert opts.result_limit == 10


class TestDocumentIdsNormalization:
    def test_document_ids_tuple_is_immutable(self):
        """frozen dataclass + 强制 tuple 化,保证 options 在多协程间共享不会被改。"""
        opts = RetrievalOptions(candidate_limit=10, result_limit=5, rerank=False, document_ids=[])
        assert opts.document_ids == ()
        assert isinstance(opts.document_ids, tuple)

    def test_document_ids_preserved(self):
        from uuid import uuid4

        ids = (uuid4(), uuid4())
        opts = RetrievalOptions(candidate_limit=10, result_limit=5, rerank=False, document_ids=ids)
        assert opts.document_ids == ids


class TestPrecomputedVectorNormalization:
    def test_precomputed_vector_is_copied(self):
        """传入 list 时内部 copy 一份,options 持有独立副本,避免被外部 mutate 影响。"""
        original = [0.1, 0.2, 0.3]
        opts = RetrievalOptions(
            candidate_limit=10, result_limit=5, rerank=False, precomputed_query_vector=original
        )
        assert opts.precomputed_query_vector == original
        original.append(0.4)
        assert opts.precomputed_query_vector == [0.1, 0.2, 0.3]

    def test_none_precomputed_vector_preserved(self):
        opts = RetrievalOptions(candidate_limit=10, result_limit=5, rerank=False)
        assert opts.precomputed_query_vector is None


class TestFactoryMethods:
    """with_* 工厂返回新对象,不改原 options,适合 HybridRetriever 链式拼装。"""

    def test_with_precomputed_query_vector_keeps_other_fields(self):
        opts = RetrievalOptions.defaults()
        vector = [0.1, 0.2, 0.3]
        new_opts = opts.with_precomputed_query_vector(vector)
        assert new_opts is not opts
        assert new_opts.precomputed_query_vector == vector
        assert new_opts.candidate_limit == opts.candidate_limit
        assert new_opts.result_limit == opts.result_limit
        assert new_opts.rerank == opts.rerank
        assert new_opts.bm25_weight == opts.bm25_weight
        assert new_opts.vector_weight == opts.vector_weight
        assert new_opts.document_ids == opts.document_ids

    def test_with_precomputed_query_vector_none_clears(self):
        opts = RetrievalOptions.defaults().with_precomputed_query_vector([0.1])
        new_opts = opts.with_precomputed_query_vector(None)
        assert new_opts.precomputed_query_vector is None

    def test_with_weights_rejects_negative(self):
        opts = RetrievalOptions.defaults()
        with pytest.raises(ValueError):
            opts.with_weights(-0.1, 1.0)
        with pytest.raises(ValueError):
            opts.with_weights(1.0, -0.1)

    def test_with_weights_keeps_other_fields(self):
        opts = RetrievalOptions.defaults()
        new_opts = opts.with_weights(0.7, 1.3)
        assert new_opts is not opts
        assert new_opts.bm25_weight == 0.7
        assert new_opts.vector_weight == 1.3
        assert new_opts.candidate_limit == opts.candidate_limit
        assert new_opts.result_limit == opts.result_limit
        assert new_opts.precomputed_query_vector is None
