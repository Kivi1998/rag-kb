"""`HybridRetriever` 端到端编排 + 多租户隔离 + 拒答门槛测试。

对应 Java 版 `ragcore/retrieval/HybridRetriever.java`,本次迁移里最关键的一道
纵深防御组件。重点覆盖:
- **多租户三层防御**:服务端注入边界 + ChunkHydrator 二次校验 + 越权 chunk 丢弃
- **拒答早退**:MIN_RRF_SCORE(0.01) 决定无结果/单路 0 分时是否走 REFUSAL_EMPTY
- **Embedding 失败降级**:ModelClientException → BM25-only,不抛给上游
- **Rerank 失败降级**:Rerank 异常 → 退回 RRF 顺序,rerank_fallback=True
- **MIN_RERANK_SCORE 门槛**:0.06(从 rerank.thresholds import,不是本地常量)
- **unweighted 早退**:即使查询意图调低某路权重,top rrf_score 必须按等权重算
"""

from __future__ import annotations

from typing import Iterable
from uuid import UUID, uuid4

import pytest

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.model import (
    Chunk,
    EmbeddingResult,
    ModelClientException,
    RetrievedChunk,
)
from app.ragcore.retrieval.chunk_hydrator import ChunkHydrator
from app.ragcore.retrieval.hybrid_retriever import (
    HybridRetriever,
    REFUSAL_BLANK_QUERY,
    REFUSAL_EMPTY,
    REFUSAL_RERANK_BELOW,
)
from app.ragcore.retrieval.lexical_candidate_source import LexicalCandidateSource
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest
from app.ragcore.retrieval.rrf_fusion import MIN_RRF_SCORE
from app.ragcore.rerank.client import RerankerClient
from app.ragcore.rerank.thresholds import MIN_RERANK_SCORE


# ---- Test doubles --------------------------------------------------------


def _make_chunk(
    chunk_id: str = "c-1",
    org_id: UUID | None = None,
    kb_id: UUID | None = None,
    document_id: UUID | None = None,
    content: str = "正文",
) -> Chunk:
    return Chunk(
        id=chunk_id,
        organization_id=org_id or uuid4(),
        knowledge_base_id=kb_id or uuid4(),
        document_id=document_id or uuid4(),
        ordinal=0,
        content=content,
    )


def _retrieved(
    chunk: Chunk, *, bm25_rank: int | None = None, vector_rank: int | None = None
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=chunk,
        bm25_rank=bm25_rank,
        vector_rank=vector_rank,
        rrf_score=None,
        rerank_score=None,
        final_score=None,
    )


class _StubLexicalSource(LexicalCandidateSource):
    """词法候选源 stub,直接吐出预置列表,供 RRF 融合测试。"""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.last_request = None
        self.call_count = 0

    async def search(self, request) -> list[RetrievedChunk]:
        self.call_count += 1
        self.last_request = request
        return self.chunks


class _StubVectorSource(VectorCandidateSource):
    """向量候选源 stub。"""

    def __init__(self, hits: list[VectorHit]) -> None:
        self.hits = hits
        self.last_request: VectorSearchRequest | None = None
        self.call_count = 0

    async def search(self, request: VectorSearchRequest) -> list[VectorHit]:
        self.call_count += 1
        self.last_request = request
        return self.hits


class _StubChunkHydrator(ChunkHydrator):
    """按 chunk_id 找 Chunk,可注入"恶意 ES 行为"(返回越权 chunk),
    验证 HybridRetriever 的回程二次校验。"""

    def __init__(self, chunks_by_id: dict[str, Chunk]) -> None:
        self._chunks_by_id = chunks_by_id
        self.last_org: UUID | None = None
        self.last_kb: UUID | None = None
        self.call_count = 0

    async def find_by_chunk_ids(
        self, organization_id: UUID, knowledge_base_id: UUID, chunk_ids: list[str]
    ) -> list[Chunk]:
        self.call_count += 1
        self.last_org = organization_id
        self.last_kb = knowledge_base_id
        return [self._chunks_by_id[cid] for cid in chunk_ids if cid in self._chunks_by_id]


