## Why

rag-kb 当前是完全无状态的单轮问答：`QueryRequest.history`/`rewrite` 是无人消费的预留空字段，没有会话或消息持久化，"那它过了还能退吗"这类指代性追问会直接检索失败。本 change 补上多轮对话与记忆管理能力，同时借这个机会学习生产级记忆架构（滑动窗口+语义历史检索+摘要压缩、用户画像+基于访问频率的遗忘机制、Redis/MongoDB/Elasticsearch 三层存储），为未来用户规模增长预先建设——当前 rag-kb 规模（单节点、日均 5000 次查询）实际还用不到这套复杂度，是主动的能力储备，非当前刚需驱动。

## What Changes

- 新增会话生命周期管理：`chat_session`（Postgres）记录会话元数据与状态机（ACTIVE/IDLE/ARCHIVED）
- 新增短期记忆：Redis 存滑动窗口原始消息（rag-kb 专属新实例，与共享的 `thxpace-redis-local` 分开，逻辑 DB 与现有 JWT 黑名单隔离）；超 token 预算时触发摘要压缩而非硬截断
- 新增长期记忆：MongoDB 存 `chat_messages`（长期存档，写直达）与 `memory_items`（用户画像：偏好/事实/长期目标三类，增量提炼，语义去重）
- 新增统一语义记忆检索：Elasticsearch 新索引 `rag_memory_v1`，同一套向量检索机制服务于会话内语义相关历史召回（`session_id` 过滤）与跨会话用户画像召回（`member_id` 过滤）
- 新增指代消解：检索前用窄范围 LLM 调用把指代/省略补全为独立问题，失败降级用原始问题，不阻断主流程
- 新增遗忘机制：`memory_items` 按访问频率/时间戳读时计算权重衰减，久未使用且不重要的条目自然跌出检索结果，无需定时批处理任务
- **BREAKING**：`QueryController.QueryRequest` 移除未使用的 `history`/`rewrite` 字段，改为必须携带 `sessionId`
- 前端：进入知识库聊天时创建/复用会话，后续提问携带 `sessionId`

## Capabilities

### New Capabilities

- `conversation-memory`：会话生命周期管理、短期滑动窗口+语义历史记忆、长期用户画像与遗忘机制、指代消解，覆盖新增的两个会话相关 API 与内部记忆检索/提炼流程

### Modified Capabilities

- `rag-query`：`POST /api/v1/knowledge-bases/{kbId}/query` 请求契约变化——移除 `history`/`rewrite` 死字段，新增必填 `sessionId`；检索前增加指代消解步骤（对 `resolvedQuestion` 检索，不改变现有 BM25+kNN+RRF+Rerank 逻辑本身）；生成阶段新增可选的用户画像 System 上下文注入
- `frontend-chat`：聊天面板需在进入知识库/新建对话时创建会话并持有 `sessionId`，每次提问携带该值

## Impact

- 新增依赖：Redis（rag-kb 专属新实例）、MongoDB（新引入，仅服务本能力）
- 复用现有基础设施：Elasticsearch（新增索引 `rag_memory_v1`，不影响 `rag_chunks_v1`）、现有 DeepSeek 模型客户端（指代消解与画像提炼复用，不新增模型依赖）
- 数据库迁移：Postgres 新增 `chat_session` 表（Flyway V012）
- 受影响代码：`QueryController`/`QueryService`（契约变更、编排新增记忆步骤）、`HybridRetriever` 的调用方式不变（仍是黑盒调用，输入换成 `resolvedQuestion`）、前端 `ChatPanel.vue`
- 不影响：现有 `document`/`knowledge_base` 等 Postgres 业务表、现有 `rag_chunks_v1` 索引与检索/重排链路本身、现有 JWT 认证/黑名单逻辑（仅逻辑隔离，物理上迁移到 rag-kb 专属 Redis 实例）
