"""调用本机部署的 `nli-gateway`（`POST /nli`）。

对应 Java 版 `ragcore/nli/HttpNliClient.java`。与 Rerank/Generation 客户端一样，Java 版
没有重试逻辑（单次请求失败即抛出），此处原样保留。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings as default_settings
from app.ragcore.model import ModelClientException
from app.ragcore.nli.client import NliVerdict


@dataclass(frozen=True, slots=True)
class NliProperties:
    """对应 Java 版 `RagNliProperties`。不是 OpenAI 兼容端点，无需 api_key/model 字段。"""

    enabled: bool
    endpoint: str
    timeout_ms: int = 15_000

    def __post_init__(self) -> None:
        if not self.endpoint or not self.endpoint.strip():
            raise ValueError("NLI endpoint 必须配置")
        if self.timeout_ms <= 0:
            raise ValueError("rag.nli.timeout-ms 必须大于 0")


def _properties_from_settings(cfg: Settings) -> NliProperties:
    return NliProperties(
        enabled=cfg.rag_nli_enabled,
        endpoint=cfg.rag_nli_endpoint,
        timeout_ms=cfg.rag_nli_timeout_ms,
    )


class HttpNliClient:
    """对应 Java 版 `HttpNliClient`。"""

    def __init__(self, properties: NliProperties, http_client: httpx.AsyncClient | None = None) -> None:
        self._properties = properties
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=properties.timeout_ms / 1000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def check(self, premise: str, hypothesis: str) -> NliVerdict:
        body = {"premise": premise, "hypothesis": hypothesis}
        try:
            response = await self._client.post(
                self._properties.endpoint, json=body, headers={"Content-Type": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise ModelClientException("调用 NLI 服务失败") from exc
        if not (200 <= response.status_code < 300):
            raise ModelClientException(f"NLI 服务返回 HTTP {response.status_code}")
        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> NliVerdict:
        try:
            root = response.json()
        except ValueError as exc:
            raise ModelClientException("NLI 响应不是合法 JSON") from exc
        if not isinstance(root, dict):
            raise ModelClientException("NLI 响应缺少必要字段")
        label = root.get("label")
        entailment = root.get("entailment_prob")
        neutral = root.get("neutral_prob")
        contradiction = root.get("contradiction_prob")
        if (
            not isinstance(label, str)
            or not isinstance(entailment, (int, float)) or isinstance(entailment, bool)
            or not isinstance(neutral, (int, float)) or isinstance(neutral, bool)
            or not isinstance(contradiction, (int, float)) or isinstance(contradiction, bool)
        ):
            raise ModelClientException("NLI 响应缺少必要字段")
        return NliVerdict(label, float(entailment), float(neutral), float(contradiction))


def build_nli_client(cfg: Settings | None = None) -> HttpNliClient | None:
    """对应 Java 版 `RagModelConfiguration.nliClient`（`@ConditionalOnProperty` 装配）。

    `rag.nli.enabled=false`（默认）时返回 None——调用方必须把 None 当作"自检直接跳过"的信号，
    这是三个降级路径里"NLI 未启用"这一支的入口。
    """

    cfg = cfg or default_settings
    if not cfg.rag_nli_enabled:
        return None
    return HttpNliClient(_properties_from_settings(cfg))
