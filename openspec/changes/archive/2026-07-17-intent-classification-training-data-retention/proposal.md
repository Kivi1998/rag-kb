## Why

PR#25 上线的 LLM Prompt 查询意图分类（`ragcore/intent/`）用户原始诉求是"线上攒够真实 query 和标注，
再训一个 BERT 分类器替换"，但 `rag_query_audit` 按安全约定不能存问题原文，只加了 `predicted_intent`
标签字段，攒不出可训练的「文本+标签」数据集。这次要把这个此前明确搁置的独立合规决策落地：新建
一张专用表，真正积累训练数据。

## What Changes

- 新增独立表 `intent_training_sample`，字段：`id`、`org_id`、`kb_id`、`member_id`、`question`
  （问题原文，明文，不脱敏——用户已确认原样存以保证训练数据质量）、`predicted_intent`、
  `created_at`。**不设自动清理任务**（用户已确认：不自动清理，需要清理时人工执行 SQL 删除）。
- `QueryService.prepare()` 在分类完成后，异步/同步写入一条样本记录（复用已有分类调用结果，不
  新增 LLM 调用）。
- 新增全局功能开关 `rag.intent-training-data.enabled`（默认 **开启**——用户已确认，与
  `rag.nli.enabled`/`rag.intent-classification.enabled` 等既有开关默认关闭的保守惯例不同，
  这是本次用户的明确选择）。写入前提：`rag.intent-classification.enabled=true`（没有分类结果
  就没有样本可写）。
- 沿用现有多租户隔离约定（Hibernate `tenantFilter` 按 `org_id` 过滤），本表存问题原文，安全
  敏感度高于 `rag_query_audit`，需要在实现阶段确认访问路径（有没有现成的通用查询接口会不小心
  把这张表暴露出去）。

## Capabilities

### New Capabilities
- `intent-training-data-retention`: 存储「问题原文 + 预测意图标签」样本，供未来训练 BERT
  分类器使用；不含自动清理、脱敏、按租户可选开关（均在 brainstorming 阶段被用户明确排除在
  本次范围外）。

### Modified Capabilities
（无——不修改 `rag_query_audit` 已有字段/行为，也不改动 `QueryIntentClassifier` 分类逻辑本身，
只是消费其分类结果多写一条记录。）

## Non-goals（非目标）

- 不做自动清理/保留期强制执行（用户明确选择"人工删除"）。
- 不做问题原文脱敏（用户明确选择"原样存"）。
- 不做按组织可选的开关粒度（用户明确选择"全局开关"，与现有 `rag.nli.enabled` 等模式一致）。
- 不在本次范围内实际训练 BERT 模型或搭建训练流水线——只做数据积累这一步。
- 不新增数据导出/下载功能；如需导出训练集，后续单独设计。

## Impact

- **新增**：Flyway 迁移（新表 `intent_training_sample`）、JPA 实体、Repository、写入服务。
- **改动**：`QueryService.prepare()` 增加一次写入调用；`RagIntentClassificationProperties`
  同级新增 `RagIntentTrainingDataProperties`（或复用同一配置类新增字段，待 design 阶段定）。
- **不改动**：`rag_query_audit` schema、`LlmQueryIntentClassifier` 分类逻辑、前端。
- **数据敏感度**：这是本项目第一张存储用户问题原文的表（`rag_query_audit`/`ChatMessageDocument`
  除外——`ChatMessageDocument` 本来就存对话内容，属于产品已有能力，与本次新表的定位不同：本次
  是专门为训练目的、脱离对话上下文单独留存），需要在 design 阶段明确访问权限边界。
