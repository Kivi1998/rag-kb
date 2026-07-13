package com.diit.ragkb.ragcore.ingestion;

import java.util.UUID;

/** 跨事务传递给后台 Pipeline 的不可变任务快照，禁止携带 JPA 懒加载实体。 */
public record IngestionTask(
        UUID jobId,
        UUID documentId,
        UUID organizationId,
        UUID knowledgeBaseId,
        String filename,
        String contentType,
        String objectStoragePath,
        String parseArtifactPath,
        String parserVersion
) {
}
