## 1. 基础设施准备

- [x] 1.1 新建 rag-kb 专属 Redis 开发容器（`rag-kb-dev-redis`），与 `thxpace-redis-local` 分开
- [x] 1.2 新建 MongoDB 开发容器，仅服务本子系统
- [x] 1.3 `.env` 新增会话记忆用的 Redis 连接配置（逻辑 DB 索引与现有 JWT 黑名单 DB 分开）与 MongoDB 连接配置
- [x] 1.4 现有 JWT 黑名单 `RedisService` 迁移到新建的 rag-kb 专属 Redis 实例（DB 0），不再使用 `thxpace-redis-local`
- [x] 1.5 `pom.xml` 新增 MongoDB 客户端依赖（Spring Data MongoDB）
- [x] 1.6 README 补充新增的 Redis/MongoDB 本地开发访问地址（跟随现有"本地开发环境访问地址"章节的格式）

## 2. 数据模型

- [x] 2.1 编写 Flyway `V012__add_chat_session.sql`，新增 `chat_session` 表（`org_id`/`kb_id`/`member_id`/`status`/`last_active_at`）
- [x] 2.2 新建 `ChatSession` JPA 实体，配置 Hibernate `tenantFilter`（比照现有 `Member` 实体模式）
- [x] 2.3 设计并创建 Elasticsearch `rag_memory_v1` 索引 mapping（`memory_id`/`org_id`/`member_id`/`session_id`/`memory_type`/`content`/`content_vector`/`created_at`）
- [x] 2.4 定义 MongoDB `chat_messages` 与 `memory_items` 集合的文档结构（Java POJO + Spring Data MongoDB repository）

## 3. 存储接口层

- [x] 3.1 定义 `ConversationStore` 接口（读/写 Redis 滑动窗口 + MongoDB `chat_messages`，写直达）
- [x] 3.2 实现 `RedisMongoConversationStore`
- [x] 3.3 定义 `MemoryItemStore` 接口（MongoDB `memory_items` + ES `rag_memory_v1` 读写、语义去重、读时衰减计算）
- [x] 3.4 实现 `MemoryItemStore` 具体类
- [x] 3.5 单元测试：`ConversationStore`/`MemoryItemStore` 用 fake/内嵌测试环境覆盖读写、TTL、去重逻辑

## 4. 短期记忆：滑动窗口与摘要压缩

- [x] 4.1 实现 token 预算估算工具（复用或参照现有 embedding/生成模块里的 token 计数方式）
- [x] 4.2 实现摘要压缩：超预算时调 LLM 生成摘要替换最旧消息，关键事实消息不参与压缩
- [x] 4.3 单元测试：预算内不触发摘要 / 超预算触发压缩 / 关键事实消息被保留原文

## 5. 短期记忆：语义相关历史检索

- [x] 5.1 实现按 `session_id` 过滤的 `rag_memory_v1` 向量检索（复用现有 ES kNN 查询模式，参照 `ElasticsearchHybridCandidateSource.searchKnn()`）
- [x] 5.2 单元测试：命中窗口外语义相关历史 / 无相关历史时不影响主流程

## 6. 指代消解

- [x] 6.1 定义 `CoreferenceResolver` 接口
- [x] 6.2 实现窄范围指代消解 prompt（严格限定只做指代消解、禁止改写技术术语），复用现有 DeepSeek 模型客户端
- [x] 6.3 实现失败/超时降级逻辑（回退用原始问题，记 warning）
- [x] 6.4 单元测试：成功补全指代 / 调用失败降级 / 无指代问题不被误改写（比照 `HybridRetrieverTest` 的 mock 风格）

## 7. 长期记忆：用户画像提炼与遗忘机制

- [x] 7.1 定义 `MemoryExtractor` 接口，实现异步画像提炼 prompt（输出类型 PREFERENCE/FACT/GOAL）
- [x] 7.2 实现语义去重逻辑（候选条目与已有条目相似度检索，超阈值合并/跳过）—— 已随 `MemoryItemStoreImpl` 完成
- [x] 7.3 实现读时衰减计算 `effective_importance = importance × decay(...)` —— 已随 `MemoryItemStoreImpl` 完成
- [x] 7.4 实现命中巩固逻辑（更新 `accessCount`/`lastAccessedAt`） —— 已随 `MemoryItemStoreImpl` 完成
- [x] 7.5 实现低优先级定期清理任务（物理删除长期低权重条目，不影响功能正确性）—— `MemoryCleanupTask`
- [x] 7.6 单元测试：新增画像条目 / 语义去重跳过 / 提炼失败不影响已返回回答 / 久未使用条目权重衰减 / 命中巩固

