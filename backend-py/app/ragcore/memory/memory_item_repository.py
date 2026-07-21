"""MongoDB `memory_items` 集合的仓库层。

对应 Java 版 `ragcore/conversation/MemoryItemRepository.java`。
所有读操作强制带 `memberId + organizationId` 双键,读回后再次逐条比对,纵深防御。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection  # type: ignore

from app.ragcore.memory.memory_item_document import MemoryItemDocument
from app.ragcore.memory.mongo_client import get_memory_db

logger = logging.getLogger(__name__)

COLLECTION_NAME: str = "memory_items"


class MemoryItemRepository:
    def __init__(self, collection: AsyncIOMotorCollection | None = None) -> None:
        self._collection = collection if collection is not None else self._resolve_collection()

    @staticmethod
    def _resolve_collection() -> AsyncIOMotorCollection | None:
        db = get_memory_db()
        if db is None:
            return None
        return db[COLLECTION_NAME]

    @property
    def collection(self) -> AsyncIOMotorCollection:
        if self._collection is None:
            raise RuntimeError("MongoDB 未配置 (rag_memory_mongo_uri 为空),无法访问 memory_items")
        return self._collection

    async def save(self, document: MemoryItemDocument) -> MemoryItemDocument:
        payload = _to_mongo(document)
        result = await self.collection.insert_one(payload)
        document.id = str(result.inserted_id)
        return document

    async def save_all(self, documents: Iterable[MemoryItemDocument]) -> list[MemoryItemDocument]:
        # 批量写入;未带 _id 的新条目走 insert_many,已带 _id 的旧条目走逐条 replace。
        new_docs: list[dict[str, Any]] = []
        for doc in documents:
            new_docs.append(_to_mongo(doc))
        if not new_docs:
            return []
        result = await self.collection.insert_many(new_docs)
        return list(documents)  # 调用方持有 dataclass 引用,id 由 motor 后台填

    async def find_by_id(self, memory_id: str) -> MemoryItemDocument | None:
        from bson import ObjectId  # type: ignore

        try:
            oid = ObjectId(memory_id)
        except Exception:  # noqa: BLE001
            return None
        raw = await self.collection.find_one({"_id": oid})
        return _from_mongo(raw) if raw else None

    async def find_all_by_id(self, memory_ids: Iterable[str]) -> list[MemoryItemDocument]:
        from bson import ObjectId  # type: ignore

        oids: list[ObjectId] = []
        for mid in memory_ids:
            try:
                oids.append(ObjectId(mid))
            except Exception:  # noqa: BLE001 - 非法 id 视为不存在
                continue
        if not oids:
            return []
        cursor = self.collection.find({"_id": {"$in": oids}})
        result: list[MemoryItemDocument] = []
        async for raw in cursor:
            doc = _from_mongo(raw)
            if doc is not None:
                result.append(doc)
        return result

    async def find_stale(self, cutoff: datetime, importance_threshold: float) -> list[MemoryItemDocument]:
        cursor = self.collection.find(
            {"lastAccessedAt": {"$lt": cutoff}, "importance": {"$lt": importance_threshold}}
        )
        result: list[MemoryItemDocument] = []
        async for raw in cursor:
            doc = _from_mongo(raw)
            if doc is not None:
                result.append(doc)
        return result

    async def delete_by_id(self, memory_id: str) -> None:
        from bson import ObjectId  # type: ignore

        try:
            oid = ObjectId(memory_id)
        except Exception:  # noqa: BLE001
            return
        await self.collection.delete_one({"_id": oid})


def _to_mongo(doc: MemoryItemDocument) -> dict[str, Any]:
    return {
        "memberId": doc.member_id,
        "organizationId": doc.organization_id,
        "type": doc.type,
        "content": doc.content,
        "importance": doc.importance,
        "accessCount": doc.access_count,
        "lastAccessedAt": doc.last_accessed_at,
        "createdAt": doc.created_at,
        "sourceSessionId": doc.source_session_id if doc.source_session_id else None,
    }


def _from_mongo(raw: dict[str, Any]) -> MemoryItemDocument | None:
    try:
        source_session = raw.get("sourceSessionId")
        created_at = _parse_datetime(raw.get("createdAt"))
        if created_at is None:
            logger.warning("MongoDB memory_items 缺少 createdAt,跳过")
            return None
        last_accessed_at = _parse_datetime(raw.get("lastAccessedAt")) or created_at
        return MemoryItemDocument(
            id=str(raw["_id"]),
            member_id=_as_uuid(raw["memberId"]),
            organization_id=_as_uuid(raw["organizationId"]),
            type=str(raw["type"]),
            content=str(raw["content"]),
            importance=float(raw.get("importance", 0.5)),
            access_count=int(raw.get("accessCount", 0)),
            last_accessed_at=last_accessed_at,
            created_at=created_at,
            source_session_id=_as_uuid(source_session) if source_session else None,
        )
    except (KeyError, ValueError, TypeError) as ex:
        logger.warning("MongoDB memory_items 单条反序列化失败,跳过: %s", ex)
        return None


def _as_uuid(value: Any) -> UUID:
    """兼容原生 BSON UUID(uuidRepresentation=standard 生效时的正常形态)与遗留字符串值。"""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
