"""兼容常见 Cross-Encoder 网关的 Rerank 协议客户端。

对应 Java 版 `ragcore/rerank/OpenAiCompatibleRerankerClient.java`。与 Embedding 客户端不同，
Java 版 Rerank 客户端没有重试逻辑（单次请求失败即抛出），此处原样保留这一差异，不要自行加上
重试——加了反而与 Java 版行为不一致。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings as default_settings
from app.ragcore.model import ModelClientException, RetrievedChunk


@dataclass(frozen=True, slots=True)
class RerankProperties:
    """对应 Java 版 `RagModelProperties.Rerank`。"""

    enabled: bool
    endpoint: str
    api_key: str
    model: str
    timeout_ms: int = 15_000

    def __post_init__(self) -> None:
        if not self.endpoint or not self.endpoint.strip() or not self.model or not self.model.strip():
            raise ValueError("Rerank endpoint/model 必须配置")
        if self.timeout_ms <= 0:
            raise ValueError("模型服务 timeout-ms 必须大于 0")


def _properties_from_settings(cfg: Settings) -> RerankProperties:
    return RerankProperties(
        enabled=cfg.rag_rerank_enabled,
        endpoint=cfg.rag_rerank_endpoint,
        api_key=cfg.rag_rerank_api_key,
        model=cfg.rag_rerank_model,
        timeout_ms=cfg.rag_rerank_timeout_ms,
    )


class OpenAiCompatibleRerankerClient:
    """对应 Java 版 `OpenAiCompatibleRerankerClient`。"""

    def __init__(self, properties: RerankProperties, http_client: httpx.AsyncClient | None = None) -> None:
        self._properties = properties
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=properties.timeout_ms / 1000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def rerank(self, query: str, candidates: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        if not query or not query.strip() or not candidates or top_k <= 0:
            return []
        documents = [candidate.chunk.content for candidate in candidates]
        body = {
            "model": self._properties.model,
            "query": query,
            "documents": documents,
            "top_n": top_k,
        }
        headers = {"Content-Type": "application/json"}
        if self._properties.api_key and self._properties.api_key.strip():
            headers["Authorization"] = f"Bearer {self._properties.api_key}"
        try:
            response = await self._client.post(self._properties.endpoint, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ModelClientException("调用 Rerank 服务失败") from exc
        if not (200 <= response.status_code < 300):
            raise ModelClientException(f"Rerank 服务返回 HTTP {response.status_code}")
        return self._parse_response(response, candidates, top_k)

    def _parse_response(
        self, response: httpx.Response, candidates: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        try:
            root = response.json()
        except ValueError as exc:
            raise ModelClientException("Rerank 响应不是合法 JSON") from exc
        results = root.get("results") if isinstance(root, dict) else None
        if not isinstance(results, list):
            raise ModelClientException("Rerank 响应缺少 results 数组")
        scored: list[tuple[int, RetrievedChunk]] = []
        for result in results:
            if not isinstance(result, dict):
                raise ModelClientException("Rerank 响应包含非法候选索引或分数")
            index = result.get("index", -1)
            score = result.get("relevance_score", result.get("score"))
            if (
                not isinstance(index, int)
                or index < 0
                or index >= len(candidates)
                or not isinstance(score, (int, float))
                or isinstance(score, bool)
            ):
                raise ModelClientException("Rerank 响应包含非法候选索引或分数")
            old = candidates[index]
            score_value = float(score)
            scored.append(
                (
                    index,
                    RetrievedChunk(
                        chunk=old.chunk,
                        bm25_rank=old.bm25_rank,
                        vector_rank=old.vector_rank,
                        rrf_score=old.rrf_score,
                        rerank_score=score_value,
                        final_score=score_value,
                    ),
                )
            )
        scored.sort(key=lambda item: -(item[1].final_score or 0.0))
        return [chunk for _, chunk in scored[:top_k]]


def build_reranker_client(cfg: Settings | None = None) -> OpenAiCompatibleRerankerClient | None:
    """对应 Java 版 `RagModelConfiguration.rerankerClient`（`@ConditionalOnProperty` 装配）。

    `rag.model.rerank.enabled=false`（默认）时返回 None——调用方（未来的检索编排层）必须把
    None 当作"跳过 rerank、直接使用 RRF 排序结果"的信号。
    """

    cfg = cfg or default_settings
    if not cfg.rag_rerank_enabled:
        return None
    return OpenAiCompatibleRerankerClient(_properties_from_settings(cfg))
