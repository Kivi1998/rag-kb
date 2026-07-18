## Purpose

企业知识库 RAG 流式问答——自研混合检索链路（BM25 + 可配置向量候选源[ES kNN / Milvus ANN / 影子对比] + RRF + 可选 Rerank）检索知识库 chunk，通过 SSE 流式返回生成答案及引用来源，低置信度时拒答。向量候选提供方由服务端配置决定，客户端不可覆盖；Milvus 主模式下故障可降级至 ES kNN 或 BM25，任意降级组合均强制租户边界。

## Requirements

### Requirement: 成员可向知识库发起流式问答

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口，接受自然语言问题与必填的 `sessionId`，以 SSE（`text/event-stream`）流式返回自研混合检索链路生成的答案及引用来源。接口需认证（JWT），跨租户访问 SHALL 返回 404。响应事件为 `chunk`（答案片段）、`source`（引用来源）、`refusal`（拒答，检索阶段低置信度或生成阶段事实核验触发均走此事件）、`self_check_warning`（生成后自检发现疑似未支撑断言时的提醒，可选，不影响其他事件）、`done`（流结束）、`error`（异常）六类之一的组合。生成模型 SHALL 在正文之前先输出一行 `{"found": true|false}` 判断参考资料是否包含问题的具体答案；系统 SHALL 缓冲该判断行，`source` 事件的发送时机 SHALL 推迟到判断为 `found:true` 之后。检索阶段 SHALL 对每个候选片段（不只是排名第一的片段）应用 rerank 相关性阈值过滤，低于阈值的片段不得进入生成 prompt 或 `source` 事件。

#### Scenario: 正常流式问答

- **WHEN** 已认证成员向本组织知识库发起问答请求（question 非空），生成模型判断资料包含具体答案（`found:true`）
- **THEN** 系统立即返回 HTTP 200 并开始 SSE 流，先推送 `source` 事件（引用来源，含文档名/片段/相关度），再依次推送判断行之后正文对应的 `chunk` 事件，最终推送 `done` 事件

#### Scenario: 问题为空

- **WHEN** 请求体 `question` 为空字符串或缺失
- **THEN** 系统同步返回 HTTP 400，不创建 SseEmitter

#### Scenario: sessionId 缺失

- **WHEN** 请求体缺少 `sessionId` 或 `sessionId` 不属于当前认证成员
- **THEN** 系统同步返回 HTTP 400/404，不创建 SseEmitter

#### Scenario: 跨租户访问被拒

- **WHEN** 已认证成员请求不属于本组织的知识库 kbId
- **THEN** 系统同步返回 HTTP 404，不创建 SseEmitter，不执行检索

#### Scenario: 检索结果不足触发拒答

- **WHEN** 混合检索融合后最高分低于拒答阈值，或 Rerank 后最高相关性低于门槛，且当前会话没有挂任何未过期的临时文档
- **THEN** 系统推送 `refusal` 事件（含拒答原因），不推送 `chunk`/`source`，随后推送 `done`

#### Scenario: 存在临时文档时不触发检索拒答

- **WHEN** 混合检索融合后最高分低于拒答阈值，或 Rerank 后最高相关性低于门槛，但当前会话挂有至少一个未过期的临时文档（quick-document-qa 能力）
- **THEN** 系统不推送 `refusal` 事件，改为只用临时文档内容继续生成回答；引用来源中不包含本次被过滤掉的知识库片段

#### Scenario: 生成阶段事实核验触发拒答（NO_RETRIEVAL）

- **WHEN** 检索结果通过了检索阶段阈值判断（未被判定为低置信度/超出范围），但生成模型在判断行输出 `{"found": false}`（检索到的内容主题相关，但不包含该问题的具体答案）
- **THEN** 系统丢弃已缓冲的判断行内容，不推送 `source`、不推送已生成的任何正文片段，推送一条固定文案的 `refusal` 事件（"未在当前知识库中检索到该问题的具体答案"），随后推送 `done`；该轮查询审计记录状态为 `REFUSED`，不得记为 `COMPLETED`

#### Scenario: 生成模型未按格式输出判断行时的兜底

- **WHEN** 生成模型输出的前 200 个字符内既未出现换行符、也无法解析出合法的 `{"found": ...}` JSON
- **THEN** 系统 fail-open：将已缓冲的内容全部当作正文透传，正常推送 `source` 与后续 `chunk` 事件，不触发本次新增的事实核验拒答（等同于本机制关闭前的原有行为）

#### Scenario: 检索结果中低可信片段被过滤

- **WHEN** 混合检索融合并 rerank 成功后，候选片段列表中排名第一之外的某个片段相关性分数低于拒答阈值
- **THEN** 该片段不得出现在生成 prompt 的参考资料中，也不得推送对应的 `source` 事件；若过滤后候选片段列表为空，系统按"检索结果不足"场景推送 `refusal` 事件（除非当前会话挂有临时文档，见上方例外场景）

#### Scenario: 生成后自检发现疑似未支撑断言

- **WHEN** 生成完成（`found:true` 且正文推送完毕）后，系统对正文逐句核查，发现某句话未标注引用来源、或标注的引用来源与该句话的相关性低于核验阈值
- **THEN** 系统在推送 `done` 之前额外推送一条 `self_check_warning` 事件，包含存疑内容的说明；该事件不改变本轮查询的审计状态（仍按 `found` 判断结果记 `COMPLETED`/`REFUSED`），不计入会话记忆的回答内容

#### Scenario: 生成后自检未发现问题

- **WHEN** 生成完成后系统对正文逐句核查，未发现任何未标注引用或引用相关性低于阈值的句子
- **THEN** 系统不推送 `self_check_warning` 事件，直接推送 `done`

#### Scenario: 自检调用底层核查服务异常时不影响主流程

- **WHEN** 自检环节调用 Reranker 服务失败或超时
- **THEN** 系统 fail-open，不推送 `self_check_warning` 事件，不影响已经完成的正文与引用展示，仅记录日志

#### Scenario: 模型服务调用异常

- **WHEN** Embedding/生成模型调用过程中抛出异常或连接中断
- **THEN** 系统向 SseEmitter 发送 `error` 事件（含用户可读的错误描述），记录审计日志后 complete

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
