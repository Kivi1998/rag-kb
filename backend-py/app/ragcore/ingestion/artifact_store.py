"""解析结果对象存储,避免后续阶段重试时重复执行高成本 OCR。

对应 Java 版 `ragcore/ingestion/ParsedArtifactStore.java`。
产物路径约定: `<原始对象路径>.parsed-v<版本>.json`,与 `parserVersion` 字段对齐
——版本不一致时强制重新解析,避免 parser 升级后复用旧产物。
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import IO, Protocol, runtime_checkable

from app.ragcore.models import ParsedDocument
from app.ragcore.ingestion.task import IngestionTask
from app.ragcore.storage.object_storage import ObjectStorage

logger = logging.getLogger(__name__)

CURRENT_VERSION: str = "1"


class SavedArtifact:
    def __init__(self, path: str, parser_name: str, parser_version: str) -> None:
        self.path = path
        self.parser_name = parser_name
        self.parser_version = parser_version


@runtime_checkable
class ParsedArtifactStorePort(Protocol):
    async def load(self, task: IngestionTask) -> ParsedDocument | None: ...

    async def save(self, task: IngestionTask, parsed: ParsedDocument) -> SavedArtifact: ...


class ParsedArtifactStore:
    """对象存储后端的解析产物存取器;`object_storage` 必填,`object_mapper` 可选。"""

    def __init__(self, object_storage: ObjectStorage) -> None:
        self._storage = object_storage

    async def load(self, task: IngestionTask) -> ParsedDocument | None:
        if (
            not task.parse_artifact_path
            or task.parser_version is None
            or task.parser_version != CURRENT_VERSION
        ):
            return None
        try:
            stream = await self._storage.open(task.parse_artifact_path)
        except (FileNotFoundError, IOError):
            return None
        try:
            data = await asyncio.to_thread(stream.read)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        try:
            obj = json.loads(data)
            return ParsedDocument.from_json_dict(obj) if hasattr(ParsedDocument, "from_json_dict") else _from_obj(obj)
        except (json.JSONDecodeError, KeyError, ValueError) as ex:
            logger.warning(
                "解析产物读取失败,将重新解析,documentId=%s, artifact=%s: %s",
                task.document_id, task.parse_artifact_path, ex,
            )
            return None

    async def save(self, task: IngestionTask, parsed: ParsedDocument) -> SavedArtifact:
        artifact_path = f"{task.object_storage_path}.parsed-v{CURRENT_VERSION}.json"
        if hasattr(parsed, "to_json_dict"):
            payload = parsed.to_json_dict()
        else:
            payload = _to_obj(parsed)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # 序列化到临时文件以获取 size,然后走对象存储 put
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        try:
            size = tmp_path.stat().st_size
            with tmp_path.open("rb") as f:
                await self._storage.put(artifact_path, f, size, "application/json")
        finally:
            tmp_path.unlink(missing_ok=True)
        parser_name = ""
        metadata = getattr(parsed, "metadata", None)
        if isinstance(metadata, dict):
            parser_name = str(metadata.get("parser", "local-python-parser"))
        else:
            parser_name = "local-python-parser"
        return SavedArtifact(
            path=artifact_path,
            parser_name=parser_name,
            parser_version=CURRENT_VERSION,
        )


def _to_obj(parsed: ParsedDocument) -> dict:
    """兼容 `app.ragcore.chunk.models.ParsedDocument`(无 to_json_dict)的回退序列化。"""
    sections = []
    for s in getattr(parsed, "sections", []) or []:
        sections.append(
            {
                "text": getattr(s, "text", None),
                "headingPath": list(getattr(s, "heading_path", []) or []),
                "pageNo": getattr(s, "page_no", None),
                "lineStart": getattr(s, "line_start", None),
                "lineEnd": getattr(s, "line_end", None),
                "metadata": dict(getattr(s, "metadata", {}) or {}),
            }
        )
    return {
        "documentId": str(getattr(parsed, "document_id", "")),
        "contentType": getattr(parsed, "content_type", None),
        "sourcePath": getattr(parsed, "source_path", ""),
        "sections": sections,
        "metadata": dict(getattr(parsed, "metadata", {}) or {}),
    }


def _from_obj(data: dict) -> ParsedDocument:
    """反序列化回 ParsedDocument;为保持与 storage 侧零额外依赖,字段直接走 setattr 兜底。"""
    from app.ragcore.models import DocumentSection, ParsedDocument

    sections = []
    for s in data.get("sections") or []:
        sections.append(
            DocumentSection(
                text=s.get("text"),
                heading_path=tuple(s.get("headingPath") or ()),
                page_no=s.get("pageNo"),
                line_start=s.get("lineStart"),
                line_end=s.get("lineEnd"),
                metadata=dict(s.get("metadata") or {}),
            )
        )
    return ParsedDocument(
        document_id=data["documentId"],
        content_type=data.get("contentType"),
        source_path=data["sourcePath"],
        sections=tuple(sections),
        metadata=dict(data.get("metadata") or {}),
    )
