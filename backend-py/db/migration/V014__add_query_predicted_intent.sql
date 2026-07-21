-- V014: rag_query_audit 新增查询意图分类标签字段
-- 值域 precise-lookup/semantic/comparative/out-of-scope；分类失败或未启用时为 null。
-- 不存问题原文（安全约定不变）——只能用于观测分类标签分布，不能用于训练 BERT。

ALTER TABLE rag_query_audit ADD COLUMN predicted_intent VARCHAR(32);
