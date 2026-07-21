"""服务端注入租户边界的混合检索、可选重排与拒答决策。

对应 Java 版 `ragcore/retrieval/HybridRetriever.java`。
关键设计:所有租户边界由调用方注入,HybridRetriever 不接受任何"再从用户上下文里
读"的代码路径;拒答门槛 `MIN_RERANK_SCORE = 0.06` 只在重排成功执行时生效
(降级回 RRF 时不应用,避免误伤只有单路命中的合法问题)。
"""

from __future__ import annotations

import logging
from typing import Iterable, Protocol
from uuid import UUID

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.model import Chunk, EmbeddingResult, ModelClientException, RetrievedChunk
from app.ragcore.rerank.client import RerankerClient
from app.ragcore.rerank.thresholds import MIN_RERANK_SCORE
from app.ragcore.retrieval.chunk_hydrator import ChunkHydrator
from app.ragcore.retrieval.lexical_candidate_source import LexicalCandidateSource
from app.ragcore.retrieval.retrieval_diagnostics import RetrievalDiagnostics
from app.ragcore.retrieval.retrieval_options import RetrievalOptions
from app.ragcore.retrieval.retrieval_result import RetrievalResult
from app.ragcore.retrieval.retriever import Retriever
from app.ragcore.retrieval.rrf_fusion import MIN_RRF_SCORE, fuse
from app.ragcore.retrieval.vector_candidate_source import VectorCandidateSource
from app.ragcore.retrieval.vector_hit import VectorHit
from app.ragcore.retrieval.vector_retrieval_metrics import VectorRetrievalMetrics
from app.ragcore.retrieval.vector_search_request import VectorSearchRequest
from app.ragcore.index.search_request import SearchRequest

logger = logging.getLogger(__name__)

# MIN_RERANK_SCORE 定义在 app.ragcore.rerank.thresholds(评估集校准值 0.06,
# 校准依据见该模块 docstring),这里只 import 复用,不重新定义字面量,避免两处
# 各写一份容易漂移。

REFUSAL_EMPTY: str = "未在当前知识库中检索到足够依据"
REFUSAL_RERANK_BELOW: str = "重排后最高相关性低于阈值,未在当前知识库中检索到足够依据"
REFUSAL_BLANK_QUERY: str = "问题不能为空"


class _RerankerProvider(Protocol):
    """对应 Java 的 `ObjectProvider<RerankerClient>`——可空、可懒加载。"""

    def get_if_available(self) -> RerankerClient | None: ...


class _OptionalRerankerProvider:
    """最简单的 RerankerProvider 适配器:固定一个客户端或 None。"""

    def __init__(self, client: RerankerClient | None) -> None:
        self._client = client

    def get_if_available(self) -> RerankerClient | None:
        return self._client


def _chunks_to_ranks(chunks: Iterable[RetrievedChunk]) -> dict[str, int]:
    """把已排序的 RetrievedChunk 列表转成 chunk_id -> bm25 排名映射(从 1 开始)。"""
    return {chunk.chunk.id: idx + 1 for idx, chunk in enumerate(chunks)}


def _hits_to_ranks(hits: Iterable[VectorHit]) -> dict[str, int]:
    return {hit.chunk_id: hit.rank for hit in hits}


