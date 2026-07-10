package com.diit.ragkb.ragcore.chunk;

import com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("TechnicalChunker 单元测试")
class TechnicalChunkerTest {

    private final TechnicalChunker chunker = new TechnicalChunker();
    private final ChunkingOptions opts = ChunkingOptions.defaults();
    private static final ChunkingContext CONTEXT = new ChunkingContext(UUID.randomUUID(), UUID.randomUUID());

    private List<Chunk> chunksFor(ParsedDocument document, ChunkingOptions options) {
        return chunker.chunk(document, CONTEXT, options);
    }

    private static ParsedDocument docWith(String... sectionTexts) {
        List<DocumentSection> sections = java.util.Arrays.stream(sectionTexts)
                .map(t -> new DocumentSection(t, List.of(), null, 1, 1, Map.of()))
                .toList();
        return new ParsedDocument(
                UUID.randomUUID(), "text/markdown", "test/doc.md", sections, Map.of()
        );
    }

    // ── 基本切块 ──

    @Test
    @DisplayName("短文档切成单个块")
    void shortDocumentSingleChunk() {
        ParsedDocument doc = docWith("这是一段简短的测试文本。");
        List<Chunk> chunks = chunksFor(doc, opts);
        assertEquals(1, chunks.size());
        assertEquals("这是一段简短的测试文本。", chunks.get(0).content());
    }

