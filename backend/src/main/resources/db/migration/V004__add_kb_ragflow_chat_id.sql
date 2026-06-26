-- 知识库关联 RAGFlow Chat Assistant
-- 懒建策略:首次问答时由 QueryService 创建并写入
ALTER TABLE knowledge_base
    ADD COLUMN ragflow_chat_id VARCHAR(200);
