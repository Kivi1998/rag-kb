## Why

用户希望在知识库问答之外，支持"上传一个文档、立即针对这份文档提问"的轻量模式——不走切块/向量化/索引的标准 RAG 全流程，而是把解析出的全文直接塞进 LLM 上下文（长上下文直接塞入模式）。参考了同类项目 rag系统2 的 `quick_parse` 实现思路，但重新校准了大小限制（DeepSeek-chat 128K 上下文窗口远大于 rag系统2 原本的 4000 字符设定）。

## What Changes

- 新增 `POST/GET/DELETE .../sessions/{sessionId}/quick-documents` 接口：会话内上传/查看/删除临时文档，不写入知识库、不切块不索引。
- 复用 `DocumentParserFactory.parse()` 同步解析（含 OCR/ASR 网关自动降级），解析结果按会话级共享的 15000 字符总额度池截断/拒绝新上传。
- 临时文档存 Redis（新逻辑 DB，TTL 2 小时随会话活跃续期），不落 Postgres，不持久化。
- `QueryService.prepare()` 新增一步：把会话挂的临时文档包装成合成 `RetrievedChunk`，与知识库检索结果一并送入现有 `AnswerGenerator`/引用抽屉/生成后自检。
- **行为变更**：知识库检索触发拒答阈值时，若该会话存在临时文档，不再拒答，改用临时文档内容继续生成——这是对 `rag-query` 能力现有"检索结果不足触发拒答"场景的一个例外分支。

## Capabilities

### New Capabilities
- `quick-document-qa`：会话内临时文档的上传/查询/删除、大小限额与截断、Redis 存储与生命周期。

### Modified Capabilities
- `rag-query`：「检索结果不足触发拒答」场景新增例外——存在会话级临时文档时不拒答，只用临时文档内容回答。

## Non-goals（非目标）

- 不写入知识库、不参与切块/向量化/ES 索引，临时文档对其他成员/其他会话不可见。
- 不做跨会话/跨用户共享，不提供临时文档下载/导出。
- 不做异步任务状态机（QUEUED→PARSING→READY 那一套）——上传接口同步阻塞返回。
- 不做按组织可配置的额度/开关粒度，额度和 TTL 是全局固定值。
- 不改动 `HybridRetriever` 的拒答阈值本身（`MIN_RRF_SCORE`/`MIN_RERANK_SCORE` 校准逻辑不变），只是在临时文档存在时不让这个既有判断触发最终拒答。

## Impact

- **新增**：Redis 存储层（新逻辑 DB + Properties）、`QuickDocumentService`（解析+额度+存取）、Controller 端点、前端上传 UI（简化版，复用 `DocumentPanel.vue` 的文件选择/拖拽部分，不需要状态轮询）。
- **改动**：`QueryService.prepare()`（拒答判断分支、合成 chunk 拼接）、`CitationBuilder` 调用点（把临时文档 id→文件名塞进 documentNames Map，`CitationBuilder` 本身不改）、`ChatPanel.vue`（新增临时文档管理入口）。
- **不改动**：`HybridRetriever`/`RrfFusion` 检索逻辑本身、`DocumentParserFactory`（直接复用，不修改）、知识库正式文档上传流程。
