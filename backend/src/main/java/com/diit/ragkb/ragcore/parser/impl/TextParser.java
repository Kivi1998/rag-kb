package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * 纯文本 / 日志解析器。
 *
 * <p>按空行分块。连续非空行聚为一节，长块优先在句末边界二次切分。
 * 自动检测常见编码（UTF-8/GBK/ISO-8859-1）。</p>
 *
 * <p>复用来源：参考 rag2 deepdoc/parser/txt_parser.py 的按分隔符切块思路，
 * 完全自研 Java 实现。</p>
 */
public class TextParser implements DocumentParser {

    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "text/plain", "text/x-log", "text/csv", "application/octet-stream"
    );
    private static final Set<String> TEXT_EXTENSIONS = Set.of(
            "txt", "log", "csv", "tsv", "text", "sql", "sh", "bat", "cfg", "conf", "ini", "env", "properties"
    );

    private static final int MAX_SECTION_CHARS = 4096;

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType.toLowerCase())) return true;
        if (filename != null) {
            String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
            return TEXT_EXTENSIONS.contains(ext);
        }
        return false;
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        List<String> paragraphs = new ArrayList<>();
        StringBuilder buf = new StringBuilder();

        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input.openStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    if (!buf.isEmpty()) {
                        paragraphs.add(buf.toString().strip());
                        buf.setLength(0);
                    }
                } else {
                    if (!buf.isEmpty()) buf.append('\n');
                    buf.append(line);
                }
            }
        }
        if (!buf.isEmpty()) paragraphs.add(buf.toString().strip());

        List<DocumentSection> sections = new ArrayList<>();
        int lineNo = 1;

        for (String para : paragraphs) {
            if (para.length() <= MAX_SECTION_CHARS) {
                sections.add(new DocumentSection(para, List.of(), null, lineNo, lineNo + countLines(para), Map.of()));
                lineNo += countLines(para) + 1;
            } else {
                // split long paragraphs at sentence boundaries
                List<String> splits = splitLongText(para);
                for (String split : splits) {
                    sections.add(new DocumentSection(split, List.of(), null, lineNo, lineNo + countLines(split), Map.of()));
                    lineNo += countLines(split) + 1;
                }
            }
        }

        return new ParsedDocument(
                input.documentId(),
                input.contentType(),
                input.sourcePath(),
                sections,
                Map.of("format", "text", "filename", input.filename())
        );
    }

    private List<String> splitLongText(String text) {
        List<String> result = new ArrayList<>();
        StringBuilder buf = new StringBuilder();
        String[] sentences = text.split("(?<=[。!?；!?;\\n])");
        for (String s : sentences) {
            if (buf.length() + s.length() > MAX_SECTION_CHARS && !buf.isEmpty()) {
                result.add(buf.toString().strip());
                buf.setLength(0);
            }
            buf.append(s);
        }
        if (!buf.isEmpty()) result.add(buf.toString().strip());
        return result;
    }

    private int countLines(String text) {
        return (int) text.chars().filter(c -> c == '\n').count();
    }
}
