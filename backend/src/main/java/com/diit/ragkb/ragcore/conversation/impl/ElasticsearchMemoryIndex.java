package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryRecord;
import com.diit.ragkb.ragcore.conversation.MemoryType;
import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.http.HttpEntity;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.ResponseException;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * 统一记忆索引（{@code rag_memory_v1}）的原生 ES 适配器。复用 chunk 索引同一个 ES 集群
 * （同一个 {@link RestClient} 实例），只是索引名不同，比照 {@code ElasticsearchChunkIndex} 的实现模式。
 */
public class ElasticsearchMemoryIndex implements MemoryIndex {

    private final RestClient restClient;
    private final RagElasticsearchProperties esProperties;
    private final RagMemoryProperties memoryProperties;
    private final ObjectMapper objectMapper;

    public ElasticsearchMemoryIndex(RestClient restClient, RagElasticsearchProperties esProperties,
                                    RagMemoryProperties memoryProperties, ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.esProperties = Objects.requireNonNull(esProperties, "esProperties 不能为空");
        this.memoryProperties = Objects.requireNonNull(memoryProperties, "memoryProperties 不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
        ensureIndex();
    }

    @Override
    public void upsert(MemoryRecord record, List<Float> vector) {
        Objects.requireNonNull(record, "record 不能为空");
        if (vector == null || vector.size() != esProperties.getVectorDimensions()) {
            throw new IllegalArgumentException("向量维度必须为 " + esProperties.getVectorDimensions());
        }
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("memory_id", record.memoryId());
        source.put("org_id", record.organizationId().toString());
        source.put("member_id", record.memberId().toString());
        source.put("session_id", record.sessionId() == null ? null : record.sessionId().toString());
        source.put("memory_type", record.type().name());
        source.put("content", record.content());
        source.put("content_vector", vector);
        source.put("created_at", record.createdAt().toString());

        Request request = new Request("PUT",
                "/" + memoryProperties.getMemoryIndexName() + "/_doc/" + record.memoryId());
        request.setJsonEntity(writeJson(source));
        try {
            restClient.performRequest(request);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("写入记忆索引失败", ex);
        }
    }

    @Override
    public void delete(String memoryId) {
        Request request = new Request("DELETE",
                "/" + memoryProperties.getMemoryIndexName() + "/_doc/" + memoryId);
        try {
            restClient.performRequest(request);
        } catch (ResponseException ex) {
            if (ex.getResponse().getStatusLine().getStatusCode() != 404) {
                throw new ElasticsearchIndexException("删除记忆条目失败", ex);
            }
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("删除记忆条目失败", ex);
        }
    }

    @Override
    public List<ScoredMemoryRecord> searchSessionHistory(UUID organizationId, UUID sessionId, List<Float> queryVector,
                                                         int topK) {
        List<Map<String, Object>> filters = List.of(
                Map.of("term", Map.of("org_id", organizationId.toString())),
                Map.of("term", Map.of("session_id", sessionId.toString())),
                Map.of("term", Map.of("memory_type", MemoryType.SESSION_MESSAGE.name())));
        return search(filters, queryVector, topK);
    }

    @Override
    public List<ScoredMemoryRecord> searchProfileItems(UUID organizationId, UUID memberId, List<Float> queryVector,
                                                       int topK) {
        List<Map<String, Object>> filters = List.of(
                Map.of("term", Map.of("org_id", organizationId.toString())),
                Map.of("term", Map.of("member_id", memberId.toString())),
                Map.of("term", Map.of("memory_type", MemoryType.PROFILE_ITEM.name())));
        return search(filters, queryVector, topK);
    }

    private List<ScoredMemoryRecord> search(List<Map<String, Object>> filters, List<Float> queryVector, int topK) {
        if (queryVector == null || queryVector.size() != esProperties.getVectorDimensions()) {
            throw new IllegalArgumentException("查询向量维度必须为 " + esProperties.getVectorDimensions());
        }
        Map<String, Object> body = Map.of(
                "size", topK,
                "_source", List.of("memory_id", "org_id", "member_id", "session_id", "memory_type", "content",
                        "created_at"),
                "knn", Map.of(
                        "field", "content_vector",
                        "query_vector", queryVector,
                        "k", topK,
                        "num_candidates", Math.max(50, topK * 3),
                        "filter", filters));
        Request request = new Request("POST", "/" + memoryProperties.getMemoryIndexName() + "/_search");
        request.setJsonEntity(writeJson(body));
        try {
            Response response = restClient.performRequest(request);
            return parseHits(response.getEntity());
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("记忆索引检索失败", ex);
        }
    }

    private List<ScoredMemoryRecord> parseHits(HttpEntity entity) throws IOException {
        if (entity == null) {
            throw new ElasticsearchIndexException("ES 搜索响应为空");
        }
        JsonNode hits = objectMapper.readTree(entity.getContent()).path("hits").path("hits");
        List<ScoredMemoryRecord> result = new ArrayList<>();
        for (JsonNode hit : hits) {
            JsonNode source = hit.path("_source");
            UUID sessionId = source.path("session_id").isTextual()
                    ? UUID.fromString(source.path("session_id").asText()) : null;
            MemoryRecord record = new MemoryRecord(
                    source.path("memory_id").asText(),
                    UUID.fromString(source.path("org_id").asText()),
                    UUID.fromString(source.path("member_id").asText()),
                    sessionId,
                    MemoryType.valueOf(source.path("memory_type").asText()),
                    source.path("content").asText(),
                    Instant.parse(source.path("created_at").asText()));
            double score = hit.path("_score").isNumber() ? hit.path("_score").doubleValue() : 0.0;
            result.add(new ScoredMemoryRecord(record, score));
        }
        return result;
    }

    private void ensureIndex() {
        try {
            Response response = restClient.performRequest(
                    new Request("HEAD", "/" + memoryProperties.getMemoryIndexName()));
            int status = response.getStatusLine().getStatusCode();
            if (status >= 200 && status < 300) {
                return;
            }
        } catch (ResponseException ex) {
            if (ex.getResponse().getStatusLine().getStatusCode() != 404) {
                throw new ElasticsearchIndexException("检查记忆索引失败", ex);
            }
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("检查记忆索引失败", ex);
        }

        Request create = new Request("PUT", "/" + memoryProperties.getMemoryIndexName());
        create.setJsonEntity(writeJson(indexMapping()));
        try {
            restClient.performRequest(create);
        } catch (ResponseException ex) {
            if (ex.getResponse().getStatusLine().getStatusCode() == 400) {
                return; // 并发启动时另一实例已创建
            }
            throw new ElasticsearchIndexException("创建记忆索引失败", ex);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("创建记忆索引失败", ex);
        }
    }

    private Map<String, Object> indexMapping() {
        Map<String, Object> properties = new LinkedHashMap<>();
        properties.put("memory_id", Map.of("type", "keyword"));
        properties.put("org_id", Map.of("type", "keyword"));
        properties.put("member_id", Map.of("type", "keyword"));
        properties.put("session_id", Map.of("type", "keyword"));
        properties.put("memory_type", Map.of("type", "keyword"));
        properties.put("content", Map.of("type", "text"));
        properties.put("content_vector", Map.of("type", "dense_vector", "dims", esProperties.getVectorDimensions(),
                "index", true, "similarity", "cosine"));
        properties.put("created_at", Map.of("type", "date"));
        return Map.of("mappings", Map.of("dynamic", "strict", "properties", properties));
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (com.fasterxml.jackson.core.JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造记忆索引请求失败", ex);
        }
    }
}
