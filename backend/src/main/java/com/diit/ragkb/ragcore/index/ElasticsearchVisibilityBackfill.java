package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** 为迁移前存量 Chunk 回填 retrieval_ready；显式调用，不在普通启动路径自动执行。 */
public class ElasticsearchVisibilityBackfill {

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;

    public ElasticsearchVisibilityBackfill(RestClient restClient, RagElasticsearchProperties properties,
                                           ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    public BackfillResult run(boolean dryRun, int batchSize, int maxAttempts) {
        if (batchSize <= 0 || maxAttempts <= 0) {
            throw new IllegalArgumentException("回填 batchSize 与 maxAttempts 必须为正数");
        }
        long before = countMissing();
        if (dryRun || before == 0) return new BackfillResult(dryRun, before, 0, before);

        ensureMapping();
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_update_by_query");
        request.addParameter("conflicts", "proceed");
        request.addParameter("refresh", "true");
        request.addParameter("scroll_size", Integer.toString(batchSize));
        request.setJsonEntity(writeJson(Map.of(
                "script", Map.of("source", "ctx._source.retrieval_ready = true", "lang", "painless"),
                "query", missingQuery())));
        JsonNode response = performWithRetry(request, maxAttempts);
        if (!response.path("failures").isArray() || !response.path("failures").isEmpty()) {
            throw new ElasticsearchIndexException("ES retrieval_ready 回填存在分项失败");
        }
        long updated = response.path("updated").asLong(0);
        long remaining = countMissing();
        return new BackfillResult(false, before, updated, remaining);
    }

    private long countMissing() {
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_count");
        request.setJsonEntity(writeJson(Map.of("query", missingQuery())));
        try {
            Response response = restClient.performRequest(request);
            return read(response).path("count").asLong();
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("统计缺失 retrieval_ready 的 Chunk 失败", ex);
        }
    }

    private Map<String, Object> missingQuery() {
        return Map.of("bool", Map.of("must_not", List.of(
                Map.of("exists", Map.of("field", "retrieval_ready")))));
    }

    private void ensureMapping() {
        Request request = new Request("PUT", "/" + properties.getIndexName() + "/_mapping");
        request.setJsonEntity(writeJson(Map.of("properties",
                Map.of("retrieval_ready", Map.of("type", "boolean")))));
        try {
            restClient.performRequest(request);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("创建 retrieval_ready mapping 失败", ex);
        }
    }

    private JsonNode performWithRetry(Request request, int maxAttempts) {
        IOException last = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return read(restClient.performRequest(request));
            } catch (IOException ex) {
                last = ex;
            }
        }
        throw new ElasticsearchIndexException("ES retrieval_ready 回填重试耗尽", last);
    }

    private JsonNode read(Response response) throws IOException {
        if (response.getEntity() == null) throw new ElasticsearchIndexException("ES 回填响应为空");
        return objectMapper.readTree(response.getEntity().getContent());
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造 ES 回填请求失败", ex);
        }
    }

    public record BackfillResult(boolean dryRun, long missingBefore, long updated, long missingAfter) { }
}
