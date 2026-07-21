"""向后兼容重导出层。

真正的定义已收敛到 `app.ragcore.model`(单数)——这个模块(复数)最初是并行开发时
另一份独立的领域模型定义，与 `app.ragcore.model` 及 `app.ragcore.chunk.models` 三处各自
定义了一份 DocumentSection/ParsedDocument/Chunk，导致 parser 的输出类型和 chunker 的
输入类型实际上不是同一个类，真实流水线(parse → chunk)接不起来；现已收敛为一处。

parser/ 子包的文件都 import 自这里，为了不用同时改 8 个文件的 import 语句，保留这个
模块名作为重导出入口。**新代码请直接从 `app.ragcore.model` import，不要在这个文件里
新增定义。**
"""

from __future__ import annotations

from app.ragcore.model import (
    Chunk,
    DocumentInput,
    DocumentSection,
    EmbeddingResult,
    NeedsMultimodalParsingException,
    ParsedDocument,
    SupportsRead,
)

__all__ = [
    "Chunk",
    "DocumentInput",
    "DocumentSection",
    "EmbeddingResult",
    "NeedsMultimodalParsingException",
    "ParsedDocument",
    "SupportsRead",
]