## 8. 用户画像注入生成阶段

- [x] 8.1 实现 `UserProfileInjector`，按 `member_id` 检索 top-K 画像条目组装 System 上下文
- [x] 8.2 确认 `HybridRetriever`/检索参数完全不受画像影响（仅在生成阶段拼接）—— `UserProfileInjector` 无任何检索依赖，天然满足
- [x] 8.3 单元测试：画像影响生成风格但不影响检索候选集与排序

## 9. 会话生命周期管理服务与 API

- [x] 9.1 实现 `ChatSessionService`（创建会话、状态机流转：ACTIVE/IDLE/ARCHIVED、续期逻辑）
- [x] 9.2 新增 `ChatSessionController`：`POST /api/v1/knowledge-bases/{kbId}/sessions`、`GET /api/v1/knowledge-bases/{kbId}/sessions/{sessionId}/messages`
- [x] 9.3 安全测试：跨组织/跨成员访问会话被拒（404，不泄露会话是否存在）—— `ChatSessionServiceTest` + 真实 curl 验证

## 10. 现有查询链路集成

- [x] 10.1 `QueryController.QueryRequest` 移除 `history`/`rewrite` 字段，新增必填 `sessionId` 校验
- [x] 10.2 `QueryService.prepare()` 编排新增步骤：取滑动窗口+语义历史 → 指代消解 → 现有 `HybridRetriever` 检索（保持不变）→ 画像注入生成 → 写直达持久化 → 异步触发画像提炼
- [x] 10.3 更新现有 `QueryServiceTest`/`QueryControllerTest`，覆盖 sessionId 缺失/无效场景
- [x] 10.4 安全测试：记忆相关数据读写全路径强制 `org_id`/`member_id` 校验（比照 `RagCoreContractTest` 风格）—— `ElasticsearchMemoryIndexTest` 新增
      `searchSessionHistoryDoesNotLeakOtherOrganizationsSession`/`searchProfileItemsDoesNotLeakOtherMembersProfileWithinSameOrganization`
      两个真正的跨租户负向用例（两租户各自造数据，验证互相查不到，而不只是断言请求体含过滤字段）；
      `MemoryItemStoreImplTest` 新增 `findSimilarExistingRejectsCrossTenantDocumentEvenIfEsMatched`/
      `topKForGenerationFiltersOutCrossTenantDocuments` 覆盖 MongoDB 层的二次租户校验；
      `RedisMongoConversationStoreTest` 新增 `archivedMessagesQueriesMongoWithMemberIdScope` 覆盖长期存档查询的 memberId 强制校验

## 11. 前端适配

- [x] 11.1 `ChatPanel.vue`（或对应 store）新增会话创建逻辑：进入知识库/新建对话时调用创建会话接口
- [x] 11.2 持有并在每次提问请求中携带 `sessionId`
- [x] 11.3 切换知识库时重新创建会话，不复用旧 `sessionId`

## 12. 端到端验证

- [x] 12.1 手动验证：连续多轮提问，指代性追问（"那它…"）能正确检索 —— 浏览器实测："它的收敛速度怎么样"正确解析为"RPCA算法"并检索到相关内容
- [x] 12.2 手动验证：Redis 不可达时的降级行为 —— 实测发现 JWT 黑名单与会话记忆共用同一个物理 Redis 实例（仅逻辑 DB 不同），整个容器宕机时两者都不可用是预期行为（fail-close 正确触发，未见异常放行）；"记忆功能单独故障、JWT黑名单仍可用"这个更细粒度的场景已在 `RedisMongoConversationStoreTest` 用 mock 异常验证过，真实环境无法在不影响黑名单的前提下单独打断某个逻辑 DB
- [x] 12.3 跑通完整 `mvn test`，确认无回归 —— 175/175 通过；前端 `pnpm test` 80/80 通过
- [x] 12.4 更新 README「文档入口」新增会话记忆相关代码入口；更新 `docs/architecture.md` 反映新增的 Redis/MongoDB 组件
