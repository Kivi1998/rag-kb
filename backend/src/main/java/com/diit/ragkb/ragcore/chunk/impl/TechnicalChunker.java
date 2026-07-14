package com.diit.ragkb.ragcore.chunk.impl;

import com.diit.ragkb.ragcore.chunk.Chunker;
import com.diit.ragkb.ragcore.chunk.ChunkingContext;
import com.diit.ragkb.ragcore.chunk.ChunkingOptions;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 结构化技术文档切块器。
 *
 * <p>基于 rag3 {@code chunker.py} 的算法（MIT 许可），移植为 Java 实现。
 * 核心策略：
 * <ol>
 *   <li>在标题、代码围栏、类/函数定义等结构边界处优先下刀</li>
 *   <li>超长块在句子边界二次切分</li>
 *   <li>overlap 对齐到完整句子，避免半截话</li>
 *   <li>保留 headingPath、pageNo、lineStart/lineEnd、language 等元数据</li>
 * </ol>
 * </p>
 *
 * <p>许可：rag3 原始算法为 MIT License，本移植文件保留版权声明。</p>
 *
 * @implNote 移植自 rag3 的 chunker.py，在原算法基础上增加：
 *           Markdown 标题层级、代码块保护、类/函数定义边界、配置键路径。
 */
public class TechnicalChunker implements Chunker {

    // ── 结构边界正则 ──
    // Markdown 标题
    private static final Pattern MD_HEADING = Pattern.compile("(?m)^#{1,6}\\s+");
    // 中文结构：第X条、X.、一、（一）
    private static final Pattern CN_STRUCTURE = Pattern.compile(
            "(?m)^(第[一二三四五六七八九十百零\\d]+[条章节])|^([一二三四五六七八九十]+[、．.])|^([（(][一二三四五六七八九十\\d]+[）)])"
    );
    // 代码围栏
    private static final Pattern CODE_FENCE = Pattern.compile("(?m)^```");
    // Java/Python/Go 类/方法/函数定义
    private static final Pattern CODE_DEF = Pattern.compile(
            "(?m)^(public\\s+|private\\s+|protected\\s+)?(class|interface|enum|record|def|func|fn|fun|async def)\\s+\\w+"
    );
    // 句子边界
    private static final Pattern SENTENCE_END = Pattern.compile("[。!?；!?;\\n]");

    // 所有结构边界的联合 pattern
    private static final Pattern ALL_BOUNDARIES = Pattern.compile(
            MD_HEADING.pattern() + "|" + CN_STRUCTURE.pattern() + "|" + CODE_FENCE.pattern()
    );

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

    private List<Chunk> chunkSection(DocumentSection section, ParsedDocument document,
                                      UUID orgId, UUID kbId, ChunkingOptions options, HeadingStyle style) {
        List<Chunk> chunks = new ArrayList<>();
        String text = section.text();
        if (text == null || text.isBlank()) return chunks;

        // Step 1: split into semantic units at structure boundaries
        List<String> units = splitToUnits(text, options);

        // Step 2: fill buffer with units, flush when exceeding maxChars
        StringBuilder buf = new StringBuilder();
        int sourceLine = section.lineStart() != null ? section.lineStart() : 1;
        int bufferLineStart = sourceLine;
        int currentLine = sourceLine;

        for (String unit : units) {
            int unitLines = countLines(unit);
            if (startsStructuralUnit(unit) && !buf.isEmpty()) {
                chunks.add(flushBuffer(buf, section, document, orgId, kbId, chunks.size(),
                        bufferLineStart, currentLine - 1));
                buf.setLength(0);
                bufferLineStart = currentLine;
            }
            boolean isCodeFenceLine = options.preserveCodeBlocks()
                    && unit.trim().matches("^```\\w*$");

            // code fence toggle: always accumulate (code blocks kept together)
            if (isCodeFenceLine || (options.preserveCodeBlocks()
                    && buf.length() > 0 && buf.toString().trim().startsWith("```"))) {
                if (!buf.isEmpty()) buf.append('\n');
                buf.append(unit);
                currentLine += unitLines;
                continue;
            }

            // check if adding unit exceeds max
            if (!buf.isEmpty() && buf.length() + unit.length() > options.maxCharacters()) {
                String prev = buf.toString();
                chunks.add(flushBuffer(buf, section, document, orgId, kbId, chunks.size(),
                        bufferLineStart, currentLine - 1));
                buf.setLength(0);

                // carry overlap from previous block tail
                String overlap = tailOverlap(prev, options.overlapCharacters());
                if (!overlap.isEmpty()) {
                    buf.append(overlap);
                    bufferLineStart = Math.max(section.lineStart() == null ? 1 : section.lineStart(),
                            currentLine - countLines(overlap));
                } else {
                    bufferLineStart = currentLine;
                }
            }

            if (!buf.isEmpty()) buf.append('\n');
            buf.append(unit);
            currentLine += unitLines;

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
        }

        // flush remaining
        if (!buf.isEmpty()) {
            chunks.add(flushBuffer(buf, section, document, orgId, kbId, chunks.size(),
                    bufferLineStart, currentLine - 1));
        }

        return chunks;
    }

