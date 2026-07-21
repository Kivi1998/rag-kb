"""DocumentParserFactory 测试。

覆盖:
- 单个同步 parser 命中时,`factory.parse()` 不需要 await 内部结果就能拿到值
  (`parser.parse()` 直接返回 `ParsedDocument`,不是协程)。
- 单个异步 parser(`parse()` 是 `async def`,如 `LocalMultimodalDocumentParser`)
  命中时,`factory.parse()` 必须真正 `await` 协程拿到 `ParsedDocument`,而不是
  把协程对象本身当结果返回——这是这次要修的 bug(旧版 `factory.parse()` 是
  同步方法,对所有候选统一 `return parser.parse(document_input)`,遇到 async
  parser 时拿到的是未执行的协程对象)。
- 混用同步与异步 parser 时,factory 都能正确处理,不会因为用错分支而互相干扰。
- 单个 parser 抛异常(无论同步异常还是 await 时才抛出的异步异常)不阻塞其他
  候选,行为与改造前一致。
- 没有任何 parser 支持时抛 `UnsupportedDocumentTypeException`。
"""

from __future__ import annotations

import uuid

import pytest

from app.ragcore.model import ParsedDocument
from app.ragcore.parser.factory import DocumentParserFactory, UnsupportedDocumentTypeException
from tests.ragcore.parser.conftest import FakeDocumentInput


def _parsed(marker: str) -> ParsedDocument:
    return ParsedDocument(
        document_id=uuid.uuid4(),
        content_type=None,
        source_path=marker,
        sections=(),
        metadata={"marker": marker},
    )


class _SyncParser:
    """模拟现有本地解析器:supports()/parse() 都是同步方法。"""

    def __init__(self, ext: str, marker: str, raise_error: bool = False) -> None:
        self._ext = ext
        self._marker = marker
        self._raise_error = raise_error

    def supports(self, content_type, filename) -> bool:
        return bool(filename) and filename.endswith(f".{self._ext}")

    def parse(self, document_input) -> ParsedDocument:
        if self._raise_error:
            raise RuntimeError(f"{self._marker} 同步解析失败")
        return _parsed(self._marker)


class _AsyncParser:
    """模拟本地多模态解析器:parse() 是 async def,必须被 await。"""

    def __init__(self, ext: str, marker: str, raise_error: bool = False) -> None:
        self._ext = ext
        self._marker = marker
        self._raise_error = raise_error
        self.awaited = False

    def supports(self, content_type, filename) -> bool:
        return bool(filename) and filename.endswith(f".{self._ext}")

    async def parse(self, document_input) -> ParsedDocument:
        self.awaited = True
        if self._raise_error:
            raise RuntimeError(f"{self._marker} 异步解析失败")
        return _parsed(self._marker)


def _input(filename: str) -> FakeDocumentInput:
    return FakeDocumentInput(b"content", filename)


class TestSyncParserPath:
    async def test_sync_parser_result_returned_without_await_needed(self):
        parser = _SyncParser("txt", "sync")
        factory = DocumentParserFactory([parser])

        result = await factory.parse(_input("a.txt"))

        assert isinstance(result, ParsedDocument)
        assert result.metadata["marker"] == "sync"


class TestAsyncParserPath:
    async def test_async_parser_coroutine_is_awaited_not_returned_raw(self):
        """回归测试:必须拿到 ParsedDocument,而不是一个未执行的协程对象。"""
        parser = _AsyncParser("pdf", "async")
        factory = DocumentParserFactory([parser])

        result = await factory.parse(_input("scan.pdf"))

        assert parser.awaited is True
        assert isinstance(result, ParsedDocument), (
            f"factory.parse() 必须 await 协程结果,而不是返回协程对象本身,实际拿到: {type(result)!r}"
        )
        assert result.metadata["marker"] == "async"


class TestMixedSyncAndAsyncParsers:
    async def test_sync_parser_matches_first_without_touching_async_candidate(self):
        sync_parser = _SyncParser("docx", "sync-docx")
        async_parser = _AsyncParser("docx", "async-fallback")
        factory = DocumentParserFactory([sync_parser, async_parser])

        result = await factory.parse(_input("report.docx"))

        assert result.metadata["marker"] == "sync-docx"
        assert async_parser.awaited is False

    async def test_falls_through_to_async_parser_when_sync_parser_does_not_support(self):
        sync_parser = _SyncParser("docx", "sync-docx")
        async_parser = _AsyncParser("pdf", "async-pdf")
        factory = DocumentParserFactory([sync_parser, async_parser])

        result = await factory.parse(_input("scan.pdf"))

        assert result.metadata["marker"] == "async-pdf"
        assert async_parser.awaited is True

    async def test_sync_parser_exception_falls_through_to_async_parser(self):
        failing_sync = _SyncParser("pdf", "sync-fail", raise_error=True)
        async_parser = _AsyncParser("pdf", "async-fallback")
        factory = DocumentParserFactory([failing_sync, async_parser])

        result = await factory.parse(_input("scan.pdf"))

        assert result.metadata["marker"] == "async-fallback"
        assert async_parser.awaited is True

    async def test_async_parser_exception_raised_during_await_is_caught(self):
        """异步 parser 的异常要在 await 时才会抛出;factory 必须仍然捕获到它，
        跳到下一个候选，而不是让异常在 await 之外泄漏或被误判为协程返回值。"""
        failing_async = _AsyncParser("pdf", "async-fail", raise_error=True)
        fallback_sync = _SyncParser("pdf", "sync-fallback")
        factory = DocumentParserFactory([failing_async, fallback_sync])

        result = await factory.parse(_input("scan.pdf"))

        assert failing_async.awaited is True
        assert result.metadata["marker"] == "sync-fallback"


class TestNoParserSupports:
    async def test_raises_unsupported_document_type(self):
        factory = DocumentParserFactory([_SyncParser("txt", "sync")])
        with pytest.raises(UnsupportedDocumentTypeException):
            await factory.parse(_input("scan.pdf"))