class _StubEmbeddingClient(EmbeddingClient):
    """向量化 stub;可控触发 ModelClientException/ValueError 验证降级路径。"""

    def __init__(self, vectors: list[list[float]] | None = None, raise_exc: Exception | None = None) -> None:
        self.vectors = vectors or [[0.1, 0.2, 0.3]]
        self.raise_exc = raise_exc
        self.call_count = 0
        self.last_texts: list[str] | None = None

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        self.call_count += 1
        self.last_texts = list(texts)
        if self.raise_exc is not None:
            raise self.raise_exc
        return EmbeddingResult(model_version="stub-v1", vectors=tuple(tuple(v) for v in self.vectors))


class _StubReranker(RerankerClient):
    """重排 stub;可控返回顺序/分数/抛异常,验证降级路径与门槛。"""

    def __init__(
        self,
        ordered: list[RetrievedChunk] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.ordered = ordered
        self.raise_exc = raise_exc
        self.call_count = 0

    async def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        self.call_count += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.ordered is not None:
            return self.ordered[:top_k]
        return candidates[:top_k]


def _build_hybrid(
    lexical: LexicalCandidateSource,
    vector: VectorCandidateSource,
    hydrator: ChunkHydrator,
    embedding: EmbeddingClient,
    reranker: RerankerClient | None = None,
) -> HybridRetriever:
    return HybridRetriever(
        lexical_source=lexical,
        vector_source=vector,
        chunk_hydrator=hydrator,
        embedding_client=embedding,
        reranker_provider=reranker,
    )


# ---- Test cases ----------------------------------------------------------


class TestMinRerankScoreIsImportedNotLocal:
    """MIN_RERANK_SCORE 必须从 rerank.thresholds import,值 0.06(150 题评估集校准)。"""

    def test_min_rerank_score_value(self):
        assert MIN_RERANK_SCORE == 0.06

    def test_min_rrf_score_value(self):
        assert MIN_RRF_SCORE == 0.01


class TestRefusalInputs:
    @pytest.mark.asyncio
    async def test_blank_query_refused(self):
        lexical = _StubLexicalSource([])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({})
        embedding = _StubEmbeddingClient()
        retriever = _build_hybrid(lexical, vector, hydrator, embedding)

        result = await retriever.retrieve_with_decision(uuid4(), uuid4(), "", RetrievalOptions.defaults())
        assert result.refused
        assert result.refusal_reason == REFUSAL_BLANK_QUERY
        assert result.chunks == []
        # 词法源在 query 为空时早退;embedding/向量源根本不会被调用
        assert lexical.call_count == 0
        assert vector.call_count == 0
        assert embedding.call_count == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_query_refused(self):
        lexical = _StubLexicalSource([])
        retriever = _build_hybrid(
            lexical, _StubVectorSource([]), _StubChunkHydrator({}), _StubEmbeddingClient()
        )
        result = await retriever.retrieve_with_decision(uuid4(), uuid4(), "  \n  ", RetrievalOptions.defaults())
        assert result.refused
        assert result.refusal_reason == REFUSAL_BLANK_QUERY

    @pytest.mark.asyncio
    async def test_missing_org_id_rejected_by_value_error(self):
        retriever = _build_hybrid(
            _StubLexicalSource([]), _StubVectorSource([]), _StubChunkHydrator({}), _StubEmbeddingClient()
        )
        with pytest.raises(ValueError):
            await retriever.retrieve_with_decision(None, uuid4(), "q", RetrievalOptions.defaults())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_kb_id_rejected_by_value_error(self):
        retriever = _build_hybrid(
            _StubLexicalSource([]), _StubVectorSource([]), _StubChunkHydrator({}), _StubEmbeddingClient()
        )
        with pytest.raises(ValueError):
            await retriever.retrieve_with_decision(uuid4(), None, "q", RetrievalOptions.defaults())  # type: ignore[arg-type]


class TestTenantBoundaryInjection:
    """服务端注入的 org_id/kb_id 必须原样传给 Lexical / Vector / Hydrator,
    这是最基础的多租户契约——三方源都不允许从 query/embedding 中推导租户。"""

    @pytest.mark.asyncio
    async def test_lexical_source_receives_injected_org_and_kb(self):
        org = uuid4()
        kb = uuid4()
        lexical = _StubLexicalSource([])
        retriever = _build_hybrid(
            lexical, _StubVectorSource([]), _StubChunkHydrator({}), _StubEmbeddingClient()
        )
        await retriever.retrieve_with_decision(org, kb, "query", RetrievalOptions.defaults())
        assert lexical.last_request.organization_id == org
        assert lexical.last_request.knowledge_base_id == kb

    @pytest.mark.asyncio
    async def test_vector_source_receives_injected_org_and_kb(self):
        org = uuid4()
        kb = uuid4()
        lexical = _StubLexicalSource([])
        vector = _StubVectorSource([])
        retriever = _build_hybrid(
            lexical, vector, _StubChunkHydrator({}), _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        )
        await retriever.retrieve_with_decision(org, kb, "query", RetrievalOptions.defaults())
        assert vector.last_request.organization_id == org
        assert vector.last_request.knowledge_base_id == kb

    @pytest.mark.asyncio
    async def test_hydrator_receives_injected_org_and_kb(self):
        org = uuid4()
        kb = uuid4()
        chunks = [_make_chunk("c-1", org_id=org, kb_id=kb)]
        lexical = _StubLexicalSource([_retrieved(chunks[0], bm25_rank=1)])
        vector = _StubVectorSource([VectorHit(chunk_id="c-1", rank=1, score=0.9)])
        hydrator = _StubChunkHydrator({"c-1": chunks[0]})
        retriever = _build_hybrid(
            lexical, vector, hydrator, _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        )
        await retriever.retrieve_with_decision(org, kb, "query", RetrievalOptions.defaults())
        assert hydrator.last_org == org
        assert hydrator.last_kb == kb


class TestCrossTenantChunkRejected:
    """**核心回归测试** — toB 多租户隔离红线。"""

    @pytest.mark.asyncio
    async def test_chunks_with_wrong_org_or_kb_are_dropped_by_secondary_check(self):
        """向量源只返回 chunk_id,正文靠 Hydrator 补齐;若 Hydrator 返回了越权 chunk,
        HybridRetriever 在回程循环里比对 chunk.organization_id / knowledge_base_id,
        任何不一致直接丢弃。"""
        request_org = uuid4()
        request_kb = uuid4()
        foreign_org = uuid4()
        foreign_kb = uuid4()

        own_chunk = _make_chunk("own", org_id=request_org, kb_id=request_kb)
        foreign_org_chunk = _make_chunk("foreign-org", org_id=foreign_org, kb_id=request_kb)
        foreign_kb_chunk = _make_chunk("foreign-kb", org_id=request_org, kb_id=foreign_kb)

        # 词法源只返回自己 org/kb 的(第二道防御)
        lexical = _StubLexicalSource([_retrieved(own_chunk, bm25_rank=1)])
        # 向量源假设 ES 错误地把越权 chunk 也吐回来了
        vector = _StubVectorSource([
            VectorHit("own", 1, 0.9),
            VectorHit("foreign-org", 2, 0.85),
            VectorHit("foreign-kb", 3, 0.8),
        ])
        # Hydrator 也跟着越权返回(模拟 ES kNN filter 漏掉)
        hydrator = _StubChunkHydrator({
            "own": own_chunk,
            "foreign-org": foreign_org_chunk,
            "foreign-kb": foreign_kb_chunk,
        })

        retriever = _build_hybrid(
            lexical, vector, hydrator, _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        )
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )

        # 越权 chunk 必须被丢弃
        chunk_ids = [c.chunk.id for c in result.chunks]
        assert "own" in chunk_ids
        assert "foreign-org" not in chunk_ids, "跨组织 chunk 必须被丢弃"
        assert "foreign-kb" not in chunk_ids, "跨知识库 chunk 必须被丢弃"


