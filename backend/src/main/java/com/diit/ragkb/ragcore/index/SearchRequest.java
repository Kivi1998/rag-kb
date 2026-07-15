package com.diit.ragkb.ragcore.index;

import java.util.List;
import java.util.UUID;

/**
 * 带组织与知识库边界的检索请求，索引实现不得忽略租户过滤条件。
 *
 * <p>{@code documentIds} 非空时，索引实现应在租户过滤之外叠加范围过滤，只在指定文档内检索。</p>
 */
public record SearchRequest(
        UUID organizationId,
        UUID knowledgeBaseId,
        String query,
        int topK,
        List<UUID> documentIds
) {
    public SearchRequest {
        documentIds = documentIds == null ? List.of() : List.copyOf(documentIds);
        if (topK <= 0) {
            throw new IllegalArgumentException("topK 必须大于 0");
        }
    }

    public SearchRequest(UUID organizationId, UUID knowledgeBaseId, String query, int topK) {
        this(organizationId, knowledgeBaseId, query, topK, List.of());
    }
}
