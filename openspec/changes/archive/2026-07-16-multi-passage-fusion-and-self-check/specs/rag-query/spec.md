## MODIFIED Requirements

### Requirement: 成员可向知识库发起流式问答

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口，接受自然语言问题，以 SSE（`text/event-stream`）流式返回自研混合检索链路生成的答案及引用来源。接口需认证（JWT），跨租户访问 SHALL 返回 404。响应事件为 `chunk`（答案片段）、`source`（引用来源）、`refusal`（拒答，检索阶段低置信度或生成阶段事实核验触发均走此事件）、`self_check_warning`（生成后自检发现疑似未支撑断言时的提醒，可选，不影响其他事件）、`done`（流结束）、`error`（异常）六类之一的组合。生成模型 SHALL 在正文之前先输出一行 `{"found": true|false}` 判断参考资料是否包含问题的具体答案；系统 SHALL 缓冲该判断行，`source` 事件的发送时机 SHALL 推迟到判断为 `found:true` 之后。检索阶段 SHALL 对每个候选片段（不只是排名第一的片段）应用 rerank 相关性阈值过滤，低于阈值的片段不得进入生成 prompt 或 `source` 事件。

#### Scenario: 正常流式问答

- **WHEN** 已认证成员向本组织知识库发起问答请求（question 非空），生成模型判断资料包含具体答案（`found:true`）
- **THEN** 系统立即返回 HTTP 200 并开始 SSE 流，先推送 `source` 事件（引用来源，含文档名/片段/相关度），再依次推送判断行之后正文对应的 `chunk` 事件，最终推送 `done` 事件

#### Scenario: 问题为空

- **WHEN** 请求体 `question` 为空字符串或缺失
- **THEN** 系统同步返回 HTTP 400，不创建 SseEmitter

#### Scenario: 跨租户访问被拒

- **WHEN** 已认证成员请求不属于本组织的知识库 kbId
- **THEN** 系统同步返回 HTTP 404，不创建 SseEmitter，不执行检索

#### Scenario: 检索结果不足触发拒答

- **WHEN** 混合检索融合后最高分低于拒答阈值，或 Rerank 后最高相关性低于门槛
- **THEN** 系统推送 `refusal` 事件（含拒答原因），不推送 `chunk`/`source`，随后推送 `done`

#### Scenario: 生成阶段事实核验触发拒答（NO_RETRIEVAL）

- **WHEN** 检索结果通过了检索阶段阈值判断（未被判定为低置信度/超出范围），但生成模型在判断行输出 `{"found": false}`（检索到的内容主题相关，但不包含该问题的具体答案）
- **THEN** 系统丢弃已缓冲的判断行内容，不推送 `source`、不推送已生成的任何正文片段，推送一条固定文案的 `refusal` 事件（"未在当前知识库中检索到该问题的具体答案"），随后推送 `done`；该轮查询审计记录状态为 `REFUSED`，不得记为 `COMPLETED`

#### Scenario: 生成模型未按格式输出判断行时的兜底

- **WHEN** 生成模型输出的前 200 个字符内既未出现换行符、也无法解析出合法的 `{"found": ...}` JSON
- **THEN** 系统 fail-open：将已缓冲的内容全部当作正文透传，正常推送 `source` 与后续 `chunk` 事件，不触发本次新增的事实核验拒答（等同于本机制关闭前的原有行为）

#### Scenario: 检索结果中低可信片段被过滤

- **WHEN** 混合检索融合并 rerank 成功后，候选片段列表中排名第一之外的某个片段相关性分数低于拒答阈值
- **THEN** 该片段不得出现在生成 prompt 的参考资料中，也不得推送对应的 `source` 事件；若过滤后候选片段列表为空，系统按"检索结果不足"场景推送 `refusal` 事件

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
