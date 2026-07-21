-- V008: 原始文件内容指纹。内容相同的文档可在应用层按知识库去重，并支持审计与版本追溯。

ALTER TABLE document
    ADD COLUMN content_sha256 VARCHAR(64);

CREATE INDEX idx_document_org_kb_content_hash
    ON document (org_id, kb_id, content_sha256)
    WHERE content_sha256 IS NOT NULL;

COMMENT ON COLUMN document.content_sha256 IS '上传原始文件的 SHA-256 十六进制摘要';
