package com.diit.ragkb.ragcore.index;

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
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ElasticsearchVisibilityBackfillTest {

    private HttpServer server;
    private RestClient client;
    private final AtomicBoolean updated = new AtomicBoolean();
    private final AtomicInteger updateAttempts = new AtomicInteger();
    private final AtomicReference<String> updateQuery = new AtomicReference<>();

    @BeforeEach
    void setUp() throws IOException {
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
    void dryRunOnlyCountsAndDoesNotModifyIndex() {
        var result = backfill().run(true, 100, 3);

        assertTrue(result.dryRun());
        assertEquals(3, result.missingBefore());
        assertEquals(0, updateAttempts.get());
    }

    @Test
    void retriesTransientFailureAndVerifiesRemainingCount() {
        var result = backfill().run(false, 123, 3);

        assertFalse(result.dryRun());
        assertEquals(3, result.missingBefore());
        assertEquals(3, result.updated());
        assertEquals(0, result.missingAfter());
        assertEquals(2, updateAttempts.get());
        assertTrue(updateQuery.get().contains("\"retrieval_ready\""));
    }

    private ElasticsearchVisibilityBackfill backfill() {
        RagElasticsearchProperties properties = new RagElasticsearchProperties();
        properties.setIndexName("rag_chunks_v1");
        return new ElasticsearchVisibilityBackfill(client, properties, new ObjectMapper());
    }

    private void handle(HttpExchange exchange) throws IOException {
        String path = exchange.getRequestURI().getPath();
        if (path.endsWith("/_count")) {
            write(exchange, 200, "{\"count\":" + (updated.get() ? 0 : 3) + "}");
            return;
        }
        if (path.endsWith("/_mapping")) {
            write(exchange, 200, "{\"acknowledged\":true}");
            return;
        }
        if (path.endsWith("/_update_by_query")) {
            updateQuery.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            if (updateAttempts.incrementAndGet() == 1) {
                write(exchange, 503, "{\"error\":\"injected\"}");
                return;
            }
            updated.set(true);
            write(exchange, 200, "{\"updated\":3,\"failures\":[]}");
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
