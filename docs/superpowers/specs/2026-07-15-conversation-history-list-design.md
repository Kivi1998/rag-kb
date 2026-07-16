# 历史会话列表设计（conversation-history-list）

## 背景

`conversation-memory` 功能已合并到 main：后端有完整的会话生命周期（`chat_session` 表，Postgres）、消息长期存档（`chat_messages`，MongoDB）、用户画像（`memory_items`，MongoDB）与统一记忆索引（`rag_memory_v1`，Elasticsearch）。已有接口：

- `POST /api/v1/knowledge-bases/{kbId}/sessions` 创建会话
- `GET /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/messages` 查询单个会话消息

但前端 `ChatPanel.vue` 每次挂载（含 F5 刷新、切换知识库）都无条件创建新会话，不复用、不拉历史，导致"刷新就清空对话"。且完全没有"查看某知识库下所有历史会话"的能力。

用户明确要求做成类似 Claude Chat 的历史会话列表：可以在多个历史对话之间切换、F5 刷新后回到刚才的对话。

## Goals / Non-Goals

**Goals：**
- `GET .../sessions` 列表接口：返回当前成员在该知识库下最近活跃的会话（标题、最后活跃时间），按时间倒序
- 会话标题：首条用户消息前 N 字，写入时算好存库，不在查询时现算
- `DELETE .../sessions/{sessionId}`：硬删除，级联清理 Postgres/MongoDB/Redis/Elasticsearch 四处存储
- 前端在 `ChatPanel` 内新增可折叠历史侧边栏：列表展示、点击切换、新建对话按钮
- F5 刷新回到刷新前的同一个会话（不是总是新建）

**Non-Goals：**
- 不做分页（固定返回最近 N 条，当前规模下足够；接口设计不排斥未来加 cursor）
- 不做会话重命名
- 不用 LLM 生成标题（直接截取首条消息文本，零额外调用成本）
- 不影响 `memory_items` 用户画像（画像是 member 维度长期记忆，与具体会话生命周期无关，删除会话不删画像）
- 不做路由级 sessionId（不引入 `/kb/:kbId/session/:sessionId` 这类路由参数），用 localStorage 记录"每个 kb 最后活跃的 sessionId"即可满足"刷新回到原对话"的需求，不改动现有 `kbStore.selectedKbId` 驱动的选择方式

## 架构

### 后端

**1. `chat_session` 表新增 `title` 字段**（Flyway `V013__add_chat_session_title.sql`）
- 类型 `varchar(64)`，可空（新建会话还没消息时为空）
- 写入时机：`ConversationMemoryOrchestrator.recordTurn()` 里，若该会话当前 `title` 为空（说明这是本会话第一轮），把 `question` 截取前 30 个字符存入 `chat_session.title`
- 只在"当前为空"时写，避免每轮都重复截取覆盖

**2. `GET /api/v1/knowledge-bases/{kbId}/sessions`**
- `ChatSessionService.listSessions(kbId)`：`chatSessionRepository.findByOrgIdAndKbIdAndMemberIdOrderByLastActiveAtDesc(orgId, kbId, memberId, Pageable.ofSize(50))`
- 返回 DTO 列表：`{sessionId, title, lastActiveAt}`（不返回消息内容，内容按需单独查）
- `title` 为空时前端显示"新对话"占位符（后端不处理这个兜底文案，交给前端展示层）

**3. `DELETE /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}`**
- `ChatSessionService.deleteSession(kbId, sessionId)`：先 `getOwnedSession(kbId, sessionId)` 复用现有三重归属校验（越权/不存在均 404，不泄露信息）
- 级联删除顺序（参考现有 `MemoryCleanupTask` 的"先删索引再删权威存储"模式）：
  1. Elasticsearch：删除 `rag_memory_v1` 里 `org_id`+`session_id` 同时匹配的 SESSION_MESSAGE 条目（新增 `MemoryIndex.deleteBySession(organizationId, sessionId)` 方法，用 `_delete_by_query`，过滤条件与 `searchSessionHistory` 保持一致，不是裸 sessionId，延续本次 review 修复里"查询/删除都强制带租户维度"的约定）
  2. MongoDB：删除 `chat_messages` 里 `sessionId`+`organizationId`+`memberId` 同时匹配的全部文档（新增 `ChatMessageRepository.deleteBySessionIdAndOrganizationIdAndMemberId(sessionId, orgId, memberId)`，方法签名层面强制携带三重归属，而非裸 `deleteBySessionId`）
  3. Redis：删除滑动窗口 key `chat:session:{id}:messages`（新增 `ConversationStore.deleteSession(sessionId)`；Redis key 本身已经是全局唯一的 sessionId，不需要额外拼租户维度）
  4. Postgres：删除 `chat_session` 行（`getOwnedSession` 已经做过三重校验，这里直接删就是被校验过的那一行）
