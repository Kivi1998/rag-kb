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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ElasticsearchSplitCandidateSourceTest {

    private HttpServer server;
    private RestClient client;
    private final AtomicReference<String> body = new AtomicReference<>();
    private UUID orgId;
    private UUID kbId;

    @BeforeEach
    void setUp() throws IOException {
        orgId = UUID.randomUUID();
        kbId = UUID.randomUUID();
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", this::handle);
        server.start();
        client = RestClient.builder(new HttpHost("127.0.0.1", server.getAddress().getPort(), "http")).build();
    }

    @AfterEach
    void tearDown() throws IOException {
        client.close();
        server.stop(0);
    }

    @Test
    void lexicalSourcePreservesTechnicalWeightsAndBoundaries() {
        var source = new ElasticsearchLexicalCandidateSource(client, properties(), new ObjectMapper());
        var result = source.search(new SearchRequest(orgId, kbId, "SearchService", 30));

        assertEquals(1, result.size());
        assertEquals(1, result.get(0).bm25Rank());
        assertTrue(body.get().contains("\"symbol_names\""));
        assertTrue(body.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(body.get().contains("\"kb_id\":\"" + kbId + "\""));
        assertTrue(body.get().contains("\"retrieval_ready\":true"));
    }

    @Test
    void vectorSourceReturnsOnlyMinimalHitAndAppliesDocumentBoundary() {
        UUID documentId = UUID.randomUUID();
        var source = new ElasticsearchVectorCandidateSource(client, properties(), new ObjectMapper());
        var result = source.search(new VectorSearchRequest(orgId, kbId, List.of(0.1f, 0.2f), 30,
                List.of(documentId)));

        assertEquals(List.of(new VectorHit("chunk-1", 1, 1.2)), result);
        assertTrue(body.get().contains("\"_source\":[\"chunk_id\"]"));
        assertTrue(body.get().contains("\"document_id\":[\"" + documentId + "\"]"));
        assertTrue(body.get().contains("\"num_candidates\":100"));
        assertTrue(body.get().contains("\"retrieval_ready\":true"));
    }

    @Test
    void vectorHitRejectsInvalidValues() {
        assertThrows(IllegalArgumentException.class, () -> new VectorHit("", 1, 0.5));
        assertThrows(IllegalArgumentException.class, () -> new VectorHit("chunk", 0, 0.5));
        assertThrows(IllegalArgumentException.class, () -> new VectorHit("chunk", 1, Double.NaN));
    }

    private RagElasticsearchProperties properties() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        properties.setVectorDimensions(2);
        return properties;
    }

    private void handle(HttpExchange exchange) throws IOException {
        String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        body.set(requestBody);
        String source = requestBody.contains("\"_source\":[\"chunk_id\"]")
                ? "\"chunk_id\":\"chunk-1\""
                : fullSource("chunk-1", orgId, kbId);
        respond(exchange, "{\"hits\":{\"hits\":[{\"_score\":1.2,\"_source\":{" + source + "}}]}}");
    }

    private String fullSource(String id, UUID org, UUID kb) {
        return "\"chunk_id\":\"" + id + "\",\"org_id\":\"" + org + "\",\"kb_id\":\"" + kb + "\","
                + "\"document_id\":\"" + UUID.randomUUID() + "\",\"ordinal\":0,"
                + "\"content\":\"SearchService\",\"heading_path\":[\"Search\"],"
                + "\"source_path\":\"test.md\",\"language\":\"java\",\"content_hash\":\"h\"";
    }

    private void respond(HttpExchange exchange, String response) throws IOException {
        byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
