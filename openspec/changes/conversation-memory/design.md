## Context

rag-kb 现状（详见 `docs/superpowers/specs/2026-07-15-conversation-memory-design.md`，本 change 由该设计文档 + brainstorming 澄清而来）：

- `QueryController.QueryRequest` 已有 `history`/`rewrite` 字段，但无任何代码消费，前端也不回传
- 无会话/消息持久化；`rag_query_audit` 只是审计日志，不参与生成
- `HybridRetriever` 拿用户原始 query 直接检索，指代性追问会检索失败
- 现有 Redis（`RedisService`）唯一职责是 JWT 黑名单（fail-close），实例是本机共享的 `thxpace-redis-local`（与其他项目共用）
- 现有存储：Postgres（业务数据，Hibernate `tenantFilter` 按 `org_id` 过滤）、Elasticsearch（`rag_chunks_v1`，chunk 文本+向量共存）

本 change 的驱动力是学习生产级多轮记忆架构、为未来用户规模增长预先建设能力——当前规模（单节点、日均 5000 次查询）不构成刚需，是有意识的提前建设。

## Goals / Non-Goals

**Goals:**
- 短期记忆：滑动窗口（最近几轮原文）+ 语义检索历史（跨窗口捞语义相关旧轮次）+ token 预算触发的摘要压缩（非固定轮数硬截断）
- 长期记忆：用户画像（偏好/事实/长期目标三类），每轮增量提炼，语义去重，只影响生成阶段 System 上下文，不影响检索
- 指代消解：窄范围 LLM 调用，仅解决代词/省略指代，明确禁止改写技术术语/错误码/专有名词；失败/超时降级用原始问题，不阻断主流程
- 遗忘机制：基于访问频率与时间戳的读时权重衰减，不需要定时批处理任务
- 存储：Redis（rag-kb 专属新实例）+ MongoDB（新引入，仅服务本能力）+ Elasticsearch（复用现有集群，新索引）三层组合，学习该架构的同时保持与现有系统清晰隔离

**Non-Goals:**
- 不做画像影响检索参数（只影响生成）
- 不搭真实多节点 Redis Cluster（先单节点，代码走标准 API，不绑死单机形态）
- 不做定时批处理衰减任务（用读时计算代替）
- 不引入 LangChain/LlamaIndex 等编排框架（CLAUDE.md 硬性规定）；指代消解/摘要压缩/画像提炼全部自研 prompt + 现有 DeepSeek 模型客户端
- 不改动现有 Postgres 业务表（`document`/`knowledge_base` 等）、不改动 `rag_chunks_v1` 索引与 `HybridRetriever` 内部检索/重排逻辑
- 不做历史会话列表 UI 的完整交互设计（只提供 `GET .../messages` 接口，前端消费方式留待后续迭代）

## Decisions

### 1. 存储技术选型：Redis + MongoDB + Elasticsearch 三层，而非全部复用 Postgres

**决策**：短期热路径用 Redis，长期持久化用 MongoDB，语义检索复用 Elasticsearch（新索引），会话生命周期元数据例外放 Postgres。

**考虑过的替代方案**：全部用 Postgres 一张表解决（更省运维成本，在当前 5000 次/日的规模下完全够用）。

**为什么还是选三层组合**：本 change 的明确目标是学习生产级记忆架构、为未来规模预先建设，用户已确认这是主动选择而非当前刚需驱动。三层组合能体现真实生产系统里"热路径/持久层/语义层"分离的设计经验，具备教学和扩容准备的价值。若后续因维护成本反悔，回退到纯 Postgres 方案的改动面是可控的（`ConversationStore`/`MemoryItemStore` 定义为接口，替换实现不影响调用方）。

### 2. Redis 部署：新建 rag-kb 专属实例，逻辑 DB 与 JWT 黑名单隔离

**决策**：新建 `rag-kb-dev-redis` 容器，与用作 JWT 黑名单、且与其他项目共享的 `thxpace-redis-local` 完全分开；同一实例内用不同逻辑 DB 索引区分黑名单（DB 0）和会话记忆（DB 1）。

**考虑过的替代方案**：直接复用现有 `thxpace-redis-local`（零新增基础设施）。

**为什么不这么做**：JWT 黑名单是 fail-close（不可用则拒绝所有请求），会话记忆是 fail-open（不可用则优雅降级）。两者共用一个物理实例时，若会话记忆功能因 bug 导致写入量暴涨触发 `maxmemory` 淘汰策略，可能连带淘汰黑名单 key，造成"已登出 token 又能用"的安全问题。且 `thxpace-redis-local` 本身是共享给不相关项目的基础设施，不应让 rag-kb 的新功能进一步耦合别的项目。新建专属实例后用逻辑 DB 分隔，兼顾隔离性和部署简洁性（不需要两个容器）。

### 3. 语义检索：短期会话历史与长期用户画像统一成同一套向量检索实现

**决策**：新建单一 Elasticsearch 索引 `rag_memory_v1`，通过 `memory_type`（SESSION_MESSAGE/PROFILE_ITEM）+ 过滤条件（`session_id` 或 `member_id`）区分短期/长期两种用途，而非各自实现一套独立的向量检索。

**考虑过的替代方案**：短期语义检索历史和长期画像检索各自独立实现（逻辑分离更清晰）。

**为什么统一**：两者本质是同一件事——"拿当前问题的向量，去检索一批过去内容，按语义相似度排序取 top-K"，区别只是检索范围（当前会话 vs 该用户全部历史）。统一实现减少重复代码，且与"长期记忆本质就是一次 RAG，只是语料是用户的过去"这一设计原则一致。

