package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Markdown 文档解析器。
 *
 * <p>保留标题层级（headingPath）、代码围栏、列表结构和段落边界，
 * 按空行分段，追踪标题栈构建 headingPath。</p>
 *
 * <p>复用来源：参考 rag2 deepdoc/parser/markdown_parser.py 的格式能力清单，
 * 完全自研 Java 实现。</p>
 */
public class MarkdownParser implements DocumentParser {

    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "text/markdown", "text/x-markdown"
    );
    private static final Set<String> MARKDOWN_EXTENSIONS = Set.of("md", "markdown", "mdown", "mkd");

    private static final Pattern HEADING_RE = Pattern.compile("^(#{1,6})\\s+(.+)$");
    private static final Pattern CODE_FENCE_RE = Pattern.compile("^```(\\w*)$");

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType.toLowerCase())) return true;
        if (filename != null) {
            String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
            return MARKDOWN_EXTENSIONS.contains(ext);
        }
        return false;
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        List<String> allLines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input.openStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                allLines.add(line);
            }
        }

        List<DocumentSection> sections = new ArrayList<>();
        Deque<String> headingStack = new ArrayDeque<>();
        Deque<Integer> headingLevels = new ArrayDeque<>();
        StringBuilder currentBlock = new StringBuilder();
        int blockStartLine = 1;
        boolean inCodeFence = false;

        for (int i = 0; i < allLines.size(); i++) {
            String line = allLines.get(i);
            int lineNo = i + 1;

            // code fence toggle
            Matcher fenceMatcher = CODE_FENCE_RE.matcher(line.trim());
            if (fenceMatcher.matches()) {
                inCodeFence = !inCodeFence;
                currentBlock.append(line).append('\n');
                continue;
            }

            // inside code fence: accumulate without structure analysis
            if (inCodeFence) {
                currentBlock.append(line).append('\n');
                continue;
            }

            // heading detection
            Matcher headingMatcher = HEADING_RE.matcher(line);
            if (headingMatcher.matches()) {
                // flush previous block
                flushBlock(currentBlock, headingStack, blockStartLine, lineNo - 1, sections);
                currentBlock.setLength(0);

                int level = headingMatcher.group(1).length();
                String title = headingMatcher.group(2).strip();

                // 以标题真实层级回退；不能仅按栈长度判断（例如 ### 后出现 ##）。
                while (!headingLevels.isEmpty() && headingLevels.peekLast() >= level) {
                    headingLevels.pollLast();
                    headingStack.pollLast();
                }
                headingLevels.add(level);
                headingStack.add(title);

                blockStartLine = lineNo;
                currentBlock.append(line).append('\n');
                continue;
            }

            // blank line -> paragraph boundary
            if (line.isBlank()) {
                currentBlock.append('\n');
                if (currentBlock.length() > 50) { // flush when we have meaningful content
                    flushBlock(currentBlock, headingStack, blockStartLine, lineNo, sections);
                    currentBlock.setLength(0);
                    blockStartLine = lineNo + 1;
                }
                continue;
            }

            currentBlock.append(line).append('\n');
        }

        // flush remaining
        flushBlock(currentBlock, headingStack, blockStartLine, allLines.size(), sections);

        return new ParsedDocument(
                input.documentId(),
                input.contentType(),
                input.sourcePath(),
                sections,
                Map.of("format", "markdown", "filename", input.filename())
        );
    }

    private void flushBlock(StringBuilder block, Deque<String> headingStack,
                            int lineStart, int lineEnd, List<DocumentSection> sections) {
        String text = block.toString().strip();
        if (text.isEmpty()) return;
        List<String> path = headingStack.isEmpty() ? List.of() : List.copyOf(headingStack);
        sections.add(new DocumentSection(text, path, null, lineStart, lineEnd, Map.of()));
    }
}
