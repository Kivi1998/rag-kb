"""Redis 客户端封装。对应 Java 版 RedisService。DB 0 专供 JWT 黑名单,
会话记忆(DB 1)、临时文档(DB 2)在各自模块里用独立连接,不共用这个客户端。"""

import redis.asyncio as redis

from app.core.config import settings

_client = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    password=settings.redis_password or None,
    db=settings.redis_database,
    decode_responses=True,
)


async def set_with_ttl(key: str, value: str, ttl_seconds: int) -> None:
    await _client.set(key, value, ex=ttl_seconds)


async def exists(key: str) -> bool:
    return bool(await _client.exists(key))


async def is_available() -> bool:
    try:
        await _client.exists("__health_check__")
        return True
    except Exception:
        return False
