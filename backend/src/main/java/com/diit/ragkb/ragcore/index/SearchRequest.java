package com.diit.ragkb.ragcore.index;

import java.util.UUID;

/** 带组织与知识库边界的检索请求，索引实现不得忽略租户过滤条件。 */
public record SearchRequest(
        UUID organizationId,
        UUID knowledgeBaseId,
        String query,
        int topK
) {
    public SearchRequest {
        if (topK <= 0) {
            throw new IllegalArgumentException("topK 必须大于 0");
        }
    }
}
