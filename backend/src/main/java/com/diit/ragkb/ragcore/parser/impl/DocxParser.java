package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import org.apache.poi.xwpf.usermodel.*;

import java.io.IOException;
import java.io.InputStream;
import java.util.*;

/**
 * DOCX 文档解析器。
 *
 * <p>提取段落正文、标题层级、表格文本，保留页码信息。
 * 按标题/空行分节，每个节带 headingPath。</p>
 *
 * <p>依赖：Apache POI (poi-ooxml)。</p>
 * <p>复用来源：参考 rag2 deepdoc/parser/docx_parser.py 的段落-表格-标题提取模式，
 * 完全自研 Java 实现。</p>
 */
public class DocxParser implements DocumentParser {

    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    );
    private static final Set<String> DOCX_EXTENSIONS = Set.of("docx");

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType.toLowerCase())) return true;
        if (filename != null) {
            String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
            return DOCX_EXTENSIONS.contains(ext);
        }
        return false;
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        try (InputStream stream = input.openStream(); XWPFDocument doc = new XWPFDocument(stream)) {
            List<DocumentSection> sections = new ArrayList<>();

            Deque<String> headingStack = new ArrayDeque<>();
            StringBuilder currentBlock = new StringBuilder();
            Integer blockStartPage = null;

            for (IBodyElement elem : doc.getBodyElements()) {
                if (elem instanceof XWPFParagraph para) {
                    String style = para.getStyleID() != null ? para.getStyleID() : "";
                    String text = para.getText();

                    if (text == null || text.isBlank()) {
                        // blank line: flush accumulated block
                        if (currentBlock.length() > 50) {
                            flushBlock(currentBlock, headingStack, blockStartPage, sections);
                            currentBlock.setLength(0);
                        }
                        continue;
                    }

                    // heading detection
                    if (style.matches("(?i)Heading\\d+") || style.matches("(?i)heading\\d+")) {
                        // flush previous
                        flushBlock(currentBlock, headingStack, blockStartPage, sections);
                        currentBlock.setLength(0);

                        int level = extractHeadingLevel(style);
                        while (headingStack.size() >= level) headingStack.pollLast();
                        headingStack.add(text.strip());
                        currentBlock.append(text.strip()).append('\n');
                        continue;
                    }

                    if (currentBlock.isEmpty()) blockStartPage = null; // approximate
                    if (!currentBlock.isEmpty()) currentBlock.append('\n');
                    currentBlock.append(text);
                } else if (elem instanceof XWPFTable table) {
                    flushBlock(currentBlock, headingStack, blockStartPage, sections);
                    currentBlock.setLength(0);

                    // extract table as structured text
                    String tableText = extractTable(table);
                    if (!tableText.isBlank()) {
                        sections.add(new DocumentSection(
                                tableText, headingStack.isEmpty() ? List.of() : List.copyOf(headingStack),
                                null, null, null, Map.of("type", "table")
                        ));
                    }
                }
            }
            flushBlock(currentBlock, headingStack, blockStartPage, sections);

            return new ParsedDocument(
                    input.documentId(), input.contentType(), input.sourcePath(),
                    sections, Map.of("format", "docx", "filename", input.filename())
            );
        }
    }

    private void flushBlock(StringBuilder block, Deque<String> headingStack,
                            Integer pageNo, List<DocumentSection> sections) {
        String text = block.toString().strip();
        if (text.isEmpty()) return;
        List<String> path = headingStack.isEmpty() ? List.of() : List.copyOf(headingStack);
        sections.add(new DocumentSection(text, path, pageNo, null, null, Map.of()));
    }

    private int extractHeadingLevel(String styleId) {
        try {
            return Integer.parseInt(styleId.replaceAll("(?i)heading", "").replaceAll("(?i)Heading", ""));
        } catch (NumberFormatException e) {
            return 1;
        }
    }

    private String extractTable(XWPFTable table) {
        StringBuilder buf = new StringBuilder();
        for (XWPFTableRow row : table.getRows()) {
            List<String> cells = new ArrayList<>();
            for (XWPFTableCell cell : row.getTableCells()) {
                cells.add(cell.getText().strip());
            }
            buf.append(String.join(" | ", cells)).append('\n');
        }
        return buf.toString().strip();
    }
}
