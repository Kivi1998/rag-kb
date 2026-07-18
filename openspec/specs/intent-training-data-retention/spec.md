# intent-training-data-retention Specification

## Purpose

意图分类训练数据留存：把「问题原文 + 预测意图标签」样本落库，供未来训练 BERT 分类器替换现在的
LLM Prompt 粗分类（`ragcore/intent/QueryIntentClassifier`，随 PR#25 走 Superpowers brainstorming
流程实现，未走 OpenSpec propose，故未在 `openspec/specs/` 下有独立能力条目）。只存标签、不存
问题原文的 `rag_query_audit` 无法满足这个训练数据积累目的，故新建独立表。默认开启，不脱敏、
不自动清理，均为用户在 brainstorming 阶段的明确选择（详见
`openspec/changes/archive/2026-07-17-intent-classification-training-data-retention/design.md`）。

## Requirements

### Requirement: 记录意图分类训练样本
系统 SHALL 在 `rag.intent-training-data.enabled=true` 且某次查询的意图分类结果不是 `UNKNOWN`
（即分类器成功产出四个合法标签之一）时，把该查询的（问题原文、预测意图标签、组织、知识库、
成员、时间）记录到 `intent_training_sample` 表，供未来训练 BERT 分类器使用。

#### Scenario: 分类成功时记录训练样本
- **WHEN** 一次查询的 `QueryIntentClassifier` 返回 `PRECISE_LOOKUP`/`SEMANTIC`/`COMPARATIVE`/
  `OUT_OF_SCOPE` 中的任一标签，且 `rag.intent-training-data.enabled=true`
- **THEN** `intent_training_sample` 表新增一条记录，`question` 为指代消解后的问题原文，
  `predicted_intent` 为对应标签字面量，`org_id`/`kb_id`/`member_id` 与本次查询一致

#### Scenario: 分类失败或未启用时不记录
- **WHEN** 意图分类器不可用（`rag.intent-classification.enabled=false`）、调用超时/异常，或
  输出无法解析为合法标签（结果为 `UNKNOWN`）
- **THEN** `intent_training_sample` 表不新增记录

#### Scenario: 训练样本表功能关闭时不记录
- **WHEN** `rag.intent-training-data.enabled=false`（即使意图分类本身正常产出了合法标签）
- **THEN** `intent_training_sample` 表不新增记录

#### Scenario: 记录不依赖生成阶段结果
- **WHEN** 检索/生成阶段之后出现拒答、生成失败或客户端提前断开连接，但意图分类阶段已经产出了
  合法标签
- **THEN** `intent_training_sample` 表仍然记录这条样本——训练样本只关心问题该分到哪类意图，
  与本次查询最终是否成功回答无关

#### Scenario: 写入失败不影响问答主流程
- **WHEN** `intent_training_sample` 表写入过程中发生任何异常（如数据库暂时不可用）
- **THEN** 异常被捕获并记录为服务端日志，不向上抛出、不中断本次 SSE 问答响应

#### Scenario: 跨组织隔离
- **WHEN** 通过 JPA 仓库以某个 `org_id` 查询 `intent_training_sample` 表
- **THEN** 只返回该 `org_id` 的记录，不会返回其他组织的问题原文或标签（Hibernate
  `tenantFilter` 强制生效，与 `KnowledgeDocument` 等既有租户隔离约定一致）
