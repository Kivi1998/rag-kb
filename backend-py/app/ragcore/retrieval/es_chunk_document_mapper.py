"""ES Chunk 投影的反序列化唯一入口,避免词法召回与补齐路径字段漂移。

对应 Java 版 `ragcore/retrieval/ElasticsearchChunkDocumentMapper.java`(package-private,
仅供本包内 ES 实现复用)。Python 版以模块级私有约定实现。
"""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from app.ragcore.index.exceptions import ElasticsearchIndexException
from app.ragcore.model import Chunk

SOURCE_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "org_id",
    "kb_id",
    "document_id",
    "ordinal",
    "content",
    "heading_path",
    "source_path",
    "page_no",
    "line_start",
    "line_end",
    "language",
    "content_hash",
    "metadata",
)


def to_chunk(source: dict[str, Any] | Any) -> Chunk:
    """`_source` 字段或响应 dict 还原为 Chunk;缺关键字段时抛 ElasticsearchIndexException。"""
    try:
        org_id = _required_uuid(source, "org_id")
        kb_id = _required_uuid(source, "kb_id")
        document_id = _required_uuid(source, "document_id")
        heading_path = _string_list(source, "heading_path")
        metadata = _string_metadata(source, "metadata")
        return Chunk(
            id=_required_text(source, "chunk_id"),
            organization_id=org_id,
            knowledge_base_id=kb_id,
            document_id=document_id,
            ordinal=_required_int(source, "ordinal"),
            content=_required_text(source, "content"),
            heading_path=heading_path,
            source_path=_optional_text(source, "source_path"),
            page_no=_optional_int(source, "page_no"),
            line_start=_optional_int(source, "line_start"),
            line_end=_optional_int(source, "line_end"),
            language=_optional_text(source, "language"),
            content_hash=_optional_text(source, "content_hash"),
            metadata=metadata,
        )
    except ElasticsearchIndexException:
        raise
    except (ValueError, TypeError) as ex:
        raise ElasticsearchIndexException("ES chunk 字段不完整或类型错误") from ex


def _required_text(source: Any, field: str) -> str:
    value = _get(source, field)
    text = value if isinstance(value, str) else (value.asText() if hasattr(value, "asText") else None)
    if text is None or not text.strip():
        raise ElasticsearchIndexException(f"ES chunk 缺少字段 {field}")
    return text


def _optional_text(source: Any, field: str) -> str | None:
    value = _get(source, field)
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if hasattr(value, "asText"):
        text = value.asText()
        return text or None
    return str(value) or None


def _required_uuid(source: Any, field: str) -> UUID:
    text = _required_text(source, field)
    try:
        return UUID(text)
    except (ValueError, AttributeError) as ex:
        raise ElasticsearchIndexException(f"ES chunk 字段 {field} 不是合法 UUID: {text}") from ex


def _required_int(source: Any, field: str) -> int:
    value = _get(source, field)
    if value is None:
        raise ElasticsearchIndexException(f"ES chunk 缺少字段 {field}")
    if isinstance(value, bool):  # bool 是 int 子类,显式排除
        raise ElasticsearchIndexException(f"ES chunk 字段 {field} 必须是整数,不能是布尔")
    if isinstance(value, int):
        return value
    if hasattr(value, "asInt"):
        try:
            return int(value.asInt())
        except Exception as ex:  # noqa: BLE001
            raise ElasticsearchIndexException(f"ES chunk 字段 {field} 不是整数") from ex
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as ex:
            raise ElasticsearchIndexException(f"ES chunk 字段 {field} 不是整数: {value}") from ex
    raise ElasticsearchIndexException(f"ES chunk 字段 {field} 不是整数: {value!r}")


def _optional_int(source: Any, field: str) -> int | None:
    value = _get(source, field)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if hasattr(value, "isNumber") and value.isNumber():
        try:
            return int(value.intValue())
        except Exception:  # noqa: BLE001
            return None
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _string_list(source: Any, field: str) -> list[str]:
    value = _get(source, field)
    if value is None:
        return []
    result: list[str] = []
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                result.append(item)
            elif hasattr(item, "asText"):
                result.append(item.asText())
            else:
                result.append(str(item))
    return result


def _string_metadata(source: Any, field: str) -> dict[str, str]:
    value = _get(source, field)
    if value is None:
        return {}
    result: dict[str, str] = {}
    # 兼容 dict 与 ES JsonNode 对象(field 迭代 + asText)
    if hasattr(value, "fields"):
        try:
            for entry in value.fields():
                key = entry.getKey() if hasattr(entry, "getKey") else entry[0]
                node = entry.getValue() if hasattr(entry, "getValue") else entry[1]
                if hasattr(node, "asText"):
                    result[str(key)] = node.asText()
                else:
                    result[str(key)] = str(node)
            return result
        except Exception:  # noqa: BLE001
            return {}
    if isinstance(value, dict):
        for key, val in value.items():
            if hasattr(val, "asText"):
                result[str(key)] = val.asText()
            else:
                result[str(key)] = "" if val is None else str(val)
    return result


def _get(source: Any, field: str) -> Any:
    """dict 与 ES JsonNode 统一访问入口。"""
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(field)
    if hasattr(source, "path"):
        try:
            return source.path(field)
        except Exception:  # noqa: BLE001
            return None
    return None
