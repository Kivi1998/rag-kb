## Why

`conversation-memory` 功能已合并到 main：会话生命周期（Postgres `chat_session`）、消息长期存档（MongoDB `chat_messages`）、语义记忆索引（Elasticsearch `rag_memory_v1`）都已就绪，但前端从未消费这些能力——`ChatPanel.vue` 每次挂载（含 F5 刷新）都无条件新建会话，用户体验是"刷新就清空对话"，也完全没有查看/切换历史对话的入口。用户希望做成类似 Claude Chat 的历史会话列表：可在多个历史对话间切换，刷新回到刚才的对话。

## What Changes

- 新增 `GET /api/v1/knowledge-bases/{kbId}/sessions` 列表接口，返回当前成员在该知识库下最近 50 条会话（标题、最后活跃时间），按最后活跃时间倒序
- `chat_session` 表新增 `title` 字段（Flyway 迁移），首条用户消息写入时截取前 30 字存入
- 新增 `DELETE /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}` 硬删除接口，级联清理 Postgres/MongoDB/Redis/Elasticsearch 四处存储
- 前端新增可折叠历史侧边栏组件，展示会话列表、支持切换与删除、新建对话按钮
- 前端用 localStorage 记录当前知识库最后活跃的会话 ID，刷新/重新进入时优先恢复该会话而非总是新建（**BREAKING** 于现有前端 spec：`frontend-chat` 规格里"刷新重置"的历史行为不再成立）

## Capabilities

### New Capabilities
- `conversation-history`: 会话列表查询与硬删除能力，覆盖跨知识库/跨成员/跨组织越权访问被拒的安全场景

### Modified Capabilities
- `frontend-chat`: "多轮对话历史"需求从"内存存储，刷新重置"改为"刷新/重新进入时通过 localStorage 记录的会话 ID 恢复历史"；新增历史会话侧边栏的切换与删除交互需求

## Impact

- 后端：`ChatSessionRepository`/`ChatSessionService`/`ChatSessionController` 新增方法与端点；`ChatMessageRepository`/`ConversationStore`/`MemoryIndex` 新增删除方法；新增 Flyway 迁移
- 前端：新增 `ChatHistorySidebar.vue`；`ChatPanel.vue` 改造会话恢复逻辑
- 不影响 `memory_items` 用户画像（member 维度长期记忆，与会话生命周期无关）；不影响 RAG Core 检索/生成链路
