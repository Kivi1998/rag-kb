package com.diit.ragkb.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * RAGFlow 连接配置
 * 从 application.yml 的 ragflow.* 读取,密钥从 application-secret.yml 或环境变量覆盖
 */
@Data
@Component
@ConfigurationProperties(prefix = "ragflow")
public class RagFlowProperties {

    private String baseUrl = "http://localhost:9380";
    private String apiKey = "";
}
