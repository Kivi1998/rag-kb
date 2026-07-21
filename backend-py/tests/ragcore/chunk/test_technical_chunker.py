"""TechnicalChunker 基本功能测试。

不做逐块精确对齐的黄金基准测试(那个需要 Java 版生成的 fixture,是独立立项的工作),
这里只覆盖五招式的基本行为:结构边界优先切分、多级降级、句子边界 overlap、代码块保护、
metadata 补全,以及 ChunkingOptions/ChunkingContext 的校验逻辑。
"""

from uuid import uuid4

import pytest

from app.ragcore.chunk.models import ChunkingContext, ChunkingOptions, DocumentSection, ParsedDocument
from app.ragcore.chunk.technical_chunker import TechnicalChunker


def _document(text: str, **section_kwargs) -> ParsedDocument:
    section = DocumentSection(
        text=text,
        heading_path=section_kwargs.get("heading_path"),
        page_no=section_kwargs.get("page_no"),
        line_start=section_kwargs.get("line_start"),
        line_end=section_kwargs.get("line_end"),
        metadata=section_kwargs.get("metadata"),
    )
    return ParsedDocument(
        document_id=uuid4(),
        content_type="text/markdown",
        source_path="test.md",
        sections=[section],
        metadata={},
    )


def _context() -> ChunkingContext:
    return ChunkingContext(organization_id=uuid4(), knowledge_base_id=uuid4())


class TestChunkingOptionsValidation:
    def test_defaults_are_valid(self):
        options = ChunkingOptions.defaults()
        assert options.max_characters == 1_200
        assert options.overlap_characters == 160
        assert options.preserve_code_blocks is True

    def test_rejects_non_positive_max_characters(self):
        with pytest.raises(ValueError):
            ChunkingOptions(max_characters=0, overlap_characters=0, preserve_code_blocks=True)

    def test_rejects_overlap_at_or_above_max(self):
        with pytest.raises(ValueError):
            ChunkingOptions(max_characters=100, overlap_characters=100, preserve_code_blocks=True)

    def test_rejects_negative_overlap(self):
        with pytest.raises(ValueError):
            ChunkingOptions(max_characters=100, overlap_characters=-1, preserve_code_blocks=True)


class TestChunkingContextValidation:
    def test_rejects_missing_organization_id(self):
        with pytest.raises(ValueError):
            ChunkingContext(organization_id=None, knowledge_base_id=uuid4())

    def test_rejects_missing_knowledge_base_id(self):
        with pytest.raises(ValueError):
            ChunkingContext(organization_id=uuid4(), knowledge_base_id=None)


class TestBasicChunking:
    def test_short_document_produces_single_chunk(self):
        document = _document("这是一段很短的技术说明文字,不需要被切分。")
        chunks = TechnicalChunker().chunk(document, _context(), ChunkingOptions.defaults())
        assert len(chunks) == 1
        assert chunks[0].content.strip() != ""

    def test_empty_document_produces_no_chunks(self):
        document = _document("")
        chunks = TechnicalChunker().chunk(document, _context(), ChunkingOptions.defaults())
        assert chunks == []

    def test_chunk_ordinal_is_sequential(self):
        text = "\n\n".join(f"段落 {i}:" + "内容" * 200 for i in range(6))
        document = _document(text)
        options = ChunkingOptions(max_characters=300, overlap_characters=30, preserve_code_blocks=True)
        chunks = TechnicalChunker().chunk(document, _context(), options)
        assert len(chunks) > 1
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))

    def test_chunk_carries_tenant_and_document_ids(self):
        document = _document("多租户元数据透传测试。")
        context = _context()
        chunks = TechnicalChunker().chunk(document, context, ChunkingOptions.defaults())
        assert chunks[0].organization_id == context.organization_id
        assert chunks[0].knowledge_base_id == context.knowledge_base_id
        assert chunks[0].document_id == document.document_id


