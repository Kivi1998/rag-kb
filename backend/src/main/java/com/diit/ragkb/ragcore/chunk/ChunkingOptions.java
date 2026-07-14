package com.diit.ragkb.ragcore.chunk;

/** 结构感知切分的可配置参数。 */
public record ChunkingOptions(int maxCharacters, int overlapCharacters, boolean preserveCodeBlocks) {

    public ChunkingOptions {
        if (maxCharacters <= 0) {
            throw new IllegalArgumentException("maxCharacters 必须大于 0");
        }
        if (overlapCharacters < 0 || overlapCharacters >= maxCharacters) {
            throw new IllegalArgumentException("overlapCharacters 必须大于等于 0 且小于 maxCharacters");
        }
    }

    /**
     * 默认参数：maxCharacters=1200，overlapCharacters=160（约 13.3%），落在
     * 10%-20% 的性价比区间内——overlap 从 0 加到约 10%-20% 对应字符数时召回率
     * 提升明显，继续加大到 2-3 倍则召回只再小幅提升，但存储和 embedding 成本
     * 线性上升，不值得。
     */
    public static ChunkingOptions defaults() {
        return new ChunkingOptions(1_200, 160, true);
    }
}