class TestNoResultsRefused:
    @pytest.mark.asyncio
    async def test_no_chunks_anywhere_refused_with_empty_reason(self):
        retriever = _build_hybrid(
            _StubLexicalSource([]),
            _StubVectorSource([]),
            _StubChunkHydrator({}),
            _StubEmbeddingClient([[0.1, 0.2, 0.3]]),
        )
        result = await retriever.retrieve_with_decision(
            uuid4(), uuid4(), "query", RetrievalOptions.defaults()
        )
        assert result.refused
        assert result.refusal_reason == REFUSAL_EMPTY
        assert result.diagnostics.fused_candidate_count == 0
        assert result.diagnostics.bm25_candidate_count == 0
        assert result.diagnostics.vector_candidate_count == 0

    @pytest.mark.asyncio
    async def test_only_single_low_score_chunk_still_refused(self):
        """单路命中但 RRF 分数低于 MIN_RRF_SCORE(0.01)也要走 REFUSAL_EMPTY,
        这是把'主题不相关'挡在外的兜底门槛。"""
        request_org = uuid4()
        request_kb = uuid4()
        # bm25 rank 极高 → rrf_score = 1/(60+200) = 0.0038 < 0.01
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=200)])
        retriever = _build_hybrid(
            lexical, _StubVectorSource([]), _StubChunkHydrator({"c-1": chunk}),
            _StubEmbeddingClient([[0.1, 0.2, 0.3]]),
        )
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        assert result.refused
        assert result.refusal_reason == REFUSAL_EMPTY


