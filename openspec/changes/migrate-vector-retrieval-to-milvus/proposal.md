## Why

Elasticsearch 同时承担 BM25 与向量检索，向量建索引和查询无法独立扩容、调优。引入 Milvus 承载知识库 Chunk 的向量 ANN，在保留现有全文检索质量的同时，为数据增长和峰值查询提供负载隔离与专用索引能力。

## What Changes

- 新增 Milvus 向量写入、删除、过滤检索、健康检查与历史回填能力。
- 将候选源拆为 ES BM25 与 Milvus ANN，经现有 RRF、Rerank 链路融合。
- 增加 ES/Milvus 可恢复双写、影子读、差异指标、灰度开关和 ES kNN 回滚。
- Milvus 命中按 `chunk_id` 回查 ES，并再次校验组织与知识库边界。

## Capabilities

### New Capabilities

- `milvus-vector-index`: 规定 Milvus Collection、幂等写删、租户过滤、回填、影子校验与可回滚切换。

### Modified Capabilities

- `rag-query`: 向量候选改为可配置的 ES/Milvus/影子模式，并规定 Milvus 故障降级及命中二次租户校验。

## Impact

影响 `ragcore.index`、`ragcore.retrieval`、摄取 Worker、配置与指标；新增 Milvus Java SDK、开发/验收部署和索引状态迁移。外部问答 API 与 SSE 协议不变。

## Non-goals（非目标）

- 不移除 ES BM25、引用正文及观察期内的 ES 向量回滚通道。
- 不迁移 `rag_memory_v1`，不引入 RAG 编排框架。
- 不因引入 Milvus 自动宣称性能提升；切流以质量与压测门槛为准。
