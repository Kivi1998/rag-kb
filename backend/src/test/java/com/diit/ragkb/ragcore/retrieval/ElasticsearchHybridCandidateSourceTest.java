package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
import com.diit.ragkb.ragcore.index.SearchRequest;
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
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 双路 ES DSL 必须携带 org/kb 过滤，且技术标识字段优先。 */
class ElasticsearchHybridCandidateSourceTest {

    private HttpServer server;
    private RestClient restClient;
    private final AtomicReference<String> latestBody = new AtomicReference<>();
    private UUID orgId;
    private UUID kbId;

    @BeforeEach
    void setUp() throws IOException {
        orgId = UUID.randomUUID();
        kbId = UUID.randomUUID();
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
    void bm25PrioritizesTechnicalIdentifiersAndInjectsTenantBoundary() {
        var source = new ElasticsearchHybridCandidateSource(restClient, properties(), new ObjectMapper());
        var results = source.searchBm25(new SearchRequest(orgId, kbId, "SearchService", 30));

        assertEquals(1, results.size());
        assertEquals(1, results.get(0).bm25Rank());
        assertEquals("SearchService", results.get(0).chunk().content());
        assertTrue(latestBody.get().contains("\"symbol_names\""));
        assertTrue(latestBody.get().contains("\"config_keys\""));
        assertTrue(latestBody.get().contains("\"error_codes\""));
        assertTrue(latestBody.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(latestBody.get().contains("\"kb_id\":\"" + kbId + "\""));
    }

    @Test
    void knnCarriesVectorAndSameTenantBoundary() {
        var source = new ElasticsearchHybridCandidateSource(restClient, properties(), new ObjectMapper());
        var results = source.searchKnn(new VectorSearchRequest(orgId, kbId, List.of(0.1f, 0.2f), 30));

        assertEquals(1, results.size());
        assertEquals(1, results.get(0).vectorRank());
        assertTrue(latestBody.get().contains("\"query_vector\":[0.1,0.2]"));
        assertTrue(latestBody.get().contains("\"num_candidates\":100"));
        assertTrue(latestBody.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(latestBody.get().contains("\"kb_id\":\"" + kbId + "\""));
    }

    private RagElasticsearchProperties properties() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        properties.setVectorDimensions(2);
        return properties;
    }

    private void handle(HttpExchange exchange) throws IOException {
        latestBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        UUID docId = UUID.randomUUID();
        String response = "{\"hits\":{\"hits\":[{\"_score\":1.2,\"_source\":{"
                + "\"chunk_id\":\"chunk-1\",\"org_id\":\"" + orgId + "\",\"kb_id\":\"" + kbId + "\","
                + "\"document_id\":\"" + docId + "\",\"ordinal\":0,\"content\":\"SearchService\","
                + "\"heading_path\":[\"Search\"],\"source_path\":\"test.md\",\"language\":\"java\",\"content_hash\":\"h\"}}]}}";
        byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
