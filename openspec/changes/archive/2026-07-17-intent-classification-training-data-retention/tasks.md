## 1. 数据层

- [x] 1.1 新增 Flyway 迁移 `V0xx__add_intent_training_sample.sql`：建表
      `intent_training_sample`（`id`/`org_id`/`kb_id`/`member_id`/`question`/
      `predicted_intent`/`created_at`）+ `idx_intent_training_sample_org_created` 索引
      （文件号取当前 `db/migration/` 目录下最大值 +1）
- [x] 1.2 新增 JPA 实体 `IntentTrainingSample`（`@Entity`，`@Table(name =
      "intent_training_sample")`，`@Filter(name = "tenantFilter", condition = "org_id =
      :orgId")`，对齐 `KnowledgeDocument` 的既有写法）
- [x] 1.3 新增 `IntentTrainingSampleRepository extends JpaRepository<IntentTrainingSample, UUID>`

## 2. 配置与开关

- [x] 2.1 新增 `RagIntentTrainingDataProperties`（`@ConfigurationProperties(prefix =
      "rag.intent-training-data")`，字段 `enabled`，默认 `true`）
- [x] 2.2 `application.yml` 新增 `rag.intent-training-data.enabled:
      ${RAG_INTENT_TRAINING_DATA_ENABLED:true}`，紧邻 `rag.intent-classification` 配置块，
      注释里显式标注"默认开启，会存问题原文，非本项目一贯的默认关闭保守惯例"

## 3. 服务层

- [x] 3.1 新增 `IntentTrainingSampleService`：`record(orgId, kbId, memberId, question,
      predictedIntent)` 落库 + `recordSafely(...)` 包一层 try/catch，异常只记日志不抛出
      （对齐 `QueryAuditService.recordSafely` 的既有模式）
- [x] 3.2 Spring 装配：`IntentTrainingSampleService` bean 仅受
      `rag.intent-training-data.enabled=true` 门控（`@ConditionalOnProperty`），放进合适的
      `config/` 装配类

## 4. 接入现有问答链路

- [x] 4.1 `QueryController` 注入 `ObjectProvider<IntentTrainingSampleService>`
      （bean 不存在时 `getIfAvailable()` 返回 null，与既有 `rerankerProvider` 等模式一致）
- [x] 4.2 `QueryController.query()` 里 `queryService.prepare(...)` 成功返回后、启动 SSE 流
      之前，若 `prepared.audit().predictedIntent() != null` 且
      `intentTrainingSampleProvider.getIfAvailable() != null`，调用
      `recordSafely(prepared.organizationId(), prepared.knowledgeBaseId(),
      prepared.memberId(), prepared.resolvedQuestion(), prepared.audit().predictedIntent())`

## 5. 测试

- [x] 5.1 `IntentTrainingSampleServiceTest`：正常落库、异常 fail-safe 不抛出两个场景
- [x] 5.2 `QueryControllerTest`（或等价集成测试）：`predictedIntent` 非空时记录样本、为
      `null`（分类失败/未启用）时不记录、`rag.intent-training-data.enabled=false` 时不记录
- [x] 5.3 安全测试：验证 `IntentTrainingSampleRepository` 查询受 `tenantFilter` 约束，跨组织
      查询拿不到其他组织的问题原文（参照 `KnowledgeDocument` 现有的跨租户测试写法）
- [x] 5.4 回归：确认现有 `QueryControllerTest`/`QueryServiceTest`/`QueryAuditServiceTest`
      全部仍然通过，本次改动不触碰 `QueryService` 构造函数

## 6. 收尾

- [x] 6.1 更新 `TODOS.md`：把"意图分类训练数据留存"条目标记为已实现，指向本 change
- [x] 6.2 更新 `CHANGELOG.md`：显著标注"新增 `intent_training_sample` 表，默认开启，会存储
      问题原文"这一行为变化
- [x] 6.3 `/review` 代码评审，修复所有 CRITICAL/HIGH 发现
- [x] 6.4 提交 PR，合并后用 `openspec-archive-change` 归档本 change 并同步 delta spec
