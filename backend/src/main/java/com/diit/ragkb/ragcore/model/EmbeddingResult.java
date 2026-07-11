package com.diit.ragkb.ragcore.model;

import java.util.List;

/** 同一模型生成的一批向量；vectors 与输入文本必须按下标一一对应。 */
public record EmbeddingResult(String modelVersion, List<List<Float>> vectors) {
    public EmbeddingResult {
        vectors = vectors == null
                ? List.of()
                : vectors.stream().map(vector -> List.copyOf(vector)).toList();
    }
}
