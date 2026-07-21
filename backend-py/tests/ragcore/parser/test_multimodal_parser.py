"""HttpMultimodalDocumentParser 测试。

覆盖 `supports()` 矩阵(settings 开关 × 扩展名)、`parse()` 在 endpoint 200/500/
网络异常/响应非 JSON 各种失败路径下的 fail-fast 行为。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.ragcore.models import DocumentInput, DocumentSection
from app.ragcore.parser.multimodal_parser import HttpMultimodalDocumentParser
from tests.ragcore.parser.conftest import FakeDocumentInput


def _input(filename: str, content: bytes = b"fake-bytes") -> FakeDocumentInput:
    return FakeDocumentInput(content, filename)


def _ok_payload() -> dict:
    return {
        "sections": [
            {
                "text": "hello",
                "headingPath": ["ocr"],
                "pageNo": 1,
                "lineStart": 1,
                "lineEnd": 1,
                "metadata": {"confidence": "0.9"},
            }
        ],
        "metadata": {"engine": "test"},
    }


class TestSupports:
    def test_supports_when_enabled_and_pdf(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        parser = HttpMultimodalDocumentParser()
        assert parser.supports(_input("scan.pdf")) is True

    def test_supports_when_enabled_and_image(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        parser = HttpMultimodalDocumentParser()
        for ext in ("png", "jpg", "jpeg", "tif", "tiff"):
            assert parser.supports(_input(f"image.{ext}")) is True, ext

    def test_supports_when_enabled_and_audio_video(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        parser = HttpMultimodalDocumentParser()
        for ext in ("mp3", "wav", "mp4", "mov", "mkv"):
            assert parser.supports(_input(f"clip.{ext}")) is True, ext

    def test_rejects_when_disabled(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", False)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        parser = HttpMultimodalDocumentParser()
        assert parser.supports(_input("scan.pdf")) is False

    def test_rejects_when_endpoint_empty(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "")
        parser = HttpMultimodalDocumentParser()
        assert parser.supports(_input("scan.pdf")) is False

    def test_rejects_unsupported_extension(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        parser = HttpMultimodalDocumentParser()
        assert parser.supports(_input("doc.txt")) is False
        assert parser.supports(_input("doc.md")) is False


def _make_async_client(handler) -> httpx.AsyncClient:
    """构造带 MockTransport 的 httpx 客户端,避免真实网络。"""

    def _transport(request: httpx.Request) -> httpx.Response:
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_transport))


class TestParseFailFast:
    @pytest.mark.asyncio
    async def test_endpoint_200_returns_parsed_document(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_api_key", "")

        async def _client_factory(*_a, **_kw):
            return _make_async_client(lambda req: httpx.Response(200, json=_ok_payload()))

        parser = HttpMultimodalDocumentParser(client=_make_async_client(lambda req: httpx.Response(200, json=_ok_payload())))
        result = await parser.parse(_input("scan.pdf"))

        assert len(result.sections) == 1
        assert result.sections[0].text == "hello"
        assert result.sections[0].heading_path == ("ocr",)
        assert result.sections[0].page_no == 1
        assert result.metadata.get("parser") == "multimodal-gateway"

    @pytest.mark.asyncio
    async def test_endpoint_500_raises_runtime_error(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")

        client = _make_async_client(lambda req: httpx.Response(500, text="oops"))
        parser = HttpMultimodalDocumentParser(client=client)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await parser.parse(_input("scan.pdf"))

    @pytest.mark.asyncio
    async def test_network_failure_raises_runtime_error(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")

        def _transport(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(_transport))
        parser = HttpMultimodalDocumentParser(client=client)
        with pytest.raises(RuntimeError, match="多模态解析网关不可达"):
            await parser.parse(_input("scan.pdf"))

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_runtime_error(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")

        client = _make_async_client(lambda req: httpx.Response(200, text="not json"))
        parser = HttpMultimodalDocumentParser(client=client)
        with pytest.raises(RuntimeError, match="不是合法 JSON"):
            await parser.parse(_input("scan.pdf"))

    @pytest.mark.asyncio
    async def test_missing_sections_raises_runtime_error(self, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "rag_multimodal_parser_enabled", True)
        monkeypatch.setattr(config.settings, "rag_multimodal_parser_endpoint", "http://gw/parse")

        client = _make_async_client(lambda req: httpx.Response(200, json={"metadata": {}}))
        parser = HttpMultimodalDocumentParser(client=client)
        with pytest.raises(RuntimeError, match="缺少 sections"):
            await parser.parse(_input("scan.pdf"))
