package com.diit.ragkb.ragcore.model;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 文档解析结果，保留标题层级、页码和代码等结构元数据。 */
public record ParsedDocument(
        UUID documentId,
        String contentType,
        String sourcePath,
        List<DocumentSection> sections,
        Map<String, String> metadata
) {
    public ParsedDocument {
        sections = sections == null ? List.of() : List.copyOf(sections);
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
    }
}
