"""RRF 融合算法与拒答阈值常量测试。

对照 Java 版 `ragcore/retrieval/RrfFusion.java`。
校验 DEFAULT_RANK_CONSTANT=60、MIN_RRF_SCORE=0.01 等校准常量,以及加权融合、空输入、
双路排名合并、rrf_score 为 None 时排序兜底等行为。
"""

from __future__ import annotations

import pytest

from app.ragcore.model import Chunk, RetrievedChunk
from app.ragcore.retrieval.rrf_fusion import (
    DEFAULT_RANK_CONSTANT,
    MIN_RRF_SCORE,
    fuse,
)


def _chunk(chunk_id: str) -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=None,
        knowledge_base_id=None,
        document_id=None,
        ordinal=0,
        content="",
    )


def _bm25(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=_chunk(chunk_id),
        bm25_rank=rank,
        vector_rank=None,
        rrf_score=None,
        rerank_score=None,
        final_score=None,
    )


def _vector(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=_chunk(chunk_id),
        bm25_rank=None,
        vector_rank=rank,
        rrf_score=None,
        rerank_score=None,
        final_score=None,
    )


class TestCalibrationConstants:
    """RRF 校准常量:rank constant 60 与 MIN_RRF_SCORE 0.01 均在 150 题评估集上
    校准过,不能随意调整,否则已发布的拒答/融合结果会失真。"""

    def test_default_rank_constant_is_60(self):
        assert DEFAULT_RANK_CONSTANT == 60

    def test_min_rrf_score_is_0_01(self):
        assert MIN_RRF_SCORE == 0.01


class TestEmptyAndSingleSidedInputs:
    """空列表/单边输入不应抛异常,RRF 是减法式融合,空路天然是 0 分。"""

    def test_both_empty_returns_empty_list(self):
        assert fuse([], []) == []

    def test_only_bm25_keeps_bm25_ordering(self):
        result = fuse([_bm25("a", 1), _bm25("b", 2)], [])
        assert [r.chunk.id for r in result] == ["a", "b"]
        # 单路命中时只有 bm25_rank,vector_rank 为 None,rrf_score 仅含 bm25 项
        assert all(r.bm25_rank is not None and r.vector_rank is None for r in result)

    def test_only_vector_keeps_vector_ordering(self):
        result = fuse([], [_vector("a", 1), _vector("b", 2)])
        assert [r.chunk.id for r in result] == ["a", "b"]
        assert all(r.vector_rank is not None and r.bm25_rank is None for r in result)


class TestNegativeWeightRejected:
    def test_negative_bm25_weight_raises(self):
        with pytest.raises(ValueError):
            fuse([_bm25("a", 1)], [_vector("b", 1)], bm25_weight=-0.1, vector_weight=1.0)

    def test_negative_vector_weight_raises(self):
        with pytest.raises(ValueError):
            fuse([_bm25("a", 1)], [_vector("b", 1)], bm25_weight=1.0, vector_weight=-0.1)


class TestFusedScoring:
    """同一 chunk 在两路都命中时,rrf_score 应该是 bm25_weight*1/(60+r_b)+vector_weight*1/(60+r_v)。
    该行为是 RRF 跨语料量纲归一的关键,绝不能"按 bm25 分或向量分原值相加"。"""

    def test_chunk_in_both_lanes_sums_both_rrf_terms(self):
        # a 在 bm25 rank=1 + vector rank=1 时,等权重 rrf_score = 1/61 + 1/61
        result = fuse([_bm25("a", 1)], [_vector("a", 1)])
        assert len(result) == 1
        expected = 1.0 / (DEFAULT_RANK_CONSTANT + 1) + 1.0 / (DEFAULT_RANK_CONSTANT + 1)
        assert result[0].rrf_score == pytest.approx(expected)

    def test_chunk_only_in_bm25_has_vector_term_zero(self):
        result = fuse([_bm25("only_bm25", 1)], [])
        assert len(result) == 1
        assert result[0].rrf_score == pytest.approx(1.0 / (DEFAULT_RANK_CONSTANT + 1))
        assert result[0].vector_rank is None

    def test_chunk_only_in_vector_has_bm25_term_zero(self):
        result = fuse([], [_vector("only_vec", 1)])
        assert len(result) == 1
        assert result[0].rrf_score == pytest.approx(1.0 / (DEFAULT_RANK_CONSTANT + 1))
        assert result[0].bm25_rank is None

    def test_final_score_mirrors_rrf_score(self):
        """HybridRetriever 的拒答早退用的是 unweighted_top,语义上 final_score 与 rrf_score
        在融合阶段相等;weighting 是后续 RRF 排序的稳定依据,不是给最终用户看的。"""
        result = fuse([_bm25("a", 1)], [_vector("a", 2)])
        assert result[0].final_score == result[0].rrf_score

    def test_weighted_score_applies_to_both_terms(self):
        # 权重 2.0/0.5: bm25 项 x2, vector 项 x0.5
        result = fuse([_bm25("a", 1)], [_vector("a", 1)], bm25_weight=2.0, vector_weight=0.5)
        expected = 2.0 / (DEFAULT_RANK_CONSTANT + 1) + 0.5 / (DEFAULT_RANK_CONSTANT + 1)
        assert result[0].rrf_score == pytest.approx(expected)


class TestFusedRanking:
    """融合后按 rrf_score 降序排列;同分时相对顺序应稳定(由 dict 迭代序保证)。"""

    def test_two_lane_dual_hit_outranks_single_lane_top(self):
        bm25 = [_bm25("dual", 1), _bm25("only_bm25", 2)]
        vector = [_vector("dual", 1), _vector("only_vec", 1)]
        result = fuse(bm25, vector)
        assert result[0].chunk.id == "dual"
        # dual 两路都是 rank 1,只有单路的只会有一路 1/(60+1),分数必然落后
        dual_score = 2 * (1.0 / (DEFAULT_RANK_CONSTANT + 1))
        assert result[0].rrf_score == pytest.approx(dual_score)

    def test_preserves_bm25_rank_when_only_bm25_appears(self):
        result = fuse([_bm25("a", 5)], [])
        assert result[0].bm25_rank == 5
        # vector_rank 保持 None,表示该 chunk 在另一路没有命中
        assert result[0].vector_rank is None

    def test_preserves_vector_rank_when_only_vector_appears(self):
        result = fuse([], [_vector("a", 7)])
        assert result[0].vector_rank == 7
        assert result[0].bm25_rank is None
