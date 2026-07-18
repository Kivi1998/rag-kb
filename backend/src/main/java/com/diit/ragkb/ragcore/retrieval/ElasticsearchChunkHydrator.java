package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.index.ElasticsearchIndexException;
import com.diit.ragkb.ragcore.model.Chunk;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/** 使用受 org/kb 过滤保护的 ES 批量查询补齐向量命中，并恢复输入 ID 顺序。 */
public class ElasticsearchChunkHydrator implements ChunkHydrator {

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;

    public ElasticsearchChunkHydrator(RestClient restClient, RagElasticsearchProperties properties,
                                     ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public List<Chunk> findByChunkIds(UUID orgId, UUID kbId, List<String> chunkIds) {
        if (orgId == null || kbId == null) throw new IllegalArgumentException("Chunk 补齐必须携带组织与知识库边界");
        if (chunkIds == null || chunkIds.isEmpty()) return List.of();
        List<String> ids = chunkIds.stream().filter(Objects::nonNull).filter(id -> !id.isBlank()).distinct().toList();
        if (ids.isEmpty()) return List.of();
        Map<String, Object> body = Map.of(
                "size", ids.size(),
                "_source", ElasticsearchChunkDocumentMapper.SOURCE_FIELDS,
                "query", Map.of("bool", Map.of("filter", List.of(
                        Map.of("term", Map.of("org_id", orgId.toString())),
                        Map.of("term", Map.of("kb_id", kbId.toString())),
                        Map.of("term", Map.of("retrieval_ready", true)),
                        Map.of("terms", Map.of("chunk_id", ids))))));
        Request esRequest = new Request("POST", "/" + properties.getIndexName() + "/_search");
        esRequest.setJsonEntity(writeJson(body));
        try {
            Response response = restClient.performRequest(esRequest);
            JsonNode hits = objectMapper.readTree(response.getEntity().getContent()).path("hits").path("hits");
            if (!hits.isArray()) throw new ElasticsearchIndexException("ES Chunk 补齐响应缺少 hits.hits");
            Map<String, Chunk> safe = new LinkedHashMap<>();
            for (JsonNode hit : hits) {
                Chunk chunk = ElasticsearchChunkDocumentMapper.toChunk(hit.path("_source"));
                if (orgId.equals(chunk.organizationId()) && kbId.equals(chunk.knowledgeBaseId()) && ids.contains(chunk.id())) {
                    safe.put(chunk.id(), chunk);
                }
            }
            List<Chunk> result = new ArrayList<>();
            for (String id : ids) {
                Chunk chunk = safe.get(id);
                if (chunk != null) result.add(chunk);
            }
            return result;
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES Chunk 补齐失败", ex);
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造 ES Chunk 补齐请求失败", ex);
        }
    }
}
