"""结构化技术文档切块的数据模型。

对应 Java 版:
- com.diit.ragkb.ragcore.model.DocumentSection / ParsedDocument / Chunk
- com.diit.ragkb.ragcore.chunk.ChunkingContext / ChunkingOptions

Java record 的字段校验(compact constructor 里的非空/取值范围检查)与不可变语义
(List.copyOf/Map.copyOf 防御性拷贝)在这里分别对应到 frozen dataclass 的
__post_init__ 里做校验 + 防御性拷贝。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DocumentSection:
    """解析后、切分前的结构化文档区段。对应 Java DocumentSection record。"""

    text: str | None
    heading_path: list[str] | None
    page_no: int | None
    line_start: int | None
    line_end: int | None
    metadata: dict[str, str] | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "heading_path", list(self.heading_path) if self.heading_path is not None else []
        )
        object.__setattr__(self, "metadata", dict(self.metadata) if self.metadata is not None else {})


@dataclass(frozen=True)
class ParsedDocument:
    """文档解析结果,保留标题层级、页码和代码等结构元数据。对应 Java ParsedDocument record。"""

    document_id: UUID
    content_type: str
    source_path: str
    sections: list[DocumentSection] | None
    metadata: dict[str, str] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", list(self.sections) if self.sections is not None else [])
        object.__setattr__(self, "metadata", dict(self.metadata) if self.metadata is not None else {})


@dataclass(frozen=True)
class ChunkingContext:
    """服务端摄取编排层注入的、不可为空的租户与知识库上下文。对应 Java ChunkingContext record。"""

    organization_id: UUID
    knowledge_base_id: UUID

    def __post_init__(self) -> None:
        if self.organization_id is None:
            raise ValueError("organization_id 不能为空")
        if self.knowledge_base_id is None:
            raise ValueError("knowledge_base_id 不能为空")


@dataclass(frozen=True)
class ChunkingOptions:
    """结构感知切分的可配置参数。对应 Java ChunkingOptions record。"""

    max_characters: int
    overlap_characters: int
    preserve_code_blocks: bool

    def __post_init__(self) -> None:
        if self.max_characters <= 0:
            raise ValueError("max_characters 必须大于 0")
        if self.overlap_characters < 0 or self.overlap_characters >= self.max_characters:
            raise ValueError("overlap_characters 必须大于等于 0 且小于 max_characters")

    @staticmethod
    def defaults() -> "ChunkingOptions":
        """默认参数:max_characters=1200,overlap_characters=160(约 13.3%),落在
        10%-20% 的性价比区间内——overlap 从 0 加到约 10%-20% 对应字符数时召回率
        提升明显,继续加大到 2-3 倍则召回只再小幅提升,但存储和 embedding 成本
        线性上升,不值得。
        """
        return ChunkingOptions(1_200, 160, True)


@dataclass(frozen=True)
class Chunk:
    """进入检索索引的最小上下文单元。对应 Java Chunk record。"""

    id: str
    organization_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    ordinal: int
    content: str
    heading_path: list[str] | None
    source_path: str
    page_no: int | None
    line_start: int | None
    line_end: int | None
    language: str
    content_hash: str
    metadata: dict[str, str] | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "heading_path", list(self.heading_path) if self.heading_path is not None else []
        )
        object.__setattr__(self, "metadata", dict(self.metadata) if self.metadata is not None else {})
