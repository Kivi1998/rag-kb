## Context

当前知识库 Chunk 全文与 1024 维 BGE-M3 向量共同写入 Elasticsearch `rag_chunks_v1`，查询由 `ElasticsearchHybridCandidateSource` 分别执行 BM25 和 kNN，再交给 `HybridRetriever` 做 RRF、Rerank 与拒答。摄取使用 PostgreSQL `ingestion_job`、确定性 Chunk ID、Worker 租约和失败重试；解析产物可复用。

本变更把知识库向量 ANN 独立到 Milvus，同时维持外部问答 API、SSE、引用、RRF/Rerank 行为。ES 仍是 Chunk 正文和引用定位的检索投影；Milvus 是可重建的向量投影。多租户隔离必须同时出现在两端过滤和结果回查中。

## Goals / Non-Goals

**Goals:**

- 将知识库向量写入、过滤检索和删除迁至 Milvus，ES 保留 BM25。
- 解耦词法与向量候选源，保持自研 RAG Core 和现有融合/重排协议。
- 复用现有 Worker 实现幂等双写、失败重试和最终一致。
- 支持 ES、Milvus、影子三种向量模式，一键回滚。
- 以可见性闸门、双重租户过滤和安全测试阻止半写入及跨租户数据泄露。

**Non-Goals:**

- 不迁移 `rag_memory_v1`，不替换 ES 的 BM25 与引用正文。
- 不引入 Kafka、RabbitMQ 或高层 RAG 编排框架。
- 不在本变更中删除 ES `content_vector`；不承诺未经基准测试的性能提升。
- 不改变问答 REST/SSE 契约、RRF 算法和 Rerank/拒答阈值。

## Decisions

### D1：ES 与 Milvus 分工，而非整体替换 ES

ES 负责 `content_search`、技术标识字段、Chunk 正文和引用定位；Milvus 只保存向量及最小过滤字段。Milvus 返回 `chunk_id` 和分数，系统通过 ES `_mget`/受过滤查询批量补齐 Chunk。

备选方案是把正文也复制进 Milvus，或完全使用 Milvus BM25。前者扩大双写一致性面，后者会丢失现有技术字段加权和已验证的 ES 词法基线，因此不选。

### D2：按端口拆分候选源和索引投影

新增 `LexicalCandidateSource`、`VectorCandidateSource`、`ChunkHydrator`、`LexicalChunkIndex` 与 `VectorChunkIndex`。ES 与 Milvus 各自实现对应端口，`HybridRetriever` 只编排两路结果，不依赖数据库 SDK。

为控制迁移风险，原 `HybridCandidateSource` 与 `ChunkIndex` 先由适配器兼容；测试迁移完成后再删除重复接口。这样每个提交均可构建、可回滚。

### D3：Milvus Collection 只保存向量投影

Collection 使用 `rag_chunks_vector_v1`：

| 字段 | 类型 | 约束 |
|---|---|---|
| `chunk_id` | `VARCHAR` | 主键，复用确定性 Chunk ID |
| `embedding` | `FLOAT_VECTOR(1024)` | BGE-M3 dense 向量 |
| `org_id` | `VARCHAR` | 必填标量过滤 |
| `kb_id` | `VARCHAR` | 必填标量过滤 |
| `document_id` | `VARCHAR` | 文档过滤与删除 |
| `embedding_model` | `VARCHAR` | 模型版本 |
| `chunk_version` | `VARCHAR` | 切块版本 |
| `retrieval_ready` | `BOOL` | 可见性闸门，默认 false |
| `indexed_at` | `INT64` | 排障时间戳 |

首版采用 HNSW、COSINE、`M=16`、`efConstruction=200`、查询 `ef=128`。所有参数配置化，并以现有 150 题评测集和目标负载校准。维度、距离类型或模型不兼容时创建新 Collection，不原地覆盖。

### D4：双端暂存，ES 最后激活

摄取时使用确定性 Chunk ID，并按以下顺序收敛：

1. ES Upsert Chunk，`retrieval_ready=false`；
2. Milvus Upsert 向量，`retrieval_ready=false`；
3. Milvus 将该文档投影更新为 `retrieval_ready=true`；
4. ES 最后更新为 `retrieval_ready=true`；
5. 只有第 4 步成功，`ingestion_job` 与文档才进入 `READY`。

