"""多模态解析网关 HTTP 适配器。对应 HttpMultimodalDocumentParser.java。

把扫描件 PDF / 图片 / 音视频等本地无能为力的输入透传到外部多模态解析网关
(OCR / ASR / 版面识别)。请求体为原始文件字节，避免编排服务把大文件读入
内存；网关返回 JSON：
```
{
  "sections": [
    {"text": "...", "headingPath": ["..."], "pageNo": int|null,
     "lineStart": int|null, "lineEnd": int|null, "metadata": {"key": "value"}}
  ],
  "metadata": {"key": "value"}
}
```
网关实现可对接 OCR、PDF 版面分析、PPT 图片文字识别或视频 ASR。

**失败语义**：与 Java 版保持一致——网络异常、HTTP 非 2xx、响应解析失败都向上抛
`RuntimeError`，由上层 (`DefaultDocumentIngestionPipeline`) 把它转成 `fail()`，
绝不在本地静默吞掉。`supports()` 在 `rag_multimodal_parser_enabled=false` 或
endpoint 为空时直接返回 False,让本地解析器链(若有匹配)继续尝试。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import httpx

from app.core.config import settings
from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import MultimodalDocumentParser

logger = logging.getLogger(__name__)

# 仅下列扩展名才会被多模态网关兜底:扫描件 PDF、图片、音视频。
# 文本型 PDF/Office/代码/Markdown 等已经被本地解析器覆盖,不送网关。
_MULTIMODAL_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "tif", "tiff",
    "mp4", "mov", "mkv", "mp3", "wav",
}


class HttpMultimodalDocumentParser(MultimodalDocumentParser):
    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """endpoint/api_key/timeout_seconds 默认从 settings 读取,允许测试时显式注入。

        留 `client` 参数方便单测里注入一个 transport=MockTransport 的 AsyncClient,
        不真去打网络就能覆盖网络异常、HTTP 5xx、响应 JSON 异常三类 fail-fast 路径。
        """
        self._endpoint = endpoint if endpoint is not None else settings.rag_multimodal_parser_endpoint
        self._api_key = api_key if api_key is not None else settings.rag_multimodal_parser_api_key
        cfg_timeout_ms = settings.rag_multimodal_parser_timeout_ms
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else max(1.0, cfg_timeout_ms / 1000.0)
        )
        self._client = client  # 调用方负责其生命周期;为 None 时按需创建
        self._owns_client = client is None

    def supports(self, document_input: DocumentInput) -> bool:
        if not settings.rag_multimodal_parser_enabled:
            return False
        if not self._endpoint:
            return False
        filename = document_input.filename()
        if not filename:
            return False
        return extension_of(filename) in _MULTIMODAL_EXTENSIONS

    async def parse(self, document_input: DocumentInput) -> ParsedDocument:
        if not self._endpoint:
            raise RuntimeError("多模态解析已启用但未配置 rag_multimodal_parser_endpoint")

        stream = document_input.open_stream()
        try:
            content = stream.read()
        finally:
            stream.close()

        # 关闭 `client` 的所有权判断:本对象是短生命周期解析动作,每次 parse 都创建
        # 一个新 client,避免跨请求复用 socket 引发 stale-connection 问题。
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout_seconds)

        filename = document_input.filename() or ""
        content_type = document_input.content_type() or "application/octet-stream"
        try:
            files = {"file": (filename, content, content_type)}
            data = {
                "documentId": str(document_input.document_id()),
                "filename": filename,
                "sourcePath": document_input.source_path(),
            }
            headers = self._build_headers()
            try:
                response = await client.post(
                    self._endpoint, files=files, data=data, headers=headers
                )
            except httpx.HTTPError as ex:
                # 任何 httpx 异常(连接拒绝、超时、SSL 等)都视为 fail-fast
                raise RuntimeError(
                    f"多模态解析网关不可达: {ex.__class__.__name__}: {ex}"
                ) from ex

            if response.status_code < 200 or response.status_code >= 300:
                # 非 2xx: 截断 body 到 500 字符避免把整个网关错误页塞进日志/异常 message
                body = (response.text or "").strip()
                if len(body) > 500:
                    body = body[:500]
                raise RuntimeError(
                    f"多模态解析网关返回 HTTP {response.status_code}"
                    + (f": {body}" if body else "")
                )

            try:
                payload: Any = json.loads(response.content)
            except json.JSONDecodeError as ex:
                raise RuntimeError(
                    f"多模态解析网关响应不是合法 JSON: {ex}"
                ) from ex

            return _to_parsed_document(document_input, payload)
        finally:
            if self._owns_client and client is not None:
                await client.aclose()

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


def _to_parsed_document(document_input: DocumentInput, payload: Any) -> ParsedDocument:
    """网关 JSON → ParsedDocument。响应结构不合法时抛 RuntimeError 让上层 fail-fast。"""
    if not isinstance(payload, dict):
        raise RuntimeError("多模态解析网关响应不是 JSON 对象")
    section_nodes = payload.get("sections")
    if not isinstance(section_nodes, list):
        raise RuntimeError("多模态解析网关响应缺少 sections 数组")

    sections: list[DocumentSection] = []
    for node in section_nodes:
        if not isinstance(node, dict):
            continue
        text = (node.get("text") or "").strip()
        if not text:
            continue
        raw_heading = node.get("headingPath") or node.get("heading_path") or []
        if not isinstance(raw_heading, list):
            raw_heading = []
        heading_path = tuple(str(h) for h in raw_heading if h is not None)
        page_no = _to_optional_int(node.get("pageNo"))
        line_start = _to_optional_int(node.get("lineStart"))
        line_end = _to_optional_int(node.get("lineEnd"))
        meta_raw = node.get("metadata") or {}
        if not isinstance(meta_raw, dict):
            meta_raw = {}
        metadata = {str(k): str(v) for k, v in meta_raw.items()}
        sections.append(DocumentSection(
            text=text,
            heading_path=heading_path,
            page_no=page_no,
            line_start=line_start,
            line_end=line_end,
            metadata=metadata,
        ))

    if not sections:
        raise RuntimeError("多模态解析网关未返回可索引文本")

    raw_meta = payload.get("metadata") or {}
    if not isinstance(raw_meta, dict):
        raw_meta = {}
    top_metadata: dict[str, str] = {str(k): str(v) for k, v in raw_meta.items()}
    top_metadata.setdefault("parser", "multimodal-gateway")
    top_metadata.setdefault("format", "multimodal")

    return ParsedDocument(
        document_id=document_input.document_id(),
        content_type=document_input.content_type(),
        source_path=document_input.source_path(),
        sections=tuple(sections),
        metadata=top_metadata,
    )


def _to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        # bool 是 int 的子类,需要单独排除掉 True/False 误当页码
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
