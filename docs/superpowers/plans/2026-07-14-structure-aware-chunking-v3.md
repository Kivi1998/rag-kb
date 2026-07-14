# 结构感知切分 V3 五招式 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `TechnicalChunker` 从"两级降级"（结构单元→句子）升级为完整的 V3 结构感知切分：多风格自动识别文档层级、真正的多级递归降级、表格分块保留表头、以及丰富的 chunk 元数据（章节路径字符串、内容类型、关键条款标记、前后块链接）。overlap 对齐句子边界的机制已经存在，只补充调优验证。

**Architecture:** 新增 `HeadingStyle` 枚举（4 套多级编号正则 + 自动选主导风格，思路参考 RAGFlow deepdoc 的 `bullets_category()`，本项目重新实现，非移植代码），在 `TechnicalChunker` 里用它驱动"识别层级→递归降级"；表格分块和 chunk 元数据增强都是 `TechnicalChunker` 内的新增私有方法。全部改动落在切块模块内部，`Chunker`/`ChunkingContext` 接口签名不变，`Chunk` 记录的 `metadata: Map<String,String>` 字段已经原样透传进 ES 的 `dynamic: true` 的 `metadata` 对象字段（`ElasticsearchChunkIndex.toIndexDocument()` 第 200 行 `source.put("metadata", chunk.metadata())`），所以新增的 chunk 元数据**不需要改 ES mapping、不需要改索引写入代码**。

**Tech Stack:** Java 17，JUnit 5，现有 `com.diit.ragkb.ragcore.chunk` 包。

## Global Constraints

- 不引入新的第三方依赖（纯正则 + 标准库，不接 ML 分类器——分类器兜底本轮明确不做，见 Task 1 的范围说明）。
- `Chunker`/`ChunkingContext`/`ChunkingOptions` 的公开接口签名不变，避免影响 `DocumentIngestionPipeline` 等调用方。
- `Chunk` record 的字段不新增（`headingPath` 已经承担 section_path 的结构化角色），新元数据一律写入既有的 `metadata: Map<String,String>`。
- 所有正则改动必须保留现有测试全部通过（`TechnicalChunkerTest.java` 现有 16 个测试用例）。
- 中文/英文混合文档、无编号体系的文档（比如纯 Markdown）必须继续按现有逻辑工作，不能因为引入"风格检测"而在没有编号的文档上产生回归。

---

## Task 1: HeadingStyle —— 多风格自动识别文档层级

对应招式 1（"识别文档层级"）。当前 `TechnicalChunker` 只有一套写死的正则（`CN_STRUCTURE` 只认"第X条/一、/（一）"，不区分文档实际用的是哪种编号体系）。这个任务新增一个能同时准备 4 套编号风格、扫一遍全文自动选出命中最多的那一套的机制——参考 RAGFlow deepdoc 里 `bullets_category()` 的思路（见 `rag系统2/swxy/backend/app/service/core/rag/nlp/__init__.py:240-256` 的 `BULLET_PATTERN` + `bullets_category`），但正则集合和选择逻辑是本项目重新设计的，不是移植代码。

**范围说明（本任务不做的事）：** 原文提到的"轻量分类器兜底"本轮不做——训练/维护一个分类器成本远超收益，本任务用一个更便宜的兜底策略代替：如果所有风格的命中数都低于阈值（说明文档没有清晰编号体系），就返回"未检测到风格"，调用方退化到现有的 Markdown 标题 + 空行分段逻辑，不强行按编号切。这个决策记录在 Task 1 完成后需要同步更新到 `TODOS.md`。

**Files:**
- Create: `backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyle.java`
- Test: `backend/src/test/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyleTest.java`

**Interfaces:**
- Produces: `enum HeadingStyle { CN_FORMAL, CN_NUMERIC, CN_INFORMAL, EN }`，包级私有（不加 `public`，只在 `chunk.impl` 包内使用）。
  - `List<Pattern> levels()` —— 由粗到细排列的正则列表。
  - `int levelOf(String line)` —— 该行命中的级别下标（0 = 最粗），未命中返回 `-1`。
  - `static Optional<HeadingStyle> detectDominant(List<String> lines, int minHits)` —— 扫描全部行，返回命中数最多且 ≥ `minHits` 的风格；否则 `Optional.empty()`。
  - Task 2 会消费 `levels()` 和 `levelOf()` 做递归降级。

- [ ] **Step 1: 写失败的测试**

创建 `backend/src/test/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyleTest.java`：

