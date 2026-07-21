"""RAG Core 共享领域模型 —— 唯一权威定义。

对应 Java 版 `ragcore/model/` 包下的纯领域记录类。这些类型贯穿 parser/chunk/embedding/
index/retrieval/ingestion 各子包,因此放在 app.ragcore 顶层,避免子包互相循环 import。

Java 用 record 做不可变值对象；这里用 `frozen=True` 的 dataclass 对应,并在
`__post_init__` 里做同样的默认值归一化(None -> 空 tuple/dict,不可变复制)。

历史遗留说明:并行开发阶段,`app.ragcore.models`(复数,parser 子包用)和
`app.ragcore.chunk.models`(chunk 子包用)曾各自独立定义过一份 DocumentSection/
ParsedDocument/Chunk,导致 parser 的输出类型和 chunker 的输入类型实际上不是同一个类,
真实流水线(parse → chunk)接不起来。现在以本文件为唯一权威来源,`app.ragcore.models`
和 `app.ragcore.chunk.models` 改为对本文件的重新导出(向后兼容旧 import 路径),
新代码一律从 `app.ragcore.model` import。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class ModelClientException(RuntimeError):
    """模型服务不可用、超时或协议不兼容时抛出的可识别异常。

    对应 Java 版 `ragcore/model/ModelClientException.java`。调用方据此实现降级：
    Embedding 抛出时降级为 BM25-only，Rerank 抛出时直接使用 RRF 排序结果。
    """


class NeedsMultimodalParsingException(IOError):
    """本地解析器确认文档需要 OCR、版面理解或语音转写时抛出，由多模态网关接管。

    对应 Java 版 `NeedsMultimodalParsingException.java`。
    """


@runtime_checkable
class SupportsRead(Protocol):
    def read(self, size: int = -1) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class DocumentInput(Protocol):
    """待解析文档的抽象输入。对应 Java 版 `DocumentInput.java`。

    解析器只依赖这个协议，调用方可以把它实现成 MinIO/本地文件系统/内存测试数据，
    避免核心层绑定具体存储实现。`open_stream()` 返回的是同步二进制流(与现有
    parser-gateway 风格一致，解析器内部按需读取)。
    """

    def document_id(self) -> uuid.UUID: ...

    def filename(self) -> str: ...

    def content_type(self) -> str | None: ...

    def source_path(self) -> str: ...

    def open_stream(self) -> SupportsRead: ...


@dataclass(frozen=True)
class DocumentSection:
    """解析后、切分前的结构化文档区段。对应 Java 版 `DocumentSection.java` record。"""

    text: str | None
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    page_no: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "heading_path", tuple(self.heading_path or ()))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


@dataclass(frozen=True)
class ParsedDocument:
    """文档解析结果，保留标题层级、页码和代码等结构元数据。对应 Java 版 `ParsedDocument.java`。"""

    document_id: uuid.UUID
    content_type: str | None
    source_path: str
    sections: tuple[DocumentSection, ...] = field(default_factory=tuple)
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections or ()))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_json_dict(self) -> dict:
        """序列化为 ParsedArtifactStore 落盘用的 JSON 结构(camelCase 字段名，
        与 Java Jackson 默认序列化 ParsedDocument 的产物保持字段兼容)。"""
        return {
            "documentId": str(self.document_id),
            "contentType": self.content_type,
            "sourcePath": self.source_path,
            "sections": [
                {
                    "text": s.text,
                    "headingPath": list(s.heading_path),
                    "pageNo": s.page_no,
                    "lineStart": s.line_start,
                    "lineEnd": s.line_end,
                    "metadata": dict(s.metadata),
                }
                for s in self.sections
            ],
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_json_dict(data: dict) -> "ParsedDocument":
        sections = tuple(
            DocumentSection(
                text=s["text"],
                heading_path=tuple(s.get("headingPath") or ()),
                page_no=s.get("pageNo"),
                line_start=s.get("lineStart"),
                line_end=s.get("lineEnd"),
                metadata=dict(s.get("metadata") or {}),
            )
            for s in data.get("sections") or ()
        )
        return ParsedDocument(
            document_id=uuid.UUID(data["documentId"]),
            content_type=data.get("contentType"),
            source_path=data["sourcePath"],
            sections=sections,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class Chunk:
    """进入检索索引的最小上下文单元。对应 Java 版 `Chunk.java` record。"""

    id: str
    organization_id: UUID | None
    knowledge_base_id: UUID | None
    document_id: UUID | None
    ordinal: int
    content: str
    heading_path: tuple[str, ...] = field(default_factory=tuple)
    source_path: str | None = None
    page_no: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    language: str | None = None
    content_hash: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "heading_path", tuple(self.heading_path or ()))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))


@dataclass(frozen=True)
class RetrievedChunk:
    """混合检索与重排过程中的候选分块及其可解释分数。

    对应 Java 版 `ragcore/model/RetrievedChunk.java`。
    """

    chunk: Chunk
    bm25_rank: int | None = None
    vector_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    final_score: float | None = None


@dataclass(frozen=True)
class Citation:
    """供前端展示、审计与溯源使用的回答引用。对应 Java 版 `ragcore/model/Citation.java`。"""

    document_id: UUID | None
    document_name: str
    heading_path: tuple[str, ...]
    snippet: str
    page_no: int | None
    line_start: int | None
    line_end: int | None
    score: float | None


@dataclass(frozen=True)
class EmbeddingResult:
    """同一模型生成的一批向量；vectors 与输入文本必须按下标一一对应。

    对应 Java 版 `ragcore/model/EmbeddingResult.java`。
    """

    model_version: str
    vectors: tuple[tuple[float, ...], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "vectors", tuple(tuple(v) for v in (self.vectors or ())))


class QueryEventType(StrEnum):
    """SSE 查询流事件类型。对应 Java 版 `ragcore/model/QueryEventType.java`。

    枚举值即 SSE `event:` 头使用的小写稳定名称，对外协议不得依赖成员名本身。
    """

    CHUNK = "chunk"
    SOURCE = "source"
    REFUSAL = "refusal"
    SELF_CHECK_WARNING = "self_check_warning"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class QueryEvent:
    """查询流的统一输出事件。对应 Java 版 `ragcore/model/QueryEvent.java`。

    CHUNK 使用 content；SOURCE 使用 citation；REFUSAL、ERROR、SELF_CHECK_WARNING 使用
    message；DONE 不携带业务负载。
    """

    type: QueryEventType
    content: str | None = None
    citation: Citation | None = None
    message: str | None = None

    @property
    def sse_event_name(self) -> str:
        return self.type.value

    @staticmethod
    def chunk(content: str) -> "QueryEvent":
        return QueryEvent(QueryEventType.CHUNK, content=content)

    @staticmethod
    def source(citation: Citation) -> "QueryEvent":
        return QueryEvent(QueryEventType.SOURCE, citation=citation)

    @staticmethod
    def refusal(message: str) -> "QueryEvent":
        return QueryEvent(QueryEventType.REFUSAL, message=message)

    @staticmethod
    def self_check_warning(message: str) -> "QueryEvent":
        return QueryEvent(QueryEventType.SELF_CHECK_WARNING, message=message)

    @staticmethod
    def done() -> "QueryEvent":
        return QueryEvent(QueryEventType.DONE)

    @staticmethod
    def error(message: str) -> "QueryEvent":
        return QueryEvent(QueryEventType.ERROR, message=message)