- 若 `rag.memory.enabled=false`（`ConversationStore`/`MemoryIndex` bean 不存在），只删 Postgres 行（`conversationStoreProvider.getIfAvailable()` 为空时跳过 1-3 步，与现有 `getMessages()` 的降级模式一致）

### 前端

**1. `ChatHistorySidebar.vue`（新组件，嵌在 `ChatPanel.vue` 内部）**
- 折叠/展开一个细长侧边栏（默认折叠，点击图标展开，类似 Claude 左上角历史图标）
- 展开时调用 `GET .../sessions`，列表按 `lastActiveAt` 倒序展示 `title || '新对话'`
- 每项可点击切换、可删除（hover 出现删除图标，点击调用 `DELETE .../sessions/{id}`，若删的是当前会话则自动新建一个）
- 顶部"新建对话"按钮：调用现有 `createSession()`，清空 `messages`，写入 localStorage

**2. `ChatPanel.vue` 改造**
- localStorage key：`rag-kb:last-session:{kbId}`
- 挂载/切换 kb 时：先读 localStorage 有没有该 kb 的 sessionId；有则调用 `GET .../messages` 拉历史、hydrate 进 `messages`，复用该 sessionId；没有或拉取失败（如会话已被删）则退回现有 `createNewSession()` 逻辑
- 每次成功切换到某个 sessionId（新建或从列表选择）都写入 localStorage
- 点击历史列表某一项：调用 `GET .../messages`、替换当前 `sessionId`/`messages`、写 localStorage

## 数据流

```
挂载/切kb → 读 localStorage 有 sessionId？
  ├─ 有 → GET messages 成功？
  │        ├─ 是 → hydrate messages，sessionReady=true
  │        └─ 否(如已删除/404) → 走"没有"分支
  └─ 没有 → createSession() → sessionReady=true，写 localStorage

点击历史列表项 → GET messages → 替换 messages/sessionId → 写 localStorage
点击"新建对话" → createSession() → 清空 messages → 写 localStorage
点击删除某一项 → DELETE session → 若删的是当前会话 → 触发"新建对话"逻辑
```

## 测试覆盖

- 后端：`ChatSessionServiceTest` 新增 `listSessions`/`deleteSession` 用例（含跨 kb/跨成员越权删除被拒、级联删除四处存储都被调用到）
- 后端：`RedisMongoConversationStoreTest`/`ElasticsearchMemoryIndexTest` 新增各自的 `deleteSession`/`deleteBySession` 用例
- 前端：`ChatPanel.test.ts` 新增"挂载时读到 localStorage sessionId 则拉历史而非新建会话"、"删除当前会话后自动新建"等用例
- 新增 `ChatHistorySidebar.test.ts`：列表渲染、切换、删除交互

## Risks / Trade-offs

- **[风险] 级联删除跨 4 个存储，非原子操作，中途失败会留下部分残留** → 缓解：删除顺序遵循"先删衍生索引（ES/Redis），最后删权威记录（Postgres）"，即使中途失败，用户下次访问该 sessionId 时 Postgres 里已找不到记录（会被当作不存在处理），残留的 ES/Redis 数据不会再被检索到，属于可接受的"孤儿数据"（后续可加清理任务，不影响功能正确性）
- **[风险] localStorage 记录的 sessionId 可能已被删除或过期** → 缓解：`GET messages` 404 时前端捕获并退回创建新会话，不阻断使用
- **[风险] 标题只在"首条消息且当前为空"时写入，若第一条消息很短或全是标点** → 影响很小，属于展示层瑕疵，不影响功能