```java
package com.diit.ragkb.ragcore.chunk.impl;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("HeadingStyle 多风格识别测试")
class HeadingStyleTest {

    @Test
    @DisplayName("正式中文编号（第X条+（一）在同一文档）被识别为 CN_FORMAL")
    void detectsFormalChineseStyle() {
        List<String> lines = List.of(
                "第一条 本合同的构成",
                "本合同由保险单及所附条款组成。",
                "第二条 投保范围",
                "（一）年满十八周岁",
                "（二）身体健康",
                "第三条 保险责任"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.CN_FORMAL, style.get());
    }

    @Test
    @DisplayName("数字编号（1. / 1.1 / 1.1.1）被识别为 CN_NUMERIC")
    void detectsNumericStyle() {
        List<String> lines = List.of(
                "1. 系统架构",
                "1.1 前端设计",
                "1.1.1 组件划分",
                "1.2 后端设计",
                "2. 部署方案"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.CN_NUMERIC, style.get());
    }

    @Test
    @DisplayName("英文编号（Chapter/Section）被识别为 EN")
    void detectsEnglishStyle() {
        List<String> lines = List.of(
                "Chapter I Introduction",
                "This chapter covers the basics.",
                "Section 1 Overview",
                "Section 2 Scope",
                "Chapter II Methodology"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isPresent());
        assertEquals(HeadingStyle.EN, style.get());
    }

    @Test
    @DisplayName("没有清晰编号体系的文档返回 empty（不强行按编号切）")
    void returnsEmptyWhenNoStructure() {
        List<String> lines = List.of(
                "这是一段普通说明文字。",
                "没有任何编号。",
                "只是纯段落。"
        );
        Optional<HeadingStyle> style = HeadingStyle.detectDominant(lines, 2);
        assertTrue(style.isEmpty());
    }

    @Test
    @DisplayName("levelOf 返回正确的级别下标")
    void levelOfReturnsCorrectIndex() {
        assertEquals(0, HeadingStyle.CN_FORMAL.levelOf("第一章 总则"));
        assertEquals(3, HeadingStyle.CN_FORMAL.levelOf("第一条 定义"));
        assertEquals(-1, HeadingStyle.CN_FORMAL.levelOf("普通文字"));
    }

    @Test
    @DisplayName("levels() 按从粗到细排列且每个风格至少 4 级")
    void levelsAreOrderedCoarseToFine() {
        for (HeadingStyle style : HeadingStyle.values()) {
            assertTrue(style.levels().size() >= 4,
                    style + " 应至少有 4 级，实际: " + style.levels().size());
        }
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && export JAVA_HOME=$(/usr/libexec/java_home -v 17) && export PATH="$JAVA_HOME/bin:$PATH"
mvn -q test -Dtest=HeadingStyleTest
```

预期：编译失败（`HeadingStyle` 类不存在）。

- [ ] **Step 3: 实现 HeadingStyle**

创建 `backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyle.java`：

```java
package com.diit.ragkb.ragcore.chunk.impl;

import java.util.List;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * 一套文档编号风格：由粗到细排列的多级正则，覆盖同一份文档常见的编号写法。
 *
 * <p>用于在切分前先扫一遍全文，自动选出命中次数最多的一套风格，而不是像
 * 旧版那样对所有文档都用同一套死板正则。思路参考 RAGFlow deepdoc 的
 * {@code bullets_category()}（多套候选正则 + 统计命中数选优），
 * 正则集合与选择逻辑是本项目独立设计实现，不是移植代码。</p>
 */
enum HeadingStyle {

    /** 正式合同/法规常见：第X编/章/节/条，(一)(二) */
    CN_FORMAL(List.of(
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+(编|部分)"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+章"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+节"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+条"),
            Pattern.compile("^[（(][零一二三四五六七八九十0-9]+[）)]")
    )),

    /** 技术文档/报告常见：第X章/节，1. / 1.1 / 1.1.1 */
    CN_NUMERIC(List.of(
            Pattern.compile("^第[0-9]+章"),
            Pattern.compile("^第[0-9]+节"),
            Pattern.compile("^[0-9]{1,2}[、.．][^0-9]"),
            Pattern.compile("^[0-9]{1,2}\\.[0-9]{1,2}(?!\\.[0-9])"),
            Pattern.compile("^[0-9]{1,2}\\.[0-9]{1,2}\\.[0-9]{1,2}")
    )),

    /** 非正式文档常见：第X章/节，一、二、，（一）（1） */
    CN_INFORMAL(List.of(
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+章"),
            Pattern.compile("^第[零一二三四五六七八九十百0-9]+节"),
            Pattern.compile("^[一二三四五六七八九十]+[、.]"),
            Pattern.compile("^[（(][一二三四五六七八九十]+[）)]"),
            Pattern.compile("^[（(][0-9]{1,2}[）)]")
    )),

    /** 英文文档：Part/Chapter/Section/Article */
    EN(List.of(
            Pattern.compile("(?i)^part (one|two|three|four|five|six|seven|eight|nine|ten)"),
            Pattern.compile("(?i)^chapter [ivxlcdm]+"),
            Pattern.compile("(?i)^section [0-9]+"),
            Pattern.compile("(?i)^article [0-9]+")
    ));

    private final List<Pattern> levels;

    HeadingStyle(List<Pattern> levels) {
        this.levels = levels;
    }

    List<Pattern> levels() {
        return levels;
    }

    /** 该行命中的最细级别下标（0 = 最粗）；未命中任何级别返回 -1。 */
    int levelOf(String line) {
        String stripped = line.strip();
        if (stripped.isEmpty()) return -1;
        for (int i = 0; i < levels.size(); i++) {
            if (levels.get(i).matcher(stripped).find()) {
                return i;
            }
        }
        return -1;
    }

    private int countMatches(List<String> lines) {
        int count = 0;
        for (String line : lines) {
            if (levelOf(line) >= 0) count++;
        }
        return count;
    }

    /**
     * 扫描全文，返回命中次数最多的风格；如果最高命中数低于 minHits，
     * 说明文档没有清晰的编号体系，返回 empty，调用方应退化为不强制按结构切分。
     */
    static Optional<HeadingStyle> detectDominant(List<String> lines, int minHits) {
        HeadingStyle best = null;
        int bestCount = 0;
        for (HeadingStyle style : values()) {
            int count = style.countMatches(lines);
            if (count > bestCount) {
                best = style;
                bestCount = count;
            }
        }
        if (best == null || bestCount < minHits) {
            return Optional.empty();
        }
        return Optional.of(best);
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
mvn -q test -Dtest=HeadingStyleTest
```

