## ADDED Requirements

### Requirement: 可配置的知识库向量候选提供方

系统 SHALL 通过服务端配置在 `elasticsearch`、`shadow`、`milvus` 三种知识库向量模式间切换，且 MUST 保持现有问答 API、SSE 事件、BM25、RRF、Rerank、拒答与引用契约不变。客户端不得通过请求参数选择底层提供方。

#### Scenario: Elasticsearch 回滚模式
- **WHEN** Provider 配置为 `elasticsearch`
- **THEN** 系统使用 ES BM25 与 ES kNN 候选执行现有混合检索，不访问 Milvus 主查询路径

#### Scenario: Milvus 主模式
- **WHEN** Provider 配置为 `milvus` 且 Milvus 查询成功
- **THEN** 系统融合 ES BM25 与经 ES 安全补齐的 Milvus ANN 候选，再执行现有 Rerank、拒答、生成和引用流程

#### Scenario: 客户端尝试指定提供方
- **WHEN** 客户端在问答请求中附带向量提供方或任意 Milvus 过滤表达式
- **THEN** 系统忽略或拒绝该字段，底层提供方及租户过滤仅由服务端决定

### Requirement: Milvus 影子检索不得影响回答

影子模式 SHALL 复用主查询已生成的同一问题向量，并并行记录 ES 与 Milvus 的延迟、TopK 重合率和差异；线上融合与回答 MUST 继续使用 ES kNN 结果。

#### Scenario: 影子结果与 ES 不同
- **WHEN** Milvus TopK 与 ES kNN TopK 存在差异
- **THEN** 系统记录差异指标和受租户保护的诊断信息，返回内容仍完全由 ES 主结果决定

#### Scenario: 影子查询失败
- **WHEN** Milvus 影子查询超时或异常
- **THEN** 系统不中断 SSE、不改变拒答判断，仅记录失败与延迟指标

### Requirement: Milvus 故障时检索可降级

Milvus 主模式下，系统 SHALL 在 Milvus 超时或不可用时按配置回退 ES kNN；若 ES kNN 也不可用，则 SHALL 保留 ES BM25 候选，并在诊断和审计中记录降级路径。

#### Scenario: Milvus 失败回退 ES kNN
- **WHEN** Milvus 主查询失败且 ES kNN 回退已启用并成功
- **THEN** 系统使用 ES BM25 + ES kNN 完成现有混合检索，不向用户暴露底层异常细节

#### Scenario: 两种向量检索均不可用
- **WHEN** Milvus 查询失败且 ES kNN 回退也失败
- **THEN** 系统仅使用当前租户的 ES BM25 结果继续检索；若 BM25 也无足够依据，则按现有规则拒答

#### Scenario: 跨租户数据不得在降级中泄露
- **WHEN** Milvus、ES kNN 或回查发生故障并触发任意降级组合
- **THEN** 每一路仍强制 `org_id + kb_id` 边界，另一组织内容不得进入回答、引用、SSE 或审计明细