class TestEmbeddingFailureFallback:
    """Embedding 不可用时降级为 BM25-only,绝不抛给上游;同时 diagnostics 标记
    embedding_fallback=True,便于切流期可观测性。"""

    @pytest.mark.asyncio
    async def test_model_client_exception_falls_back_to_bm25_only(self):
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient(raise_exc=ModelClientException("embedding service down"))
        retriever = _build_hybrid(lexical, vector, hydrator, embedding)

        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        # 没抛异常 + BM25 命中
        assert result.refused is False
        assert [c.chunk.id for c in result.chunks] == ["c-1"]
        assert result.diagnostics.embedding_fallback is True
        assert result.diagnostics.vector_candidate_count == 0
        # 向量源没被调用
        assert vector.call_count == 0

    @pytest.mark.asyncio
    async def test_embedding_value_error_also_falls_back(self):
        """ValueError(查询向量维度校验失败)同属降级路径,与 Java 版语义一致。"""
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient(raise_exc=ValueError("dim mismatch"))
        retriever = _build_hybrid(lexical, _StubVectorSource([]), hydrator, embedding)

        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        assert result.refused is False
        assert result.diagnostics.embedding_fallback is True

    @pytest.mark.asyncio
    async def test_precomputed_query_vector_skips_embedding_call(self):
        """查询意图分类器若预先算好向量,可由 options.precomputed_query_vector 透传,
        避免对同一句 resolved_question 重复调用 Embedding。"""
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        vector = _StubVectorSource([VectorHit("c-1", 1, 0.9)])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient(raise_exc=AssertionError("should not be called"))
        retriever = _build_hybrid(lexical, vector, hydrator, embedding)

        options = RetrievalOptions.defaults().with_precomputed_query_vector([0.1, 0.2, 0.3])
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", options
        )
        assert result.refused is False
        assert embedding.call_count == 0
        # 向量源拿到了透传的向量
        assert vector.last_request.query_vector == [0.1, 0.2, 0.3]


