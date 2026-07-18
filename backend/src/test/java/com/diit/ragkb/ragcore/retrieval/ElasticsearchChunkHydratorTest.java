package com.diit.ragkb.ragcore.retrieval;

import com.diit.ragkb.config.RagElasticsearchProperties;
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

class ElasticsearchChunkHydratorTest {

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
    void restoresRequestedOrderAndDropsMissingAndForeignTenantHits() {
        var hydrator = new ElasticsearchChunkHydrator(client, properties(), new ObjectMapper());
        var chunks = hydrator.findByChunkIds(orgId, kbId, List.of("chunk-a", "missing", "chunk-b", "chunk-a"));

        assertEquals(List.of("chunk-a", "chunk-b"), chunks.stream().map(chunk -> chunk.id()).toList());
        assertTrue(body.get().contains("\"org_id\":\"" + orgId + "\""));
        assertTrue(body.get().contains("\"kb_id\":\"" + kbId + "\""));
        assertTrue(body.get().contains("\"chunk_id\":[\"chunk-a\",\"missing\",\"chunk-b\"]"));
        assertTrue(body.get().contains("\"retrieval_ready\":true"));
    }

    @Test
    void rejectsMissingBoundaryBeforeCallingElasticsearch() {
        var hydrator = new ElasticsearchChunkHydrator(client, properties(), new ObjectMapper());
        assertThrows(IllegalArgumentException.class,
                () -> hydrator.findByChunkIds(null, kbId, List.of("chunk-a")));
        assertEquals(null, body.get());
    }

    private RagElasticsearchProperties properties() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        return properties;
    }

    private void handle(HttpExchange exchange) throws IOException {
        body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        UUID foreignOrg = UUID.randomUUID();
        String response = "{\"hits\":{\"hits\":["
                + hit("chunk-b", orgId, kbId) + ","
                + hit("foreign", foreignOrg, kbId) + ","
                + hit("chunk-a", orgId, kbId) + "]}}";
        byte[] bytes = response.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private String hit(String id, UUID org, UUID kb) {
        return "{\"_source\":{\"chunk_id\":\"" + id + "\",\"org_id\":\"" + org
                + "\",\"kb_id\":\"" + kb + "\",\"document_id\":\"" + UUID.randomUUID()
                + "\",\"ordinal\":0,\"content\":\"" + id + " content\",\"heading_path\":[],"
                + "\"source_path\":\"test.md\",\"content_hash\":\"h\"}}";
    }
}
