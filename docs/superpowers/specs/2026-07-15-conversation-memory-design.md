# 多轮对话与记忆管理（conversation-memory）设计文档

日期：2026-07-15

## 背景与目标

rag-kb 目前是完全无状态的单轮问答系统：`QueryController.QueryRequest` 里的 `history`/`rewrite` 字段是预留空壳，无任何代码消费；没有会话/消息持久化；`HybridRetriever` 拿用户原始 query 直接检索，遇到"那它过了还能退吗"这类指代性追问会检索失败。

本 change 的目标是学习生产级多轮记忆架构，并为未来用户规模增长预先建设能力（当前 rag-kb 规模——单节点、日均 5000 次查询——其实还用不到这套复杂度，是有意识地提前建设，不是当前刚需驱动）。

### 目标

- 短期记忆：会话内 Selective Context 组合——滑动窗口（最近几轮原文）+ 语义检索历史（跨窗口捞语义相关的旧轮次）+ token 预算触发的摘要压缩（非固定轮数硬截断）
- 长期记忆：跨会话的用户画像（偏好/事实/长期目标三类，来自历次对话的增量提炼），只影响生成阶段的 System 上下文，不影响检索
- 指代消解：检索前用窄范围 LLM 调用把"它/这个"补全成独立问题，失败降级用原始问题
- 遗忘机制：基于访问频率/时间戳的画像条目重要度衰减，读时计算，不需要定时衰减任务
- 存储采用 Redis（新建 rag-kb 专属实例）+ MongoDB（新建，只管本子系统）+ Elasticsearch（复用现有集群）三层组合

### 非目标

- 不做画像影响检索参数（只影响生成，已与用户确认）
- 不搭真实多节点 Redis Cluster（先单节点，代码走标准 API 不绑死单机形态）
- 不做定时批处理衰减任务（用读时计算代替）
- 不引入 LangChain/LlamaIndex 等编排框架（CLAUDE.md 硬性规定），指代消解/摘要压缩/画像提炼全部自研 prompt + 现有模型客户端
- 不改动现有 Postgres 业务表（document/knowledge_base 等）；消息内容和画像条目本身完全隔离在 Redis/MongoDB/ES 里，不进 Postgres——但会话生命周期的元数据（`sessionId`/状态/归属租户）例外，见下文数据模型说明

---

## 架构总览

```
用户提问（携带 sessionId，首次为空）
  ↓
ConversationService（新）── 读/写 Redis(热路径) + MongoDB(持久化，写直达)
  ↓ 取最近N轮(token预算) + 语义相关历史(ES统一记忆索引 rag_memory_v1，session_id过滤)
CoreferenceResolver（新，窄范围LLM调用，只做指代消解）── 失败/超时退回原始问题
  ↓ resolvedQuestion
HybridRetriever（现有，完全不改动）── 检索知识库chunk
  ↓
UserProfileInjector（新）── 从 rag_memory_v1(member_id过滤，语义检索) 取相关画像条目
  ↓ 拼进 System Prompt，只影响生成风格
AnswerGenerator（现有，只加一段System上下文）── 生成回答
  ↓
异步：MemoryExtractor（新）── 从这轮问答提炼偏好/事实/目标，语义去重后写 MongoDB + ES
```

### 存储角色分工

| 存储 | 角色 | 内容 |
|---|---|---|
| Redis（新建 `rag-kb-dev-redis`，与 `thxpace-redis-local` 彻底分开） | ACTIVE 会话热路径 | 滑动窗口原始消息；逻辑 DB 索引与 JWT 黑名单分开（黑名单 DB 0，会话记忆 DB 1），避免记忆功能的内存压力波及 fail-close 的黑名单查询 |
| MongoDB（新建，只管本子系统） | 持久化系统记录 | `chat_messages`（长期存档，写直达）、`memory_items`（画像条目，含 importance/access_count/last_accessed_at） |
| Elasticsearch（复用现有集群，新索引 `rag_memory_v1`） | 语义检索层 | 短期会话内语义相关历史 + 长期跨会话画像检索，统一成同一套向量检索实现，只是过滤条件不同（`session_id` vs `member_id`） |
| Postgres（不变） | 现有业务数据 | 不受影响 |

---

## 数据流：一轮对话的完整步骤

