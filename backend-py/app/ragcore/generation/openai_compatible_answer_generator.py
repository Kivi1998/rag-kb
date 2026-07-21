"""OpenAI Chat Completions 兼容的上游流式生成适配器(面向用户问答主流程)。

对应 Java 版 `ragcore/generation/OpenAiCompatibleAnswerGenerator.java`。实现
`AnswerGenerator` 协议,以 async generator 形式逐块 `yield QueryEvent`(CHUNK/DONE 等),
`GenerationMetrics` 由调用方传入、由生成过程原地更新字段(详见 `metrics.py` 协议说明)。

SSE 解析:
- 仅消费 `data: ` 前缀的行(其它行是 SSE 注释/心跳)
- `[DONE]` 哨兵行遇到即结束
- 每个 `data: <json>` 行解析 `choices[0].delta.content`,有正文时 `yield QueryEvent.chunk(...)`
  并累加 `metrics.output_characters`
- `usage` 字段(由 `stream_options.include_usage=true` 触发,生成服务在最后一个块附带
  完整用量)在出现时回填 `metrics.prompt_tokens` / `metrics.completion_tokens` / `metrics.model`

Java 版用回调 `Consumer<QueryEvent>` 推事件给下游,Python 用 async generator 自然 pull,
`metrics` 用原地更新避免 Java 那种"执行完再返回值"机制在生成器里无法表达的问题。
HTTP 失败/响应非法统一抛 `ModelClientException`,由调用方降级或展示给用户。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Iterator

import httpx

from app.core.config import Settings, settings as default_settings
from app.ragcore.generation.client import AnswerGenerator
from app.ragcore.generation.metrics import GenerationMetrics
from app.ragcore.generation.prompt_assembler import PromptAssembler
from app.ragcore.model import ModelClientException, QueryEvent, RetrievedChunk

logger = logging.getLogger(__name__)

# SSE 数据行的前缀。Java 版 `if (!line.startsWith("data:"))` 同款。
_SSE_DATA_PREFIX = "data:"
# OpenAI 风格的流式结束哨兵。Java 版 `"[DONE]".equals(data)` 同款。
_SSE_DONE_SENTINEL = "[DONE]"


@dataclass(frozen=True, slots=True)
class GenerationProperties:
    """OpenAI 兼容流式生成所需的端点配置。对应 Java 版 `RagModelProperties.Generation`。"""

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


def _properties_from_settings(cfg: Settings) -> GenerationProperties:
    return GenerationProperties(
        enabled=cfg.rag_generation_enabled,
        endpoint=cfg.rag_generation_endpoint,
        api_key=cfg.rag_generation_api_key,
        model=cfg.rag_generation_model,
        timeout_ms=cfg.rag_generation_timeout_ms,
        include_usage=cfg.rag_generation_include_usage,
    )


class OpenAiCompatibleAnswerGenerator:
    """OpenAI 兼容流式生成器,实现 `AnswerGenerator` 协议。"""

    def __init__(
        self,
        properties: GenerationProperties,
        prompt_assembler: PromptAssembler,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._properties = properties
        self._prompt_assembler = prompt_assembler
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=properties.timeout_ms / 1000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def model_id(self) -> str:
        return self._properties.model

    async def stream_with_metrics(
        self,
        question: str,
        contexts: list[RetrievedChunk],
        metrics: GenerationMetrics,
        additional_system_context: str | None = None,
    ) -> AsyncIterator[QueryEvent]:
        """流式产出 `QueryEvent`,`metrics` 原地更新。

        调用方约定:`async for` 正常耗尽时 `metrics` 已携带最终用量统计(模型/输入/输出
        token 数 + 输出字符数)。中途取消或异常退出时 `metrics` 可能不完整,这是预期行为。
        """
        # 先用 properties.model 兜底,后面如果 stream 返回了 model 字段会再覆盖。
        # 对应 Java `usage.model() == null ? properties.getModel() : usage.model()`。
        metrics.model = self._properties.model
        body = self._build_request_body(question, contexts, additional_system_context)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self._properties.api_key and self._properties.api_key.strip():
            headers["Authorization"] = f"Bearer {self._properties.api_key}"

        response: httpx.Response | None = None
        try:
            response = await self._client.send(
                self._client.build_request("POST", self._properties.endpoint, json=body, headers=headers),
                stream=True,
            )
            if not (200 <= response.status_code < 300):
                # 把响应体读出来再 raise,方便上游日志定位是 4xx 还是 5xx
                await response.aread()
                raise ModelClientException(f"Generation 服务返回 HTTP {response.status_code}")
            async for raw_line in response.aiter_lines():
                if not raw_line.startswith(_SSE_DATA_PREFIX):
                    continue
                data = raw_line[len(_SSE_DATA_PREFIX) :].strip()
                if data == _SSE_DONE_SENTINEL:
                    break
                if not data:
                    # 空 data 行(常见于 SSE 注释/心跳)跳过。Java `readTree("")` 不会
                    # 抛异常,而 Python `json.loads("")` 会抛,所以这里显式拦截以保持
                    # 语义一致。
                    continue
                event = self._parse_data_line(data, metrics)
                if event is not None:
                    yield event
        except ModelClientException:
            raise
        except httpx.HTTPError as exc:
            raise ModelClientException("调用 Generation 服务失败") from exc
        except json.JSONDecodeError as exc:
            raise ModelClientException("Generation 服务响应不是合法 JSON") from exc
        finally:
            # 显式关闭响应:async generator 被 close() 时 (e.g. 消费方 `break` 提前退出)
            # 上面的 `async for` 会触发 `GeneratorExit`,这里再 await 一次 aclose 兜底,
            # 避免 httpx 在异步上下文清理时出现 "coroutine never awaited" 警告。
            if response is not None:
                await response.aclose()

    def _build_request_body(
        self,
        question: str,
        contexts: list[RetrievedChunk],
        additional_system_context: str | None,
    ) -> dict:
        """构造 OpenAI Chat Completions 请求体。Java `ChatCompletionRequest` 字段映射。"""
        return {
            "model": self._properties.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": self._prompt_assembler.system_prompt(additional_system_context)},
                {"role": "user", "content": self._prompt_assembler.user_prompt(question, contexts)},
            ],
            "temperature": 0,
            "stream_options": {"include_usage": self._properties.include_usage},
        }

    @staticmethod
    def _parse_data_line(data: str, metrics: GenerationMetrics) -> QueryEvent | None:
        """解析一行 SSE data,产出 CHUNK 事件并更新 metrics。

        顶层 `model` / `usage.prompt_tokens` / `usage.completion_tokens` 出现时回填 metrics。
        `choices[0].delta.content` 非空文本时产出 CHUNK 事件。其它情况返回 None。
        """
        root = json.loads(data)
        if not isinstance(root, dict):
            return None
        if isinstance(root.get("model"), str):
            metrics.model = root["model"]
        usage = root.get("usage")
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            if isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool):
                metrics.prompt_tokens = prompt_tokens
            completion_tokens = usage.get("completion_tokens")
            if isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool):
                metrics.completion_tokens = completion_tokens
        choices = root.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        if not isinstance(delta, dict):
            return None
        content = delta.get("content")
        if not isinstance(content, str) or not content:
            return None
        # output_characters 累加对应 delta content 的真实字符长度,与 Java 版
        # `outputCharacters += content.asText().length()` 语义一致(Java length() 即
        # 字符数,Python len() 同样按字符计算;两者对 ASCII 相同,对中文等 CJK 字符
        # Python 返回 codepoint 数,Java 返回 UTF-16 code unit 数——实际上 CJK 字符
        # 在 BMP 内两者一致)。
        metrics.output_characters += len(content)
        return QueryEvent.chunk(content)


def build_answer_generator(cfg: Settings | None = None) -> OpenAiCompatibleAnswerGenerator | None:
    """对应 Java 版 `RagModelConfiguration.answerGenerator`(`@ConditionalOnProperty` 装配)。

    `rag.generation.enabled=false`(默认)时返回 None——调用方(查询编排层)必须把
    None 当作"生成服务不可用,本轮跳过"的信号。
    """

    cfg = cfg or default_settings
    if not cfg.rag_generation_enabled:
        return None
    return OpenAiCompatibleAnswerGenerator(_properties_from_settings(cfg), PromptAssembler())
