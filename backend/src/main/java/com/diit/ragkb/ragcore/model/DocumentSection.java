package com.diit.ragkb.ragcore.model;

import java.util.List;
import java.util.Map;

/** 解析后、切分前的结构化文档区段。 */
public record DocumentSection(
        String text,
        List<String> headingPath,
        Integer pageNo,
        Integer lineStart,
        Integer lineEnd,
        Map<String, String> metadata
) {
    public DocumentSection {
        headingPath = headingPath == null ? List.of() : List.copyOf(headingPath);
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
    }
}
