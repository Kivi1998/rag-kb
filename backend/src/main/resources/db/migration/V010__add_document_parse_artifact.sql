-- V010: 解析产物及解析器版本。Embedding/索引重试可复用已成功的 OCR/ASR 结果。

ALTER TABLE document
    ADD COLUMN parse_artifact_path VARCHAR(1000),
    ADD COLUMN parser_name VARCHAR(200),
    ADD COLUMN parser_version VARCHAR(100),
    ADD COLUMN parsed_at TIMESTAMPTZ;

COMMENT ON COLUMN document.parse_artifact_path IS '结构化 ParsedDocument JSON 的对象存储路径';
COMMENT ON COLUMN document.parser_version IS '解析产物协议/算法版本，变更后触发重建';
