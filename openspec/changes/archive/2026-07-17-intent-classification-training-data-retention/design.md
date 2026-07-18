## Context

PR#25（`ragcore/intent/`）已经实现 LLM Prompt 查询意图分类：`QueryService.prepare()` 在指代
消解之后、检索之前，调用 `QueryIntentClassifier.classify(resolvedQuestion)` 得到
`QueryIntent`（`PRECISE_LOOKUP`/`SEMANTIC`/`COMPARATIVE`/`OUT_OF_SCOPE`/`UNKNOWN`），并把结果
写进 `PreparedQuery.audit().predictedIntent()`（四个标签字面量之一，或分类失败/未启用时为
`null`）。`rag_query_audit` 表按既有安全约定"不得出现问题、模型回答、Prompt、文档片段"，只落了
这个标签，没有落问题原文，攒不出可训练的「文本+标签」数据集。

本设计新增一张独立表，专门积累这类数据，目标是未来训练 BERT 分类器替换现在的 LLM 零样本分类
（降低每次查询的分类延迟/成本）。以下关键参数已在 brainstorming 阶段由用户明确决定，本设计不
重新讨论：不做自动清理（人工删除）、不做脱敏（原样存问题原文）、全局开关而非按组织可选、默认
**开启**。

## Goals / Non-Goals

**Goals:**
- 积累「问题原文 + 预测意图标签」样本，供未来训练 BERT 使用。
- 复用已有分类调用结果，不新增 LLM 调用、不影响现有分类逻辑。
- 与现有多租户隔离约定一致（`org_id` + Hibernate `tenantFilter`），即使本次不新增查询该表的
  API，也要让表结构本身在架构上不留下"忘了加隔离"的隐患。
- 写入失败不得影响问答主流程（`recordSafely` 式 fail-safe，对齐 `QueryAuditService` 的既有模式）。

**Non-Goals（同 proposal.md，重申）:**
- 不做自动清理/保留期强制执行、不做脱敏、不做按组织可选开关、不做数据导出功能、不训练模型本身。

## Decisions

### 1. 写入触发点：`QueryController.query()`，`prepare()` 成功后立即写，不等生成完成

**决策**：在 `QueryController.query()`（`prepare()` 调用之后、启动 SSE 流之前）同步调用
`intentTrainingSampleService.recordSafely(...)`，而不是像 `rag_query_audit` 那样等
`writeStream()` 里生成完成才落库。

**理由**：训练样本关心的是"这句问题该分到哪类意图"，跟这次生成有没有拒答、有没有报错无关——
一个被 `MIN_RERANK_SCORE` 拒答的查询，它的意图标签依然是有效的训练信号。挂在生成完成之后反而
会因为生成阶段失败/客户端断开丢失本该记录的样本。`predictedIntent` 在 `prepare()` 返回时已经
固化在 `PreparedQuery.audit()` 里，不需要等生成阶段的任何信息。

**备选方案**：挂在 `QueryService.prepare()` 内部（分类完成后立即写）。放弃原因：`QueryService`
目前不持有任何 Repository/持久化依赖（`rag_query_audit` 的实际落库也是在 Controller 层的
`QueryAuditService`，`QueryService` 只构造不可变的 `QueryAuditSnapshot`），把持久化放进
`QueryController` 保持这个既有分层不变，也避免了给 `QueryService` 构造函数再加一个参数
（本次改动要新增的话，`QueryServiceTest.java` 里全部 10 处 `new QueryService(...)` 调用点
都要跟着改，纯属维护负担，且没有必要——`QueryController` 已经拿得到写这条记录所需的一切）。

### 2. 只在 `predictedIntent != null` 时写入

**决策**：`prepared.audit().predictedIntent()` 为 `null`（分类失败/`rag.intent-classification`
未启用/`COMPARATIVE`——等等，`COMPARATIVE`/`OUT_OF_SCOPE` 也会有非空标签，只有 `UNKNOWN` 映射
成 `null`）时不写入训练样本表。

**理由**：没有有效标签的样本对训练没有意义，写入只会白占存储和查询开销。

### 3. 新表结构与租户隔离

```sql
CREATE TABLE intent_training_sample (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID NOT NULL,
    kb_id          UUID NOT NULL,
    member_id      UUID NOT NULL,
    question       TEXT NOT NULL,
    predicted_intent VARCHAR(32) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_intent_training_sample_org_created ON intent_training_sample (org_id, created_at);
```

