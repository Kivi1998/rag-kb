package com.diit.ragkb.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 在创建外部客户端前统一校验向量 Provider 与 Milvus 配置。 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties({RagMilvusProperties.class, VectorProviderProperties.class})
public class RagVectorPropertiesConfiguration {

    @Bean
    VectorConfigurationGuard vectorConfigurationGuard(RagMilvusProperties milvus,
                                                      VectorProviderProperties vector) {
        vector.validate();
        milvus.validate();
        if (vector.getProvider() != VectorProvider.ELASTICSEARCH && !milvus.isEnabled()) {
            throw new IllegalStateException("shadow/milvus Provider 要求 rag.milvus.enabled=true");
        }
        return new VectorConfigurationGuard();
    }

    /** 仅用于触发配置校验，避免把校验副作用放进属性 getter。 */
    static final class VectorConfigurationGuard { }
}
