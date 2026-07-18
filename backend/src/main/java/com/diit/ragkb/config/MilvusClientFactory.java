package com.diit.ragkb.config;

import io.milvus.v2.client.ConnectConfig;
import io.milvus.v2.client.MilvusClientV2;

/** 隔离 Milvus SDK 客户端构造，便于验证生命周期且不在测试中建立网络连接。 */
@FunctionalInterface
public interface MilvusClientFactory {
    MilvusClientV2 create(ConnectConfig connectConfig);
}