`IntentTrainingSample`（JPA `@Entity`）加 `@Filter(name = "tenantFilter", condition = "org_id =
:orgId")`，对齐 `KnowledgeDocument`/`KnowledgeBase` 等既有租户隔离约定——即使本次不新增任何
读取这张表的 API（读取/导出是后续独立待办），表结构和实体层面的隔离能力必须从一开始就到位，
不能等到"以后要读的时候"再补，那时候历史数据已经缺了这层保护。

`idx_intent_training_sample_org_created` 复合索引：为后续（不在本次范围）按组织+时间窗导出
训练数据做准备，写多读少场景下索引维护成本可忽略。

### 4. `IntentTrainingSampleService`：独立的 fail-safe 写入服务

对齐 `QueryAuditService.recordSafely()` 的既有模式：

```java
public class IntentTrainingSampleService {
    public void recordSafely(UUID orgId, UUID kbId, UUID memberId, String question, String predictedIntent) {
        try {
            record(orgId, kbId, memberId, question, predictedIntent);
        } catch (RuntimeException ex) {
            log.error("意图训练样本落库失败 orgId={} errorType={}", orgId, ex.getClass().getSimpleName());
        }
    }
    ...
}
```

写入失败只记日志，不抛出、不影响 SSE 响应——这张表是"锦上添花"的数据积累，不是问答主流程的
必需环节。

### 5. 功能开关：`rag.intent-training-data.enabled`，独立 bean，默认开启

新增 `RagIntentTrainingDataProperties`（`@ConfigurationProperties(prefix =
"rag.intent-training-data")`，字段 `enabled`，默认 `true`——用户已明确决定，与
`rag.nli.enabled`/`rag.intent-classification.enabled` 默认关闭的既有保守惯例不同，这是本次
特意的例外，不是疏漏）。`IntentTrainingSampleService` bean 只受这一个开关门控，不强制要求
`rag.intent-classification.enabled=true` 同时开启——两者独立时，训练样本服务会因为
`predictedIntent` 恒为 `null`（见决策 2）而自然变成空写入，不算错误状态，不需要额外校验。

## Risks / Trade-offs

- **[风险] 默认开启，意味着任何同时打开 `rag.intent-classification.enabled` 的部署，一升级
  就会开始把真实用户问题原文写进新表，没有显式的"我知道我在存什么"确认步骤** → **缓解**：
  在 `CHANGELOG.md`/发版说明里显著标注这一行为变化，让运维/管理员在升级前就知情，而不是事后
  才发现库里多了一张存明文问题的表。这是用户在 brainstorming 阶段权衡后的明确选择（相比"默认
  关闭"更快积累到有用的数据量），本设计只负责把这个风险显式记录下来，不代为收窄范围。
- **[风险] 不脱敏 + 不自动清理，问题原文可能包含业务敏感内容且无限期留存** → **缓解**：
  已有 `tenantFilter` 隔离 + 本次不提供任何跨表/跨用户的读取或导出 API，攻击面仅限于"能直接
  连数据库"的场景（等同于能直接读 `document`/`chat_message` 等本来就存业务正文的表），风险
  级别与既有数据面持平，不是新增的攻击面类别。人工清理依赖运维流程之外的纪律，不在代码层面
  强制。
- **[权衡] 不做脱敏换来更高的训练数据质量** → 后续如果真的用这批数据训练 BERT 且发现脱敏
  是必需的（如需要把训练集分享给第三方标注），需要另开一个 change 补脱敏，且历史数据需要
  单独批处理脱敏或直接不用于分享。

## Migration Plan

1. Flyway 迁移新增 `intent_training_sample` 表（不改动任何既有表）。
2. 部署新版本后，`rag.intent-training-data.enabled` 默认开启即生效——无需额外部署步骤，但
   见上方风险项，建议先在发版说明里知会。
3. 回滚：新表只有写入路径、没有其他代码依赖它，直接回退代码版本即可；表本身可以留着不删（数据
   不会因为代码回滚而失效），或按需手工 `DROP TABLE`。

## Open Questions

无——本次范围内的关键决策（保留期、脱敏、开关粒度、默认状态）均已在 brainstorming 阶段由用户
逐项确认，design 阶段新增的技术决策（写入触发点、表结构、服务分层）见上方"Decisions"。
