package com.diit.ragkb.ragcore.model;

import com.diit.ragkb.config.RagModelProperties;
import com.diit.ragkb.ragcore.embedding.OpenAiCompatibleEmbeddingClient;
import com.diit.ragkb.ragcore.rerank.OpenAiCompatibleRerankerClient;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** OpenAI 兼容 Embedding/Rerank 客户端的协议、分批与超时回归。 */
class OpenAiCompatibleModelClientTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private HttpServer server;

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.start();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }

    @Test
    void embedding_batchesAndRestoresResponseOrder() {
        AtomicInteger requestCount = new AtomicInteger();
        server.createContext("/embeddings", exchange -> {
            requestCount.incrementAndGet();
            JsonNode input = objectMapper.readTree(exchange.getRequestBody()).path("input");
            List<String> data = new ArrayList<>();
            for (int index = input.size() - 1; index >= 0; index--) {
                data.add("{\"index\":" + index + ",\"embedding\":[" + (index + 1) + ",0.5]}");
            }
            writeJson(exchange, 200, "{\"model\":\"embedding-v1\",\"data\":[" + String.join(",", data) + "]}");
        });

        RagModelProperties.Embedding properties = embeddingProperties("/embeddings");
        properties.setBatchSize(2);
        var result = new OpenAiCompatibleEmbeddingClient(properties, objectMapper)
                .embed(List.of("one", "two", "three"));

        assertEquals(2, requestCount.get());
        assertEquals("embedding-v1", result.modelVersion());
        assertEquals(List.of(1.0f, 0.5f), result.vectors().get(0));
        assertEquals(List.of(2.0f, 0.5f), result.vectors().get(1));
        assertEquals(List.of(1.0f, 0.5f), result.vectors().get(2));
    }

    @Test
    void embedding_timeoutBecomesRecognizableModelException() {
        server.createContext("/slow", exchange -> {
            try {
                Thread.sleep(200);
                writeJson(exchange, 200, "{\"data\":[]}");
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
            }
        });
        RagModelProperties.Embedding properties = embeddingProperties("/slow");
        properties.setTimeoutMs(30);

        assertThrows(ModelClientException.class,
                () -> new OpenAiCompatibleEmbeddingClient(properties, objectMapper).embed(List.of("timeout")));
    }

    @Test
    void rerank_usesServiceScoreAndHonorsTopK() {
        server.createContext("/rerank", exchange ->
                writeJson(exchange, 200, "{\"results\":[{\"index\":1,\"relevance_score\":0.9},{\"index\":0,\"relevance_score\":0.3}]}"));
        RagModelProperties.Rerank properties = new RagModelProperties.Rerank();
        properties.setEndpoint(endpoint("/rerank"));
        properties.setModel("rerank-v1");

        Chunk first = chunk("first");
        Chunk second = chunk("second");
        var output = new OpenAiCompatibleRerankerClient(properties, objectMapper).rerank("q", List.of(
                new RetrievedChunk(first, 1, null, 0.1, null, null),
                new RetrievedChunk(second, 2, null, 0.2, null, null)), 1);

        assertEquals(1, output.size());
        assertEquals("second", output.get(0).chunk().content());
        assertEquals(0.9, output.get(0).rerankScore());
    }

    private RagModelProperties.Embedding embeddingProperties(String path) {
        RagModelProperties.Embedding properties = new RagModelProperties.Embedding();
        properties.setEndpoint(endpoint(path));
        properties.setModel("embedding-test");
        return properties;
    }

    private String endpoint(String path) {
        return "http://127.0.0.1:" + server.getAddress().getPort() + path;
    }

    private Chunk chunk(String content) {
        return new Chunk(content, java.util.UUID.randomUUID(), java.util.UUID.randomUUID(), java.util.UUID.randomUUID(),
                0, content, List.of(), "test", null, 1, 1, "text", content, java.util.Map.of());
    }

    private void writeJson(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
