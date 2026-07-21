"""DocumentDirectUploadService 的对象校验回归测试。

背景:acceptance 生产同构验收(针对 backend-py 改造后首次真实跑通)发现
`_verify_uploaded_object` 对 `MinioObjectStorage.open()` 返回的流调用
`stream.seek(0)` 全量失败,报 `{"code":400,"message":"seek"}`——因为 MinIO SDK
的 `get_object()` 返回的是 urllib3 HTTP 响应体,只能顺序读一次,不支持 seek,
和本地文件流语义不同。这个方法在此之前完全没有单元测试覆盖。
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.document_direct_upload_service import (
    CONTENT_SNIFF_BYTES,
    DocumentDirectUploadService,
    _VerificationSnapshot,
)


class _NonSeekableStream:
    """模拟 MinIO SDK `get_object()` 返回的 HTTP 响应体:只能顺序 `read()`,
    没有 `seek()` 方法(真实 urllib3 HTTPResponse 在非缓冲模式下同样如此)。"""

    def __init__(self, content: bytes) -> None:
        self._buffer = content
        self._offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk, self._offset = self._buffer[self._offset :], len(self._buffer)
            return chunk
        chunk = self._buffer[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def _build_service(object_storage) -> DocumentDirectUploadService:
    return DocumentDirectUploadService(
        kb_repository=MagicMock(),
        member_repository=MagicMock(),
        document_repository=MagicMock(),
        job_repository=MagicMock(),
        session_repository=MagicMock(),
        object_storage=object_storage,
        upload_policy=MagicMock(),
        metrics=MagicMock(),
        session=AsyncMock(),
    )


class TestVerifyUploadedObject:
    async def test_does_not_call_seek_on_non_seekable_stream(self):
        """核心回归点:流对象根本没有 `seek` 方法也不能报错——MinIO 真实返回的流就是这样。"""
        content = b"%PDF-1.4\n" + b"x" * 100
        stream = _NonSeekableStream(content)
        assert not hasattr(stream, "seek")  # 确认这个 mock 忠实模拟了"没有 seek"这个约束

        object_storage = MagicMock()
        object_storage.stat = AsyncMock(return_value=MagicMock(size_bytes=len(content)))
        object_storage.open = AsyncMock(return_value=stream)

        service = _build_service(object_storage)
        snapshot = _VerificationSnapshot(
            session_id=None,
            verification_token=None,
            file_name="report.pdf",
            object_storage_path="org/x/kb/y/documents/z.pdf",
            expected_size_bytes=len(content),
        )

        verified = await service._verify_uploaded_object(snapshot)

        assert verified.size_bytes == len(content)
        assert verified.sha256 == hashlib.sha256(content).hexdigest()
        assert stream.closed is True

    async def test_sha256_correct_when_content_longer_than_sniff_window(self):
        """内容长度超过 CONTENT_SNIFF_BYTES 时,prefix 之后的剩余字节也要被摘要覆盖到——
        回归防止"跳过第一段" 或 "漏摘要末尾 chunk" 这类拼接错误。"""
        content = b"%PDF-1.4\n" + b"A" * (CONTENT_SNIFF_BYTES + 65536 + 123)
        stream = _NonSeekableStream(content)

        object_storage = MagicMock()
        object_storage.stat = AsyncMock(return_value=MagicMock(size_bytes=len(content)))
        object_storage.open = AsyncMock(return_value=stream)

        service = _build_service(object_storage)
        snapshot = _VerificationSnapshot(
            session_id=None,
            verification_token=None,
            file_name="big.pdf",
            object_storage_path="org/x/kb/y/documents/big.pdf",
            expected_size_bytes=len(content),
        )

        verified = await service._verify_uploaded_object(snapshot)

        assert verified.sha256 == hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
