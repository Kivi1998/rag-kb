package com.diit.ragkb.ragcore.model;

import java.util.List;
import java.util.UUID;

/** 供前端展示、审计与溯源使用的回答引用。 */
public record Citation(
        UUID documentId,
        String documentName,
        List<String> headingPath,
        String snippet,
        Integer pageNo,
        Integer lineStart,
        Integer lineEnd,
        Double score
) {
    public Citation {
        headingPath = headingPath == null ? List.of() : List.copyOf(headingPath);
    }
}