class HybridRetriever(Retriever):
    """BM25 + 向量双路召回 + RRF 融合 + 可选 Rerank + 拒答决策。

    参数:
        lexical_source: 词法候选源,内部强制注入 org/kb 过滤。
        vector_source: 向量候选源,只返回 chunk_id/rank/score,正文走 hydrator 补齐。
        chunk_hydrator: 用受租户保护的 ES 查询把 chunk_id 还原为 Chunk(纵深防御第三道)。
        embedding_client: 生成 query embedding;`options.precomputed_query_vector` 非空
            时跳过,避免对同一文本重复调用 Embedding。
        reranker_provider: Reranker 懒加载句柄;返回 None 时不重排,或 rerank 调用
            抛异常时降级使用 RRF 顺序结果(绝不抛给上游)。
        vector_metrics: 切流期可观测性指标;无 Prometheus 环境时可传 None。
    """

    def __init__(
        self,
        lexical_source: LexicalCandidateSource,
        vector_source: VectorCandidateSource,
        chunk_hydrator: ChunkHydrator,
        embedding_client: EmbeddingClient,
        reranker_provider: _RerankerProvider | RerankerClient | None = None,
        vector_metrics: VectorRetrievalMetrics | None = None,
    ) -> None:
        self._lexical = lexical_source
        self._vector = vector_source
        self._hydrator = chunk_hydrator
        self._embedding = embedding_client
        self._reranker_provider = self._coerce_reranker_provider(reranker_provider)
        self._metrics = vector_metrics

    @staticmethod
    def _coerce_reranker_provider(
        provider: _RerankerProvider | RerankerClient | None,
    ) -> _RerankerProvider:
        if provider is None or isinstance(provider, RerankerClient):
            return _OptionalRerankerProvider(provider if isinstance(provider, RerankerClient) else None)
        return provider

    # ---- Retriever --------------------------------------------------------

    async def retrieve(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
        query: str,
        options: RetrievalOptions,
    ) -> list[RetrievedChunk]:
        return (await self.retrieve_with_decision(organization_id, knowledge_base_id, query, options)).chunks

    async def retrieve_with_decision(
        self,
        organization_id: UUID,
        knowledge_base_id: UUID,
        query: str,
        options: RetrievalOptions,
    ) -> RetrievalResult:
        if not query or not query.strip():
            return RetrievalResult.refuse(REFUSAL_BLANK_QUERY)

        if organization_id is None or knowledge_base_id is None:
            raise ValueError("HybridRetriever 必须由服务端注入 org_id 与 kb_id,不允许从 query 中推断")

        bm25_request = SearchRequest(
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            query=query,
            top_k=options.candidate_limit,
            document_ids=options.document_ids,
        )
        bm25 = await self._lexical.search(bm25_request)

        vector: list[RetrievedChunk] = []
        embedding_fallback = False
        try:
            query_vector = options.precomputed_query_vector
            if query_vector is None:
                embedding = await self._embedding.embed([query])
                if not isinstance(embedding, EmbeddingResult) or len(embedding.vectors) != 1:
                    raise ModelClientException("查询 Embedding 返回数量不正确")
                query_vector = embedding.vectors[0]
            vector_request = VectorSearchRequest(
                organization_id=organization_id,
                knowledge_base_id=knowledge_base_id,
                query_vector=list(query_vector),
                top_k=options.candidate_limit,
                document_ids=options.document_ids,
            )
            vector = await self._search_vector(vector_request)
        except ModelClientException as ex:
            logger.warning("Embedding 不可用,降级为 BM25 结果: %s", ex)
            vector = []
            embedding_fallback = True
        except ValueError as ex:
            # query_vector 维度校验失败属于 embedding 客户端契约问题,
            # 同样降级为 BM25-only,不要把 5xx 抛给上游。
            logger.warning("查询向量构造失败,降级为 BM25 结果: %s", ex)
            vector = []
            embedding_fallback = True

        fused = fuse(bm25, vector, options.bm25_weight, options.vector_weight)
        diagnostics = RetrievalDiagnostics(
            bm25_candidate_count=len(bm25),
            vector_candidate_count=len(vector),
            fused_candidate_count=len(fused),
            embedding_fallback=embedding_fallback,
            rerank_fallback=False,
        )

        # 早退检查:始终按等权重(1.0/1.0)计算 top rrf_score。查询意图分类会调低某路
        # 权重(如语义型 bm25Weight=0.7),若直接对加权后的 fused.get(0) 判断,会把
        # 加权前本该过阈值的单路命中(如 BM25-only 排名 11 的候选)误判拒答。
        unweighted_top = self._unweighted_top_score(bm25, vector)
        if not fused or unweighted_top < MIN_RRF_SCORE:
            return RetrievalResult.refuse(REFUSAL_EMPTY, diagnostics)

        selected = fused[: options.result_limit]
        reranker = self._reranker_provider.get_if_available()
        rerank_fallback = False
        reranked = False
        if options.rerank and reranker is not None:
            try:
                selected = await reranker.rerank(query, fused, options.result_limit)
                reranked = True
            except Exception as ex:  # noqa: BLE001 - Rerank 失败时降级,绝不上抛
                logger.warning("Rerank 不可用,回退 RRF 结果: %s", ex)
                rerank_fallback = True

        final_diagnostics = RetrievalDiagnostics(
            bm25_candidate_count=len(bm25),
            vector_candidate_count=len(vector),
            fused_candidate_count=len(fused),
            embedding_fallback=embedding_fallback,
            rerank_fallback=rerank_fallback,
        )
        if not selected:
            return RetrievalResult.refuse(REFUSAL_EMPTY, final_diagnostics)

        if reranked:
            # 排名靠后的低可信片段会和高分片段一起进入 prompt 与引用,会干扰多段融合。
            # 同一阈值应用到每个候选;top-1 已不达标时,过滤后必为空,走同一条拒答分支。
            threshold_ok = [
                c
                for c in selected
                if c.final_score is None or c.final_score >= MIN_RERANK_SCORE
            ]
            if not threshold_ok:
                return RetrievalResult.refuse(REFUSAL_RERANK_BELOW, final_diagnostics)
            selected = threshold_ok

        return RetrievalResult.of(selected, final_diagnostics)

    # ---- 内部实现 --------------------------------------------------------

    async def _search_vector(self, request: VectorSearchRequest) -> list[RetrievedChunk]:
        hits = await self._vector.search(request)
        if not hits:
            return []

        hit_ids = [hit.chunk_id for hit in hits]
        chunks = await self._hydrator.find_by_chunk_ids(
            request.organization_id,
            request.knowledge_base_id,
            hit_ids,
        )
        # 第三道纵深防御:即便 ES 查询已带 org/kb 过滤,回程结果也再校验一次。
        safe: dict[str, Chunk] = {}
        for chunk in chunks:
            if (
                chunk.organization_id == request.organization_id
                and chunk.knowledge_base_id == request.knowledge_base_id
                and chunk.id in hit_ids
            ):
                safe[chunk.id] = chunk

        if self._metrics is not None:
            self._metrics.record_orphans(len(hits) - len(safe))

        result: list[RetrievedChunk] = []
        for hit in hits:
            hydrated = safe.get(hit.chunk_id)
            if hydrated is None:
                continue
            assert hydrated.organization_id == request.organization_id
            assert hydrated.knowledge_base_id == request.knowledge_base_id
            result.append(
                RetrievedChunk(
                    chunk=hydrated,
                    bm25_rank=None,
                    vector_rank=hit.rank,
                    rrf_score=None,
                    rerank_score=None,
                    final_score=hit.score,
                )
            )
        return result

    @staticmethod
    def _unweighted_top_score(
        bm25: list[RetrievedChunk],
        vector: list[RetrievedChunk],
    ) -> float:
        unweighted = fuse(bm25, vector)
        if not unweighted:
            return 0.0
        score = unweighted[0].rrf_score
        return score if score is not None else 0.0
