"""MinIO/S3 兼容对象存储实现。

对应 Java 版 `ragcore/storage/MinioObjectStorage.java`。
`rag_storage_type=minio` 时启用;`supports_direct_upload` 返回 True,
可签发短期 PUT 直传地址,绕开应用层大文件 IO。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import IO

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings, settings as default_settings
from app.ragcore.storage.object_storage import ObjectStorage, PresignedUpload, StoredObject

logger = logging.getLogger(__name__)


class MinioObjectStorage(ObjectStorage):
    def __init__(
        self,
        client: Minio | None = None,
        cfg: Settings | None = None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool = True,
    ) -> None:
        cfg = cfg or default_settings
        self._endpoint = endpoint or cfg.minio_endpoint
        self._access_key = access_key or cfg.minio_access_key
        self._secret_key = secret_key or cfg.minio_secret_key
        self._bucket = bucket or cfg.minio_bucket
        if not self._endpoint or not self._access_key or not self._secret_key:
            raise RuntimeError(
                "MinIO 存储已启用但 endpoint/access_key/secret_key 未完整配置"
            )
        # minio.Minio() 的 endpoint 参数只接受裸 host:port,scheme 由独立的 secure
        # 布尔参数控制(不像 Java SDK 的 builder().endpoint() 能直接解析 URL 里的
        # scheme)。这里从配置的 endpoint 字符串里剥离 scheme 换算成 secure,
        # 避免默认值 True 在本机纯 HTTP 的 MinIO 容器上握手失败
        # (SSLError: WRONG_VERSION_NUMBER)。
        host = self._endpoint
        if host.startswith("https://"):
            host, secure = host[len("https://") :], True
        elif host.startswith("http://"):
            host, secure = host[len("http://") :], False
        self._client = client or Minio(
            host,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=secure,
        )

    async def put(
        self,
        object_key: str,
        input: IO[bytes],
        size_bytes: int,
        content_type: str,
    ) -> None:
        def _put() -> None:
            try:
                self._client.put_object(
                    bucket_name=self._bucket,
                    object_name=object_key,
                    data=input,  # type: ignore[arg-type]
                    length=size_bytes,
                    content_type=content_type,
                )
            except S3Error as ex:
                raise IOError(f"MinIO 上传失败: {ex}") from ex

        await asyncio.to_thread(_put)

    async def open(self, object_key: str) -> IO[bytes]:
        def _open() -> IO[bytes]:
            try:
                response = self._client.get_object(self._bucket, object_key)
                return response  # type: ignore[return-value]
            except S3Error as ex:
                raise IOError(f"MinIO 读取失败: {ex}") from ex

        return await asyncio.to_thread(_open)

    async def delete(self, object_key: str) -> None:
        def _delete() -> None:
            try:
                self._client.remove_object(self._bucket, object_key)
            except S3Error as ex:
                raise IOError(f"MinIO 删除失败: {ex}") from ex

        await asyncio.to_thread(_delete)

    def supports_direct_upload(self) -> bool:
        return True

    async def presign_put(
        self,
        object_key: str,
        content_type: str,
        ttl: timedelta,
    ) -> PresignedUpload:
        def _presign() -> PresignedUpload:
            try:
                url = self._client.presigned_put_object(
                    bucket_name=self._bucket,
                    object_name=object_key,
                    expires=ttl,
                )
            except S3Error as ex:
                raise IOError(f"MinIO 预签名上传地址生成失败: {ex}") from ex
            return PresignedUpload(
                url=url,
                method="PUT",
                headers={"Content-Type": content_type},
                expires_at=datetime.now(tz=timezone.utc) + ttl,
            )

        return await asyncio.to_thread(_presign)

    async def stat(self, object_key: str) -> StoredObject:
        def _stat() -> StoredObject:
            try:
                stat = self._client.stat_object(self._bucket, object_key)
            except S3Error as ex:
                raise IOError(f"MinIO 对象元数据查询失败: {ex}") from ex
            return StoredObject(
                size_bytes=int(stat.size or 0),
                content_type=stat.content_type or "application/octet-stream",
                etag=stat.etag or "",
            )

        return await asyncio.to_thread(_stat)
