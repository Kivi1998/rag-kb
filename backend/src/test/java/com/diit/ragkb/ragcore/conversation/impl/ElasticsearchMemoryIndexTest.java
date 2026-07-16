package com.diit.ragkb.ragcore.conversation.impl;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.config.RagMemoryProperties;
import com.diit.ragkb.ragcore.conversation.MemoryIndex;
import com.diit.ragkb.ragcore.conversation.MemoryRecord;
import com.diit.ragkb.ragcore.conversation.MemoryType;
import com.fasterxml.jackson.databind.JsonNode;
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
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 统一记忆索引：短期会话检索按 session_id 过滤，长期画像检索按 member_id 过滤，都强制携带 org_id。
 *
 * <p>假 ES 服务端不只回显固定文档，而是维护一个含多租户数据的小型内存"索引"，并根据请求里
 * {@code knn.filter} 的 term 条件真正做过滤匹配——这样跨租户测试才能真实验证"用 org A 的凭据
 * 查询查不到 org B 的数据"，而不仅仅是断言请求体里出现了过滤字段。</p>
 */
class ElasticsearchMemoryIndexTest {

    private HttpServer server;
    private RestClient restClient;
    private final AtomicReference<String> latestPath = new AtomicReference<>();
    private final AtomicReference<String> latestBody = new AtomicReference<>();
    private final List<FakeDocument> fakeIndex = new ArrayList<>();
    private final ObjectMapper objectMapper = new ObjectMapper();

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
        seedDocument("mem-1", orgId, memberId, sessionId, MemoryType.SESSION_MESSAGE, "命中内容");
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
        seedDocument("mem-1", orgId, memberId, null, MemoryType.PROFILE_ITEM, "命中内容");

        List<MemoryIndex.ScoredMemoryRecord> results =
                index.searchProfileItems(orgId, memberId, List.of(0.1f, 0.2f), 5);

        assertTrue(latestBody.get().contains("\"member_id\":\"" + memberId + "\""));
        assertTrue(latestBody.get().contains("\"memory_type\":\"PROFILE_ITEM\""));
        assertEquals(1, results.size());
    }

    @Test
    void searchSessionHistoryDoesNotLeakOtherOrganizationsSession() {
        // 跨租户隔离回归测试：两个不同组织各有一条会话历史，用 org A 的凭据查询必须查不到 org B 的数据。
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());
        UUID orgB = UUID.randomUUID();
        UUID memberB = UUID.randomUUID();
        UUID sessionB = UUID.randomUUID();
        seedDocument("mem-org-a", orgId, memberId, sessionId, MemoryType.SESSION_MESSAGE, "org A 自己的会话内容");
        seedDocument("mem-org-b", orgB, memberB, sessionB, MemoryType.SESSION_MESSAGE, "org B 自己的会话内容");

        List<MemoryIndex.ScoredMemoryRecord> resultsForOrgA =
                index.searchSessionHistory(orgId, sessionId, List.of(0.1f, 0.2f), 5);
        List<MemoryIndex.ScoredMemoryRecord> resultsForOrgB =
                index.searchSessionHistory(orgB, sessionB, List.of(0.1f, 0.2f), 5);

        assertEquals(1, resultsForOrgA.size());
        assertEquals("org A 自己的会话内容", resultsForOrgA.get(0).record().content());
        assertEquals(1, resultsForOrgB.size());
        assertEquals("org B 自己的会话内容", resultsForOrgB.get(0).record().content());
    }

    @Test
    void searchProfileItemsDoesNotLeakOtherMembersProfileWithinSameOrganization() {
        // 跨租户隔离回归测试：同一组织内两个不同成员各有画像条目，成员 A 的查询必须查不到成员 B 的画像。
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());
        UUID memberB = UUID.randomUUID();
        seedDocument("mem-member-a", orgId, memberId, null, MemoryType.PROFILE_ITEM, "成员A的偏好");
        seedDocument("mem-member-b", orgId, memberB, null, MemoryType.PROFILE_ITEM, "成员B的偏好");

        List<MemoryIndex.ScoredMemoryRecord> resultsForMemberA =
                index.searchProfileItems(orgId, memberId, List.of(0.1f, 0.2f), 5);
        List<MemoryIndex.ScoredMemoryRecord> resultsForMemberB =
                index.searchProfileItems(orgId, memberB, List.of(0.1f, 0.2f), 5);

        assertEquals(1, resultsForMemberA.size());
        assertEquals("成员A的偏好", resultsForMemberA.get(0).record().content());
        assertEquals(1, resultsForMemberB.size());
        assertEquals("成员B的偏好", resultsForMemberB.get(0).record().content());
    }

    @Test
    void deleteBySessionSendsDeleteByQueryWithOrgAndSessionFilter() {
        var index = new ElasticsearchMemoryIndex(restClient, esProperties(), memoryProperties(), new ObjectMapper());
        latestPath.set(null);

        index.deleteBySession(orgId, sessionId);

        assertTrue(latestPath.get().endsWith("/_delete_by_query"));
        assertTrue(latestBody.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(latestBody.get().contains("\"session_id\":\"" + sessionId + "\""));
        assertTrue(latestBody.get().contains("\"memory_type\":\"SESSION_MESSAGE\""));
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

    private void seedDocument(String memoryId, UUID org, UUID member, UUID session, MemoryType type,
                             String content) {
        fakeIndex.add(new FakeDocument(memoryId, org, member, session, type, content));
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
            bytes = searchResponse(latestBody.get()).getBytes(StandardCharsets.UTF_8);
        }
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    /** 模拟真实 ES 的 {@code knn.filter} term 过滤行为：只返回同时满足所有 term 条件的种子文档。 */
    private String searchResponse(String requestBody) throws IOException {
        JsonNode root = objectMapper.readTree(requestBody);
        JsonNode filters = root.path("knn").path("filter");
        StringBuilder hits = new StringBuilder();
        int matched = 0;
        for (FakeDocument document : fakeIndex) {
            if (matchesAllFilters(document, filters)) {
                if (matched > 0) hits.append(",");
                hits.append(document.toHitJson());
                matched++;
            }
        }
        return "{\"hits\":{\"hits\":[" + hits + "]}}";
    }

    private boolean matchesAllFilters(FakeDocument document, JsonNode filters) {
        for (JsonNode filter : filters) {
            JsonNode term = filter.path("term");
            var fieldNames = term.fieldNames();
            while (fieldNames.hasNext()) {
                String field = fieldNames.next();
                String expected = term.path(field).asText();
                if (!expected.equals(document.fieldValue(field))) {
                    return false;
                }
            }
        }
        return true;
    }

    private record FakeDocument(String memoryId, UUID orgId, UUID memberId, UUID sessionId, MemoryType type,
                                String content) {

        String fieldValue(String field) {
            return switch (field) {
                case "org_id" -> orgId.toString();
                case "member_id" -> memberId.toString();
                case "session_id" -> sessionId == null ? null : sessionId.toString();
                case "memory_type" -> type.name();
                default -> null;
            };
        }

        String toHitJson() {
            String sessionField = sessionId == null ? "" : "\"session_id\":\"" + sessionId + "\",";
            return "{\"_score\":0.95,\"_source\":{"
                    + "\"memory_id\":\"" + memoryId + "\",\"org_id\":\"" + orgId + "\",\"member_id\":\"" + memberId
                    + "\"," + sessionField + "\"memory_type\":\"" + type.name() + "\",\"content\":\"" + content
                    + "\",\"created_at\":\"2026-07-15T00:00:00Z\"}}";
        }
    }
}
