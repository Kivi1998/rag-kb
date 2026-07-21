-- V015: 意图分类训练数据留存表
-- 存「问题原文 + 预测意图标签」样本，供未来训练 BERT 分类器替换现在的 LLM Prompt 粗分类。
-- 与 rag_query_audit 不同：本表存问题原文，明文不脱敏，默认开启（rag.intent-training-data.enabled=true），
-- 不做自动清理（需要清理时人工执行 DELETE）——均为 2026-07-17 brainstorming 阶段用户明确决定。

-- 三个外键均带 ON DELETE CASCADE：对齐 document 表（V003）删除知识库时级联清理子数据的既有模式。
-- rag_query_audit（V006）当初没有加这个子句，导致有查询记录后删除知识库/组织会被 FK 卡住——
-- 那是已有技术债，不在本次修复范围，但本表是新建的，没有理由重复同一个缺陷。
CREATE TABLE intent_training_sample (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            UUID NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    kb_id             UUID NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    member_id         UUID NOT NULL REFERENCES member(id) ON DELETE CASCADE,
    question          TEXT NOT NULL,
    predicted_intent  VARCHAR(32) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_intent_training_sample_org_created ON intent_training_sample (org_id, created_at DESC);
COMMENT ON TABLE intent_training_sample IS '意图分类训练数据留存：存问题原文，默认开启，不做自动清理/脱敏（2026-07-17 用户明确决定）';
