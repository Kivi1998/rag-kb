package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.model.Chunk;
import com.diit.ragkb.ragcore.model.RetrievedChunk;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.http.HttpEntity;
import org.elasticsearch.client.Request;
import org.elasticsearch.client.Response;
import org.elasticsearch.client.ResponseException;
import org.elasticsearch.client.RestClient;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 共享 `rag_chunks_v1` 索引的原生 ES 适配器。
 *
 * <p>所有写入都包含组织、知识库和文档标识。删除 API 同时强制三个条件，防止误删相同
 * documentId 之外的数据。检索由 T201 专门实现，避免在索引层暴露无租户过滤的泛型 search。</p>
 */
public class ElasticsearchChunkIndex implements ChunkIndex, LexicalChunkIndex {

    private static final Pattern SYMBOL = Pattern.compile("\\b(?:[A-Za-z_$][\\w$]*\\.)*[A-Za-z_$][\\w$]*\\b");
    private static final Pattern CONFIG_KEY = Pattern.compile("(?m)^\\s*([A-Za-z][\\w.-]{1,})\\s*[:=]");
    private static final Pattern ERROR_CODE = Pattern.compile("\\b(?:[A-Z][A-Z0-9_]{2,}|ERR(?:OR)?[-_]?\\d+)\\b");

    private final RestClient restClient;
    private final RagElasticsearchProperties properties;
    private final ObjectMapper objectMapper;
    private final AtomicBoolean visibilityMappingEnsured = new AtomicBoolean();

    public ElasticsearchChunkIndex(RestClient restClient, RagElasticsearchProperties properties,
                                   ObjectMapper objectMapper) {
        this.restClient = Objects.requireNonNull(restClient, "restClient 不能为空");
        this.properties = Objects.requireNonNull(properties, "Elasticsearch 配置不能为空");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper 不能为空");
    }

    @Override
    public void upsert(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion) {
        stage(chunks, vectors, embeddingModelVersion);
        if (chunks == null || chunks.isEmpty()) return;
        chunks.stream()
                .map(chunk -> new DocumentBoundary(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId()))
                .distinct()
                .forEach(boundary -> activateDocument(boundary.organizationId(), boundary.knowledgeBaseId(),
                        boundary.documentId()));
    }

    @Override
    public void stage(List<Chunk> chunks, List<List<Float>> vectors, String embeddingModelVersion) {
        if (chunks == null || chunks.isEmpty()) {
            return;
        }
        if (vectors == null || chunks.size() != vectors.size()) {
            throw new IllegalArgumentException("chunks 与 vectors 必须一一对应");
        }
        ensureIndex();
        StringBuilder ndjson = new StringBuilder();
        for (int i = 0; i < chunks.size(); i++) {
            Chunk chunk = chunks.get(i);
            validateChunk(chunk, vectors.get(i));
            appendJsonLine(ndjson, Map.of("index", Map.of("_index", properties.getIndexName(), "_id", chunk.id())));
            appendJsonLine(ndjson, toIndexDocument(chunk, vectors.get(i), embeddingModelVersion, false));
        }
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_bulk");
        request.setJsonEntity(ndjson.toString());
        request.setOptions(request.getOptions().toBuilder()
                .addHeader("Content-Type", "application/x-ndjson").build());
        try {
            Response response = restClient.performRequest(request);
            JsonNode root = readEntity(response.getEntity());
            if (root.path("errors").asBoolean(false)) {
                throw new ElasticsearchIndexException("ES Bulk 写入出现分项失败: " + firstBulkError(root));
            }
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES Bulk 写入失败", ex);
        }
    }

