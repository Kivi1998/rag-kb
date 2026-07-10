package com.diit.ragkb.ragcore.model;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 进入检索索引的最小上下文单元。 */
public record Chunk(
        String id,
        UUID organizationId,
        UUID knowledgeBaseId,
        UUID documentId,
        int ordinal,
        String content,
        List<String> headingPath,
        String sourcePath,
        Integer pageNo,
        Integer lineStart,
        Integer lineEnd,
        String language,
        String contentHash,
        Map<String, String> metadata
) {
    public Chunk {
        headingPath = headingPath == null ? List.of() : List.copyOf(headingPath);
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
    }
}
