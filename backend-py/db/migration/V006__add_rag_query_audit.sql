-- V006: RAG 查询审计只保存可观测性元数据，不保存问题、答案、Prompt 或正文。
CREATE TABLE rag_query_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    org_id UUID NOT NULL REFERENCES organization(id),
    kb_id UUID NOT NULL REFERENCES knowledge_base(id),
    member_id UUID NOT NULL REFERENCES member(id),
    status VARCHAR(20) NOT NULL,
    retrieval_latency_ms BIGINT NOT NULL,
    generation_latency_ms BIGINT NOT NULL,
    total_latency_ms BIGINT NOT NULL,
    chunk_ids_json TEXT NOT NULL,
    document_ids_json TEXT NOT NULL,
    final_scores_json TEXT NOT NULL,
    embedding_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    rerank_fallback BOOLEAN NOT NULL DEFAULT FALSE,
    refusal_reason VARCHAR(300),
    generation_model VARCHAR(300),
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    output_characters BIGINT NOT NULL DEFAULT 0,
    error_code VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_rag_query_audit_latency CHECK (retrieval_latency_ms >= 0 AND generation_latency_ms >= 0
        AND total_latency_ms >= 0 AND output_characters >= 0)
);

CREATE INDEX idx_rag_query_audit_org_kb_created ON rag_query_audit(org_id, kb_id, created_at DESC);
CREATE INDEX idx_rag_query_audit_trace_id ON rag_query_audit(trace_id);
COMMENT ON TABLE rag_query_audit IS '自研 RAG 查询审计；严禁写入问题、回答、Prompt 或文档正文';