1. 前端带 `sessionId`（为空则服务端新建会话）+ 问题发起请求
2. `ConversationService` 从 Redis 取该 session 最近消息，按 token 预算圈定窗口（默认预算 1000 token）；超预算时不直接丢弃最旧消息，而是调 LLM 生成摘要替换掉最旧的部分；标记为"关键事实"的消息（见下文）优先保留原文，不参与压缩
3. 同时用当前问题向量化后查 `rag_memory_v1`：
   - 过滤 `session_id` → 语义相关的历史轮次（哪怕在滑动窗口之外）
   - 过滤 `member_id`（不限 session）→ 该用户的画像条目，按 `effective_importance` 排序取 top-K
4. 滑动窗口原文 + 语义相关历史一起喂给 `CoreferenceResolver`：prompt 严格限定"只做指代消解，补全成独立完整的问题，禁止改写技术术语/错误码/专有名词"，输出 `resolvedQuestion`；调用失败或超时，直接用原始问题兜底，记 warning，不阻断主流程
5. `resolvedQuestion` 送入现有 `HybridRetriever`（BM25+kNN+RRF+Rerank，完全不改动）
6. 步骤3查到的画像条目整理成一段 System 上下文，跟检索到的 chunk 一起送进 `AnswerGenerator`；**只影响生成，不影响检索**
7. 生成完成后：
   - 同步写直达：Redis（滑动窗口追加）+ MongoDB `chat_messages`（长期存档），两者都成功才算这轮写入完成
   - 异步：`MemoryExtractor` 调 LLM 从这轮问答提炼候选画像条目（类型：PREFERENCE/FACT/GOAL），对每条候选先在该用户已有画像里做语义相似度检索，相似度过高则合并/跳过（去重），否则新增，同步写 MongoDB `memory_items` + `rag_memory_v1`

---

## 会话生命周期

```
CREATED → ACTIVE(30分钟无新消息) → IDLE(2小时无新消息) → ARCHIVED
             ↑____________________________|
                    有新消息就续期回 ACTIVE
```

- **ACTIVE**：原始消息全量驻留 Redis，支持随机读写；同时已经写直达在 MongoDB
- **IDLE**：触发一次摘要生成（如果还没因为 token 预算触发过），Redis 滑动窗口 key 让 TTL 自然过期，不需要额外落盘动作（写直达策略下数据从一开始就在 MongoDB）
- **ARCHIVED**：纯状态标记，恢复时直接从 MongoDB 按 `session_id` 查历史消息、读摘要字段，不需要专门的"重建"逻辑

---

## 数据模型

### MongoDB `chat_messages`

```json
{
  "_id": "ObjectId",
  "sessionId": "uuid字符串",
  "orgId": "uuid字符串",
  "kbId": "uuid字符串",
  "memberId": "uuid字符串",
  "role": "user | assistant",
  "content": "string",
  "isKeyFact": false,
  "createdAt": "ISODate"
}
```

### MongoDB `memory_items`

```json
{
  "_id": "ObjectId",
  "memberId": "uuid字符串",
  "orgId": "uuid字符串",
  "type": "PREFERENCE | FACT | GOAL",
  "content": "string（提炼后的自然语言描述）",
  "importance": 0.0,
  "accessCount": 0,
  "lastAccessedAt": "ISODate",
  "createdAt": "ISODate",
  "sourceSessionId": "uuid字符串（首次提炼来源，供追溯）"
}
```

### Elasticsearch `rag_memory_v1`

```json
{
  "memory_id": "keyword（对应 MongoDB _id）",
  "org_id": "keyword",
  "member_id": "keyword",
  "session_id": "keyword，可为空（画像条目跨session，为空）",
  "memory_type": "SESSION_MESSAGE | PROFILE_ITEM",
  "content": "text",
  "content_vector": "dense_vector",
  "created_at": "date"
}
```

### Redis Key 结构（DB 1，与 JWT 黑名单 DB 0 分开）

```
chat:session:{sessionId}:messages → List（滑动窗口原始消息，JSON 序列化）
chat:session:{sessionId}:summary  → String（触发压缩后的摘要，可为空）
```

### Postgres（不新增表，会话元数据存哪由 API 设计决定）

会话创建/状态机所需的最小元数据（`sessionId`/`orgId`/`kbId`/`memberId`/`status`/`lastActiveAt`）需要一个查询入口——考虑到多租户过滤要复用现有 Hibernate `tenantFilter` 机制，这部分放 Postgres 新表 `chat_session` 更省事（一次 Flyway 迁移），MongoDB 只管消息内容和画像条目本身。