    @Override
    public void activateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        updateVisibility(organizationId, knowledgeBaseId, documentId, true);
    }

    @Override
    public void deactivateDocument(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        updateVisibility(organizationId, knowledgeBaseId, documentId, false);
    }

    @Override
    public void deleteByDocumentId(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        requireIds(organizationId, knowledgeBaseId, documentId);
        ensureIndex();
        Map<String, Object> query = Map.of("query", Map.of("bool", Map.of("filter", List.of(
                Map.of("term", Map.of("org_id", organizationId.toString())),
                Map.of("term", Map.of("kb_id", knowledgeBaseId.toString())),
                Map.of("term", Map.of("document_id", documentId.toString()))))));
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_delete_by_query");
        request.addParameter("conflicts", "proceed");
        request.setJsonEntity(writeJson(query));
        try {
            restClient.performRequest(request);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("ES 文档 chunk 删除失败", ex);
        }
    }

    @Override
    public List<RetrievedChunk> search(SearchRequest request) {
        throw new UnsupportedOperationException("混合检索由 T201 的 HybridRetriever 实现，禁止调用无过滤通用 search");
    }

    /** 幂等创建索引与 mapping；重复调用不会覆盖既有生产 mapping。 */
    void ensureIndex() {
        try {
            Response response = restClient.performRequest(new Request("HEAD", "/" + properties.getIndexName()));
            int status = response.getStatusLine().getStatusCode();
            if (status >= 200 && status < 300) {
                ensureVisibilityMapping();
                return;
            }
            if (status != 404) {
                throw new ElasticsearchIndexException("检查 ES 索引失败，HTTP " + status);
            }
        } catch (ResponseException ex) {
            if (ex.getResponse().getStatusLine().getStatusCode() != 404) {
                throw new ElasticsearchIndexException("检查 ES 索引失败", ex);
            }
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("检查 ES 索引失败", ex);
        }

        Request create = new Request("PUT", "/" + properties.getIndexName());
        create.setJsonEntity(writeJson(indexMapping()));
        try {
            restClient.performRequest(create);
            visibilityMappingEnsured.set(true);
        } catch (ResponseException ex) {
            // 多实例并发启动时另一个实例可能已经创建；再次 HEAD 确认即可。
            if (ex.getResponse().getStatusLine().getStatusCode() == 400 && indexExists()) {
                return;
            }
            throw new ElasticsearchIndexException("创建 ES chunk 索引失败", ex);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("创建 ES chunk 索引失败", ex);
        }
    }

    private boolean indexExists() {
        try {
            Response response = restClient.performRequest(new Request("HEAD", "/" + properties.getIndexName()));
            int status = response.getStatusLine().getStatusCode();
            return status >= 200 && status < 300;
        } catch (IOException ignored) {
            return false;
        }
    }

    private Map<String, Object> indexMapping() {
        Map<String, Object> propertiesMap = new LinkedHashMap<>();
        keyword(propertiesMap, "chunk_id");
        keyword(propertiesMap, "org_id");
        keyword(propertiesMap, "kb_id");
        keyword(propertiesMap, "document_id");
        propertiesMap.put("ordinal", Map.of("type", "integer"));
        propertiesMap.put("content", Map.of("type", "text", "copy_to", "content_search"));
        propertiesMap.put("content_search", Map.of("type", "text"));
        propertiesMap.put("content_vector", Map.of("type", "dense_vector", "dims", properties.getVectorDimensions(),
                "index", true, "similarity", "cosine"));
        propertiesMap.put("retrieval_ready", Map.of("type", "boolean"));
        propertiesMap.put("heading_path", Map.of("type", "keyword"));
        keyword(propertiesMap, "source_path");
        propertiesMap.put("page_no", Map.of("type", "integer"));
        propertiesMap.put("line_start", Map.of("type", "integer"));
        propertiesMap.put("line_end", Map.of("type", "integer"));
        keyword(propertiesMap, "language");
        keyword(propertiesMap, "content_hash");
        keyword(propertiesMap, "model_version");
        keyword(propertiesMap, "parser_version");
        keyword(propertiesMap, "chunk_version");
        propertiesMap.put("symbol_names", Map.of("type", "keyword"));
        propertiesMap.put("config_keys", Map.of("type", "keyword"));
        propertiesMap.put("error_codes", Map.of("type", "keyword"));
        propertiesMap.put("metadata", Map.of("type", "object", "dynamic", true));
        return Map.of("mappings", Map.of("dynamic", "strict", "properties", propertiesMap));
    }

    private void keyword(Map<String, Object> propertiesMap, String field) {
        propertiesMap.put(field, Map.of("type", "keyword"));
    }

    private Map<String, Object> toIndexDocument(Chunk chunk, List<Float> vector, String modelVersion,
                                                boolean retrievalReady) {
        Map<String, Object> source = new LinkedHashMap<>();
        source.put("chunk_id", chunk.id());
        source.put("org_id", chunk.organizationId().toString());
        source.put("kb_id", chunk.knowledgeBaseId().toString());
        source.put("document_id", chunk.documentId().toString());
        source.put("ordinal", chunk.ordinal());
        source.put("content", chunk.content());
        source.put("content_search", chunk.content());
        source.put("content_vector", vector);
        source.put("retrieval_ready", retrievalReady);
        source.put("heading_path", chunk.headingPath());
        source.put("source_path", chunk.sourcePath());
        source.put("page_no", chunk.pageNo());
        source.put("line_start", chunk.lineStart());
        source.put("line_end", chunk.lineEnd());
        source.put("language", chunk.language());
        source.put("content_hash", chunk.contentHash());
        source.put("model_version", modelVersion == null ? "unknown" : modelVersion);
        source.put("parser_version", chunk.metadata().getOrDefault("parserVersion", "v1"));
        source.put("chunk_version", chunk.metadata().getOrDefault("chunkVersion", "v1"));
        source.put("symbol_names", extract(SYMBOL, chunk.content(), 128));
        source.put("config_keys", extract(CONFIG_KEY, chunk.content(), 64));
        source.put("error_codes", extract(ERROR_CODE, chunk.content(), 64));
        source.put("metadata", chunk.metadata());
        return source;
    }

    private void ensureVisibilityMapping() {
        if (visibilityMappingEnsured.get()) return;
        Request request = new Request("PUT", "/" + properties.getIndexName() + "/_mapping");
        request.setJsonEntity(writeJson(Map.of("properties",
                Map.of("retrieval_ready", Map.of("type", "boolean")))));
        try {
            restClient.performRequest(request);
            visibilityMappingEnsured.set(true);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException("更新 ES retrieval_ready mapping 失败", ex);
        }
    }

    private void updateVisibility(UUID organizationId, UUID knowledgeBaseId, UUID documentId, boolean ready) {
        requireIds(organizationId, knowledgeBaseId, documentId);
        ensureIndex();
        Map<String, Object> body = Map.of(
                "script", Map.of("source", "ctx._source.retrieval_ready = params.ready", "lang", "painless",
                        "params", Map.of("ready", ready)),
                "query", Map.of("bool", Map.of("filter", List.of(
                        Map.of("term", Map.of("org_id", organizationId.toString())),
                        Map.of("term", Map.of("kb_id", knowledgeBaseId.toString())),
                        Map.of("term", Map.of("document_id", documentId.toString()))))));
        Request request = new Request("POST", "/" + properties.getIndexName() + "/_update_by_query");
        request.addParameter("conflicts", "proceed");
        request.addParameter("refresh", "true");
        request.setJsonEntity(writeJson(body));
        try {
            restClient.performRequest(request);
        } catch (IOException ex) {
            throw new ElasticsearchIndexException(ready ? "激活 ES Chunk 失败" : "隐藏 ES Chunk 失败", ex);
        }
    }

    private List<String> extract(Pattern pattern, String content, int limit) {
        LinkedHashSet<String> values = new LinkedHashSet<>();
        Matcher matcher = pattern.matcher(content);
        while (matcher.find() && values.size() < limit) {
            String value = matcher.groupCount() > 0 && matcher.group(1) != null ? matcher.group(1) : matcher.group();
            values.add(value);
        }
        return List.copyOf(values);
    }

    private void validateChunk(Chunk chunk, List<Float> vector) {
        if (chunk == null || chunk.id() == null || chunk.id().isBlank() || chunk.content() == null || chunk.content().isBlank()) {
            throw new IllegalArgumentException("chunk id 与 content 不能为空");
        }
        requireIds(chunk.organizationId(), chunk.knowledgeBaseId(), chunk.documentId());
        if (vector == null || vector.size() != properties.getVectorDimensions()) {
            throw new IllegalArgumentException("Embedding 向量维度必须为 " + properties.getVectorDimensions());
        }
    }

    private void requireIds(UUID organizationId, UUID knowledgeBaseId, UUID documentId) {
        if (organizationId == null || knowledgeBaseId == null || documentId == null) {
            throw new IllegalArgumentException("orgId、kbId 与 documentId 均不能为空");
        }
    }

    private void appendJsonLine(StringBuilder output, Object value) {
        output.append(writeJson(value)).append('\n');
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            throw new ElasticsearchIndexException("构造 ES 请求 JSON 失败", ex);
        }
    }

    private JsonNode readEntity(HttpEntity entity) throws IOException {
        if (entity == null) {
            throw new ElasticsearchIndexException("ES 响应为空");
        }
        return objectMapper.readTree(entity.getContent());
    }

    private String firstBulkError(JsonNode root) {
        for (JsonNode item : root.path("items")) {
            JsonNode operation = item.path("index");
            if (operation.path("error").isMissingNode()) {
                continue;
            }
            return operation.path("error").path("reason").asText(operation.path("status").asText("unknown"));
        }
        return "unknown";
    }

    private record DocumentBoundary(UUID organizationId, UUID knowledgeBaseId, UUID documentId) { }
}
