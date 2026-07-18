package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
import com.diit.ragkb.ragcore.model.Chunk;
import com.fasterxml.jackson.databind.JsonNode;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** ES Chunk 投影的唯一反序列化入口，避免词法召回与补齐路径字段漂移。 */
final class ElasticsearchChunkDocumentMapper {

    static final List<String> SOURCE_FIELDS = List.of(
            "chunk_id", "org_id", "kb_id", "document_id", "ordinal", "content", "heading_path", "source_path",
            "page_no", "line_start", "line_end", "language", "content_hash", "metadata");

    private ElasticsearchChunkDocumentMapper() { }

    static Chunk toChunk(JsonNode source) {
        try {
            UUID orgId = UUID.fromString(requiredText(source, "org_id"));
            UUID kbId = UUID.fromString(requiredText(source, "kb_id"));
            UUID documentId = UUID.fromString(requiredText(source, "document_id"));
            List<String> heading = new ArrayList<>();
            for (JsonNode item : source.path("heading_path")) heading.add(item.asText());
            return new Chunk(requiredText(source, "chunk_id"), orgId, kbId, documentId,
                    source.path("ordinal").asInt(), requiredText(source, "content"), heading,
                    source.path("source_path").asText(null), nullableInt(source, "page_no"),
                    nullableInt(source, "line_start"), nullableInt(source, "line_end"),
                    source.path("language").asText(null), source.path("content_hash").asText(null),
                    stringMetadata(source.path("metadata")));
        } catch (IllegalArgumentException ex) {
            throw new ElasticsearchIndexException("ES chunk 字段不完整或类型错误", ex);
        }
    }

    private static Map<String, String> stringMetadata(JsonNode metadata) {
        if (!metadata.isObject()) return Map.of();
        Map<String, String> values = new LinkedHashMap<>();
        metadata.fields().forEachRemaining(entry -> values.put(entry.getKey(), entry.getValue().asText()));
        return values;
    }

    private static String requiredText(JsonNode source, String field) {
        String value = source.path(field).asText();
        if (value == null || value.isBlank()) throw new IllegalArgumentException("缺少 " + field);
        return value;
    }

    private static Integer nullableInt(JsonNode source, String field) {
        return source.path(field).isNumber() ? source.path(field).intValue() : null;
    }
}
