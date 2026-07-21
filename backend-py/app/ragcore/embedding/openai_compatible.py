"""OpenAI `/v1/embeddings` 兼容客户端，支持本地模型网关和云端兼容服务。

对应 Java 版 `ragcore/embedding/OpenAiCompatibleEmbeddingClient.java`。429/5xx 重试
（含重试次数、指数级 backoff、5 秒封顶）与 4xx 参数错误不重试的区分逻辑与 Java 版保持一致。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings as default_settings
from app.ragcore.model import EmbeddingResult, ModelClientException

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingProperties:
    """对应 Java 版 `RagModelProperties.Embedding`。"""

    enabled: bool
    endpoint: str
    api_key: str
    model: str
    timeout_ms: int = 15_000
    batch_size: int = 32
    max_attempts: int = 3
    retry_backoff_ms: int = 200

    def __post_init__(self) -> None:
        if (
            not self.endpoint
            or not self.endpoint.strip()
            or not self.model
            or not self.model.strip()
            or self.batch_size <= 0
            or not (1 <= self.max_attempts <= 10)
            or not (0 <= self.retry_backoff_ms <= 60_000)
        ):
            raise ValueError("Embedding endpoint/model/batch-size/max-attempts/retry-backoff-ms 配置不合法")
        if self.timeout_ms <= 0:
            raise ValueError("模型服务 timeout-ms 必须大于 0")


def _properties_from_settings(cfg: Settings) -> EmbeddingProperties:
    return EmbeddingProperties(
        enabled=cfg.rag_embedding_enabled,
        endpoint=cfg.rag_embedding_endpoint,
        api_key=cfg.rag_embedding_api_key,
        model=cfg.rag_embedding_model,
        timeout_ms=cfg.rag_embedding_timeout_ms,
        batch_size=cfg.rag_embedding_batch_size,
        max_attempts=cfg.rag_embedding_max_attempts,
        retry_backoff_ms=cfg.rag_embedding_retry_backoff_ms,
    )


@dataclass
class _BatchResponse:
    model_version: str | None
    vectors: list[list[float]]


class OpenAiCompatibleEmbeddingClient:
    """对应 Java 版 `OpenAiCompatibleEmbeddingClient`。"""

    def __init__(self, properties: EmbeddingProperties, http_client: httpx.AsyncClient | None = None) -> None:
        self._properties = properties
        # httpx 默认即 HTTP/1.1（未显式开启 http2），与 Java 版强制 HTTP_1_1 的行为一致：
        # 部分本地模型网关（如 Xinference）不支持明文 h2c 升级协商，HTTP/2 优先会导致 500/502。
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=properties.timeout_ms / 1000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(self._properties.model, [])
        if any(text is None or not text.strip() for text in texts):
            raise ValueError("Embedding 输入不能包含空文本")

        all_vectors: list[list[float]] = []
        model_version = self._properties.model
        batch_size = self._properties.batch_size
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = await self._embed_batch(batch)
            all_vectors.extend(response.vectors)
            if response.model_version and response.model_version.strip():
                model_version = response.model_version
        return EmbeddingResult(model_version, all_vectors)

    async def _embed_batch(self, texts: list[str]) -> _BatchResponse:
        body = {"model": self._properties.model, "input": texts}
        headers = self._headers()
        last_error: Exception | None = None
        for attempt in range(1, self._properties.max_attempts + 1):
            try:
                response = await self._client.post(self._properties.endpoint, json=body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._properties.max_attempts:
                    await self._backoff(attempt)
                    continue
                break
            if not (200 <= response.status_code < 300):
                if self._is_retryable_status(response.status_code) and attempt < self._properties.max_attempts:
                    await self._backoff(attempt)
                    continue
                raise ModelClientException(f"Embedding 服务返回 HTTP {response.status_code}")
            # 响应解析失败（ModelClientException）不在重试范围内，直接向上抛出，与 Java 版一致。
            return self._parse_response(response, len(texts))
        raise ModelClientException("调用 Embedding 服务失败") from last_error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._properties.api_key and self._properties.api_key.strip():
            headers["Authorization"] = f"Bearer {self._properties.api_key}"
        return headers

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        return status == 429 or status >= 500

    async def _backoff(self, completed_attempt: int) -> None:
        delay_ms = min(5_000, self._properties.retry_backoff_ms * completed_attempt)
        if delay_ms <= 0:
            return
        await asyncio.sleep(delay_ms / 1000)

    def _parse_response(self, response: httpx.Response, expected_size: int) -> _BatchResponse:
        try:
            root = response.json()
        except ValueError as exc:
            raise ModelClientException("Embedding 响应不是合法 JSON") from exc
        data = root.get("data")
        if not isinstance(data, list) or len(data) != expected_size:
            raise ModelClientException("Embedding 响应数量与请求不一致")
        items: list[tuple[int, list[float]]] = []
        for node in data:
            index = node.get("index", -1) if isinstance(node, dict) else -1
            embedding = node.get("embedding") if isinstance(node, dict) else None
            if (
                not isinstance(index, int)
                or index < 0
                or index >= expected_size
                or not isinstance(embedding, list)
                or len(embedding) == 0
            ):
                raise ModelClientException("Embedding 响应缺少合法 index 或向量")
            vector: list[float] = []
            for value in embedding:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ModelClientException("Embedding 向量包含非数值元素")
                vector.append(float(value))
            items.append((index, vector))
        items.sort(key=lambda item: item[0])
        for i, (index, _) in enumerate(items):
            if index != i:
                raise ModelClientException("Embedding 响应 index 不连续或重复")
        model_version = root.get("model") if isinstance(root.get("model"), str) else self._properties.model
        return _BatchResponse(model_version, [vector for _, vector in items])


def build_embedding_client(cfg: Settings | None = None) -> OpenAiCompatibleEmbeddingClient | None:
    """对应 Java 版 `RagModelConfiguration.embeddingClient`（`@ConditionalOnProperty` 装配）。

    `rag.model.embedding.enabled=false`（默认）时返回 None——调用方（未来的检索编排层）必须把
    None 当作"降级为 BM25-only"的信号，而不是尝试用空 endpoint 构造客户端后再报错。
    """

    cfg = cfg or default_settings
    if not cfg.rag_embedding_enabled:
        return None
    return OpenAiCompatibleEmbeddingClient(_properties_from_settings(cfg))
