package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.MultimodalDocumentParser;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 多模态解析网关 HTTP 适配器。
 *
 * <p>请求体为原始文件字节，避免编排服务将大文件读入内存；网关返回 JSON：
 * {@code {sections:[{text,headingPath,pageNo,lineStart,lineEnd,metadata}],metadata:{...}}}。
 * 网关实现可对接 OCR、PDF 版面分析、PPT 图片文字识别或视频 ASR。</p>
 */
public class HttpMultimodalDocumentParser implements MultimodalDocumentParser {

    private static final Set<String> EXTENSIONS = Set.of("pdf", "docx", "pptx", "png", "jpg", "jpeg", "tif", "tiff",
            "mp4", "mov", "mkv", "mp3", "wav");

    private final HttpClient client;
    private final ObjectMapper objectMapper;
    private final URI endpoint;
    private final String apiKey;
    private final Duration timeout;

    public HttpMultimodalDocumentParser(ObjectMapper objectMapper, String endpoint, String apiKey, long timeoutMs) {
        if (endpoint == null || endpoint.isBlank()) {
            throw new IllegalArgumentException("多模态解析已启用但未配置 rag.parser.multimodal.endpoint");
        }
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalArgumentException("多模态解析已启用但未配置 rag.parser.multimodal.api-key");
        }
        // Uvicorn 默认不支持 Java HttpClient 的明文 h2c 升级；固定 HTTP/1.1 以保证流式请求体不丢失。
        this.client = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(10))
                .build();
        this.objectMapper = objectMapper;
        this.endpoint = URI.create(endpoint);
        this.apiKey = apiKey;
        this.timeout = Duration.ofMillis(timeoutMs);
    }

    @Override
    public boolean supports(DocumentInput input) {
        String name = input.filename() == null ? "" : input.filename();
        int dot = name.lastIndexOf('.');
        return dot >= 0 && EXTENSIONS.contains(name.substring(dot + 1).toLowerCase(Locale.ROOT));
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        try {
            HttpRequest request = buildRequest(input);
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                String body = response.body() == null ? "" : response.body().strip();
                if (body.length() > 500) body = body.substring(0, 500);
                throw new IOException("多模态解析网关返回 HTTP " + response.statusCode()
                        + (body.isEmpty() ? "" : ": " + body));
            }
            return toParsedDocument(input, objectMapper.readTree(response.body()));
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IOException("多模态解析请求被中断", ex);
        } catch (IllegalArgumentException ex) {
            throw new IOException("多模态解析请求构造或网关响应不合法: " + ex.getMessage(), ex);
        }
    }

    /** 拆出请求构造逻辑，便于单元测试直接检查 header 而不必真的发网络请求。 */
    HttpRequest buildRequest(DocumentInput input) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(endpoint)
                .timeout(timeout)
                .header("Content-Type", input.contentType() == null || input.contentType().isBlank()
                        ? "application/octet-stream" : input.contentType())
                .header("X-Document-Id", input.documentId().toString())
                // Java HttpRequest 的 header 值只接受 ASCII 可见字符；中文等非 ASCII 文件名
                // 直接塞进去会抛 IllegalArgumentException: invalid header value。用
                // application/x-www-form-urlencoded 的百分号编码规避，网关侧对称解码。
                .header("X-Document-Filename", URLEncoder.encode(input.filename(), StandardCharsets.UTF_8))
                .header("X-Source-Path", input.sourcePath())
                .header("Authorization", "Bearer " + apiKey)
                .POST(HttpRequest.BodyPublishers.ofInputStream(() -> {
                    try {
                        return input.openStream();
                    } catch (IOException ex) {
                        throw new IllegalStateException("无法读取待解析对象", ex);
                    }
                }));
        return builder.build();
    }

    private ParsedDocument toParsedDocument(DocumentInput input, JsonNode root) throws IOException {
        JsonNode sectionNodes = root.path("sections");
        if (!sectionNodes.isArray()) {
            throw new IOException("多模态解析网关响应缺少 sections 数组");
        }
        List<DocumentSection> sections = new ArrayList<>();
        for (JsonNode node : sectionNodes) {
            String text = node.path("text").asText("").strip();
            if (text.isEmpty()) {
                continue;
            }
            List<String> headingPath = new ArrayList<>();
            node.path("headingPath").forEach(item -> headingPath.add(item.asText()));
            sections.add(new DocumentSection(text, headingPath,
                    optionalInt(node, "pageNo"), optionalInt(node, "lineStart"), optionalInt(node, "lineEnd"),
                    stringMap(node.path("metadata"))));
        }
        if (sections.isEmpty()) {
            throw new IOException("多模态解析网关未返回可索引文本");
        }
        Map<String, String> metadata = stringMap(root.path("metadata"));
        metadata.putIfAbsent("parser", "multimodal-gateway");
        return new ParsedDocument(input.documentId(), input.contentType(), input.sourcePath(), sections, metadata);
    }

    private Integer optionalInt(JsonNode node, String field) {
        return node.hasNonNull(field) ? node.get(field).asInt() : null;
    }

    private Map<String, String> stringMap(JsonNode node) {
        Map<String, String> map = new LinkedHashMap<>();
        if (node.isObject()) {
            node.fields().forEachRemaining(entry -> map.put(entry.getKey(), entry.getValue().asText()));
        }
        return map;
    }
}
