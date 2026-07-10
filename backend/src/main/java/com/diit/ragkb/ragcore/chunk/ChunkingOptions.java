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

    public static ChunkingOptions defaults() {
        return new ChunkingOptions(1_200, 160, true);
    }
}
