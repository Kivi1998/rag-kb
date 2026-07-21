"""DeepSeek 画像提炼实现。对应 Java 版 `DeepSeekMemoryExtractor.java`。

从一轮问答提炼候选画像条目(PREFERENCE / FACT / GOAL),语义去重后写入长期记忆。
所有异常在内部捕获记录,绝不向调用方传播——这是异步增强,不应影响已返回给用户的回答。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from app.ragcore.embedding.client import EmbeddingClient
from app.ragcore.generation.client import ChatCompletionClient
from app.ragcore.memory.memory_extractor import MemoryExtractor
from app.ragcore.memory.memory_item_store import MemoryItemStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT: str = (
    "从下面这轮问答里提炼值得长期记住的用户偏好/事实/长期目标"
    "(没有就返回空数组,不要为了凑数编造)。"
    "严格按以下 JSON 格式输出,不要有其他文字:\n"
    '{"items":[{"type":"PREFERENCE|FACT|GOAL",'
    '"content":"一句话描述","importance":0.0到1.0之间的数字}]}'
)

VALID_TYPES: frozenset[str] = frozenset({"PREFERENCE", "FACT", "GOAL"})

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fence(text: str | None) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned)
    return cleaned.strip()


def _parse_json(response: str | None) -> dict[str, Any]:
    cleaned = _strip_code_fence(response)
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as ex:
        raise ValueError(f"画像提炼响应解析失败: {ex}") from ex
    if not isinstance(parsed, dict):
        return {}
    return parsed


class DeepSeekMemoryExtractor(MemoryExtractor):
    def __init__(
        self,
        chat_completion_client: ChatCompletionClient,
        embedding_client: EmbeddingClient,
        memory_item_store: MemoryItemStore,
    ) -> None:
        self._chat = chat_completion_client
        self._embedding = embedding_client
        self._store = memory_item_store

    async def extract_and_store(
        self,
        organization_id: UUID,
        member_id: UUID,
        session_id: UUID,
        question: str,
        answer: str,
    ) -> None:
        try:
            user_prompt = f"用户问题:{question}\n助手回答:{answer}"
            response = await self._chat.complete(SYSTEM_PROMPT, user_prompt)
            root = _parse_json(response)
            items = root.get("items")
            if not isinstance(items, list) or not items:
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                await self._process_candidate(organization_id, member_id, session_id, item)
        except Exception as ex:  # noqa: BLE001 - 全局 fail-open,绝不抛出
            logger.warning(
                "画像提炼失败,不影响本轮已返回的回答: sessionId=%s, ex=%s",
                session_id, ex,
            )

    async def _process_candidate(
        self,
        organization_id: UUID,
        member_id: UUID,
        session_id: UUID,
        item: dict[str, Any],
    ) -> None:
        type_ = str(item.get("type") or "").strip()
        content = str(item.get("content") or "").strip()
        importance_raw = item.get("importance")
        if not content or type_ not in VALID_TYPES:
            return
        try:
            importance = float(importance_raw) if importance_raw is not None else 0.5
        except (TypeError, ValueError):
            importance = 0.5
        importance = max(0.0, min(1.0, importance))

        try:
            embedding = await self._embedding.embed([content])
        except Exception as ex:  # noqa: BLE001
            logger.debug("画像候选向量化失败,跳过: %s", ex)
            return
        if not embedding.vectors:
            return
        vector = list(embedding.vectors[0])

        existing = await self._store.find_similar_existing(organization_id, member_id, vector)
        if existing is not None:
            logger.debug(
                "画像条目语义去重,跳过: memberId=%s, content=%s", member_id, content
            )
            return
        await self._store.create_item(
            organization_id=organization_id,
            member_id=member_id,
            type=type_,
            content=content,
            initial_importance=importance,
            vector=vector,
            source_session_id=session_id,
        )
