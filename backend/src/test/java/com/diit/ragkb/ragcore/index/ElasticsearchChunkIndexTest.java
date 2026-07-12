package com.diit.ragkb.ragcore.index;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.model.Chunk;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.apache.http.HttpHost;
import org.elasticsearch.client.RestClient;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertTrue;

/** ES ChunkIndex 的 mapping、Bulk 元数据与三重租户删除过滤回归。 */
class ElasticsearchChunkIndexTest {

    private HttpServer server;
    private RestClient restClient;
    private final AtomicBoolean indexCreated = new AtomicBoolean();
    private final AtomicReference<String> mapping = new AtomicReference<>();
    private final AtomicReference<String> bulk = new AtomicReference<>();
    private final AtomicReference<String> deleteQuery = new AtomicReference<>();

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", this::handle);
        server.start();
        restClient = RestClient.builder(new HttpHost("127.0.0.1", server.getAddress().getPort(), "http")).build();
    }

    @AfterEach
    void tearDown() throws IOException {
        restClient.close();
        server.stop(0);
    }

    @Test
    void upsertCreatesVersionedMappingAndWritesTenantBoundBulkDocument() {
        ElasticsearchChunkIndex index = new ElasticsearchChunkIndex(restClient, properties(), new ObjectMapper());
        Chunk chunk = chunk();
        index.upsert(List.of(chunk), List.of(List.of(0.1f, 0.2f)), "embedding-v1");

        assertTrue(mapping.get().contains("\"content_vector\""));
        assertTrue(mapping.get().contains("\"dims\":2"));
        assertTrue(bulk.get().contains("\"org_id\":\"" + chunk.organizationId() + "\""));
        assertTrue(bulk.get().contains("\"kb_id\":\"" + chunk.knowledgeBaseId() + "\""));
        assertTrue(bulk.get().contains("\"document_id\":\"" + chunk.documentId() + "\""));
        assertTrue(bulk.get().contains("\"model_version\":\"embedding-v1\""));
    }

    @Test
    void deleteAlwaysCarriesOrgKbAndDocumentFilters() {
        ElasticsearchChunkIndex index = new ElasticsearchChunkIndex(restClient, properties(), new ObjectMapper());
        UUID orgId = UUID.randomUUID();
        UUID kbId = UUID.randomUUID();
        UUID documentId = UUID.randomUUID();
        index.deleteByDocumentId(orgId, kbId, documentId);

        assertTrue(deleteQuery.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(deleteQuery.get().contains("\"kb_id\":\"" + kbId + "\""));
        assertTrue(deleteQuery.get().contains("\"document_id\":\"" + documentId + "\""));
    }

    private RagElasticsearchProperties properties() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        properties.setVectorDimensions(2);
        return properties;
    }

    private Chunk chunk() {
        return new Chunk("doc:0:hash", UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), 0,
                "class SearchService {}", List.of("Search"), "org/test/doc.md", 1, 1, 1,
                "java", "hash", Map.of("parserVersion", "parser-v1", "chunkVersion", "chunk-v1"));
    }

    private void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        String method = exchange.getRequestMethod();
        if ("HEAD".equals(method) && "/rag_chunks_v1".equals(path)) {
            exchange.sendResponseHeaders(indexCreated.get() ? 200 : 404, -1);
            exchange.close();
            return;
        }
        if ("PUT".equals(method) && "/rag_chunks_v1".equals(path)) {
            mapping.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            indexCreated.set(true);
            write(exchange, 200, "{\"acknowledged\":true}");
            return;
        }
        if ("POST".equals(method) && "/rag_chunks_v1/_bulk".equals(path)) {
            bulk.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            write(exchange, 200, "{\"errors\":false,\"items\":[]}");
            return;
        }
        if ("POST".equals(method) && "/rag_chunks_v1/_delete_by_query".equals(path)) {
            deleteQuery.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            write(exchange, 200, "{\"deleted\":1}");
            return;
        }
        write(exchange, 404, "{}");
    }

    private void write(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
