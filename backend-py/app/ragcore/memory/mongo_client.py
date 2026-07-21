"""会话记忆 MongoDB 客户端。

对应 Java 版 `ChatMessageRepository` / `MemoryItemRepository` 的底层连接。
使用 motor(异步 PyMongo)。`rag_memory_mongo_uri` 未配置时返回 None,允许上层
(RedisMongoConversationStore / MemoryItemStoreImpl) 在配置缺失时安全降级。
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)

# 兜底库名,仅在 URI 里没有指定默认数据库时使用。
# 注意:此前这里硬编码过 "ragkb",但真实 URI(`rag_memory_mongo_uri`)指向的库是
# `rag_kb_memory`(Java 原版实际写入的库),两者不一致会导致 get_memory_db() 悄悄连到
# 一个空库,查询永远返回空结果且不报错。现在优先用 client.get_default_database()
# 从 URI 里解析真实库名,避免重蹈覆辙。
FALLBACK_DB_NAME: str = "rag_kb_memory"


@lru_cache(maxsize=1)
def get_memory_mongo_client():
    """惰性建立 MongoDB 异步客户端;URI 未配置时返回 None。"""
    if not settings.rag_memory_mongo_uri:
        return None
    try:
        from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore

        return AsyncIOMotorClient(settings.rag_memory_mongo_uri, tz_aware=True)
    except Exception as ex:  # noqa: BLE001 - 启动期不希望崩溃
        logger.warning("MongoDB 客户端初始化失败: %s", ex)
        return None


def get_memory_db():
    client = get_memory_mongo_client()
    if client is None:
        return None
    try:
        # 优先使用 URI 中显式指定的数据库名(如 `.../rag_kb_memory?...`),
        # 与 Java 原版实际写入的库保持一致。
        return client.get_default_database()
    except Exception:  # noqa: BLE001 - URI 未指定默认库时 pymongo 会抛异常
        return client[FALLBACK_DB_NAME]
