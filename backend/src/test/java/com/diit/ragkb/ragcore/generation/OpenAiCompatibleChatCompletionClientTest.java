package com.diit.ragkb.ragcore.generation;

import com.diit.ragkb.config.RagModelProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/** 未配置 API Key 的本地网关场景不应发送 {@code Authorization: Bearer null}，需与其余两个 OpenAI 兼容客户端行为一致。 */
class OpenAiCompatibleChatCompletionClientTest {

    private HttpServer server;
    private final AtomicReference<String> latestAuthorizationHeader = new AtomicReference<>();

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/", this::handle);
        server.start();
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    private void handle(HttpExchange exchange) throws IOException {
        latestAuthorizationHeader.set(exchange.getRequestHeaders().getFirst("Authorization"));
        String body = "{\"choices\":[{\"message\":{\"content\":\"ok\"}}]}";
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(200, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    @Test
    void omitsAuthorizationHeaderWhenApiKeyBlank() {
        OpenAiCompatibleChatCompletionClient client =
                new OpenAiCompatibleChatCompletionClient(properties(null), new ObjectMapper());

        client.complete("系统提示", "用户问题");

        assertNull(latestAuthorizationHeader.get(), "未配置 apiKey 时不应发送 Authorization 请求头");
    }

    @Test
    void sendsBearerAuthorizationHeaderWhenApiKeyConfigured() {
        OpenAiCompatibleChatCompletionClient client =
                new OpenAiCompatibleChatCompletionClient(properties("sk-test"), new ObjectMapper());

        client.complete("系统提示", "用户问题");

        assertEquals("Bearer sk-test", latestAuthorizationHeader.get());
    }

    private RagModelProperties.Generation properties(String apiKey) {
        RagModelProperties.Generation properties = new RagModelProperties.Generation();
        properties.setEndpoint("http://127.0.0.1:" + server.getAddress().getPort() + "/v1/chat/completions");
        properties.setModel("test-chat");
        properties.setApiKey(apiKey);
        properties.setTimeoutMs(5000);
        return properties;
    }
}