    /**
     * Split text at natural structure boundaries. Overlong units are split in
     * {@link #chunkSection(DocumentSection, ParsedDocument, UUID, UUID, ChunkingOptions, HeadingStyle)}
     * so that {@link ChunkingOptions#maxCharacters()} is the only length limit.
     */
    List<String> splitToUnits(String text, ChunkingOptions options) {
        List<String> units = new ArrayList<>();

        // split by lines, detect structure boundaries, group into semantic units
        String[] lines = text.split("\n", -1);
        StringBuilder current = new StringBuilder();
        boolean inCodeFence = false;
        boolean preserveCode = options.preserveCodeBlocks();

        for (int i = 0; i < lines.length; i++) {
            String line = lines[i];
            String stripped = line.strip();

            // code fence toggle — only if preserveCodeBlocks is enabled
            if (preserveCode && stripped.matches("^```\\w*$")) {
                if (inCodeFence) {
                    current.append(line).append('\n');
                    units.add(current.toString().strip());
                    current.setLength(0);
                    inCodeFence = false;
                } else {
                    flushCurrent(current, units);
                    current.append(line).append('\n');
                    inCodeFence = true;
                }
                continue;
            }

            // inside code fence: accumulate everything
            if (inCodeFence) {
                current.append(line).append('\n');
                continue;
            }

            // markdown heading: new semantic unit
            if (MD_HEADING.matcher(line).find()) {
                flushCurrent(current, units);
                current.append(line).append('\n');
                continue;
            }

            // Chinese structure heading
            if (!stripped.isEmpty() && CN_STRUCTURE.matcher(stripped).find()) {
                flushCurrent(current, units);
                current.append(line).append('\n');
                continue;
            }

            // blank line: paragraph boundary
            if (line.isBlank()) {
                if (current.length() > 50) {
                    flushCurrent(current, units);
                    current.setLength(0);
                } else if (!current.isEmpty()) {
                    current.append('\n');
                }
                continue;
            }

            current.append(line).append('\n');
        }

        flushCurrent(current, units);
        return units;
    }

    private void flushCurrent(StringBuilder buf, List<String> units) {
        String s = buf.toString().strip();
        if (!s.isEmpty()) {
            // 保留原始标点与换行；长度切分统一由 chunkSection 按 options.maxCharacters 处理。
            units.add(s);
        }
        buf.setLength(0);
    }

    /**
     * Take tail of text up to overlap chars, aligned to sentence boundary.
     * Ported from rag3 {@code _tail_overlap}.
     */
    String tailOverlap(String text, int overlap) {
        if (overlap <= 0 || text.length() <= overlap) return "";
        String tail = text.substring(text.length() - overlap);
        java.util.regex.Matcher m = SENTENCE_END.matcher(tail);
        if (m.find()) {
            int idx = m.end();
            if (idx < tail.length()) return tail.substring(idx);
        }
        return "";
    }

    /**
     * Find the best position to split text at or before maxChars, aligned to a sentence boundary.
     */
    private int findSentenceSplit(String text, int maxChars) {
        String slice = text.substring(0, Math.min(maxChars, text.length()));
        java.util.regex.Matcher m = SENTENCE_END.matcher(slice);
        int lastEnd = maxChars;
        while (m.find()) lastEnd = m.end();
        return lastEnd;
    }

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

    private Chunk flushBuffer(StringBuilder buf, DocumentSection section, ParsedDocument document,
                               UUID orgId, UUID kbId, int ordinal, int lineStart, int lineEnd) {
        String content = buf.toString();

        String lang = document.metadata() != null ? document.metadata().getOrDefault("language", "") : "";
        String id = chunkId(document.documentId(), ordinal, content);

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
                section.metadata()
        );
    }

    private boolean startsStructuralUnit(String unit) {
        String stripped = unit.strip();
        return MD_HEADING.matcher(stripped).find() || CN_STRUCTURE.matcher(stripped).find();
    }

    private int countLines(String text) {
        if (text == null || text.isEmpty()) return 0;
        return (int) text.chars().filter(c -> c == '\n').count() + 1;
    }

    private static String sha256_8(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(input.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash).substring(0, 8);
        } catch (NoSuchAlgorithmException e) {
            return Integer.toHexString(input.hashCode());
        }
    }

    private static String chunkId(UUID documentId, int ordinal, String content) {
        return documentId + ":" + ordinal + ":" + sha256_8(content);
    }
}
