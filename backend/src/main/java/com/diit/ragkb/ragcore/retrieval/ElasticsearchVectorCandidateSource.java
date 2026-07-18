package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
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

/** ES kNN 基线与回滚候选源；只返回 Chunk ID、排名和分数。 */
public class ElasticsearchVectorCandidateSource implements VectorCandidateSource {

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;

    public ElasticsearchVectorCandidateSource(RestClient restClient, RagElasticsearchProperties properties,
                                              ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public List<VectorHit> search(VectorSearchRequest request) {
        if (request.queryVector().size() != properties.getVectorDimensions()) {
            throw new IllegalArgumentException("查询向量维度必须为 " + properties.getVectorDimensions());
        }
        Map<String, Object> body = Map.of(
                "size", request.topK(),
                "_source", List.of("chunk_id"),
                "knn", Map.of(
                        "field", "content_vector",
                        "query_vector", request.queryVector(),
                        "k", request.topK(),
                        "num_candidates", Math.max(100, request.topK() * 3),
                        "filter", tenantFilters(request.organizationId(), request.knowledgeBaseId(), request.documentIds())));
        Request esRequest = new Request("POST", "/" + properties.getIndexName() + "/_search");
        esRequest.setJsonEntity(writeJson(body));
        try {
            Response response = restClient.performRequest(esRequest);
            JsonNode hits = objectMapper.readTree(response.getEntity().getContent()).path("hits").path("hits");
            if (!hits.isArray()) throw new ElasticsearchIndexException("ES kNN 响应缺少 hits.hits");
            List<VectorHit> result = new ArrayList<>();
            int rank = 1;
            for (JsonNode hit : hits) {
                String chunkId = hit.path("_source").path("chunk_id").asText();
                double score = hit.path("_score").asDouble(0);
                result.add(new VectorHit(chunkId, rank++, score));
            }
            return result;
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES kNN 召回失败", ex);
        }
    }

    private List<Map<String, Object>> tenantFilters(UUID orgId, UUID kbId, List<UUID> documentIds) {
        if (orgId == null || kbId == null) throw new IllegalArgumentException("向量请求必须携带组织与知识库边界");
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
            throw new ElasticsearchIndexException("构造 ES kNN 请求失败", ex);
        }
    }
}
