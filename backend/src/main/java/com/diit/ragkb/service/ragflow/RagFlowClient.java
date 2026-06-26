package com.diit.ragkb.service.ragflow;

import com.diit.ragkb.config.RagFlowProperties;
import com.diit.ragkb.exception.ResourceNotFoundException;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

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
