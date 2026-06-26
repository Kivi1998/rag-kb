package com.diit.ragkb.service.ragflow;

import com.diit.ragkb.config.RagFlowProperties;
import com.diit.ragkb.dto.QueryChunkEvent;
import com.diit.ragkb.exception.ResourceNotFoundException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.Resource;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RequestCallback;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * RAGFlow REST 客户端
 * 负责 dataset 的创建与删除
 *
 * 命名规则:
 * - name:        ragkb:{kbId}         (用于查重/幂等)
 * - description: ragkb:{orgId}:{kbId} (用于对账识别归属)
 * 创建幂等:先按 name 查重再创建
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RagFlowClient {

    private final RestTemplate ragFlowRestTemplate;
    private final RagFlowProperties ragFlowProperties;
    private final ObjectMapper objectMapper;

    /**
     * 创建 dataset
     *
     * @param name        dataset 名称(用于查重:ragkb:{kbId})
     * @param description 描述(含 orgId:ragkb:{orgId}:{kbId},用于对账识别归属)
     * @return dataset ID(RAGFlow 返回)
     */
    public String createDataset(String name, String description) {
        // 幂等:按 name 查重
        String existing = findDatasetByTag(name);
        if (existing != null) {
            log.info("dataset 已存在(幂等),name={},datasetId={}", name, existing);
            return existing;
        }

        // 创建
        Map<String, Object> body = Map.of(
                "name", name,
                "description", description,
                "chunk_method", "naive",
                "parser_config", Map.of()
        );

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets";
        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.POST, request, Map.class);

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map data = (Map) response.getBody().get("data");
            if (data != null && data.get("id") != null) {
                String datasetId = data.get("id").toString();
                log.info("创建 dataset 成功,name={},datasetId={}", name, datasetId);
                return datasetId;
            }
        }
        throw new RuntimeException("RAGFlow 创建 dataset 失败: " + response.getBody());
    }

    /**
     * 删除 dataset
     *
     * @param datasetId RAGFlow dataset ID
     */
    public void deleteDataset(String datasetId) {
        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets/" + datasetId;
        HttpHeaders headers = new HttpHeaders();
        HttpEntity<Void> request = new HttpEntity<>(headers);

        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.DELETE, request, Map.class);
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new RuntimeException("RAGFlow 删除 dataset 失败: " + response.getBody());
        }
        log.info("删除 dataset 成功,datasetId={}", datasetId);
    }

    // ===== 文档操作 =====

    /**
     * 上传文档到 RAGFlow dataset(流式传输,不读成 byte[])
     *
     * @param datasetId   RAGFlow dataset ID
     * @param fileName    文件名
     * @param fileResource 文件资源(流式,来自 multipart 临时文件)
     * @param contentType MIME 类型
     * @return ragflowDocId(RAGFlow 返回的文档 ID)
     */
    public String uploadDocument(String datasetId, String fileName, Resource fileResource, String contentType) {
        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets/" + datasetId + "/documents";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.MULTIPART_FORM_DATA);

        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        // 流式传输:Resource 来自 multipart 临时文件,不会将整个文件读入堆内存
        body.add("file", fileResource);

        HttpEntity<MultiValueMap<String, Object>> request = new HttpEntity<>(body, headers);
        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.POST, request, Map.class);

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map data = (Map) response.getBody().get("data");
            if (data != null) {
                java.util.List items = (java.util.List) data.get("items");
                if (items != null && !items.isEmpty()) {
                    Map first = (Map) items.get(0);
                    String docId = first.get("id").toString();
                    log.info("上传文档到 RAGFlow 成功,datasetId={},fileName={},docId={}", datasetId, fileName, docId);
                    return docId;
                }
            }
        }
        throw new RuntimeException("RAGFlow 上传文档失败: " + response.getBody());
    }

    /**
     * 触发 RAGFlow 文档解析
     * 若 RAGFlow 上传即自动解析,此方法退化为空操作
     *
     * @param datasetId   RAGFlow dataset ID
     * @param ragflowDocId RAGFlow 文档 ID
     */
    public void parseDocument(String datasetId, String ragflowDocId) {
        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets/" + datasetId + "/documents/" + ragflowDocId + "/status";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        Map<String, Object> body = Map.of("status", "1"); // RAGFlow 解析触发标记
        HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.PUT, request, Map.class);
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new RuntimeException("触发 RAGFlow 解析失败: " + response.getBody());
        }
        log.info("触发 RAGFlow 解析成功,datasetId={},docId={}", datasetId, ragflowDocId);
    }

    /**
     * 查询 RAGFlow 文档解析状态
     *
     * @param datasetId   RAGFlow dataset ID
     * @param ragflowDocId RAGFlow 文档 ID
     * @return 状态字符串(如 "1"=解析中, "0"=已完成等,RAGFlow 实际值待联调确认)
     */
    public String getDocumentStatus(String datasetId, String ragflowDocId) {
        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets/" + datasetId + "/documents/" + ragflowDocId;

        HttpHeaders headers = new HttpHeaders();
        HttpEntity<Void> request = new HttpEntity<>(headers);

        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.GET, request, Map.class);
        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map data = (Map) response.getBody().get("data");
            if (data != null) {
                Object run = data.get("run");
                // RAGFlow 解析状态由 run 字段标识: "3"=完成, "4"=失败
                // 优先返回 run;若缺失则返回 status 作为降级
                Object status = data.get("status");
                log.debug("查询 RAGFlow 文档状态,datasetId={},docId={},run={},status={}", datasetId, ragflowDocId, run, status);
                return String.valueOf(run != null ? run : status);
            }
        }
        throw new RuntimeException("RAGFlow 查询文档状态失败: " + response.getBody());
    }

    /**
     * 删除 RAGFlow 文档
     *
     * @param datasetId   RAGFlow dataset ID
     * @param ragflowDocId RAGFlow 文档 ID
     */
    public void deleteDocument(String datasetId, String ragflowDocId) {
        String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets/" + datasetId + "/documents";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        Map<String, Object> body = Map.of("ids", java.util.List.of(ragflowDocId));
        HttpEntity<Map<String, Object>> request = new HttpEntity<>(body, headers);

        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.DELETE, request, Map.class);
        if (!response.getStatusCode().is2xxSuccessful()) {
            throw new RuntimeException("RAGFlow 删除文档失败: " + response.getBody());
        }
        log.info("删除 RAGFlow 文档成功,datasetId={},docId={}", datasetId, ragflowDocId);
    }

    // ===== Chat 操作 =====

    /**
     * 创建 JSON 请求体(HttpHeaders + HttpEntity)
     *
     * @param body 请求体
     * @return HttpEntity(带 Content-Type: application/json)
     */
    private HttpEntity<Map<String, Object>> createJsonRequest(Map<String, Object> body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new HttpEntity<>(body, headers);
    }

    /**
     * 创建 Chat Assistant
     *
     * @param kbId      知识库 ID(用于命名:ragkb-chat:{kbId})
     * @param datasetId 绑定的 RAGFlow dataset ID
     * @return chatId(RAGFlow 返回)
     */
    public String createChat(String kbId, String datasetId) {
        Map<String, Object> body = Map.of(
                "name", "ragkb-chat:" + kbId,
                "dataset_ids", java.util.List.of(datasetId)
        );

        String url = ragFlowProperties.getBaseUrl() + "/api/v1/chats";
        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.POST, createJsonRequest(body), Map.class);

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map data = (Map) response.getBody().get("data");
            if (data != null && data.get("id") != null) {
                String chatId = data.get("id").toString();
                log.info("创建 Chat Assistant 成功,kbId={},chatId={}", kbId, chatId);
                return chatId;
            }
        }
        throw new RuntimeException("RAGFlow 创建 Chat 失败: " + response.getBody());
    }

    /**
     * 创建临时 Session
     *
     * @param chatId RAGFlow Chat Assistant ID
     * @return sessionId(RAGFlow 返回)
     */
    public String createSession(String chatId) {
        Map<String, Object> body = Map.of(
                "name", "session-" + System.currentTimeMillis()
        );

        String url = ragFlowProperties.getBaseUrl() + "/api/v1/chats/" + chatId + "/sessions";
        ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.POST, createJsonRequest(body), Map.class);

        if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
            Map data = (Map) response.getBody().get("data");
            if (data != null && data.get("id") != null) {
                String sessionId = data.get("id").toString();
                log.info("创建 Session 成功,chatId={},sessionId={}", chatId, sessionId);
                return sessionId;
            }
        }
        throw new RuntimeException("RAGFlow 创建 Session 失败: " + response.getBody());
    }

    /**
     * 流式消费 RAGFlow Chat Completion SSE 流
     *
     * @param chatId    Chat Assistant ID
     * @param sessionId Session ID
     * @param question  用户问题
     * @param topN      返回引用来源数量
     * @param emitter   SseEmitter(推送给客户端)
     */
    public void streamCompletion(String chatId, String sessionId, String question, int topN, SseEmitter emitter) {
        String url = ragFlowProperties.getBaseUrl()
                + "/api/v1/chats/" + chatId
                + "/sessions/" + sessionId
                + "/completions";

        Map<String, Object> body = Map.of(
                "question", question,
                "stream", true
        );

        RequestCallback requestCallback = req -> {
            req.getHeaders().setContentType(MediaType.APPLICATION_JSON);
            req.getBody().write(objectMapper.writeValueAsBytes(body));
        };

        ragFlowRestTemplate.execute(url, HttpMethod.POST, requestCallback, response -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(response.getBody(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.startsWith("data:")) {
                        String json = line.substring(5).trim();
                        if ("[DONE]".equals(json)) {
                            break;
                        }
                        dispatchSseEvent(json, emitter);
                    }
                }
            }
            return null;
        });
    }

    /**
     * 解析 RAGFlow SSE 数据行并分发到 SseEmitter
     *
     * RAGFlow Chat Completion SSE 格式(待联调确认):
     * - 答案片段:{"data":"答案文本"}
     * - 引用来源:{"reference":[...]}(流末尾)
     * - 结束标记:[DONE]
     */
    private void dispatchSseEvent(String json, SseEmitter emitter) {
        try {
            Map<String, Object> payload = objectMapper.readValue(json, Map.class);

            // 答案片段
            Object data = payload.get("data");
            if (data instanceof String && !((String) data).isBlank()) {
                emitter.send(SseEmitter.event()
                        .name("chunk")
                        .data(QueryChunkEvent.chunk((String) data)));
            }

            // 引用来源(流末尾携带)
            Object refs = payload.get("reference");
            if (refs instanceof java.util.List) {
                java.util.List<?> refList = (java.util.List<?>) refs;
                for (Object ref : refList) {
                    if (ref instanceof Map) {
                        Map<String, Object> refMap = (Map<String, Object>) ref;
                        String docName = String.valueOf(refMap.getOrDefault("doc_name", "unknown"));
                        String content = String.valueOf(refMap.getOrDefault("content", ""));
                        Object scoreObj = refMap.get("similarity");
                        double score = scoreObj instanceof Number ? ((Number) scoreObj).doubleValue() : 0.0;
                        emitter.send(SseEmitter.event()
                                .name("source")
                                .data(QueryChunkEvent.source(docName, content, score)));
                    }
                }
            }
        } catch (Exception e) {
            log.warn("解析 RAGFlow SSE 数据失败,json={}: {}", json, e.getMessage());
        }
    }

    /**
     * 删除 Session(fire-and-forget,异常静默忽略)
     *
     * @param chatId    Chat Assistant ID
     * @param sessionId Session ID
     */
    public void deleteSession(String chatId, String sessionId) {
        try {
            String url = ragFlowProperties.getBaseUrl() + "/api/v1/chats/" + chatId + "/sessions";
            Map<String, Object> body = Map.of("ids", java.util.List.of(sessionId));

            ragFlowRestTemplate.exchange(url, HttpMethod.DELETE, createJsonRequest(body), Map.class);
            log.info("删除 Session 成功,chatId={},sessionId={}", chatId, sessionId);
        } catch (Exception e) {
            log.warn("删除 Session 失败(忽略),chatId={},sessionId={}: {}", chatId, sessionId, e.getMessage());
        }
    }

    /**
     * 删除 Chat Assistant(供知识库删除时级联清理)
     *
     * @param chatId RAGFlow Chat Assistant ID
     */
    public void deleteChat(String chatId) {
        if (chatId == null) return;
        try {
            String url = ragFlowProperties.getBaseUrl() + "/api/v1/chats";
            Map<String, Object> body = Map.of("ids", java.util.List.of(chatId));

            ragFlowRestTemplate.exchange(url, HttpMethod.DELETE, createJsonRequest(body), Map.class);
            log.info("删除 Chat Assistant 成功,chatId={}", chatId);
        } catch (Exception e) {
            log.warn("删除 Chat Assistant 失败,chatId={}: {}", chatId, e.getMessage());
        }
    }

    /**
     * 按 description 查找 dataset(幂等查重)
     * 创建时 description 设为 "ragkb:{kbId}",此处按同一格式搜索
     */
    private String findDatasetByTag(String tag) {
        try {
            String url = ragFlowProperties.getBaseUrl() + "/api/v1/datasets?name=" + tag;
            HttpHeaders headers = new HttpHeaders();
            HttpEntity<Void> request = new HttpEntity<>(headers);

            ResponseEntity<Map> response = ragFlowRestTemplate.exchange(url, HttpMethod.GET, request, Map.class);
            if (response.getStatusCode().is2xxSuccessful() && response.getBody() != null) {
                Map data = (Map) response.getBody().get("data");
                if (data != null) {
                    java.util.List items = (java.util.List) data.get("items");
                    if (items != null && !items.isEmpty()) {
                        Map first = (Map) items.get(0);
                        return first.get("id").toString();
                    }
                }
            }
        } catch (Exception e) {
            log.warn("查重 dataset 异常(忽略): {}", e.getMessage());
        }
        return null;
    }
}