预期：6 个测试全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyle.java \
        backend/src/test/java/com/diit/ragkb/ragcore/chunk/impl/HeadingStyleTest.java
git commit -m "feat: 新增 HeadingStyle 多风格文档层级自动识别"
```

---

## Task 2: 递归级联切分 —— 用 HeadingStyle 驱动多级降级

对应招式 2（"超长章节递归切分"）。当前 `chunkSection` 只有两级：结构单元整体 vs 句子级二次切分（`findSentenceSplit`）。这个任务改成真正的多级降级：过长的结构单元先尝试用同一套编号风格里"更细一级"的模式再切一刀，切不动再退到空行分段，最后才退到已有的句子边界切分。

**Files:**
- Modify: `backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java`
- Test: `backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java`

**Interfaces:**
- Consumes: `HeadingStyle.levels()`、`HeadingStyle.levelOf(String)`、`HeadingStyle.detectDominant(List<String>, int)`（Task 1 产出）。
- Produces: `TechnicalChunker` 内部新增私有方法 `recursiveSplit(String unit, HeadingStyle style, int level, ChunkingOptions options) -> List<String>`，供 `chunkSection` 内部替换原来"单元超长直接句子切"的分支使用；不改变 `Chunker.chunk()` 的对外签名。

- [ ] **Step 1: 写失败的测试**

在 `TechnicalChunkerTest.java` 新增（放在"结构感知"分组之后）：

```java
    // ── 递归级联切分（招式 2）──

    @Test
    @DisplayName("过长的「第X条」先按内部的（一）（二）细分，而不是直接按句子硬切")
    void recursiveSplitPrefersFinerStructureBeforeSentence() {
        StringBuilder article = new StringBuilder("第一条 责任范围\n");
        for (int i = 1; i <= 6; i++) {
            article.append("（").append(cnNum(i)).append("）本公司对被保险人在保险期间内因下列第")
                    .append(i).append("项原因导致的损失承担赔偿责任，具体包括但不限于因意外事故、"
                            + "疾病或其他约定情形所产生的医疗费用、误工损失及相关合理支出。\n");
        }
        ParsedDocument doc = docWith(article.toString());
        ChunkingOptions tight = new ChunkingOptions(200, 30, true);
        List<Chunk> chunks = chunksFor(doc, tight);

        assertTrue(chunks.size() > 1, "过长条款应被切成多块");
        // 每一块要么完整包含一个「（X）」小项，要么至少不是从「（X）」中间任意字符处硬切断
        for (Chunk c : chunks) {
            String content = c.content().strip();
            assertFalse(content.matches("^[，,].*"), "不应该从子项中间开始，出现悬空的逗号开头: " + content);
        }
    }

    private static String cnNum(int i) {
        String[] cn = {"一", "二", "三", "四", "五", "六"};
        return cn[i - 1];
    }

    @Test
    @DisplayName("没有更细编号可用时降级到空行分段，而不是直接句子切")
    void fallsBackToParagraphWhenNoFinerStructure() {
        StringBuilder article = new StringBuilder("第一条 释义\n");
        for (int i = 0; i < 4; i++) {
            article.append("这是第").append(i).append("个自然段，描述与本条款相关的背景信息和适用范围，"
                    + "内容较长以触发超长条款的降级切分逻辑。\n\n");
        }
        ParsedDocument doc = docWith(article.toString());
        ChunkingOptions tight = new ChunkingOptions(150, 20, true);
        List<Chunk> chunks = chunksFor(doc, tight);
        assertTrue(chunks.size() > 1);
    }
```

- [ ] **Step 2: 运行测试确认失败**

```bash
mvn -q test -Dtest=TechnicalChunkerTest#recursiveSplitPrefersFinerStructureBeforeSentence
```

预期：FAIL（当前实现会在文本中间任意位置按 `maxCharacters` 硬切，可能切出悬空逗号开头的块）。

- [ ] **Step 3: 在 TechnicalChunker 里接入 HeadingStyle 并实现递归降级**

在 `TechnicalChunker.java` 顶部新增字段常量后，修改 `chunk()` 方法先探测全文风格：

```java
    @Override
    public List<Chunk> chunk(ParsedDocument document, ChunkingContext context, ChunkingOptions options) {
        List<Chunk> chunks = new ArrayList<>();

        List<String> allLines = document.sections().stream()
                .flatMap(s -> s.text() == null ? java.util.stream.Stream.<String>empty()
                        : java.util.Arrays.stream(s.text().split("\n")))
                .toList();
        HeadingStyle style = HeadingStyle.detectDominant(allLines, 3).orElse(null);

        for (DocumentSection section : document.sections()) {
            List<Chunk> sectionChunks = chunkSection(
                    section, document, context.organizationId(), context.knowledgeBaseId(), options, style);
            chunks.addAll(sectionChunks);
        }

        // renumber ordinals globally
        for (int i = 0; i < chunks.size(); i++) {
            Chunk old = chunks.get(i);
            chunks.set(i, new Chunk(
                    chunkId(old.documentId(), i, old.content()),
                    old.organizationId(), old.knowledgeBaseId(), old.documentId(),
                    i, old.content(), old.headingPath(), old.sourcePath(),
                    old.pageNo(), old.lineStart(), old.lineEnd(),
                    old.language(), old.contentHash(), old.metadata()
            ));
        }

        return chunks;
    }
