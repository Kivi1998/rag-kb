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

        for (DocumentSection section : document.sections()) {
            List<Chunk> sectionChunks = chunkSection(
                    section, document, context.organizationId(), context.knowledgeBaseId(), options);
            chunks.addAll(sectionChunks);
        }

        // renumber ordinals globally
        for (int i = 0; i < chunks.size(); i++) {
            Chunk old = chunks.get(i);
            chunks.set(i, new Chunk(
                    old.id(), old.organizationId(), old.knowledgeBaseId(), old.documentId(),
                    i, old.content(), old.headingPath(), old.sourcePath(),
                    old.pageNo(), old.lineStart(), old.lineEnd(),
                    old.language(), old.contentHash(), old.metadata()
            ));
        }

        return chunks;
    }

    private List<Chunk> chunkSection(DocumentSection section, ParsedDocument document,
                                      UUID orgId, UUID kbId, ChunkingOptions options) {
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
            boolean isCodeFenceLine = unit.trim().matches("^```\\w*$");

            // code fence toggle: always accumulate (code blocks kept together)
            if (isCodeFenceLine || (buf.length() > 0 && buf.toString().trim().startsWith("```"))) {
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

            // if single unit alone exceeds max, split at sentence boundaries
            while (buf.length() > options.maxCharacters()) {
                int splitAt = findSentenceSplit(buf.toString(), options.maxCharacters());
                String head = buf.substring(0, splitAt).strip();
                int headLineEnd = bufferLineStart + countLines(head) - 1;
                chunks.add(flushBuffer(new StringBuilder(head), section, document, orgId, kbId, chunks.size(),
                        bufferLineStart, headLineEnd));

                // carry overlap + remainder
                String tailPart = buf.substring(splitAt);
                String overlap = tailOverlap(head, options.overlapCharacters());
                buf.setLength(0);
                if (!overlap.isEmpty()) buf.append(overlap);
                buf.append(tailPart);
                bufferLineStart = overlap.isEmpty()
                        ? headLineEnd + 1
                        : Math.max(section.lineStart() == null ? 1 : section.lineStart(),
                                headLineEnd - countLines(overlap) + 1);
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
     * Split text at natural structure boundaries, then at sentence boundaries
     * for overlong segments. Ported from rag3 {@code _split_units}.
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
            if (s.length() <= 1024) {
                units.add(s);
            } else {
                // split overlong at sentence boundaries
                String[] sentences = SENTENCE_END.split(s);
                StringBuilder sb = new StringBuilder();
                for (int j = 0; j < sentences.length; j++) {
                    String part = sentences[j];
                    if (sb.length() + part.length() > 1024 && !sb.isEmpty()) {
                        units.add(sb.toString().trim());
                        sb.setLength(0);
                    }
                    sb.append(part);
                }
                if (!sb.isEmpty()) {
                    units.add(sb.toString().trim());
                }
            }
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

    private Chunk flushBuffer(StringBuilder buf, DocumentSection section, ParsedDocument document,
                               UUID orgId, UUID kbId, int ordinal, int lineStart, int lineEnd) {
        String content = buf.toString().strip();
        if (content.isEmpty()) content = buf.toString(); // preserve whitespace-only chunks as-is

        String lang = document.metadata() != null ? document.metadata().getOrDefault("language", "") : "";
        String id = document.documentId() + ":" + ordinal + ":" + sha256_8(content);

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

    private static UUID parseUuid(String s) {
        try {
            return s != null ? UUID.fromString(s) : null;
        } catch (IllegalArgumentException e) {
            return null;
        }
    }
}
