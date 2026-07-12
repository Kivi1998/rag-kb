package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
import com.diit.ragkb.ragcore.index.SearchRequest;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.http.HttpEntity;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** ES 原生 BM25/kNN 双路候选召回。禁止构造无 org/kb filter 的查询。 */
public class ElasticsearchHybridCandidateSource implements HybridCandidateSource {

    private static final List<String> SOURCE_FIELDS = List.of(
            "chunk_id", "org_id", "kb_id", "document_id", "ordinal", "content", "heading_path", "source_path",
            "page_no", "line_start", "line_end", "language", "content_hash", "metadata");

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;

    public ElasticsearchHybridCandidateSource(RestClient restClient, RagElasticsearchProperties properties,
                                              ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public List<RetrievedChunk> searchBm25(SearchRequest request) {
        requireBoundary(request.organizationId(), request.knowledgeBaseId());
        if (request.query() == null || request.query().isBlank()) {
            return List.of();
        }
        Map<String, Object> body = Map.of(
                "size", request.topK(),
                "_source", SOURCE_FIELDS,
                "query", Map.of("bool", Map.of(
                        "filter", tenantFilters(request.organizationId(), request.knowledgeBaseId()),
                        "should", List.of(
                                Map.of("term", Map.of("symbol_names", Map.of("value", request.query(), "boost", 8))),
                                Map.of("term", Map.of("config_keys", Map.of("value", request.query(), "boost", 7))),
                                Map.of("term", Map.of("error_codes", Map.of("value", request.query(), "boost", 7))),
                                Map.of("match", Map.of("content_search", Map.of("query", request.query(), "boost", 1)))),
                        "minimum_should_match", 1)));
        return execute(body, true);
    }

    @Override
    public List<RetrievedChunk> searchKnn(VectorSearchRequest request) {
        requireBoundary(request.organizationId(), request.knowledgeBaseId());
        if (request.queryVector().size() != properties.getVectorDimensions()) {
            throw new IllegalArgumentException("查询向量维度必须为 " + properties.getVectorDimensions());
        }
        Map<String, Object> body = Map.of(
                "size", request.topK(),
                "_source", SOURCE_FIELDS,
                "knn", Map.of(
                        "field", "content_vector",
                        "query_vector", request.queryVector(),
                        "k", request.topK(),
                        "num_candidates", Math.max(100, request.topK() * 3),
                        "filter", tenantFilters(request.organizationId(), request.knowledgeBaseId())));
        return execute(body, false);
    }

    private List<RetrievedChunk> execute(Map<String, Object> body, boolean bm25) {
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_search");
        request.setJsonEntity(writeJson(body));
        try {
            Response response = restClient.performRequest(request);
            return parseHits(response.getEntity(), bm25);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES 候选召回失败", ex);
        }
    }

    private List<Map<String, Object>> tenantFilters(UUID organizationId, UUID knowledgeBaseId) {
        return List.of(
                Map.of("term", Map.of("org_id", organizationId.toString())),
                Map.of("term", Map.of("kb_id", knowledgeBaseId.toString())));
    }

    private List<RetrievedChunk> parseHits(HttpEntity entity, boolean bm25) throws IOException {
        if (entity == null) {
            throw new ElasticsearchIndexException("ES 搜索响应为空");
        }
        JsonNode hits = objectMapper.readTree(entity.getContent()).path("hits").path("hits");
        if (!hits.isArray()) {
            throw new ElasticsearchIndexException("ES 搜索响应缺少 hits.hits");
        }
        List<RetrievedChunk> result = new ArrayList<>();
        int rank = 1;
        for (JsonNode hit : hits) {
            Chunk chunk = toChunk(hit.path("_source"));
            Double score = hit.path("_score").isNumber() ? hit.path("_score").doubleValue() : null;
            result.add(bm25
                    ? new RetrievedChunk(chunk, rank++, null, null, null, score)
                    : new RetrievedChunk(chunk, null, rank++, null, null, score));
        }
        return result;
    }

    private Chunk toChunk(JsonNode source) {
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
                    source.path("language").asText(null), source.path("content_hash").asText(null), Map.of());
        } catch (IllegalArgumentException ex) {
            throw new ElasticsearchIndexException("ES chunk 字段不完整或类型错误", ex);
        }
    }

    private String requiredText(JsonNode source, String field) {
        String value = source.path(field).asText();
        if (value == null || value.isBlank()) throw new IllegalArgumentException("缺少 " + field);
        return value;
    }

    private Integer nullableInt(JsonNode source, String field) {
        return source.path(field).isNumber() ? source.path(field).intValue() : null;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造 ES 检索请求失败", ex);
        }
    }

    private void requireBoundary(UUID organizationId, UUID knowledgeBaseId) {
        if (organizationId == null || knowledgeBaseId == null) {
            throw new IllegalArgumentException("检索请求必须携带服务端组织与知识库边界");
        }
    }
}
