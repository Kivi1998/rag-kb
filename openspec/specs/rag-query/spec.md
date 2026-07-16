## Purpose

企业知识库 RAG 流式问答——自研混合检索链路（BM25+kNN+RRF+可选 Rerank）检索知识库 chunk，通过 SSE 流式返回生成答案及引用来源，低置信度时拒答。

## Requirements

### Requirement: 成员可向知识库发起流式问答

系统 SHALL 提供 `POST /api/v1/knowledge-bases/{kbId}/query` 接口，接受自然语言问题，以 SSE（`text/event-stream`）流式返回自研混合检索链路生成的答案及引用来源。接口需认证（JWT），跨租户访问 SHALL 返回 404。响应事件为 `chunk`（答案片段）、`source`（引用来源）、`refusal`（低置信度拒答）、`done`（流结束）、`error`（异常）五类之一的组合。

#### Scenario: 正常流式问答

- **WHEN** 已认证成员向本组织知识库发起问答请求（question 非空）
- **THEN** 系统立即返回 HTTP 200 并开始 SSE 流，依次推送 `chunk` 事件（答案片段）、`source` 事件（引用来源，含文档名/片段/相关度）、最终 `done` 事件

#### Scenario: 问题为空

- **WHEN** 请求体 `question` 为空字符串或缺失
- **THEN** 系统同步返回 HTTP 400，不创建 SseEmitter

#### Scenario: 跨租户访问被拒

- **WHEN** 已认证成员请求不属于本组织的知识库 kbId
- **THEN** 系统同步返回 HTTP 404，不创建 SseEmitter，不执行检索

#### Scenario: 检索结果不足触发拒答

- **WHEN** 混合检索融合后最高分低于拒答阈值，或 Rerank 后最高相关性低于门槛
- **THEN** 系统推送 `refusal` 事件（含拒答原因），不推送 `chunk`/`source`，随后推送 `done`

#### Scenario: 模型服务调用异常

- **WHEN** Embedding/生成模型调用过程中抛出异常或连接中断
- **THEN** 系统向 SseEmitter 发送 `error` 事件（含用户可读的错误描述），记录审计日志后 complete