```

`chunkSection` 签名增加 `HeadingStyle style` 参数（找到方法定义 `private List<Chunk> chunkSection(...)`，在参数列表末尾加 `, HeadingStyle style`，并把方法体里"单个 unit 超长时按句子切"的这一段：

```java
            // if single unit alone exceeds max, split at sentence boundaries
            while (buf.length() > options.maxCharacters()) {
                int splitAt = findSentenceSplit(buf.toString(), options.maxCharacters());
                ...
            }
```

替换为调用新的递归降级方法。把整个 `while` 块替换成：

```java
            // if single unit alone exceeds max, recursively split at finer structure,
            // then paragraph, then sentence boundaries (招式 2：多级递归降级)
            if (buf.length() > options.maxCharacters()) {
                String overlong = buf.toString();
                buf.setLength(0);
                int unitLevel = style == null ? -1 : style.levelOf(overlong.lines().findFirst().orElse(""));
                for (String piece : recursiveSplit(overlong, style, unitLevel, options)) {
                    int pieceLineEnd = bufferLineStart + countLines(piece) - 1;
                    chunks.add(flushBuffer(new StringBuilder(piece), section, document, orgId, kbId, chunks.size(),
                            bufferLineStart, pieceLineEnd));
                    bufferLineStart = pieceLineEnd + 1;
                }
                currentLine = bufferLineStart;
            }
