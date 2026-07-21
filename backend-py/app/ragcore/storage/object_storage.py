"""原始文档对象存储端口。

对应 Java 版 `ragcore/storage/ObjectStorage.java`。
支持本地开发(`local`)与 MinIO/S3 生产(`minio`)两种实现,由 `settings.rag_storage_type` 切换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO, Protocol, runtime_checkable
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", dict(self.headers or {}))


@dataclass(frozen=True, slots=True)
class StoredObject:
    size_bytes: int
    content_type: str
    etag: str


@runtime_checkable
class ObjectStorage(Protocol):
    async def put(
        self,
        object_key: str,
        input: IO[bytes],
        size_bytes: int,
        content_type: str,
    ) -> None: ...

    async def open(self, object_key: str) -> IO[bytes]: ...

    async def delete(self, object_key: str) -> None: ...

    def supports_direct_upload(self) -> bool: ...

    async def presign_put(
        self,
        object_key: str,
        content_type: str,
        ttl: timedelta,
    ) -> PresignedUpload: ...

    async def stat(self, object_key: str) -> StoredObject: ...
