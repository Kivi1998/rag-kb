"""parser 测试共享 fixtures。

`DocumentInput` 是一个 Protocol（`app.ragcore.model.DocumentInput`），测试里不依赖真实
MinIO/文件系统，直接用内存 `BytesIO` 实现一个最小 fake，覆盖 `document_id()` /
`filename()` / `content_type()` / `source_path()` / `open_stream()` 五个方法。
"""

from __future__ import annotations

import io
import uuid

import pytest


class FakeDocumentInput:
    def __init__(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        source_path: str | None = None,
    ) -> None:
        self._data = data
        self._filename = filename
        self._content_type = content_type
        self._source_path = source_path or filename
        self._document_id = uuid.uuid4()

    def document_id(self) -> uuid.UUID:
        return self._document_id

    def filename(self) -> str:
        return self._filename

    def content_type(self) -> str | None:
        return self._content_type

    def source_path(self) -> str:
        return self._source_path

    def open_stream(self) -> io.BytesIO:
        return io.BytesIO(self._data)


@pytest.fixture
def make_document_input():
    def _factory(data: bytes, filename: str, content_type: str | None = None) -> FakeDocumentInput:
        return FakeDocumentInput(data, filename, content_type)

    return _factory