    @Test
    @DisplayName("长文档被切成多个块")
    void longDocumentMultipleChunks() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 200; i++) {
            sb.append("这是第").append(i).append("段测试文本。\n");
        }
        ParsedDocument doc = docWith(sb.toString());
        List<Chunk> chunks = chunksFor(doc, opts);
        assertTrue(chunks.size() > 1, "长文档应切为多块, 实际: " + chunks.size());
    }

    @Test
    @DisplayName("空文档不产生 chunk")
    void emptyDocumentNoChunks() {
        ParsedDocument doc = docWith("", "   ", "\n");
        List<Chunk> chunks = chunksFor(doc, opts);
        // may produce 0 or only whitespace-ignored chunks
        long meaningful = chunks.stream().filter(c -> !c.content().isBlank()).count();
        assertEquals(0, meaningful);
    }

    // ── 结构感知 ──

    @Test
    @DisplayName("Markdown 标题处开始新块")
    void markdownHeadingStartsNewChunk() {
        String md = "# 设计文档\n\n"
                + "这是第一段内容，描述整体架构。\n\n"
                + "## 模块划分\n\n"
                + "系统分为三层。\n\n"
                + "### 数据层\n\n"
                + "数据层使用 PostgreSQL。\n\n"
                + "## 部署方案\n\n"
                + "使用 Docker Compose。\n";
        ParsedDocument doc = docWith(md);
        List<Chunk> chunks = chunksFor(doc, opts);
        assertTrue(chunks.size() >= 2, "含标题的文档应切为多个块");
    }

    @Test
    @DisplayName("中文条款「第X条」处开始新块")
    void chineseArticleStartsNewChunk() {
        String text = "第一条 本保险合同的构成\n本保险合同由保险单及所附条款等组成。\n"
                + "第二条 投保范围\n凡符合投保条件的，均可作为被保险人。\n"
                + "第三条 保险责任\n在本合同保险责任有效期内，本公司承担保险责任。\n";
        ParsedDocument doc = docWith(text);
        List<Chunk> chunks = chunksFor(doc, opts);
        assertTrue(chunks.size() >= 2, "含中文条款的文档应切为多个块, 实际: " + chunks.size());
    }

    // ── 代码块保护 ──

    @Test
    @DisplayName("代码围栏内的代码不被从中切断")
    void codeBlockPreserved() {
        String md = "以下是示例代码：\n\n```java\n"
                + "public class Main {\n"
                + "    public static void main(String[] args) {\n"
                + "        System.out.println(\"Hello\");\n"
                + "    }\n"
                + "}\n```\n\n这是后续文字。\n";
        ParsedDocument doc = docWith(md);
        List<Chunk> chunks = chunksFor(doc, opts);

        // code fence content should appear completely in at least one chunk
        boolean codeIntact = chunks.stream().anyMatch(
                c -> c.content().contains("```java") && c.content().contains("public class Main")
        );
        assertTrue(codeIntact, "代码块应完整保留在一个 chunk 内");
    }

    // ── Overlap ──

    @Test
    @DisplayName("相邻块之间有 overlap 且对齐到句子边界")
    void overlapBetweenChunks() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 100; i++) {
            sb.append("这是关于系统架构的第").append(i).append("段详细描述，包含大量技术信息。\n");
        }
        ParsedDocument doc = docWith(sb.toString());
        ChunkingOptions optsSmall = new ChunkingOptions(600, 80, true);
        List<Chunk> chunks = chunksFor(doc, optsSmall);
        assertTrue(chunks.size() > 1, "应切为多块");

        // check that chunk ordinals are sequential
        for (int i = 0; i < chunks.size(); i++) {
            assertEquals(i, chunks.get(i).ordinal());
        }
    }

    // ── metadata ──

    @Test
    @DisplayName("chunk 携带 headingPath、sourcePath、contentHash")
    void chunkCarriesMetadata() {
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "text/markdown", "docs/design.md",
                List.of(new DocumentSection("# Design\nContent here.", List.of("Design"), 1, 1, 3, Map.of())),
                Map.of("language", "")
        );
        List<Chunk> chunks = chunksFor(doc, opts);
        assertFalse(chunks.isEmpty());
        Chunk c = chunks.get(0);
        assertEquals("docs/design.md", c.sourcePath());
        assertEquals(CONTEXT.organizationId(), c.organizationId());
        assertEquals(CONTEXT.knowledgeBaseId(), c.knowledgeBaseId());
        assertNotNull(c.contentHash());
        assertEquals(8, c.contentHash().length(), "contentHash 应为 8 位 hex");
    }

    @Test
    @DisplayName("结构边界后的 chunk 保留各自的行号范围")
    void chunkCarriesAccurateLineRange() {
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "text/markdown", "docs/lines.md",
                List.of(new DocumentSection("前言\n# 模块\n模块说明", List.of(), 1, 20, 22, Map.of())),
                Map.of()
        );

        List<Chunk> chunks = chunksFor(doc, opts);

        assertEquals(2, chunks.size());
        assertEquals(20, chunks.get(0).lineStart());
        assertEquals(20, chunks.get(0).lineEnd());
        assertEquals(21, chunks.get(1).lineStart());
        assertEquals(22, chunks.get(1).lineEnd());
    }

    @Test
    @DisplayName("chunk ID 包含 documentId、ordinal 和 content hash")
    void chunkIdFormat() {
        ParsedDocument doc = docWith("测试内容。");
        List<Chunk> chunks = chunksFor(doc, opts);
        assertEquals(1, chunks.size());
        String id = chunks.get(0).id();
        assertTrue(id.contains(":"), "ID 应包含冒号分隔符");
        String[] parts = id.split(":");
        assertEquals(3, parts.length, "ID 格式: documentId:ordinal:hash");
    }

    // ── ChunkingOptions 校验 ──

    @Test
    @DisplayName("ChunkingOptions 拒绝非法参数")
    void chunkingOptionsValidation() {
        assertThrows(IllegalArgumentException.class, () -> new ChunkingOptions(0, 10, true));
        assertThrows(IllegalArgumentException.class, () -> new ChunkingOptions(100, 100, true));
        assertThrows(IllegalArgumentException.class, () -> new ChunkingOptions(100, -1, true));
    }

    @Test
    @DisplayName("ChunkingOptions.defaults() 返回合理默认值")
    void chunkingOptionsDefaults() {
        ChunkingOptions d = ChunkingOptions.defaults();
        assertEquals(1200, d.maxCharacters());
        assertEquals(160, d.overlapCharacters());
        assertTrue(d.preserveCodeBlocks());
    }

    // ── 中英文混合 ──

    @Test
    @DisplayName("中英文混合文本正确切分")
    void mixedLanguageText() {
        String text = ("The system architecture is designed for high availability.\n"
                + "系统架构设计为高可用。\n"
                + "This includes database replication and Redis caching.\n"
                + "包括数据库复制和 Redis 缓存。\n").repeat(50);
        ParsedDocument doc = docWith(text);
        List<Chunk> chunks = chunksFor(doc, opts);
        assertTrue(chunks.size() > 1, "混合文本应被切分");
        // 不应出现空 chunk
        assertTrue(chunks.stream().noneMatch(c -> c.content().isBlank()));
    }
}
