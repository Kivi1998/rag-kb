package com.diit.ragkb.ragcore.nli;

import com.diit.ragkb.config.RagNliProperties;
import com.diit.ragkb.ragcore.model.ModelClientException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class HttpNliClientTest {

    private HttpServer server;
    private volatile int statusCode = 200;
    private volatile String responseBody = "{\"label\":\"entailment\",\"entailment_prob\":0.95,"
            + "\"neutral_prob\":0.03,\"contradiction_prob\":0.02}";

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/nli", this::handle);
        server.start();
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    private void handle(HttpExchange exchange) throws IOException {
        byte[] bytes = responseBody.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(statusCode, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    @Test
    void parsesSuccessfulVerdict() {
        HttpNliClient client = new HttpNliClient(properties(), new ObjectMapper());

        NliVerdict verdict = client.check("资料原文", "生成的句子");

        assertEquals("entailment", verdict.label());
        assertEquals(0.95, verdict.entailmentProb());
    }

    @Test
    void nonSuccessStatusThrowsModelClientException() {
        statusCode = 500;
        HttpNliClient client = new HttpNliClient(properties(), new ObjectMapper());

        assertThrows(ModelClientException.class, () -> client.check("资料原文", "生成的句子"));
    }

    @Test
    void malformedResponseThrowsModelClientException() {
        responseBody = "{\"label\":\"entailment\"}";
        HttpNliClient client = new HttpNliClient(properties(), new ObjectMapper());

        assertThrows(ModelClientException.class, () -> client.check("资料原文", "生成的句子"));
    }

    private RagNliProperties properties() {
        RagNliProperties properties = new RagNliProperties();
        properties.setEnabled(true);
        properties.setEndpoint("http://127.0.0.1:" + server.getAddress().getPort() + "/nli");
        properties.setTimeoutMs(5000);
        return properties;
    }
}
