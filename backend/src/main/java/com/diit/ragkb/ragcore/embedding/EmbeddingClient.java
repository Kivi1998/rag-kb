package com.diit.ragkb.ragcore.embedding;

import com.diit.ragkb.ragcore.model.EmbeddingResult;

import java.util.List;

/** 向量模型适配层，屏蔽本地模型和云模型差异。 */
public interface EmbeddingClient {

    EmbeddingResult embed(List<String> texts);
}
