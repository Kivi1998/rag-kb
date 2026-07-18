package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
import com.diit.ragkb.ragcore.index.SearchRequest;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** ES 原生 BM25 候选召回，保留代码符号、配置键和错误码的精确加权。 */
public class ElasticsearchLexicalCandidateSource implements LexicalCandidateSource {

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;

    public ElasticsearchLexicalCandidateSource(RestClient restClient, RagElasticsearchProperties properties,
                                               ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public List<RetrievedChunk> search(SearchRequest request) {
        requireBoundary(request.organizationId(), request.knowledgeBaseId());
        if (request.query() == null || request.query().isBlank()) return List.of();
        Map<String, Object> body = Map.of(
                "size", request.topK(),
                "_source", ElasticsearchChunkDocumentMapper.SOURCE_FIELDS,
                "query", Map.of("bool", Map.of(
                        "filter", tenantFilters(request.organizationId(), request.knowledgeBaseId(), request.documentIds()),
                        "should", List.of(
                                Map.of("term", Map.of("symbol_names", Map.of("value", request.query(), "boost", 8))),
                                Map.of("term", Map.of("config_keys", Map.of("value", request.query(), "boost", 7))),
                                Map.of("term", Map.of("error_codes", Map.of("value", request.query(), "boost", 7))),
                                Map.of("match", Map.of("content_search", Map.of("query", request.query(), "boost", 1)))),
                        "minimum_should_match", 1)));
        Request esRequest = new Request("POST", "/" + properties.getIndexName() + "/_search");
        esRequest.setJsonEntity(writeJson(body));
        try {
            Response response = restClient.performRequest(esRequest);
            JsonNode hits = objectMapper.readTree(response.getEntity().getContent()).path("hits").path("hits");
            if (!hits.isArray()) throw new ElasticsearchIndexException("ES 搜索响应缺少 hits.hits");
            List<RetrievedChunk> result = new ArrayList<>();
            int rank = 1;
            for (JsonNode hit : hits) {
                Double score = hit.path("_score").isNumber() ? hit.path("_score").doubleValue() : null;
                result.add(new RetrievedChunk(ElasticsearchChunkDocumentMapper.toChunk(hit.path("_source")),
                        rank++, null, null, null, score));
            }
            return result;
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES BM25 召回失败", ex);
        }
    }

    private List<Map<String, Object>> tenantFilters(UUID orgId, UUID kbId, List<UUID> documentIds) {
        List<Map<String, Object>> filters = new ArrayList<>(List.of(
                Map.of("term", Map.of("org_id", orgId.toString())),
                Map.of("term", Map.of("kb_id", kbId.toString())),
                Map.of("term", Map.of("retrieval_ready", true))));
        if (documentIds != null && !documentIds.isEmpty()) {
            filters.add(Map.of("terms", Map.of("document_id", documentIds.stream().map(UUID::toString).toList())));
        }
        return filters;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造 ES BM25 请求失败", ex);
        }
    }

    private void requireBoundary(UUID orgId, UUID kbId) {
        if (orgId == null || kbId == null) throw new IllegalArgumentException("BM25 请求必须携带组织与知识库边界");
    }
}
