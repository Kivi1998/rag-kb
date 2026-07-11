package com.diit.ragkb.ragcore.chunk;

import java.util.Objects;
import java.util.UUID;

/** 服务端摄取编排层注入的、不可为空的租户与知识库上下文。 */
public record ChunkingContext(UUID organizationId, UUID knowledgeBaseId) {

    public ChunkingContext {
        Objects.requireNonNull(organizationId, "organizationId 不能为空");
        Objects.requireNonNull(knowledgeBaseId, "knowledgeBaseId 不能为空");
    }
}
