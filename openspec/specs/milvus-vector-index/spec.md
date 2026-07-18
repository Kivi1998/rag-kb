## Purpose

知识库 Chunk 向量投影的独立索引与检索能力——用 Milvus 承载向量 ANN（HNSW + COSINE），与 Elasticsearch 的 BM25/正文/引用定位分工协作。Milvus Collection 只保存向量与最小租户/版本过滤字段；命中必须回查 ES 补齐正文并二次校验租户边界。写入与删除均遵循"双端暂存、ES 最后激活/最先关闭可见性"的可见性闸门协议，保证半写入不会导致脏数据可见或跨租户泄露。

## Requirements

### Requirement: Milvus Collection 初始化与兼容性校验

系统 SHALL 在启用 Milvus 前确保目标 Collection 存在，并校验主键、向量维度、距离类型、过滤字段与配置一致；已有 Collection 不兼容时 MUST 启动失败，不得静默重建或覆盖。

#### Scenario: 首次初始化 Collection
- **WHEN** Milvus 已启用且目标 Collection 不存在
- **THEN** 系统创建包含 `chunk_id`、1024 维向量、租户过滤字段、版本字段和 `retrieval_ready` 的 Collection，并创建配置指定的 ANN 索引

#### Scenario: 已有 Collection 与配置不兼容
- **WHEN** Collection 的向量维度、主键或距离类型与当前配置不一致
- **THEN** 系统拒绝启用 Milvus 写入和检索，健康检查报告不可用，且不修改已有 Collection

### Requirement: 知识库向量幂等写入与可见性闸门

系统 SHALL 使用确定性 `chunk_id` 幂等 Upsert Milvus 向量。新投影 MUST 先以 `retrieval_ready=false` 写入；只有 ES 和 Milvus 暂存均成功后才按 Milvus、ES 的顺序激活，ES 激活成功后文档才可进入 `READY`。

#### Scenario: 双端索引成功
- **WHEN** Worker 完成切块与 Embedding，ES 暂存、Milvus 暂存、Milvus 激活和 ES 激活均成功
- **THEN** 两端对应 Chunk 均可检索，任务与文档状态进入 `READY`

#### Scenario: Milvus 写入失败
- **WHEN** ES 暂存成功但 Milvus Upsert 或激活失败
- **THEN** 文档不得进入 `READY`，ES 暂存 Chunk 不得被任何检索返回，任务记录错误并可使用相同 `chunk_id` 重试

#### Scenario: ES 最终激活失败
- **WHEN** Milvus 已激活但 ES 最终激活失败
- **THEN** 文档不得进入 `READY`，Milvus 命中因 ES 回查不可见而不得进入 RRF、生成上下文或引用，任务可幂等重试

### Requirement: Milvus 查询强制租户与知识库过滤

系统 MUST 为每次 Milvus ANN 查询强制添加服务端构造的 `org_id`、`kb_id` 和可选 `document_id` 过滤，且 SHALL 拒绝缺少组织或知识库边界的内部调用。

#### Scenario: 本租户向量召回
- **WHEN** 已认证成员查询本组织知识库
- **THEN** Milvus 仅返回同时匹配该 `org_id`、`kb_id` 且 `retrieval_ready=true` 的向量结果

#### Scenario: 跨租户隔离
- **WHEN** 查询向量与另一组织的 Chunk 高度相似
- **THEN** 另一组织的 `chunk_id` 不得出现在 Milvus 候选、RRF 结果、生成上下文、引用或审计明细中

#### Scenario: 缺少租户边界的调用被拒
- **WHEN** 内部代码以空 `org_id` 或空 `kb_id` 调用向量检索
- **THEN** 系统在访问 Milvus 前拒绝调用并记录错误

### Requirement: 向量命中必须经 ES 安全补齐

Milvus 候选 SHALL 只携带 ID、排名和分数；系统 MUST 按 `chunk_id` 从 ES 批量补齐正文与引用字段，并再次校验 `org_id`、`kb_id` 和 `retrieval_ready=true`。

#### Scenario: 正常补齐向量候选
- **WHEN** Milvus 返回属于当前组织和知识库的可见 Chunk ID
- **THEN** 系统从 ES 补齐完整 Chunk，保留 Milvus 排名并进入 RRF

#### Scenario: Milvus 返回孤儿 ID
- **WHEN** Milvus 命中在 ES 中不存在或尚未激活
- **THEN** 系统丢弃该候选、增加孤儿向量指标，且不得向用户泄露该 ID

#### Scenario: ES 回查发现租户不一致
- **WHEN** Milvus 命中的 ID 在 ES 中属于其他组织或知识库
- **THEN** 系统丢弃该候选并产生安全告警，不进入融合、生成或引用

### Requirement: 文档向量删除可补偿

系统 SHALL 在文档删除时先关闭 ES Chunk 可见性，再按 `org_id + kb_id + document_id` 删除 Milvus 和 ES 投影；任一步失败 MUST 保留 `DELETING` 状态并允许补偿任务重试。

#### Scenario: 正常删除双端投影
- **WHEN** 管理员删除本组织知识库中的文档
- **THEN** 系统关闭其检索可见性，删除 Milvus 向量和 ES Chunk 后再清理对象及业务记录

#### Scenario: Milvus 删除失败
- **WHEN** ES 可见性已关闭但 Milvus 删除超时或失败
- **THEN** 文档保持 `DELETING` 并进入补偿重试，已请求删除的内容不得出现在后续检索中

#### Scenario: 跨租户删除被拒
- **WHEN** 删除条件中的组织或知识库与目标文档不一致
- **THEN** 系统不得删除任何 Milvus 或 ES 数据，并按现有资源访问规则返回 404

### Requirement: 历史向量回填与一致性验证

系统 SHALL 提供可断点续跑的历史回填任务，将与当前模型、维度和 Chunk 版本兼容的 ES 向量写入 Milvus，并在切流前验证数量、租户分布、重复主键和抽样数据。

#### Scenario: 兼容向量直接回填
- **WHEN** ES Chunk 的模型版本、维度与目标 Collection 一致
- **THEN** 回填任务复用既有向量并以 `chunk_id` 幂等写入 Milvus，不重复调用 Embedding

#### Scenario: 不兼容向量不被混写
- **WHEN** ES Chunk 的模型版本或维度与目标 Collection 不一致
- **THEN** 任务跳过并记录待重新向量化项，禁止将不兼容向量写入 Collection

#### Scenario: 回填中断后恢复
- **WHEN** 回填在批次间失败或进程重启
- **THEN** 任务从持久检查点继续，重复批次通过主键 Upsert 收敛，不产生重复向量

### Requirement: Milvus 可观测与就绪检查

系统 SHALL 暴露 Milvus 连接、Collection 兼容性、双写、查询、回退、影子差异和孤儿向量指标；Milvus 主模式启动时，关键依赖不可用 MUST 使就绪检查失败。

#### Scenario: Milvus 主模式依赖健康
- **WHEN** Provider 为 `milvus` 且连接与 Collection 校验通过
- **THEN** 就绪检查报告可用，并记录查询延迟与结果数

#### Scenario: Milvus 主模式依赖不可用
- **WHEN** Provider 为 `milvus` 且 Milvus 无法连接或 Collection 不兼容
- **THEN** 就绪检查报告不可用，系统不得静默宣称 Milvus 已启用

#### Scenario: 影子模式不阻塞线上结果
- **WHEN** Provider 为 `shadow` 且影子 Milvus 查询超时
- **THEN** 线上继续使用 ES kNN 结果，同时记录影子超时和回退指标
