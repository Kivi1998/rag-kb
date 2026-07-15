package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryRecord;
import com.diit.ragkb.ragcore.conversation.MemoryType;
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
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 统一记忆索引：短期会话检索按 session_id 过滤，长期画像检索按 member_id 过滤，都强制携带 org_id。 */
class ElasticsearchMemoryIndexTest {

    private HttpServer server;
    private RestClient restClient;
    private final AtomicReference<String> latestPath = new AtomicReference<>();
    private final AtomicReference<String> latestBody = new AtomicReference<>();
    private final UUID orgId = UUID.randomUUID();
    private final UUID memberId = UUID.randomUUID();
    private final UUID sessionId = UUID.randomUUID();

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
    void searchSessionHistoryFiltersBySessionAndOrg() {
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());
        latestPath.set(null);

        List<MemoryIndex.ScoredMemoryRecord> results =
                index.searchSessionHistory(orgId, sessionId, List.of(0.1f, 0.2f), 5);

        assertTrue(latestBody.get().contains("\"session_id\":\"" + sessionId + "\""));
        assertTrue(latestBody.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(latestBody.get().contains("\"memory_type\":\"SESSION_MESSAGE\""));
        assertEquals(1, results.size());
        assertEquals(MemoryType.SESSION_MESSAGE, results.get(0).record().type());
    }

    @Test
    void searchProfileItemsFiltersByMemberAndOrg() {
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());

        List<MemoryIndex.ScoredMemoryRecord> results =
                index.searchProfileItems(orgId, memberId, List.of(0.1f, 0.2f), 5);

        assertTrue(latestBody.get().contains("\"member_id\":\"" + memberId + "\""));
        assertTrue(latestBody.get().contains("\"memory_type\":\"PROFILE_ITEM\""));
        assertEquals(1, results.size());
    }

    @Test
    void upsertSendsVectorAndFields() {
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());
        MemoryRecord record = new MemoryRecord("mem-1", orgId, memberId, sessionId, MemoryType.SESSION_MESSAGE,
                "内容", Instant.parse("2026-07-15T00:00:00Z"));

        index.upsert(record, List.of(0.1f, 0.2f));

        assertTrue(latestPath.get().endsWith("/_doc/mem-1"));
        assertTrue(latestBody.get().contains("\"content_vector\":[0.1,0.2]"));
    }

    private RagElasticsearchProperties esProperties() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        properties.setVectorDimensions(2);
        return properties;
    }

    private RagMemoryProperties memoryProperties() {
        RagMemoryProperties properties = new RagMemoryProperties();
        properties.setMemoryIndexName("rag_memory_v1");
        return properties;
    }

    private void handle(HttpExchange exchange) throws IOException {
        latestPath.set(exchange.getRequestURI().getPath());
        latestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        byte[] bytes;
        if ("HEAD".equals(exchange.getRequestMethod())) {
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
            return;
        }
        if ("PUT".equals(exchange.getRequestMethod()) || "DELETE".equals(exchange.getRequestMethod())) {
            bytes = "{}".getBytes(StandardCharsets.UTF_8);
        } else {
            boolean sessionScoped = latestBody.get().contains("SESSION_MESSAGE");
            String memoryType = sessionScoped ? "SESSION_MESSAGE" : "PROFILE_ITEM";
            String sessionField = sessionScoped ? "\"session_id\":\"" + sessionId + "\"," : "";
            String response = "{\"hits\":{\"hits\":[{\"_score\":0.95,\"_source\":{"
                    + "\"memory_id\":\"mem-1\",\"org_id\":\"" + orgId + "\",\"member_id\":\"" + memberId + "\","
                    + sessionField + "\"memory_type\":\"" + memoryType + "\",\"content\":\"命中内容\","
                    + "\"created_at\":\"2026-07-15T00:00:00Z\"}}]}}";
            bytes = response.getBytes(StandardCharsets.UTF_8);
        }
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
