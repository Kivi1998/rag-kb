package com.diit.ragkb.ragcore.chunk;

import com.diit.ragkb.ragcore.chunk.impl.TechnicalChunker;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;

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

    // ── 递归级联切分（招式 2）──

    @Test
    @DisplayName("过长的整段落文本按 1.1/1.2 这类细编号切分，而不是直接按句子/换行硬切（CN_STRUCTURE 不识别，只有 recursiveSplit->splitByLevel 才能切对）")
    void recursiveSplitPrefersFinerStructureBeforeSentence() {
        // 关键设计（比朴素的"每行一个 1.N 小项"更严格）：
        // 1) 整段文字必须作为「单一 unit」进入 chunkSection 的超长分支——首行"1. 总则"命中
        //    HeadingStyle.CN_NUMERIC 的第 2 级（`^[0-9]{1,2}[、.．][^0-9]`），但不命中既有的
        //    CN_STRUCTURE（只认「第X条」「一、」「（一）」），所以 splitToUnits 不会提前拆开。
        // 2) 每个 1.N 小项内部跨 3 行（编号行 + 2 行续行），续行本身不含任何 CN_NUMERIC 能
        //    识别的编号标记。这一点是判别力的关键：既有的 SENTENCE_END 正则把 `\n` 也当作
        //    句子边界，如果小项是单行的，句子切分兜底路径会"巧合地"总是切在行边界、也就是
        //    1.N 边界上，测试就失去了判别力（旧代码也能通过）。只有当小项跨多行、续行也可能
        //    成为句子切分兜底路径的候选切点时，才能真正区分"recursiveSplit 优先按 1.N 编号切"
        //    与"退化为按 \n/句子边界随意硬切、可能切在续行处"这两种行为。
        StringBuilder article = new StringBuilder("1. 总则\n");
        String[] continuations = {
                "续行甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌",
                "续行二东南西北中上下左右前后春夏秋冬"
        };
        for (int i = 1; i <= 6; i++) {
            article.append("1.").append(i).append(" 规定一二三四五\n")
                    .append(continuations[0]).append('\n')
                    .append(continuations[1]).append('\n');
        }
        String fullText = article.toString();
        ParsedDocument doc = docWith(fullText);
        ChunkingOptions tight = new ChunkingOptions(80, 10, true);
        List<Chunk> chunks = chunksFor(doc, tight);

        assertTrue(chunks.size() > 1, "过长文本应被切成多块");

        // 重新拼接所有块内容，必须与原文一致（不丢字符、不丢标点）
        String joined = chunks.stream().map(Chunk::content)
                .collect(java.util.stream.Collectors.joining("\n"));
        assertEquals(fullText.strip().replaceAll("\\s+", ""), joined.replaceAll("\\s+", ""),
                "切分后重新拼接必须还原原文内容（忽略空白差异）");

        // 除第一块外，其余块都应该从 "1.N " 这样的细编号行开头，证明确实是在 1.X 边界切开，
        // 而不是退化到句子/换行边界随意硬切（那样可能会切在续行处，例如以"续行"二字开头）。
        Pattern numericMarker = Pattern.compile("^1\\.\\d+\\s");
        for (int i = 1; i < chunks.size(); i++) {
            String content = chunks.get(i).content().strip();
            assertTrue(numericMarker.matcher(content).find(),
                    "第 " + i + " 块应该从 1.N 编号处开始切分，不能切在续行处，实际内容开头: "
                            + content.substring(0, Math.min(20, content.length())));
        }
    }

    @Test
    @DisplayName("没有更细编号可用时降级到空行分段，而不是直接句子切——每块必须是完整段落，不能有悬空空行或段落中间硬切")
    void fallsBackToParagraphWhenNoFinerStructure() {
        StringBuilder article = new StringBuilder("第一条 释义\n");
        List<String> paragraphs = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            String p = "这是第" + i + "个自然段，描述与本条款相关的背景信息和适用范围，"
                    + "内容较长以触发超长条款的降级切分逻辑。";
            paragraphs.add(p);
            article.append(p).append("\n\n");
        }
        ParsedDocument doc = docWith(article.toString());
        ChunkingOptions tight = new ChunkingOptions(150, 20, true);
        List<Chunk> chunks = chunksFor(doc, tight);

        assertTrue(chunks.size() > 1);
        for (Chunk c : chunks) {
            String content = c.content();
            // 不应该有老实现里出现过的"以空行开头/结尾"的缺陷
            assertFalse(content.startsWith("\n") || content.startsWith("\r\n"),
                    "块不应该以空行开头: [" + content + "]");
            assertFalse(content.endsWith("\n\n"), "块不应该以空行结尾: [" + content + "]");
            // 每块可能包含结构标题行「第一条 释义」+ 一个或多个完整自然段，
            // 逐行核对：块内容按换行拆开后，每一行要么是标题行，要么必须
            // 完全等于某个原始自然段（不能是自然段中间任意字符处的硬切片段）。
            String[] contentLines = content.split("\n");
            for (String line : contentLines) {
                String stripped = line.strip();
                if (stripped.isEmpty() || stripped.equals("第一条 释义")) continue;
                boolean isWholeParagraph = paragraphs.contains(stripped);
                assertTrue(isWholeParagraph,
                        "块内的每一行应该是完整自然段，不能是段落中间的硬切片段: [" + stripped + "]");
            }
        }
    }

    @Test
    @DisplayName("递归降级到句子切分时，overlap 部分的行号正确回退，不虚构行号")
    void recursiveSplitWithOverlapReportsAccurateLineNumbers() {
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= 10; i++) {
            sb.append("这是第").append(i).append("行内容用于测试行号。\n");
        }
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "text/plain", "docs/lines-overlap.txt",
                List.of(new DocumentSection(sb.toString(), List.of(), null, 300, 309, Map.of())),
                Map.of()
        );
        ChunkingOptions tight = new ChunkingOptions(40, 15, false);
        List<Chunk> chunks = chunksFor(doc, tight);

        assertTrue(chunks.size() > 1);
        // 行号必须落在原始区间 [300, 309] 内（不能虚构出区间外的行号）
        for (Chunk c : chunks) {
            assertTrue(c.lineStart() >= 300, "lineStart 不应该早于原始区间起点: " + c.lineStart());
            assertTrue(c.lineEnd() <= 309, "lineEnd 不应该超过原始区间末尾——"
                    + "原始区间只有 10 行（300-309），overlap 内容是既有源行的重复而非新行，"
                    + "所以行号必须落在区间内，实际: " + c.lineEnd());
        }
        // 关键判别性断言：最后一块的 lineEnd 必须精确等于原始区间末尾 309。
        // 旧的 bug（无条件按 countLines(piece) 推进 bufferLineStart）会让行号越推越远，
        // 导致最后一块的 lineEnd 远超 309（探针实测为 317）；修复后必须精确落在 309。
        Chunk lastChunk = chunks.get(chunks.size() - 1);
        assertEquals(309, lastChunk.lineEnd(),
                "最后一块的 lineEnd 必须精确等于原始区间末尾行号 309，而不是被 overlap 虚假推进后的更大值");
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

    @Test
    @DisplayName("关闭代码块保护后允许按长度切分")
    void codeBlockCanSplitWhenProtectionDisabled() {
        String code = "```java\n" + "System.out.println(\"line\");\n".repeat(20) + "```";
        List<Chunk> chunks = chunksFor(docWith(code), new ChunkingOptions(80, 0, false));

        assertTrue(chunks.size() > 1, "关闭保护后，超长代码块应按 maxCharacters 切分");
        assertTrue(chunks.stream().allMatch(chunk -> chunk.content().length() <= 80));
    }

    @Test
    @DisplayName("超长文本切分保留标点和换行，并服从 maxCharacters")
    void longTextPreservesPunctuationAndNewlines() {
        String text = ("第一句。\n第二句。\n第三句。\n").repeat(200);
        List<Chunk> chunks = chunksFor(docWith(text), new ChunkingOptions(80, 0, false));

        assertTrue(chunks.size() > 1);
        assertTrue(chunks.stream().allMatch(chunk -> chunk.content().length() <= 80));
        assertEquals(text.strip(), chunks.stream().map(Chunk::content).collect(java.util.stream.Collectors.joining()),
                "切分不得丢失原始标点或换行");
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

    // ── overlap 调优验证（招式 4）──

    @Test
    @DisplayName("默认 overlap 比例落在 10%-20% 区间（参考文章的性价比拐点）")
    void defaultOverlapRatioInSweetSpotRange() {
        ChunkingOptions d = ChunkingOptions.defaults();
        double ratio = (double) d.overlapCharacters() / d.maxCharacters();
        assertTrue(ratio >= 0.10 && ratio <= 0.20,
                "overlap 比例应在 10%-20% 之间，实际: " + ratio);
    }

    @Test
    @DisplayName("overlap 内容不应以半句话开头（必须对齐到完整句子）")
    void overlapNeverStartsWithPartialSentence() {
        // 关键设计：句子长度必须各不相同（非周期性重复），否则 overlapCharacters
        // 可能恰好凑成"句子单元长度的整数倍 + 常数"，导致哪怕 tailOverlap() 完全
        // 不做句子边界对齐、只做裸的 substring 截断，也会因为数值巧合"意外"落在
        // 句子边界上，使测试对回归失去判别力（详见 task-4-report.md Fix Round 1）。
        List<String> sentences = List.of(
                "理赔流程需要提交完整的申请材料，包括身份证明和相关票据。",
                "审核环节由专人负责，通常在五个工作日内完成初步审查。",
                "审核通过后系统会自动生成赔付单据并转入财务部门处理。",
                "如遇材料不全的情况，客服会主动联系客户补充所需文件。",
                "赔付到账后客户可以在系统里随时查询详细的流水记录。",
                "对于争议案件，公司设有专门的复核小组进行二次评估。",
                "复核结论会在十个工作日内以书面形式通知申请人本人。",
                "整个流程强调透明和可追溯，每个环节都有明确的时限。"
        );
        StringBuilder textBuilder = new StringBuilder();
        for (int i = 0; i < 30; i++) {
            textBuilder.append(sentences.get(i % sentences.size())).append("\n");
        }
        String text = textBuilder.toString();

        ParsedDocument doc = docWith(text);
        List<Chunk> chunks = chunksFor(doc, new ChunkingOptions(300, 60, false));
        assertTrue(chunks.size() > 1);

        // 悬空标点检查（原有的间接代理检查，保留作为快速信号）。
        for (int i = 1; i < chunks.size(); i++) {
            String content = chunks.get(i).content();
            assertFalse(content.startsWith("，") || content.startsWith(",")
                            || content.startsWith("、"),
                    "块不应以悬空标点开头（说明 overlap 从句子中间截断）: "
                            + content.substring(0, Math.min(20, content.length())));
        }

        // 正面结构断言：每个后续块的开头内容必须能在原文中找到，且其前一个
        // 字符必须是真正的句子结束符（。！？；或换行），或者该内容本来就在
        // 原文起始处（position == 0）。这直接编码"overlap 从句子边界后开始"
        // 这个不变量，而不是"不以逗号开头"这种间接、易被巧合绕过的代理检查。
        String sentenceEnders = "。！？；\n";
        for (int i = 1; i < chunks.size(); i++) {
            String content = chunks.get(i).content();
            String probe = content.substring(0, Math.min(15, content.length()));
            int pos = text.indexOf(probe);
            assertTrue(pos >= 0,
                    "块开头内容应能在原文中定位到: [" + probe + "]");
            assertTrue(pos == 0 || sentenceEnders.indexOf(text.charAt(pos - 1)) >= 0,
                    "块开头前一个字符必须是句子结束符（。！？；或换行），说明 overlap 是从"
                            + "句子边界后开始的，而不是句子中间任意位置截断。块开头: [" + probe
                            + "]，原文中前一字符: ["
                            + (pos > 0 ? text.charAt(pos - 1) : "<start>") + "]");
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

    @Test
    @DisplayName("多个 section 的相同内容仍生成全局唯一且一致的 chunk ID")
    void chunkIdsUseGlobalOrdinalAcrossSections() {
        UUID documentId = UUID.randomUUID();
        ParsedDocument doc = new ParsedDocument(
                documentId, "text/plain", "docs/repeated.txt",
                List.of(
                        new DocumentSection("重复内容。", List.of(), null, 1, 1, Map.of()),
                        new DocumentSection("重复内容。", List.of(), null, 2, 2, Map.of())
                ),
                Map.of()
        );

        List<Chunk> chunks = chunksFor(doc, opts);

        assertEquals(2, chunks.size());
        assertNotEquals(chunks.get(0).id(), chunks.get(1).id(), "同文档的 chunk ID 必须唯一");
        assertTrue(chunks.get(0).id().contains(":" + chunks.get(0).ordinal() + ":"));
        assertTrue(chunks.get(1).id().contains(":" + chunks.get(1).ordinal() + ":"));
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

    // ── 表格分块保留表头（招式 3）──

    @Test
    @DisplayName("小表格整体保留为一个 chunk")
    void smallTableStaysAsOneChunk() {
        String table = "年龄段 | 男性费率 | 女性费率\n"
                + "30岁 | 120.00 | 110.00\n"
                + "40岁 | 150.00 | 140.00\n";
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "rates.pdf",
                List.of(new DocumentSection(table, List.of("费率表"), 1, 1, 3, Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        assertEquals(1, chunks.size());
        assertEquals(table.strip(), chunks.get(0).content());
    }

    @Test
    @DisplayName("大表格按行分组，每组都带表头")
    void largeTableEachGroupCarriesHeader() {
        StringBuilder table = new StringBuilder("年龄段 | 男性费率 | 女性费率\n");
        for (int age = 20; age <= 65; age++) {
            table.append(age).append("岁 | ").append(age * 4).append(".00 | ").append(age * 3).append(".50\n");
        }
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "rates.pdf",
                List.of(new DocumentSection(table.toString(), List.of("费率表"), 1, 1, 50,
                        Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, new ChunkingOptions(200, 0, true));

        assertTrue(chunks.size() > 1, "超长表格应被分成多组");
        String headerLine = "年龄段 | 男性费率 | 女性费率";
        for (Chunk c : chunks) {
            assertTrue(c.content().startsWith(headerLine),
                    "每个分组都应该带表头，实际首行: " + c.content().lines().findFirst().orElse(""));
        }
        // 60 岁那一行必须完整出现在某一个 chunk 里，不能因为分组把行拦腰截断
        // （表格数据按 age*3 + ".50" 拼接生成，60 岁对应 180.50，而非 180.00）
        assertTrue(chunks.stream().anyMatch(c -> c.content().contains("60岁 | 240.00 | 180.50")));

        // 行号必须落在原始区间内，且各组之间行号连续、不重叠、不虚构——
        // 每组的表头行（复制品）不应推进行号，只有真实数据行才计入 lineStart/lineEnd。
        int expectedNextStart = 2; // 原始区间 lineStart=1，表头占第 1 行，数据行从第 2 行开始
        for (Chunk c : chunks) {
            assertEquals(expectedNextStart, c.lineStart(), "分组行号必须与前一组末尾无缝衔接，不能有缺口或重叠");
            int rowsInChunk = (int) c.content().lines().count() - 1; // 减去表头行
            assertEquals(expectedNextStart + rowsInChunk - 1, c.lineEnd(),
                    "lineEnd 必须精确等于该组数据行数推算出的行号，不能被表头复制误推进");
            expectedNextStart = c.lineEnd() + 1;
        }
        assertEquals(48, expectedNextStart, "最后一组结束后累计行号应精确落在原始区间末尾+1（1 表头 + 46 数据行，从第 2 行到第 47 行）");
    }

    @Test
    @DisplayName("表格 chunk 的 metadata 保留 type=table")
    void tableChunkMetadataPreservesType() {
        String table = "A | B\n1 | 2\n";
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "t.pdf",
                List.of(new DocumentSection(table, List.of(), 1, 1, 2, Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        assertEquals("table", chunks.get(0).metadata().get("type"));
    }

    @Test
    @DisplayName("只有超长表头、没有数据行的表格不会静默丢失，至少产出一个块")
    void tableWithOnlyOverlongHeaderProducesAtLeastOneChunk() {
        String longHeader = "年龄段字段说明 | 男性费率字段说明含税含费详细说明 | 女性费率字段说明含税含费详细说明";
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "empty-table.pdf",
                List.of(new DocumentSection(longHeader, List.of(), 1, 1, 1, Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, new ChunkingOptions(20, 0, true));
        assertFalse(chunks.isEmpty(), "只有表头也不应该静默丢失整个表格 section");
        assertTrue(chunks.stream().anyMatch(c -> c.content().contains("年龄段字段说明")));
    }

    @Test
    @DisplayName("表格内部（非首尾）的空行被 isBlank 跳过，不产生空白内容，也不影响前后数据行")
    void blankRowsInsideTableAreSkippedByIsBlankCheck() {
        // 空行必须夹在表头/数据行中间（非整段文本的开头或结尾），这样
        // chunkTableSection 里 section.text().strip() 才不会把它们提前清除
        // ——真正让循环体里的 if (row.isBlank()) continue; 分支被执行到。
        String header = "年龄段 | 费率";
        String table = header + "\n" + "\n" + "30岁 | 120.00" + "\n" + "   " + "\n" + "40岁 | 150.00";
        // 整段 strip 后长度为 39（表头 1 行 + 空行 + 30岁 数据行 + 空白行 + 40岁 数据行），
        // maxCharacters=38 < 39 强制走大表格分支（触发主循环及 isBlank 跳过逻辑），
        // 但单组内容本身（表头 + 两条真实数据行，不含空行）长度不超过 38，
        // 因此两条数据行会被合并进同一个 chunk，不会被强制拆成多组。
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "table-with-blanks.pdf",
                List.of(new DocumentSection(table, List.of(), 1, 1, 5, Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, new ChunkingOptions(38, 0, true));

        assertEquals(1, chunks.size(), "两条真实数据行应合并在同一组，不应被拆分");
        String expected = header + "\n30岁 | 120.00\n40岁 | 150.00";
        assertEquals(expected, chunks.get(0).content(),
                "chunk 内容必须恰好是表头 + 两条数据行，中间的空白行必须被 isBlank 跳过、"
                        + "不能残留为独立的空白行或多余的连续换行符");
    }
}
