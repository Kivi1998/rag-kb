"""VectorHit 端口契约与字段校验测试。

`VectorHit` 是 ES / Milvus 召回路径上的最小命中单元,只携带 chunk_id + 排名 + 分数。
任何在 VectorHit 上追加正文/元数据的"方便"做法都会绕过 ChunkHydrator 的租户过滤校验,
属于 toB 多租户隔离红线,本测试锁住字段集合与校验。
"""

from __future__ import annotations

import math

import pytest

from app.ragcore.retrieval.vector_hit import VectorHit


class TestConstruction:
    def test_minimal_fields_required(self):
        hit = VectorHit(chunk_id="c-1", rank=1, score=0.9)
        assert hit.chunk_id == "c-1"
        assert hit.rank == 1
        assert hit.score == 0.9

    def test_is_frozen(self):
        """VectorHit 是 frozen dataclass,命中数据不应被下游修改。"""
        hit = VectorHit(chunk_id="c-1", rank=1, score=0.9)
        with pytest.raises((AttributeError, Exception)):
            hit.chunk_id = "c-2"  # type: ignore[misc]


class TestFieldValidation:
    @pytest.mark.parametrize("bad_id", ["", "   ", "\n\t"])
    def test_blank_chunk_id_rejected(self, bad_id: str):
        with pytest.raises(ValueError):
            VectorHit(chunk_id=bad_id, rank=1, score=0.1)

    @pytest.mark.parametrize("bad_rank", [0, -1, -100])
    def test_non_positive_rank_rejected(self, bad_rank: int):
        with pytest.raises(ValueError):
            VectorHit(chunk_id="c-1", rank=bad_rank, score=0.1)

    @pytest.mark.parametrize(
        "bad_score", [math.inf, -math.inf, math.nan, float("nan")],
    )
    def test_non_finite_score_rejected(self, bad_score: float):
        with pytest.raises(ValueError):
            VectorHit(chunk_id="c-1", rank=1, score=bad_score)

    def test_zero_score_accepted(self):
        """rank 越靠后分数越接近 0;零分是合法值,不能误伤。"""
        hit = VectorHit(chunk_id="c-1", rank=1, score=0.0)
        assert hit.score == 0.0

    def test_negative_score_accepted(self):
        """余弦距离(L2)下分值可为负,VectorHit 不应假设分值范围。"""
        hit = VectorHit(chunk_id="c-1", rank=1, score=-0.1)
        assert hit.score == -0.1


class TestEquality:
    """frozen dataclass 自带 dataclass-generated __eq__,锁住"相同字段=相等"语义,
    便于 HybridRetriever 等调用方在 dict/set 中去重。"""

    def test_same_fields_are_equal(self):
        a = VectorHit(chunk_id="c", rank=2, score=0.5)
        b = VectorHit(chunk_id="c", rank=2, score=0.5)
        assert a == b

    def test_different_rank_not_equal(self):
        a = VectorHit(chunk_id="c", rank=1, score=0.5)
        b = VectorHit(chunk_id="c", rank=2, score=0.5)
        assert a != b
