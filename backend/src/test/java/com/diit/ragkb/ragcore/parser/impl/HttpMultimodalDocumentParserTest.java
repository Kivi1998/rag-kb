package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.net.URLDecoder;
import java.net.http.HttpRequest;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 2026-07-15 真实文档上传时发现：中文文件名直接塞进 Java {@link HttpRequest}
 * 的 header 值会抛 {@code IllegalArgumentException: invalid header value}
 * （header 值只接受 ASCII 可见字符）。回归覆盖 {@link HttpMultimodalDocumentParser#buildRequest}
 * 对非 ASCII 文件名的编码处理。
 */
class HttpMultimodalDocumentParserTest {

    private final HttpMultimodalDocumentParser parser = new HttpMultimodalDocumentParser(
            new ObjectMapper(), "http://localhost:8081/v1/parse", "test-api-key", 5_000);

    @Test
    @DisplayName("中文文件名不应导致请求构造抛出 invalid header value")
    void chineseFilenameDoesNotThrow() {
        DocumentInput input = fakeInput("2020年中国地球物理联合年会投稿-贾昊-高建军.docx");
        HttpRequest request = assertDoesNotThrow(() -> parser.buildRequest(input));
        String encoded = request.headers().firstValue("X-Document-Filename").orElseThrow();
        assertEquals("2020年中国地球物理联合年会投稿-贾昊-高建军.docx",
                URLDecoder.decode(encoded, StandardCharsets.UTF_8));
    }

    @Test
    @DisplayName("含空格与特殊符号的文件名编码/解码后原样还原")
    void filenameWithSpaceAndSymbolsRoundTrips() {
        DocumentInput input = fakeInput("上传测量标志点zip包、查询测量标志点信息接口(3).pdf");
        HttpRequest request = parser.buildRequest(input);
        String encoded = request.headers().firstValue("X-Document-Filename").orElseThrow();
        assertEquals("上传测量标志点zip包、查询测量标志点信息接口(3).pdf",
                URLDecoder.decode(encoded, StandardCharsets.UTF_8));
    }

    @Test
    @DisplayName("纯 ASCII 文件名不受编码影响，行为与改动前一致")
    void asciiFilenameUnaffected() {
        DocumentInput input = fakeInput("deployment-guide.pdf");
        HttpRequest request = parser.buildRequest(input);
        assertEquals("deployment-guide.pdf", request.headers().firstValue("X-Document-Filename").orElseThrow());
    }

    @Test
    @DisplayName("X-Document-Id 与 Authorization 头正确携带")
    void otherHeadersPreserved() {
        UUID documentId = UUID.randomUUID();
        DocumentInput input = fakeInput(documentId, "报告.pdf");
        HttpRequest request = parser.buildRequest(input);
        assertEquals(documentId.toString(), request.headers().firstValue("X-Document-Id").orElseThrow());
        assertEquals("Bearer test-api-key", request.headers().firstValue("Authorization").orElseThrow());
    }

    private DocumentInput fakeInput(String filename) {
        return fakeInput(UUID.randomUUID(), filename);
    }

    private DocumentInput fakeInput(UUID documentId, String filename) {
        return new DocumentInput() {
            @Override public UUID documentId() { return documentId; }
            @Override public String filename() { return filename; }
            @Override public String contentType() { return "application/octet-stream"; }
            @Override public String sourcePath() { return "org/test/kb/test/documents/" + documentId + ".docx"; }
            @Override public InputStream openStream() { return new ByteArrayInputStream(new byte[0]); }
        };
    }
}
