package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.ragcore.model.Citation;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;

import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 将最终参与回答的 chunk 转为前端可定位的服务端引用。 */
public final class CitationBuilder {

    private static final int MAX_SNIPPET_CHARS = 500;

    private CitationBuilder() {
    }

    public static List<Citation> build(List<RetrievedChunk> chunks, Map<UUID, String> documentNames) {
        return chunks.stream().map(item -> build(item, documentNames)).toList();
    }

    private static Citation build(RetrievedChunk item, Map<UUID, String> documentNames) {
        Chunk chunk = item.chunk();
        String content = chunk.content();
        String snippet = content.length() <= MAX_SNIPPET_CHARS ? content
                : content.substring(0, MAX_SNIPPET_CHARS) + "…";
        return new Citation(chunk.documentId(), documentNames.getOrDefault(chunk.documentId(), "已删除或不可访问的文档"),
                chunk.headingPath(), snippet, chunk.pageNo(), chunk.lineStart(), chunk.lineEnd(), item.finalScore());
    }
}