所有 ES BM25、ES kNN、Milvus ANN 和 ES 回查都强制过滤 `retrieval_ready=true`。因此任意中间步骤失败时：ES 不返回暂存 Chunk；即使 Milvus 已激活，ES 回查也会丢弃它。Worker 复用解析产物、重新生成确定性 Chunk ID 并幂等重试，无需新增消息队列。

### D5：删除先关闭 ES 可见性，再物理清理

删除请求将文档置为 `DELETING` 后，先把 ES 对应 Chunk 的 `retrieval_ready` 设为 false，再删除 Milvus 向量、ES Chunk、对象和数据库元数据。中途失败则保留 `DELETING`，由现有补偿任务重试。ES 是最后一道正文回查边界，先关闭它可确保已删除文档不会继续出现在 BM25 或向量引用中。

### D6：三种提供方模式与降级

- `elasticsearch`：现有 ES kNN，默认回滚模式。
- `shadow`：线上回答仍采用 ES kNN，同时查询 Milvus并记录 TopK 差异和延迟。
- `milvus`：Milvus 是主向量候选源；超时或不可用时按配置回退 ES kNN，再失败则保留 BM25。

模式由服务端配置决定，不接受请求参数覆盖。外部 API 不暴露底层提供方。

### D7：租户过滤执行三次

Milvus 查询表达式必须由服务端根据类型化的 `orgId + kbId + documentIds` 构造，禁止透传任意表达式；Milvus 命中后，ES 批量回查再次带相同边界；转换为 `RetrievedChunk` 前再比对返回记录中的组织与知识库。任何不一致均丢弃并产生安全指标。

Collection 采用共享 Collection + 标量过滤，而非每租户一个 Collection。当前百人级团队和未知租户数下，共享 Collection 运维更简单；若未来超大租户需要物理隔离，再通过独立 Collection/数据库演进。

## Risks / Trade-offs

- [双存储增加运维复杂度] → 先用 Standalone 验收，提供健康检查、延迟、差异和积压指标，生产高可用另行容量设计。
- [分布式写入没有跨库事务] → 使用 `retrieval_ready` 闸门、确定性主键、幂等操作和现有持久任务重试。
- [Milvus 命中无法直接生成引用] → 统一通过 ES 批量补齐；缺失或越界的 ID 丢弃并计数。
- [影子查询增加模型/存储开销] → 复用同一查询向量，影子比例和超时独立配置，不阻塞主结果。
- [HNSW 参数导致召回或内存变化] → 保留 ES 基线，用评测集和压力测试校准，未达门槛不得切流。
- [历史 ES Chunk 缺少可见性字段] → 在新查询启用过滤前执行迁移回填并校验计数。
- [ES 回退长期存在形成双份向量成本] → 观察期后单独评审；本变更不把清理和切流捆绑发布。

## Migration Plan

1. 添加 ES `retrieval_ready` mapping/写入过滤，并把存量 Chunk 回填为 true；保持提供方为 `elasticsearch`。
2. 部署 Milvus、创建 Collection/索引，增加 SDK、健康检查和指标。
3. 完成端口拆分与 ES 适配器，验证行为基线不变。
4. 启用双写，历史向量按模型/Chunk 版本回填 Milvus；校验总数、租户分布和抽样向量。
5. 启用 `shadow`，比较 TopK、Recall@K、MRR、P95/P99 与资源占用。
6. 通过门槛后将少量实例/流量改为 `milvus`，逐步扩大；持续保留 ES kNN。
7. 稳定观察后将 Milvus 设为默认。是否移除 ES 向量另开 change。

回滚只修改 `RAG_VECTOR_PROVIDER=elasticsearch` 并重启/刷新配置；ES 向量在本 change 全程保留，无需重建。若双写导致摄取异常，关闭 Milvus 双写并将失败任务重新排队。

## Open Questions

- 生产部署最终采用 Milvus Standalone 还是 Kubernetes 集群，由目标 Chunk 数、峰值 QPS、P95 和可用性目标在压测后决定。
- 影子采样比例与稳定观察期暂定 10% 和 7 天，部署前可由运维目标调整。
- ES 向量何时清理、会话记忆是否迁移，不属于本 change，需独立评审。