```

新增三个私有方法（放在 `findSentenceSplit` 方法之后）：

```java
    /**
     * 递归地把一个过长的文本单元按"更细一级编号 → 空行分段 → 句子边界"逐级
     * 降级切分，每一级都优先保住更大的语义单元，装不下才继续往下降级。
     */
    private List<String> recursiveSplit(String unit, HeadingStyle style, int level, ChunkingOptions options) {
        if (unit.length() <= options.maxCharacters()) {
            return List.of(unit);
        }
        if (style != null && level + 1 < style.levels().size()) {
            List<String> finer = splitByLevel(unit, style, level + 1);
            if (finer.size() > 1) {
                List<String> result = new ArrayList<>();
                for (String piece : finer) {
                    result.addAll(recursiveSplit(piece, style, level + 1, options));
                }
                return result;
            }
        }
        List<String> paragraphs = splitByBlankLine(unit);
        if (paragraphs.size() > 1) {
            List<String> result = new ArrayList<>();
            for (String p : paragraphs) {
                result.addAll(recursiveSplit(p, style, level, options));
            }
            return result;
        }
        return splitBySentenceWithOverlap(unit, options);
    }

    /** 按某个编号级别的正则，在行边界处把文本切成若干段（每段以命中该级别的行开头）。 */
    private List<String> splitByLevel(String text, HeadingStyle style, int level) {
        String[] lines = text.split("\n", -1);
        List<String> pieces = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        for (String line : lines) {
            if (style.levelOf(line) == level && !current.isEmpty()) {
                pieces.add(current.toString().strip());
                current.setLength(0);
            }
            current.append(line).append('\n');
        }
        if (!current.isEmpty()) pieces.add(current.toString().strip());
        return pieces.stream().filter(s -> !s.isEmpty()).toList();
    }

    /** 按连续空行把文本切成自然段。 */
    private List<String> splitByBlankLine(String text) {
        return java.util.Arrays.stream(text.split("\n\\s*\n"))
                .map(String::strip)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    /** 最后一级降级：按句子边界切分，沿用已有的 findSentenceSplit + tailOverlap。 */
    private List<String> splitBySentenceWithOverlap(String text, ChunkingOptions options) {
        List<String> pieces = new ArrayList<>();
        StringBuilder remaining = new StringBuilder(text);
        while (remaining.length() > options.maxCharacters()) {
            int splitAt = findSentenceSplit(remaining.toString(), options.maxCharacters());
            String head = remaining.substring(0, splitAt);
            pieces.add(head);
            String overlap = tailOverlap(head, options.overlapCharacters());
            String tail = remaining.substring(splitAt);
            remaining = new StringBuilder(overlap.isEmpty() ? tail : overlap + tail);
        }
        if (!remaining.isEmpty()) pieces.add(remaining.toString());
        return pieces;
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
mvn -q test -Dtest=TechnicalChunkerTest
```

预期：全部测试（含新增的 2 个和原有 16 个）PASS。如果原有的行号相关测试（`chunkCarriesAccurateLineRange` 等）失败，检查 `bufferLineStart`/`currentLine` 的更新是否与新的递归分支保持一致——这是本任务风险最高的点，务必逐个跑一遍现有测试确认没有回归。

- [ ] **Step 5: 提交**

```bash
git add backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java \
        backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java
git commit -m "feat: 切块器接入 HeadingStyle，超长结构单元改为多级递归降级"
```

---

## Task 3: 表格分块保留表头

对应招式 3。当前表格（`section.metadata().get("type").equals("table")`，DocxParser/parser-gateway 已经这样标记）如果超长，会走通用的句子切分逻辑，表头信息在切分后的块里完全丢失。这个任务让大表格按行分组，每组前面都带上表头行。

**Files:**
- Modify: `backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java`
- Test: `backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java`

**Interfaces:**
- Consumes: `DocumentSection.metadata()`（已有字段，DocxParser 已经用 `Map.of("type", "table")` 标记表格 section，见 `backend/src/main/java/com/diit/ragkb/ragcore/parser/impl/DocxParser.java:94`）；表格文本格式是每行 `cell1 | cell2 | cell3`（`extractTable` 方法产出，同文件第 128-138 行）。
- Produces: `TechnicalChunker` 内新增私有方法 `chunkTableSection(DocumentSection, ParsedDocument, UUID, UUID, ChunkingOptions) -> List<Chunk>`，在 `chunkSection` 分发时优先判断走这条路径。

- [ ] **Step 1: 写失败的测试**

在 `TechnicalChunkerTest.java` 新增：

```java
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
        assertTrue(chunks.stream().anyMatch(c -> c.content().contains("60岁 | 240.00 | 180.00")));
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
mvn -q test -Dtest=TechnicalChunkerTest#largeTableEachGroupCarriesHeader
```

预期：FAIL（当前实现不识别表格类型，会把表格当普通文本按句子切，表头只出现在第一个 chunk）。

- [ ] **Step 3: 实现表格分块**

在 `chunkSection` 方法开头加一个分发判断（找到 `private List<Chunk> chunkSection(...)` 方法体的第一行 `List<Chunk> chunks = new ArrayList<>();` 之前插入）：

```java
        if ("table".equals(section.metadata().get("type"))) {
            return chunkTableSection(section, document, orgId, kbId, options);
        }
```

新增方法（放在 `chunkSection` 之后）：

```java
    /**
     * 表格分块：小表格整体保留为一个 chunk；超出 maxCharacters 的大表格按行
     * 分组，每组前面都重新带上表头行，避免"模型只看到中间几行、不知道每列
     * 是什么"（招式 3）。
     */
    private List<Chunk> chunkTableSection(DocumentSection section, ParsedDocument document,
                                           UUID orgId, UUID kbId, ChunkingOptions options) {
        String text = section.text().strip();
        if (text.length() <= options.maxCharacters()) {
            return new ArrayList<>(List.of(flushBuffer(new StringBuilder(text), section, document,
                    orgId, kbId, 0, section.lineStart() == null ? 1 : section.lineStart(),
                    section.lineEnd() == null ? 1 : section.lineEnd())));
        }

        String[] lines = text.split("\n", -1);
        String headerLine = lines[0];
        List<Chunk> chunks = new ArrayList<>();
        StringBuilder group = new StringBuilder(headerLine);
        int groupStartLine = (section.lineStart() == null ? 1 : section.lineStart()) + 1;
        int currentLine = groupStartLine;

        for (int i = 1; i < lines.length; i++) {
            String row = lines[i];
            if (row.isBlank()) continue;
            String candidate = group + "\n" + row;
            if (candidate.length() > options.maxCharacters() && group.length() > headerLine.length()) {
                chunks.add(flushBuffer(group, section, document, orgId, kbId, chunks.size(),
                        groupStartLine, currentLine - 1));
                group = new StringBuilder(headerLine);
                groupStartLine = currentLine;
            }
            group.append('\n').append(row);
            currentLine++;
        }
        if (group.length() > headerLine.length()) {
            chunks.add(flushBuffer(group, section, document, orgId, kbId, chunks.size(),
                    groupStartLine, currentLine - 1));
        }
        return chunks;
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
mvn -q test -Dtest=TechnicalChunkerTest
```

预期：全部 PASS（原有 16 + Task 2 新增 2 + Task 3 新增 3 = 21 个）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java \
        backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java
git commit -m "feat: 大表格按行分组分块并在每组重复表头"
```

---

## Task 4: Overlap 调优验证（复用现有实现，补测试和注释）

对应招式 4。`tailOverlap()` 已经实现"对齐句子边界的 overlap"，不需要新代码；这个任务只是：(a) 确认默认参数落在 5 篇参考文章统一提到的 10%-20% overlap 比例区间内，(b) 补一个明确断言"overlap 不应包含半截话"的测试，把这个不变量用测试锁定，避免以后有人改坏。

**Files:**
- Modify: `backend/src/main/java/com/diit/ragkb/ragcore/chunk/ChunkingOptions.java`（只加注释，不改逻辑）
- Test: `backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java`

**Interfaces:**
- 无新接口，纯验证性任务。

- [ ] **Step 1: 写测试锁定 overlap 比例与句子边界不变量**

在 `TechnicalChunkerTest.java` 新增：

```java
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
        String text = ("这是关于理赔流程的完整说明，包含多个步骤和注意事项。"
                + "首先需要提交申请材料，然后等待审核结果，审核通过后进行赔付。\n").repeat(30);
        ParsedDocument doc = docWith(text);
        List<Chunk> chunks = chunksFor(doc, new ChunkingOptions(300, 60, false));
        assertTrue(chunks.size() > 1);
        // 除第一块外，其余块要么以完整句首开头，要么是上一块结尾的整句重叠，
        // 不应该以一个"半句片段+后续内容"的形式开头导致读起来断章取义。
        for (int i = 1; i < chunks.size(); i++) {
            String content = chunks.get(i).content();
            assertFalse(content.startsWith("，") || content.startsWith(",")
                            || content.startsWith("、"),
                    "块不应以悬空标点开头（说明 overlap 从句子中间截断）: "
                            + content.substring(0, Math.min(20, content.length())));
        }
    }
```

- [ ] **Step 2: 运行测试确认结果**

```bash
mvn -q test -Dtest=TechnicalChunkerTest#defaultOverlapRatioInSweetSpotRange
mvn -q test -Dtest=TechnicalChunkerTest#overlapNeverStartsWithPartialSentence
```

预期：两个测试都 PASS（现有 `ChunkingOptions.defaults()` 是 `maxCharacters=1200, overlapCharacters=160`，比例 13.3%，已经在区间内；`tailOverlap()` 已经对齐句子边界）。如果第一个测试失败，说明默认参数需要调整到区间内（比如把 overlap 调到 150-240 之间）。

- [ ] **Step 3: 补充参数选择依据的注释**

修改 `backend/src/main/java/com/diit/ragkb/ragcore/chunk/ChunkingOptions.java`，在 `defaults()` 方法上加注释：

```java
    /**
     * 默认参数：maxCharacters=1200，overlapCharacters=160（约 13.3%），落在
     * 10%-20% 的性价比区间内——overlap 从 0 加到约 10%-20% 对应字符数时召回率
     * 提升明显，继续加大到 2-3 倍则召回只再小幅提升，但存储和 embedding 成本
     * 线性上升，不值得。
     */
    public static ChunkingOptions defaults() {
        return new ChunkingOptions(1_200, 160, true);
    }
```

- [ ] **Step 4: 提交**

```bash
git add backend/src/main/java/com/diit/ragkb/ragcore/chunk/ChunkingOptions.java \
        backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java
git commit -m "test: 锁定 overlap 比例区间与句子边界不变量"
```

---

## Task 5: Chunk 元数据增强

对应招式 5。`section_path` 已经由既有的 `headingPath` 字段承担（结构化的 `List<String>`，已经写入 ES 的 `heading_path` 字段），这个任务补的是：`sectionPath`（拼接成人类可读字符串，方便前端引用卡片直接显示）、`contentType`（从 section 的 `type` 元数据透传）、`isKeyClause`（关键词命中）、`prevChunkId`/`nextChunkId`（同文档内链式引用，用于检索后自动补全语义不完整的相邻块）。全部写入既有的 `Chunk.metadata()` `Map<String,String>` 字段——**不需要改 `Chunk` record、不需要改 ES mapping、不需要改 `ElasticsearchChunkIndex`**，因为 `toIndexDocument()` 已经把整个 `chunk.metadata()` 原样透传进 ES 的 `dynamic: true` 的 `metadata` 对象字段。

**Files:**
- Modify: `backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java`
- Test: `backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java`

**Interfaces:**
- Produces：每个 `Chunk.metadata()` 新增以下 key（都是 `String` 值，因为 `Chunk.metadata()` 类型是 `Map<String,String>`）：
  - `"sectionPath"` —— `headingPath` 用 `" > "` 拼接的字符串，空 headingPath 时该 key 不写入。
  - `"contentType"` —— 透传自 `section.metadata().getOrDefault("type", "text")`。
  - `"isKeyClause"` —— `"true"`/`"false"`，命中关键词列表时为 `"true"`。
  - `"prevChunkId"` / `"nextChunkId"` —— 同文档内按 ordinal 顺序的前后 chunk id，首尾块对应方向不写入该 key。

- [ ] **Step 1: 写失败的测试**

在 `TechnicalChunkerTest.java` 新增：

```java
    // ── chunk 元数据增强（招式 5）──

    @Test
    @DisplayName("chunk metadata 携带 sectionPath 与 contentType")
    void chunkMetadataCarriesSectionPathAndContentType() {
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "text/markdown", "docs/design.md",
                List.of(new DocumentSection("正文内容。", List.of("第3条", "3.2", "(1)"), 1, 1, 1, Map.of())),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        assertEquals("第3条 > 3.2 > (1)", chunks.get(0).metadata().get("sectionPath"));
        assertEquals("text", chunks.get(0).metadata().get("contentType"));
    }

    @Test
    @DisplayName("表格 chunk 的 contentType 为 table")
    void tableChunkContentTypeIsTable() {
        ParsedDocument doc = new ParsedDocument(
                UUID.randomUUID(), "application/pdf", "t.pdf",
                List.of(new DocumentSection("A | B\n1 | 2\n", List.of(), 1, 1, 2, Map.of("type", "table"))),
                Map.of()
        );
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        assertEquals("table", chunks.get(0).metadata().get("contentType"));
    }

    @Test
    @DisplayName("命中关键词的 chunk 被标记 isKeyClause=true")
    void keyClauseKeywordsAreFlagged() {
        ParsedDocument doc = docWith("第一条 责任免除\n本公司对下列情形不承担赔偿责任：战争、核辐射。",
                "第二条 说明\n本条款仅作说明性描述，不涉及具体权利义务。");
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        boolean anyKeyClause = chunks.stream()
                .anyMatch(c -> "true".equals(c.metadata().get("isKeyClause")));
        assertTrue(anyKeyClause, "包含「免除」「责任」等关键词的块应标记 isKeyClause=true");
    }

    @Test
    @DisplayName("chunk 携带同文档内顺序的 prevChunkId/nextChunkId")
    void chunksCarryPrevAndNextChunkId() {
        ParsedDocument doc = docWith("第一段。", "第二段。", "第三段。");
        List<Chunk> chunks = chunksFor(doc, ChunkingOptions.defaults());
        assertTrue(chunks.size() >= 3);

        assertNull(chunks.get(0).metadata().get("prevChunkId"), "第一块不应有 prevChunkId");
        assertEquals(chunks.get(1).id(), chunks.get(0).metadata().get("nextChunkId"));

        assertEquals(chunks.get(0).id(), chunks.get(1).metadata().get("prevChunkId"));
        assertEquals(chunks.get(2).id(), chunks.get(1).metadata().get("nextChunkId"));

        int last = chunks.size() - 1;
        assertNull(chunks.get(last).metadata().get("nextChunkId"), "最后一块不应有 nextChunkId");
    }
```

- [ ] **Step 2: 运行测试确认失败**

```bash
mvn -q test -Dtest=TechnicalChunkerTest#chunkMetadataCarriesSectionPathAndContentType
```

预期：FAIL（`metadata()` 里还没有这些 key）。

- [ ] **Step 3: 实现元数据增强**

在 `TechnicalChunker.java` 顶部新增关键词常量（放在现有 `Pattern` 常量之后）：

```java
    // 责任/免责/费率类关键词——命中即标记 isKeyClause=true，供检索侧加权
    // （本轮不做检索侧改动，只落地标记本身）。关键词列表后续可按业务扩展。
    private static final java.util.Set<String> KEY_CLAUSE_KEYWORDS = java.util.Set.of(
            "免除", "免责", "除外", "责任范围", "保险责任", "赔偿限额", "保险金额",
            "费率", "违约金", "解除合同", "终止合同"
    );
```

修改 `flushBuffer` 方法，在构造 `Chunk` 之前加元数据增强：

```java
    private Chunk flushBuffer(StringBuilder buf, DocumentSection section, ParsedDocument document,
                               UUID orgId, UUID kbId, int ordinal, int lineStart, int lineEnd) {
        String content = buf.toString();

        String lang = document.metadata() != null ? document.metadata().getOrDefault("language", "") : "";
        String id = chunkId(document.documentId(), ordinal, content);

        Map<String, String> enrichedMetadata = enrichMetadata(section, content);

        return new Chunk(
                id, orgId, kbId, document.documentId(), ordinal,
                content,
                section.headingPath(),
                document.sourcePath(),
                section.pageNo(),
                section.lineStart() == null ? null : lineStart,
                section.lineEnd() == null ? null : lineEnd,
                lang,
                sha256_8(content),
                enrichedMetadata
        );
    }

    /** 招式 5：给每个 chunk 补 sectionPath / contentType / isKeyClause 元数据。 */
    private Map<String, String> enrichMetadata(DocumentSection section, String content) {
        java.util.LinkedHashMap<String, String> metadata = new java.util.LinkedHashMap<>(section.metadata());
        if (!section.headingPath().isEmpty()) {
            metadata.put("sectionPath", String.join(" > ", section.headingPath()));
        }
        metadata.put("contentType", section.metadata().getOrDefault("type", "text"));
        boolean isKeyClause = KEY_CLAUSE_KEYWORDS.stream().anyMatch(content::contains);
        metadata.put("isKeyClause", String.valueOf(isKeyClause));
        return metadata;
    }
```

同样在 `chunkTableSection` 里，`flushBuffer` 调用不需要改（已经统一走 `flushBuffer`，会自动带上 `contentType=table`）。

最后修改 `chunk()` 方法里的"renumber ordinals globally"这段，改成同时写入 prev/next chunk id（把 Task 2 里已经改过的这段再改一次）：

```java
        // renumber ordinals globally + 招式 5：链接 prev/next chunk id
        for (int i = 0; i < chunks.size(); i++) {
            Chunk old = chunks.get(i);
            String newId = chunkId(old.documentId(), i, old.content());

            java.util.LinkedHashMap<String, String> metadata = new java.util.LinkedHashMap<>(old.metadata());
            metadata.remove("prevChunkId");
            metadata.remove("nextChunkId");

            chunks.set(i, new Chunk(
                    newId, old.organizationId(), old.knowledgeBaseId(), old.documentId(),
                    i, old.content(), old.headingPath(), old.sourcePath(),
                    old.pageNo(), old.lineStart(), old.lineEnd(),
                    old.language(), old.contentHash(), metadata
            ));
        }
        for (int i = 0; i < chunks.size(); i++) {
            Chunk c = chunks.get(i);
            java.util.LinkedHashMap<String, String> metadata = new java.util.LinkedHashMap<>(c.metadata());
            if (i > 0) metadata.put("prevChunkId", chunks.get(i - 1).id());
            if (i < chunks.size() - 1) metadata.put("nextChunkId", chunks.get(i + 1).id());
            chunks.set(i, new Chunk(
                    c.id(), c.organizationId(), c.knowledgeBaseId(), c.documentId(),
                    c.ordinal(), c.content(), c.headingPath(), c.sourcePath(),
                    c.pageNo(), c.lineStart(), c.lineEnd(),
                    c.language(), c.contentHash(), metadata
            ));
        }
```

（这里分两个循环是因为 chunk id 依赖 ordinal 重编号后的结果，必须先把所有 id 定下来，第二轮才能安全引用"下一个 chunk 的 id"。）

- [ ] **Step 4: 运行测试确认通过**

```bash
mvn -q test -Dtest=TechnicalChunkerTest
```

预期：全部测试 PASS（原有 16 + Task 2 新增 2 + Task 3 新增 3 + Task 4 新增 2 + Task 5 新增 4 = 27 个）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/main/java/com/diit/ragkb/ragcore/chunk/impl/TechnicalChunker.java \
        backend/src/test/java/com/diit/ragkb/ragcore/chunk/TechnicalChunkerTest.java
git commit -m "feat: chunk 元数据新增 sectionPath/contentType/isKeyClause/prevChunkId/nextChunkId"
```

---

## Task 6: 全量回归 + 更新 TODOS/CHANGELOG

**Files:**
- Modify: `TODOS.md`
- Modify: `CHANGELOG.md`

**Interfaces:** 无。

- [ ] **Step 1: 跑全量后端测试**

```bash
cd backend && export JAVA_HOME=$(/usr/libexec/java_home -v 17) && export PATH="$JAVA_HOME/bin:$PATH"
mvn -q test
```

预期：全部通过，尤其确认 `ElasticsearchChunkIndexTest`、`DocumentIngestionPipeline` 相关测试没有因为 `Chunk.metadata()` 内容变化而回归（这两处都不应该受影响，因为 `Chunk` record 签名没变，只是 `metadata` 这个 Map 里的内容变多了）。

- [ ] **Step 2: 更新 TODOS.md**

把 `TODOS.md` 里"deepdoc 版面/表格识别集成的后续项"章节下方新增一节，划掉"招式 1-5 未实现"的旧描述（如果之前写过），改成：

```markdown
## 结构感知切分 V3 五招式（2026-07-14 实现，见 backend/.../chunk/impl/TechnicalChunker.java + HeadingStyle.java）

已实现：多风格文档层级自动识别（HeadingStyle，非移植代码）、结构→段落→句子三级递归降级、
大表格分组分块带表头、overlap 比例区间验证、chunk 元数据增强（sectionPath/contentType/
isKeyClause/prevChunkId/nextChunkId，均落在既有 metadata Map，ES mapping 无需改动）。

后续可做但本轮未做：
- **分类器兜底未实现**：HeadingStyle 检测不到清晰编号体系时直接退化到 Markdown/空行切分，
  没有接入 ML 分类器（本身就没打算做，训练/维护成本远超收益，见计划文档的范围说明）。
- **isKeyClause 关键词列表是起点，不是终点**：目前只有责任/免责/费率类通用词，需要按实际
  业务文档语料迭代扩充或改成可配置项（当前是代码里的常量）。
- **prevChunkId/nextChunkId 目前只在 chunk 生成时写入，检索侧还没有用它自动补全语义
  不完整的相邻块**——这是文章提到的用法，但属于检索模块（HybridRetriever）的改动，
  不在本次切块计划范围内，需要单独排期。
```

- [ ] **Step 3: 更新 CHANGELOG.md**

在 `[Unreleased]` 章节（没有就新建）追加：

```markdown
### 新增

- **结构感知切分 V3 五招式** —— `TechnicalChunker` 新增多风格文档层级自动识别
  （`HeadingStyle`）、结构→段落→句子三级递归降级、大表格分组分块带表头、chunk
  元数据增强（sectionPath/contentType/isKeyClause/prevChunkId/nextChunkId）。
```

- [ ] **Step 4: 提交**

```bash
git add TODOS.md CHANGELOG.md
git commit -m "docs: 记录结构感知切分 V3 五招式的完成状态与后续项"
```

---

## Self-Review 检查清单（执行前请重新核对一遍再开始）

1. **Spec 覆盖**：招式 1(Task 1) / 招式 2(Task 2) / 招式 3(Task 3) / 招式 4(Task 4) / 招式 5(Task 5) 都有对应任务，Task 6 收尾。
2. **风险最高的点**：Task 2 改了 `chunkSection` 里行号（`bufferLineStart`/`currentLine`）的维护逻辑，必须在 Task 2 Step 4 时逐个跑现有的行号相关测试（`chunkCarriesAccurateLineRange` 等），不能只看新测试是否通过。
3. **接口一致性**：`chunkSection` 新增的 `HeadingStyle style` 参数、`recursiveSplit`/`splitByLevel`/`splitByBlankLine`/`splitBySentenceWithOverlap`/`enrichMetadata` 这几个方法名在 Task 2/3/5 之间保持一致，没有改名。
4. **不需要做的事已明确排除**：ML 分类器兜底、ES mapping 改动、`Chunk` record 新增字段、检索侧使用 prevChunkId/nextChunkId 自动补全——这四项都在对应任务里写明"本轮不做"及原因。
