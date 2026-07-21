"""OpenAI Chat Completions 兼容的非流式单轮调用(`stream:false`)。

对应 Java 版 `ragcore/generation/OpenAiCompatibleChatCompletionClient.java`。复用同一套
`rag.generation` 端点配置(同一个生成模型、同一个超时、同一个 api_key),只是用
`stream:false` 一次性拿到完整响应,供指代消解/摘要压缩/画像提炼这类"一次性、要完整结果"
的辅助 LLM 调用复用。与面向用户的流式 `OpenAiCompatibleAnswerGenerator` 分开。

Java 版无重试逻辑(单次失败即抛出 `ModelClientException`),此处原样保留。HTTP 用
`httpx`,超时由客户端实例统一管理,见 `_properties_from_settings` 里的换算。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings as default_settings
from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.model import ModelClientException


@dataclass(frozen=True, slots=True)
class ChatCompletionProperties:
    """OpenAI 兼容 Chat Completion 客户端所需的端点配置。

    对应 Java 版 `RagModelProperties.Generation`。`include_usage` 仅对流式调用生效,
    这里保留字段是为了和流式 `OpenAiCompatibleAnswerGenerator` 共享同一份配置对象。
    """

    enabled: bool
    endpoint: str
    api_key: str
    model: str
    timeout_ms: int = 60_000
    include_usage: bool = True

    def __post_init__(self) -> None:
        if not self.endpoint or not self.endpoint.strip():
            raise ValueError("Generation endpoint 必须配置")
        if not self.model or not self.model.strip():
            raise ValueError("Generation model 必须配置")
        if self.timeout_ms <= 0:
            raise ValueError("模型服务 timeout-ms 必须大于 0")


def _properties_from_settings(cfg: Settings) -> ChatCompletionProperties:
    return ChatCompletionProperties(
        enabled=cfg.rag_generation_enabled,
        endpoint=cfg.rag_generation_endpoint,
        api_key=cfg.rag_generation_api_key,
        model=cfg.rag_generation_model,
        timeout_ms=cfg.rag_generation_timeout_ms,
        include_usage=cfg.rag_generation_include_usage,
    )


class OpenAiCompatibleChatCompletionClient:
    """OpenAI 兼容 Chat Completions 客户端(`stream:false`),实现 `ChatCompletionClient` 协议。"""

    def __init__(self, properties: ChatCompletionProperties, http_client: httpx.AsyncClient | None = None) -> None:
        self._properties = properties
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=properties.timeout_ms / 1000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        body = {
            "model": self._properties.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._properties.api_key and self._properties.api_key.strip():
            headers["Authorization"] = f"Bearer {self._properties.api_key}"
        try:
            response = await self._client.post(self._properties.endpoint, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise ModelClientException("调用生成服务失败") from exc
        if not (200 <= response.status_code < 300):
            raise ModelClientException(f"生成服务返回 HTTP {response.status_code}")
        return self._parse_content(response)

    @staticmethod
    def _parse_content(response: httpx.Response) -> str:
        try:
            root = response.json()
        except ValueError as exc:
            raise ModelClientException("生成服务响应不是合法 JSON") from exc
        if not isinstance(root, dict):
            raise ModelClientException("生成服务响应缺少必要字段")
        choices = root.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelClientException("生成服务响应缺少 choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ModelClientException("生成服务响应缺少 message")
        content = message.get("content")
        if not isinstance(content, str):
            raise ModelClientException("生成服务响应缺少 content")
        return content


def build_chat_completion_client(cfg: Settings | None = None) -> OpenAiCompatibleChatCompletionClient | None:
    """对应 Java 版 `RagModelConfiguration.chatCompletionClient`(`@ConditionalOnProperty` 装配)。

    `rag.generation.enabled=false`(默认)时返回 None——调用方必须把 None 当作
    "辅助 LLM 不可用,本轮跳过"的信号,这是非流式 ChatCompletion 路径的入口。
    """

    cfg = cfg or default_settings
    if not cfg.rag_generation_enabled:
        return None
    return OpenAiCompatibleChatCompletionClient(_properties_from_settings(cfg))
