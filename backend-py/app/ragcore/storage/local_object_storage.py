"""本地开发/测试对象存储实现。

对应 Java 版 `ragcore/storage/LocalObjectStorage.java`。
`rag_storage_type=local` 时启用(默认);`supports_direct_upload` 返回 False,
不允许客户端直传。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from app.core.config import Settings, settings as default_settings
from app.ragcore.storage.object_storage import ObjectStorage, PresignedUpload, StoredObject

logger = logging.getLogger(__name__)


class LocalObjectStorage(ObjectStorage):
    def __init__(
        self,
        cfg: Settings | None = None,
        local_root: str | None = None,
    ) -> None:
        cfg = cfg or default_settings
        self._root = Path(local_root or cfg.rag_local_storage_root).resolve()

    async def put(
        self,
        object_key: str,
        input: IO[bytes],
        size_bytes: int,
        content_type: str,
    ) -> None:
        target = self._resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._copy_to_disk, input, target)
        logger.debug("local object storage put: %s (%d bytes)", object_key, size_bytes)

    @staticmethod
    def _copy_to_disk(input: IO[bytes], target: Path) -> None:
        with target.open("wb") as out:
            shutil.copyfileobj(input, out)

    async def open(self, object_key: str) -> IO[bytes]:
        target = self._resolve(object_key)
        return target.open("rb")

    async def delete(self, object_key: str) -> None:
        target = self._resolve(object_key)
        try:
            target.unlink()
        except FileNotFoundError:
            return

    def supports_direct_upload(self) -> bool:
        return False

    async def presign_put(
        self,
        object_key: str,
        content_type: str,
        ttl,  # timedelta
    ) -> PresignedUpload:
        raise NotImplementedError("本地存储不支持预签名直传")

    async def stat(self, object_key: str) -> StoredObject:
        target = self._resolve(object_key)
        if not target.exists():
            raise FileNotFoundError(object_key)
        return StoredObject(
            size_bytes=target.stat().st_size,
            content_type="application/octet-stream",
            etag="",
        )

    def _resolve(self, object_key: str) -> Path:
        if not object_key or object_key.strip() == "":
            raise ValueError("objectKey 不能为空")
        target = (self._root / object_key).resolve()
        if not str(target).startswith(str(self._root)):
            raise ValueError(f"非法对象存储路径: {object_key}")
        return target