### 4. 持久化策略：写直达（write-through），而非写后台（write-behind）

**决策**：每轮对话的消息同步写入 Redis（热路径）与 MongoDB（持久化），两者都成功才算这轮写入完成。

**考虑过的替代方案**：写后台——先只写 Redis，会话进入 IDLE 或定时任务触发时才批量落盘 MongoDB，写入延迟更低。

**为什么选写直达**：写后台在进程崩溃、Redis 未开 AOF 持久化的情况下，ACTIVE 状态尚未落盘的对话会永久丢失；写直达牺牲的性能开销在当前规模（日均 5000 次查询）下完全可以忽略，且实现更简单——不需要处理"IDLE 触发批量落盘"的额外状态转换逻辑，会话从 IDLE 恢复到 ARCHIVED 时数据已经全部在持久层里，不需要专门的"重建"步骤。

### 5. 遗忘机制：读时计算权重衰减，而非定时批处理任务

**决策**：`memory_items` 的有效重要度 `effective_importance = importance × decay(now - lastAccessedAt)` 在每次检索时实时计算；条目被检索命中时更新 `accessCount`/`lastAccessedAt`（巩固）；物理删除做成低优先级的定期清理任务，不影响功能正确性。

**考虑过的替代方案**：定时批处理任务定期重算所有画像条目的权重并物理淘汰（更接近材料描述的"艾宾浩斯遗忘曲线"字面实现）。

**为什么选读时计算**：读时计算不需要额外的调度基础设施（无需引入或复用任务调度框架），衰减效果和定时批处理在检索结果上完全等价（只是权重更新的时机不同：读时算 vs 定时批量算），复杂度更低。物理删除仍保留一个低优先级定时任务，但它只影响存储空间，不影响功能行为，即使这个清理任务从未运行，检索结果依然正确（低权重条目自然排不进 top-K）。

### 6. 用户画像作用范围：只影响生成阶段的 System 上下文，不影响检索参数

**决策**：画像条目通过语义检索取出后，只拼进生成阶段的 System Prompt，不用来调整 `HybridRetriever` 的检索参数（如 `documentIds` 过滤、RRF 权重等）。

**考虑过的替代方案**：画像同时影响检索（比如已知某用户常问后端相关问题，自动收窄检索范围或调整召回权重）。

**为什么只做生成侧**：影响检索需要额外设计"画像内容如何映射到检索参数"的规则，复杂度和不确定性都更高（可能引入难以调试的"因为画像误导致检索范围收窄导致漏检"这类隐藏 bug）；只影响生成侧风险可控——画像判断错了，最多是回答风格不够贴合，不会造成检索质量的隐性下降。

## Risks / Trade-offs

- **[风险] 新增两个数据库技术栈（Redis 新实例 + MongoDB）带来运维负担** → 缓解：严格限定 MongoDB 只服务本能力（不迁移任何现有 Postgres 业务表），`ConversationStore`/`MemoryItemStore` 接口化，未来若判断维护成本不划算，可以在不影响调用方的前提下换回纯 Postgres 实现
- **[风险] 写直达策略下，每轮对话多两次同步写入（Redis+Mongo），增加请求延迟** → 缓解：当前规模下这个开销可忽略；`MemoryExtractor` 画像提炼保持异步，不在关键路径上增加延迟
- **[风险] 指代消解/画像提炼都是额外的 LLM 调用，增加成本和延迟** → 缓解：指代消解仅在 `history` 非空时触发，且失败降级不阻断；画像提炼完全异步，不影响用户感知延迟
- **[风险] 用户画像提炼可能产生不准确或过时的偏好判断，影响回答风格** → 缓解：遗忘机制保证过时画像自然衰减；画像只影响生成风格不影响检索正确性，即使误判也不会导致检索质量下降
- **[风险] 跨租户数据泄露——会话/画像数据必须严格按 org_id/member_id 隔离** → 缓解：`chat_session` 复用现有 Hibernate `tenantFilter` 机制；MongoDB/ES 侧的查询在应用层强制携带 `org_id`/`member_id` 过滤，比照现有 `ElasticsearchHybridCandidateSource.tenantFilters()` 的强制过滤模式，配套安全测试覆盖跨租户访问被拒场景

## Migration Plan

1. Flyway V012 新增 `chat_session` 表
2. 新建 `rag-kb-dev-redis`、MongoDB 本地开发容器；`.env` 新增对应连接配置
3. Elasticsearch 新增 `rag_memory_v1` 索引 mapping（不影响 `rag_chunks_v1`）
4. 后端新增 `ragcore/conversation/` 包下的接口与实现，`service/ChatSessionService.java`、`controller/ChatSessionController.java`
5. `QueryController.QueryRequest` 移除 `history`/`rewrite`，新增必填 `sessionId`（**BREAKING**，需要前端配合发布）
6. 前端 `ChatPanel.vue` 适配：进入知识库/新建对话时调用创建会话接口，持有 `sessionId`
7. 回滚策略：本 change 是纯新增能力（除 `QueryRequest` 契约变更外），如需回滚，`QueryController` 恢复兼容旧契约（`sessionId` 改为可选，为空则退化为无记忆单轮问答）即可快速止血，不需要回滚数据库结构

## Open Questions

- 摘要压缩、指代消解、画像提炼三处 LLM 调用的具体 prompt 措辞留待实现阶段迭代验证，本设计不锁定具体文案
- token 预算（默认 1000）、衰减半衰期（默认 30 天）等具体数值留待实现后用真实使用数据调优，当前值为合理初始估计