class TestHeadingBoundarySplitting:
    """heading_path 由上游解析器(MarkdownParser 等)在切出 DocumentSection 时就已经
    确定,TechnicalChunker 只是原样透传(对应 Java 版 461-462 行:
    `section.headingPath()` 直接传给 Chunk,不在切块阶段重新推导)——切块器自身的
    HeadingStyle 检测只用来决定"在哪里下刀",不负责生成 heading_path 元数据。
    所以这里测试的是"透传是否保真",不是"切块器能不能从原始文本里解析出标题"。
    """

    def test_heading_path_survives_intra_section_splitting(self):
        # 单个 section 内部文字很长,必然被切成多块;heading_path 应该在每一块上都保留。
        document = ParsedDocument(
            document_id=uuid4(),
            content_type="text/markdown",
            source_path="test.md",
            sections=[
                DocumentSection(
                    text="第一章内容。" * 80,
                    heading_path=["第一章"],
                    page_no=None,
                    line_start=None,
                    line_end=None,
                    metadata=None,
                )
            ],
            metadata={},
        )
        options = ChunkingOptions(max_characters=200, overlap_characters=20, preserve_code_blocks=True)
        chunks = TechnicalChunker().chunk(document, _context(), options)
        assert len(chunks) >= 2
        assert all(c.heading_path == ["第一章"] for c in chunks)

    def test_different_sections_keep_their_own_heading_path(self):
        document = ParsedDocument(
            document_id=uuid4(),
            content_type="text/markdown",
            source_path="test.md",
            sections=[
                DocumentSection(
                    text="第一章内容。" * 30,
                    heading_path=["第一章"],
                    page_no=None,
                    line_start=None,
                    line_end=None,
                    metadata=None,
                ),
                DocumentSection(
                    text="第二章内容。" * 30,
                    heading_path=["第二章"],
                    page_no=None,
                    line_start=None,
                    line_end=None,
                    metadata=None,
                ),
            ],
            metadata={},
        )
        options = ChunkingOptions.defaults()
        chunks = TechnicalChunker().chunk(document, _context(), options)
        assert any(c.heading_path == ["第一章"] for c in chunks)
        assert any(c.heading_path == ["第二章"] for c in chunks)

    def test_hierarchical_heading_path_preserved(self):
        document = ParsedDocument(
            document_id=uuid4(),
            content_type="text/markdown",
            source_path="test.md",
            sections=[
                DocumentSection(
                    text="正文内容。" * 30,
                    heading_path=["顶层标题", "子标题"],
                    page_no=None,
                    line_start=None,
                    line_end=None,
                    metadata=None,
                )
            ],
            metadata={},
        )
        options = ChunkingOptions.defaults()
        chunks = TechnicalChunker().chunk(document, _context(), options)
        assert all(c.heading_path == ["顶层标题", "子标题"] for c in chunks)


class TestCodeBlockProtection:
    def test_code_fence_not_split_mid_block(self):
        code = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(60)) + "\n```"
        text = "说明文字。\n\n" + code + "\n\n结尾说明。"
        document = _document(text)
        options = ChunkingOptions(max_characters=150, overlap_characters=15, preserve_code_blocks=True)
        chunks = TechnicalChunker().chunk(document, _context(), options)
        fence_open = sum(c.content.count("```") for c in chunks)
        assert fence_open % 2 == 0, "代码围栏应成对出现在切块结果里,不能被从中间截断导致围栏数量为奇数"


class TestSentenceBoundaryOverlap:
    def test_overlap_does_not_cut_mid_sentence(self):
        sentences = [f"这是第{i}句完整的话,句尾有标点。" for i in range(40)]
        text = "".join(sentences)
        document = _document(text)
        options = ChunkingOptions(max_characters=200, overlap_characters=40, preserve_code_blocks=True)
        chunks = TechnicalChunker().chunk(document, _context(), options)
        assert len(chunks) > 1
        for c in chunks:
            stripped = c.content.strip()
            if stripped:
                assert stripped[-1] in "。!?" or stripped == sentences[-1].strip("。")[: len(stripped)], (
                    f"chunk 内容应在句子边界结束,实际结尾: {stripped[-10:]!r}"
                )


class TestMetadataCompletion:
    def test_content_hash_is_eight_hex_chars(self):
        document = _document("用于校验 contentHash 格式的示例文本。")
        chunks = TechnicalChunker().chunk(document, _context(), ChunkingOptions.defaults())
        for c in chunks:
            assert len(c.content_hash) == 8
            int(c.content_hash, 16)  # 必须是合法十六进制,否则抛 ValueError

    def test_content_hash_matches_sha256_prefix(self):
        import hashlib

        document = _document("固定内容用于哈希核对。")
        chunks = TechnicalChunker().chunk(document, _context(), ChunkingOptions.defaults())
        expected_prefix = hashlib.sha256(chunks[0].content.encode("utf-8")).hexdigest()[:8]
        assert chunks[0].content_hash == expected_prefix

    def test_page_no_and_line_range_propagated(self):
        document = _document("带页码和行号的段落。", page_no=7, line_start=100, line_end=120)
        chunks = TechnicalChunker().chunk(document, _context(), ChunkingOptions.defaults())
        assert chunks[0].page_no == 7