class TestRerankThresholdAndFallback:
    """Rerank 成功执行时才应用 MIN_RERANK_SCORE 门槛;Rerank 异常时退回 RRF 顺序。"""

    @pytest.mark.asyncio
    async def test_rerank_failure_falls_back_to_rrf_order(self):
        request_org = uuid4()
        request_kb = uuid4()
        chunk_a = _make_chunk("a", org_id=request_org, kb_id=request_kb)
        chunk_b = _make_chunk("b", org_id=request_org, kb_id=request_kb)
        # BM25 把 b 排前
        lexical = _StubLexicalSource([
            _retrieved(chunk_b, bm25_rank=1),
            _retrieved(chunk_a, bm25_rank=2),
        ])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({"a": chunk_a, "b": chunk_b})
        embedding = _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        # Rerank 抛异常 → 退回 BM25 顺序 b 在前
        reranker = _StubReranker(raise_exc=RuntimeError("rerank service down"))
        retriever = _build_hybrid(lexical, vector, hydrator, embedding, reranker)

        options = RetrievalOptions.defaults()
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", options
        )
        # 不应抛异常,且回退到 RRF 顺序
        assert result.refused is False
        assert [c.chunk.id for c in result.chunks] == ["b", "a"]
        assert result.diagnostics.rerank_fallback is True

    @pytest.mark.asyncio
    async def test_rerank_all_below_threshold_refused(self):
        """Rerank 成功但所有候选 final_score 都低于 MIN_RERANK_SCORE → REFUSAL_RERANK_BELOW。"""
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient([[0.1, 0.2, 0.3]])

        # Rerank 把 chunk 放在结果里,但 final_score 低于 MIN_RERANK_SCORE
        low_chunk = RetrievedChunk(
            chunk=chunk,
            bm25_rank=1,
            vector_rank=None,
            rrf_score=None,
            rerank_score=0.01,
            final_score=MIN_RERANK_SCORE - 0.01,
        )
        reranker = _StubReranker(ordered=[low_chunk])
        retriever = _build_hybrid(lexical, vector, hydrator, embedding, reranker)

        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        assert result.refused
        assert result.refusal_reason == REFUSAL_RERANK_BELOW

    @pytest.mark.asyncio
    async def test_rerank_above_threshold_passes(self):
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient([[0.1, 0.2, 0.3]])

        high_chunk = RetrievedChunk(
            chunk=chunk,
            bm25_rank=1,
            vector_rank=None,
            rrf_score=None,
            rerank_score=0.5,
            final_score=MIN_RERANK_SCORE + 0.5,
        )
        reranker = _StubReranker(ordered=[high_chunk])
        retriever = _build_hybrid(lexical, vector, hydrator, embedding, reranker)

        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        assert result.refused is False
        assert [c.chunk.id for c in result.chunks] == ["c-1"]

    @pytest.mark.asyncio
    async def test_rerank_provider_returns_none_skips_rerank(self):
        """reranker_provider.get_if_available() 返回 None 时不重排,直接走 RRF 顺序。"""
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=1)])
        vector = _StubVectorSource([])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        embedding = _StubEmbeddingClient([[0.1, 0.2, 0.3]])

        retriever = HybridRetriever(
            lexical_source=lexical,
            vector_source=vector,
            chunk_hydrator=hydrator,
            embedding_client=embedding,
            reranker_provider=None,
        )
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", RetrievalOptions.defaults()
        )
        assert result.refused is False
        assert result.diagnostics.rerank_fallback is False


class TestUnweightedEarlyExit:
    """查询意图分类可能调低某路权重(语义型 bm25Weight=0.7)。但**早退检查**用
    `unweighted_top` 决定,不能直接看 fused[0].rrf_score,否则会误伤单路命中。
    """

    @pytest.mark.asyncio
    async def test_bm25_only_hit_not_refused_by_low_weighted_top(self):
        """向量源空,BM25 命中 rank=11 → 等权重 rrf=1/71≈0.014 > 0.01;
        加权 0.7 后 weighted=0.0098 < 0.01。如果用 weighted 早退会拒答。"""
        request_org = uuid4()
        request_kb = uuid4()
        chunk = _make_chunk("c-1", org_id=request_org, kb_id=request_kb)
        lexical = _StubLexicalSource([_retrieved(chunk, bm25_rank=11)])
        hydrator = _StubChunkHydrator({"c-1": chunk})
        retriever = _build_hybrid(
            lexical, _StubVectorSource([]), hydrator, _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        )

        # bm25_weight=0.7, vector_weight=1.3(模拟语义型)
        options = RetrievalOptions.defaults().with_weights(0.7, 1.3)
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", options
        )
        # 等权重 rrf=1/71 仍 > MIN_RRF_SCORE,不应该被拒答
        assert result.refused is False
        assert [c.chunk.id for c in result.chunks] == ["c-1"]


class TestCandidateLimit:
    @pytest.mark.asyncio
    async def test_result_limit_truncates_rrf_output(self):
        request_org = uuid4()
        request_kb = uuid4()
        chunks = [
            _make_chunk(f"c-{i}", org_id=request_org, kb_id=request_kb)
            for i in range(1, 6)
        ]
        lexical = _StubLexicalSource([_retrieved(c, bm25_rank=i) for i, c in enumerate(chunks, start=1)])
        hydrator = _StubChunkHydrator({c.id: c for c in chunks})
        retriever = _build_hybrid(
            lexical, _StubVectorSource([]), hydrator, _StubEmbeddingClient([[0.1, 0.2, 0.3]])
        )

        options = RetrievalOptions(candidate_limit=10, result_limit=2, rerank=False)
        result = await retriever.retrieve_with_decision(
            request_org, request_kb, "query", options
        )
        assert len(result.chunks) == 2
        # 截断是按 RRF 分数,BM25 rank 越小越靠前
        assert [c.chunk.id for c in result.chunks] == ["c-1", "c-2"]
