"""会话记忆 Redis 客户端(独立逻辑 DB,默认 DB 1)。

对应 Java 版 `ConversationStore` 的 Redis 滑动窗口存储。
**不**复用 `app/core/redis_client.py`(DB 0 JWT 黑名单),按 `settings.rag_memory_redis_database`
单独建连接,避免相互影响。
"""

from __future__ import annotations

import logging
from functools import lru_cache

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_memory_redis() -> redis.Redis:
    """惰性建立 Redis 连接;单例,跨请求复用。"""
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.rag_memory_redis_database,
        decode_responses=True,
    )


async def is_available() -> bool:
    try:
        client = get_memory_redis()
        await client.exists("__health_check__")
        return True
    except Exception as ex:  # noqa: BLE001
        logger.debug("memory redis 不可达: %s", ex)
        return False
