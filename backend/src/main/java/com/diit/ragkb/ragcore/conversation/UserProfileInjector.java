package com.diit.ragkb.ragcore.conversation;

import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 把该用户相关的画像条目组装成一段 System 上下文，供生成阶段拼接。
 *
 * <p>只读取 {@link MemoryItemStore} 检索结果并格式化成文本——<b>不接触</b>
 * {@code HybridRetriever}/{@code RetrievalOptions} 等检索组件，画像 SHALL NOT
 * 影响候选池大小、过滤条件或 RRF 权重，只影响生成阶段的风格与关注点。</p>
 */
public class UserProfileInjector {

    private final MemoryItemStore memoryItemStore;
    private final int topK;

    public UserProfileInjector(MemoryItemStore memoryItemStore, int topK) {
        this.memoryItemStore = Objects.requireNonNull(memoryItemStore, "memoryItemStore 不能为空");
        this.topK = topK;
    }

    /** 返回空字符串代表没有相关画像，调用方不应拼接任何 System 上下文。 */
    public String buildSystemContext(UUID organizationId, UUID memberId, List<Float> queryVector) {
        List<MemoryItemDocument> items = memoryItemStore.topKForGeneration(organizationId, memberId, queryVector, topK);
        if (items.isEmpty()) {
            return "";
        }
        String bullets = items.stream()
                .map(item -> "- (" + item.getType() + ") " + item.getContent())
                .collect(Collectors.joining("\n"));
        return "以下是关于该用户的背景信息，仅供调整回答风格和关注点参考，不代表知识库内容："
                + "\n" + bullets;
    }
}
