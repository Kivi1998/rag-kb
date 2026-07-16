## Context

`conversation-memory` change 已合并到 main：会话生命周期（`chat_session` 表，Postgres，org/kb/member 三重归属）、消息长期存档（`chat_messages`，MongoDB）、用户画像（`memory_items`，MongoDB）、统一记忆索引（`rag_memory_v1`，Elasticsearch）均已就绪。已有接口：`POST .../sessions` 创建会话、`GET .../sessions/{sessionId}/messages` 查询单会话消息。

前端 `ChatPanel.vue` 每次挂载（含 F5 刷新、切换知识库）都无条件调用 `createSession()`，不复用旧会话、不拉历史，也没有"查看该知识库下所有历史会话"的入口。本 change 基于已完成的 brainstorming 设计文档（`docs/superpowers/specs/2026-07-15-conversation-history-list-design.md`）落地为可实施的规格。

## Goals / Non-Goals

**Goals:**
- 会话列表：按最后活跃时间倒序展示当前成员在某知识库下的历史会话（标题+时间），固定返回最近 50 条
- 会话标题：首条用户消息前 30 字，写入时算好存库，不在查询时现算
- 硬删除会话：级联清理 Postgres/MongoDB/Redis/Elasticsearch 四处存储，越权删除按 404 处理
- 前端刷新/重新进入知识库时，通过 localStorage 记录的 sessionId 恢复上一次会话，而非总是新建

**Non-Goals:**
- 不做分页（当前规模下固定 50 条足够，接口设计不排斥未来加 cursor）
- 不做会话重命名、不用 LLM 生成标题
- 不引入路由级 sessionId 参数（不改动 `kbId` 靠 store 选择、不走 URL 的现有模式）
- 不影响 `memory_items` 用户画像（member 维度长期记忆，与会话生命周期无关，删除会话不删画像）

## Decisions

### 1. 标题在写入时算好存库，而非列表查询时现取

**决策**：`ConversationMemoryOrchestrator.recordTurn()` 里，若该会话 `chat_session.title` 当前为空（即本轮是该会话第一轮），把 `question` 截取前 30 字符写入。

**考虑过的替代方案**：列表查询时对每个 session 现查 MongoDB 取首条消息。

**为什么选写时算好**：列表接口只需查 Postgres 一张表，不需要对 N 个会话各查一次 MongoDB（避免 N+1，这正是本次 review 修复里刚处理过的同类问题）；写入时机是"第一轮问答完成"，天然只会发生一次，不需要额外判断逻辑。

### 2. 硬删除而非软删除，级联顺序"先删衍生索引，最后删权威记录"

**决策**：`DELETE .../sessions/{sessionId}` 真正物理删除四处存储，顺序为 Elasticsearch → MongoDB → Redis → Postgres。

**考虑过的替代方案**：软删除（`chat_session` 新增 DELETED 状态，列表查询过滤掉，数据不真正清除）。

**为什么选硬删除**：用户对"删除"的直觉预期就是清除，软删除需要额外解释"为什么数据还在"，且没有强需求要保留已删除会话用于审计/恢复。级联顺序遵循现有 `MemoryCleanupTask` 的"先删衍生索引再删权威存储"模式——即使删除中途失败（如 ES 请求超时），Postgres 里的 `chat_session` 行仍在，用户能感知到删除没完全成功并重试；反过来若先删 Postgres 再删 ES/Mongo，一旦后续步骤失败，会产生找不到归属却仍能被检索到的孤儿数据，且没有回头路（`getOwnedSession` 会因 Postgres 行已删而 404，永远无法重新触发删除）。

### 3. Elasticsearch/MongoDB 删除方法签名强制携带租户维度

**决策**：`MemoryIndex.deleteBySession(organizationId, sessionId)` 用 `org_id`+`session_id` 一起做 `_delete_by_query` 过滤（与 `searchSessionHistory` 的过滤条件一致）；`ChatMessageRepository.deleteBySessionIdAndOrganizationIdAndMemberId(sessionId, orgId, memberId)` 方法签名层面强制三重归属，而非裸 `deleteBySessionId`。

**考虑过的替代方案**：只传 `sessionId`（反正 UUID 全局唯一，理论上不会撞库）。

**为什么坚持带租户维度**：延续本次 `/review` 评审门刚修复的"查询/删除都强制在方法签名层面携带租户过滤，不完全信任调用方已经做过校验"的约定（`MemoryItemStoreImpl`/`ChatMessageRepository` 的查询方法都是这个模式）。虽然 `getOwnedSession` 已经在 Service 层做过归属校验，但让 Repository/Index 层的删除方法本身也不依赖调用方纪律，是同一套纵深防御逻辑的延伸，成本几乎为零（多传两个已有变量）。

### 4. 前端用 localStorage 记录当前会话，而非路由参数

**决策**：`localStorage` key `rag-kb:last-session:{kbId}`，挂载/切 kb 时优先读取并调用 `GET .../messages` 恢复；读取失败（如会话已被删，404）时退回 `createSession()`。

**考虑过的替代方案**：把 `sessionId` 做成路由参数（如 `/kb/:kbId/session/:sessionId`），刷新时从 URL 恢复。

**为什么选 localStorage**：当前 `kbId` 本身就不是路由参数，而是 `kbStore.selectedKbId` 这个 store 状态驱动的（见 `KbWorkspaceView.vue`），引入 URL 级会话参数需要同时改造 kbId 的路由方式，改动面明显更大；localStorage 方案在不动现有路由结构的前提下就能满足"刷新回到原会话"的核心诉求。代价是不支持"分享某个具体对话链接"这类能力，但这不在本次 Goals 范围内。

## Risks / Trade-offs

- **[风险] 级联删除跨 4 个存储非原子操作，中途失败留下部分残留** → 缓解：删除顺序"先删衍生索引，最后删权威存储"，中途失败时 Postgres 记录仍在，用户可重试；即使残留 ES/Redis 孤儿数据，因为不再被任何检索路径引用（`org_id`+`session_id` 过滤），不会造成功能性错误或跨租户泄露，只是空间浪费
- **[风险] localStorage 记录的 sessionId 可能已失效（如在另一浏览器删除了该会话）** → 缓解：`GET messages` 404 时前端捕获并退回创建新会话，不阻断使用
- **[风险] 标题截取可能在多字节字符边界截断，或首条消息很短/全标点导致标题无意义** → 影响仅限展示层，不影响功能；后续如需要可换成按 UTF-16 code point 安全截断
- **[风险] `rag.memory.enabled=false` 时 `ConversationStore`/`MemoryIndex` bean 不存在，删除接口需要正确降级** → 缓解：复用现有 `ObjectProvider.getIfAvailable()` 判空模式，为空时只删 Postgres 行，与 `getMessages()` 的既有降级逻辑一致

## Migration Plan

1. Flyway `V013__add_chat_session_title.sql` 新增 `title` 字段（可空，无需回填历史数据）
2. 后端新增列表/删除接口与级联删除方法
3. 前端新增 `ChatHistorySidebar.vue`，`ChatPanel.vue` 接入 localStorage 恢复逻辑
4. 回滚策略：纯新增能力（除 `frontend-chat` 规格里"刷新重置"的行为描述变更外不涉及既有契约变更），如需回滚只需前端恢复到"每次刷新新建会话"的旧逻辑，后端新增的接口/字段可以保留不影响旧前端

## Open Questions

- 历史列表的展示上限（50 条）是否需要做成可配置项，留待实际使用后再评估