---

## 遗忘机制实现

- `memory_items.importance` 由 `MemoryExtractor` 提炼时的 LLM 判断初始值（明确的长期目标给高分，随口提及的小事实给低分）
- 衰减用读时计算：`effective_importance = importance × decay(now - lastAccessedAt)`，`decay` 用简单指数衰减函数，半衰期作为可调参数（默认 30 天）
- 画像条目被检索命中并实际注入 prompt 时，更新 `accessCount+1`、`lastAccessedAt=now`（巩固）
- 检索画像按 `effective_importance` 排序取 top-K，久不用又不重要的自然排不进 top-K，等效"被遗忘"，不需要真删除数据
- 物理删除做成低优先级定期清理任务（如每天一次），删掉 `effective_importance` 长期低于阈值的条目，纯粹是空间优化，不影响功能正确性

---

## API 契约改动

新增：
- `POST /api/v1/knowledge-bases/{kbId}/sessions` — 创建会话，返回 `sessionId`
- `GET /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/messages` — 查历史消息（供前端展示/未来历史会话列表）

改动：
- `QueryController.QueryRequest` 删除 `history`/`rewrite` 死字段，改为必须携带 `sessionId`

---

## 新增文件（预估）

| 文件/包 | 职责 |
|---|---|
| `ragcore/conversation/ConversationStore.java`（接口） | Redis+MongoDB 读写抽象，模仿现有 `ObjectStorage` 接口风格 |
| `ragcore/conversation/impl/RedisMongoConversationStore.java` | 具体实现 |
| `ragcore/conversation/CoreferenceResolver.java`（接口）+ 实现 | 指代消解 LLM 调用 |
| `ragcore/conversation/MemoryItemStore.java`（接口）+ 实现 | MongoDB+ES 画像存取，含语义去重、衰减计算 |
| `ragcore/conversation/MemoryExtractor.java`（接口）+ 实现 | 从问答对提炼候选画像条目 |
| `ragcore/conversation/UserProfileInjector.java` | 组装 System 上下文 |
| `service/ChatSessionService.java` | 会话生命周期管理（Postgres `chat_session` 表 CRUD + 状态机） |
| `controller/ChatSessionController.java` | 新增两个会话接口 |
| `backend/src/main/resources/db/migration/V012__add_chat_session.sql` | 新增 `chat_session` 表 |

---

## 错误处理与降级

| 场景 | 行为 |
|---|---|
| Redis 不可达（会话记忆） | fail-open：跳过滑动窗口注入，退化成无历史的单轮问答，记 warning；**不同于** JWT 黑名单场景的 fail-close，两者必须分开测试验证 |
| MongoDB 写入失败 | 本轮问答仍正常返回给用户（生成不依赖 Mongo 写入是否成功），但要记 error 日志并告警，因为这意味着这轮对话没有被持久化 |
| CoreferenceResolver 调用失败/超时 | 直接使用原始问题检索，不阻断主流程 |
| MemoryExtractor 调用失败 | 静默失败（这轮问答不产生新画像条目），不影响用户已收到的回答 |
| ES `rag_memory_v1` 不可达 | 语义相关历史/画像检索为空，只依赖滑动窗口原文，不阻断主流程 |

---

## 测试覆盖（预估）

| 测试用例 | 验证点 |
|---|---|
| 滑动窗口 token 预算触发摘要压缩 | 超预算时最旧消息被摘要替换而非硬截断，关键事实消息不参与压缩 |
| 指代消解成功 | "那它过了还能退吗" + 历史"重疾险" → 补全为独立问题，检索命中 |
| 指代消解失败降级 | LLM 调用异常时，检索仍用原始问题完成，不抛出异常给用户 |
| 画像条目语义去重 | 提炼出的新候选条目与已有条目高相似度时不重复插入 |
| 遗忘机制读时衰减 | 久未访问的条目 `effective_importance` 低于阈值，不出现在 top-K 结果里 |
| Redis 不可达降级 | 会话记忆功能优雅降级为无历史单轮问答；同一场景下 JWT 黑名单查询仍正确 fail-close（验证两套降级策略互不影响） |
| 跨租户隔离 | 会话/画像查询严格按 `org_id`/`member_id` 过滤，跨租户不可见 |
