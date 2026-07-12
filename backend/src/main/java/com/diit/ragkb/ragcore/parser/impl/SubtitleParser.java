package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** SRT/WebVTT 字幕解析器，保留时间轴用于问答引用定位。 */
public class SubtitleParser implements DocumentParser {

    @Override
    public boolean supports(String contentType, String filename) {
        String type = contentType == null ? "" : contentType.toLowerCase(Locale.ROOT);
        if (type.equals("application/x-subrip") || type.equals("text/vtt") || type.equals("text/srt")) {
            return true;
        }
        String name = filename == null ? "" : filename.toLowerCase(Locale.ROOT);
        return name.endsWith(".srt") || name.endsWith(".vtt");
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        List<DocumentSection> sections = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input.openStream(), StandardCharsets.UTF_8))) {
            List<String> block = new ArrayList<>();
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    appendBlock(block, sections);
                    block.clear();
                } else if (!line.strip().equalsIgnoreCase("WEBVTT")) {
                    block.add(line.strip());
                }
            }
            appendBlock(block, sections);
        }
        if (sections.isEmpty()) {
            throw new IOException("字幕文件中没有可索引的字幕内容");
        }
        String format = input.filename().toLowerCase(Locale.ROOT).endsWith(".vtt") ? "vtt" : "srt";
        return new ParsedDocument(input.documentId(), input.contentType(), input.sourcePath(), sections,
                Map.of("format", format, "cueCount", String.valueOf(sections.size())));
    }

    private void appendBlock(List<String> rawBlock, List<DocumentSection> sections) {
        if (rawBlock.isEmpty()) {
            return;
        }
        int timeIndex = -1;
        for (int i = 0; i < rawBlock.size(); i++) {
            if (rawBlock.get(i).contains("-->")) {
                timeIndex = i;
                break;
            }
        }
        if (timeIndex < 0 || timeIndex == rawBlock.size() - 1) {
            return;
        }
        String timeRange = rawBlock.get(timeIndex).replaceAll("\\s+", " ");
        String text = String.join("\n", rawBlock.subList(timeIndex + 1, rawBlock.size())).strip();
        if (!text.isEmpty()) {
            sections.add(new DocumentSection(text, List.of(), null, null, null,
                    Map.of("type", "subtitle", "timeRange", timeRange)));
        }
    }
}
