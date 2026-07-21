#!/usr/bin/env python3
"""评测集 dump 工具 —— 读取 corpus 目录里的所有文档，
用 V3 DocumentParserFactory 解析 + TechnicalChunker 切块，
输出 JSONL 索引（每行一个 chunk），供人工标注 ground-truth 使用。

移植自已删除的 `EvalCorpusIndexer.java`（V3 backend/ Java 后端退役后，evel 工具链
最后 4 个 Java 文件之一），调用 backend-py 的生产类（与 Java 版同一套解析/切块
逻辑的 Python 等价物），而非重新实现一套。

用法（可在任意目录下执行，脚本自己处理 backend-py 的 import 路径与 cwd）：

    python3 eval/scripts/eval_corpus_indexer.py <corpus-dir> <output.jsonl> [org-id] [kb-id]

例：

    python3 eval/scripts/eval_corpus_indexer.py \\
        eval/datasets/corpus/本科毕设 eval/datasets/corpus-index.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import BinaryIO

import _eval_common

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_KB_ID = "00000000-0000-0000-0000-000000000002"


class _FileDocumentInput:
    """基于本地文件系统的 `DocumentInput` 实现，绕开摄取编排层（对应 Java 内部类 `FileDocumentInput`）。"""

    def __init__(self, document_id: uuid.UUID, filename: str, content_type: str, source: Path) -> None:
        self._document_id = document_id
        self._filename = filename
        self._content_type = content_type
        self._source = source

    def document_id(self) -> uuid.UUID:
        return self._document_id

    def filename(self) -> str:
        return self._filename

    def content_type(self) -> str:
        return self._content_type

    def source_path(self) -> str:
        return str(self._source)

    def open_stream(self) -> BinaryIO:
        return self._source.open("rb")


def _guess_content_type(filename: str) -> str:
    """对应 Java `guessContentType`：按扩展名猜 content-type，逐个分支原样移植。"""
    lower = filename.lower()
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "text/markdown"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if lower.endswith(".txt"):
        return "text/plain"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".xml"):
        return "application/xml"
    if lower.endswith(".yaml") or lower.endswith(".yml"):
        return "application/x-yaml"
    if lower.endswith(".srt") or lower.endswith(".vtt"):
        return "text/plain"
    return "application/octet-stream"


def _snippet(content: str | None) -> str:
    """对应 Java `snippet`：去首尾空白后截断到 200 字符 + "..."。"""
    if content is None:
        return ""
    stripped = content.strip()
    return stripped if len(stripped) <= 200 else stripped[:200] + "..."


async def _run(corpus_dir: Path, output: Path, org_id: uuid.UUID, kb_id: uuid.UUID) -> None:
    # 延迟到 bootstrap_backend_py() 之后再 import，确保 app.* 能正确解析。
    from app.ragcore.chunk.models import ChunkingContext, ChunkingOptions
    from app.ragcore.chunk.technical_chunker import TechnicalChunker
    from app.ragcore.parser.code_parser import CodeParser
    from app.ragcore.parser.docx_parser import DocxParser
    from app.ragcore.parser.factory import DocumentParserFactory
    from app.ragcore.parser.local_multimodal_parser import LocalMultimodalDocumentParser
    from app.ragcore.parser.markdown_parser import MarkdownParser
    from app.ragcore.parser.pdf_parser import PdfParser
    from app.ragcore.parser.pptx_parser import PptxParser
    from app.ragcore.parser.structured_data_parser import StructuredDataParser
    from app.ragcore.parser.subtitle_parser import SubtitleParser
    from app.ragcore.parser.text_parser import TextParser

    # 与生产 `app/routers/_factories.py::build_parser_factory()` 完全同一份 9 个解析器链，
    # 保证「用产品真实解析逻辑」而非另起一套。
    parser_factory = DocumentParserFactory(
        [
            PdfParser(),
            DocxParser(),
            PptxParser(),
            MarkdownParser(),
            StructuredDataParser(),
            CodeParser(),
            TextParser(),
            SubtitleParser(),
            LocalMultimodalDocumentParser(),
        ]
    )
    chunker = TechnicalChunker()
    options = ChunkingOptions.defaults()
    context = ChunkingContext(org_id, kb_id)

    files = sorted(p for p in corpus_dir.iterdir() if p.is_file())

    file_count = 0
    skipped_count = 0
    chunk_count = 0
    lines: list[str] = []

    for path in files:
        filename = path.name
        content_type = _guess_content_type(filename)
        doc_id = _eval_common.java_name_uuid_from_bytes(filename.encode("utf-8"))

        try:
            document_input = _FileDocumentInput(doc_id, filename, content_type, path)
            parsed = await parser_factory.parse(document_input)
            chunks = chunker.chunk(parsed, context, options)

            for c in chunks:
                obj = {
                    "chunk_id": c.id,
                    "document_id": str(c.document_id),
                    "document_name": filename,
                    "ordinal": c.ordinal,
                    "heading_path": list(c.heading_path),
                    "page_no": c.page_no,
                    "line_start": c.line_start,
                    "line_end": c.line_end,
                    "language": c.language or "",
                    "content_hash": c.content_hash,
                    "snippet": _snippet(c.content),
                    "content": c.content,
                    "metadata": dict(c.metadata),
                }
                lines.append(json.dumps(obj, ensure_ascii=False))
                chunk_count += 1
            file_count += 1
            print(f"[ok] {filename} -> {len(chunks)} chunks")
        except Exception as ex:  # noqa: BLE001 - 单个文档失败不阻塞其他文件，对应 Java catch(Exception)
            skipped_count += 1
            print(f"[skip] {filename} : {ex}", file=sys.stderr)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    print()
    print("=================================")
    print(f"  files ok: {file_count}, skipped: {skipped_count}, chunks total: {chunk_count}")
    print(f"  output: {output}")
    print("=================================")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="评测集 dump 工具：用 V3 DocumentParserFactory + TechnicalChunker 解析/切块 corpus 目录，输出 JSONL 索引"
    )
    parser.add_argument("corpus_dir", help="语料目录（如 eval/datasets/corpus/本科毕设）")
    parser.add_argument("output", help="输出 JSONL 路径")
    parser.add_argument("org_id", nargs="?", default=DEFAULT_ORG_ID, help="切块用的组织 ID（默认占位值）")
    parser.add_argument("kb_id", nargs="?", default=DEFAULT_KB_ID, help="切块用的知识库 ID（默认占位值）")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    # 必须在 bootstrap_backend_py()（会 chdir 到 backend-py/）之前把用户传入的路径参数
    # 解析成绝对路径，否则相对路径会在 chdir 后指向错误位置。
    corpus_dir = Path(args.corpus_dir).resolve()
    output = Path(args.output).resolve()
    org_id = uuid.UUID(args.org_id)
    kb_id = uuid.UUID(args.kb_id)

    if not corpus_dir.is_dir():
        print(f"corpus-dir 不存在或不是目录: {corpus_dir}", file=sys.stderr)
        return 2

    _eval_common.bootstrap_backend_py()
    asyncio.run(_run(corpus_dir, output, org_id, kb_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
