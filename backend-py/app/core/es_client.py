"""Elasticsearch 共享异步客户端单例。

对应 Java 版 `config/RagElasticsearchConfiguration.ragRestClient`。
chunk 索引(`rag_chunks_v1`)、记忆索引(`rag_memory_v1`)等所有 ES 接入点共用同一个
`AsyncElasticsearch` 实例与底层连接池,避免每模块各自建客户端造成连接数膨胀。

连接参数与 Java 版对齐:
  * `rag_es_endpoint` → `hosts`(单节点或 URL 列表)
  * `rag_es_api_key` → `api_key`(空时不传)
  * `rag_es_socket_timeout_ms` → `request_timeout`(秒)
  * `rag_es_connect_timeout_ms` 在 elasticsearch-py 8.x 的 `AsyncElasticsearch` 构造器中
    没有 1:1 的直接参数(底层走 `elastic_transport`/`httpx` 的传输层,需要替换
    `node_class` 才能下钻),先在文档里保留,待后续若有强制连接超时诉求再补
    `HttpxAsyncHttpNode` 子类。

`rag_es_enabled=false` 时不抛错(惰性建立),上层按需检查开关,避免导入期就因配置
缺失导致整应用启动失败——和 `mongo_client.get_memory_mongo_client()` 的处理风格一致。
"""

from __future__ import annotations

from functools import lru_cache

from elasticsearch import AsyncElasticsearch

from app.core.config import settings


@lru_cache(maxsize=1)
def get_es_client() -> AsyncElasticsearch:
    """惰性建立 ES 异步客户端,模块级单例(lru_cache 保证全局只构造一次)。"""
    return AsyncElasticsearch(
        hosts=settings.rag_es_endpoint,
        api_key=settings.rag_es_api_key or None,
        request_timeout=settings.rag_es_socket_timeout_ms / 1000,
    )
