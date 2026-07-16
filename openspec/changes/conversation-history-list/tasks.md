## 1. 数据模型

- [x] 1.1 新增 Flyway `V013__add_chat_session_title.sql`：`chat_session` 表新增可空 `title varchar(64)` 字段
- [x] 1.2 `ChatSession` 实体新增 `title` 字段与 getter/setter

## 2. 会话标题写入

- [x] 2.1 `ChatSessionService` 新增 `maybeSetTitle(sessionId, firstMessageContent)` 或在 `ConversationMemoryOrchestrator.recordTurn()` 里内联判断当前 `title` 为空时截取前 30 字符写入
- [x] 2.2 单元测试：首轮消息生成标题；非首轮不覆盖已有标题

## 3. 会话列表查询

- [x] 3.1 `ChatSessionRepository` 新增 `findByOrgIdAndKbIdAndMemberIdOrderByLastActiveAtDesc(orgId, kbId, memberId, Pageable)`
- [x] 3.2 `ChatSessionService` 新增 `listSessions(kbId)`，固定取最近 50 条，返回 `ChatSessionSummary` DTO（`sessionId`/`title`/`lastActiveAt`）
- [x] 3.3 `ChatSessionController` 新增 `GET /api/v1/knowledge-bases/{kbId}/sessions`
- [x] 3.4 安全测试：跨知识库/跨成员/跨组织的会话不出现在列表结果里

## 4. 会话级联删除

- [x] 4.1 `MemoryIndex` 新增 `deleteBySession(organizationId, sessionId)`，`ElasticsearchMemoryIndex` 用 `_delete_by_query` 实现，过滤条件与 `searchSessionHistory` 一致（`org_id`+`session_id`+`memory_type=SESSION_MESSAGE`）
- [x] 4.2 `ChatMessageRepository` 新增 `deleteBySessionIdAndOrganizationIdAndMemberId(sessionId, orgId, memberId)`
- [x] 4.3 `ConversationStore` 新增 `deleteSession(sessionId)`，`RedisMongoConversationStore` 实现：删 Redis 滑动窗口 key + 调用 `ChatMessageRepository` 的删除方法
- [x] 4.4 `ChatSessionService` 新增 `deleteSession(kbId, sessionId)`：先 `getOwnedSession` 校验归属（越权/不存在 404），再按 Elasticsearch → MongoDB/Redis → Postgres 顺序级联删除；`ConversationStore`/`MemoryIndex` 的 `ObjectProvider` 为空时（`rag.memory.enabled=false`）跳过前三步，只删 Postgres 行
- [x] 4.5 `ChatSessionController` 新增 `DELETE /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}`
- [x] 4.6 安全测试：删除他人/跨知识库会话被拒（404，不泄露存在性）；删除会话不影响该成员的 `memory_items` 画像条目；`rag.memory.enabled=false` 时仅删 Postgres 行

## 5. 前端：会话恢复

- [x] 5.1 `frontend/src/api/queryApi.ts` 新增 `listSessions(kbId, headers)`、`deleteSession(kbId, sessionId, headers)` 封装
- [x] 5.2 `ChatPanel.vue`：挂载/切 kb 时优先读取 localStorage（`rag-kb:last-session:{kbId}`）记录的 sessionId，调用 `GET .../messages` 恢复历史；404 或异常时退回现有 `createNewSession()` 逻辑
- [x] 5.3 每次成功切换到某个 sessionId（新建/恢复/从列表选择）都写入 localStorage
- [x] 5.4 更新 `ChatPanel.test.ts`：新增"localStorage 有记录时优先恢复历史而非新建"“恢复失败退回新建”用例

## 6. 前端：历史侧边栏

- [x] 6.1 新增 `ChatHistorySidebar.vue`：默认折叠，展开时调用 `listSessions` 渲染列表（`title || '新对话'`，按 `lastActiveAt` 倒序）
- [x] 6.2 列表项点击切换：调用 `GET .../messages`，替换当前 `messages`/`sessionId`，写 localStorage
- [x] 6.3 列表项 hover 展示删除按钮，点击调用 `deleteSession`；若删除的是当前会话，触发新建对话逻辑
- [x] 6.4 顶部"新建对话"按钮：调用现有创建会话逻辑，清空 `messages`，写 localStorage
- [x] 6.5 新增 `ChatHistorySidebar.test.ts`：列表渲染、切换、删除（含删除当前会话后自动新建）交互测试

## 7. 收尾

- [x] 7.1 `mvn test` 全绿
- [x] 7.2 前端 `pnpm test` 全绿
- [x] 7.3 更新 `README.md`/`docs/architecture.md` 补充本次新增的接口与前端交互
- [x] 7.4 `openspec validate conversation-history-list --strict` 通过
