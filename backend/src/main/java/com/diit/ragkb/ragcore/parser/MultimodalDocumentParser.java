package com.diit.ragkb.ragcore.parser;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import java.io.IOException;

/**
 * OCR、版面识别和语音转写的外部适配边界。
 *
 * <p>编排服务不绑定 MinerU、PaddleOCR、Whisper 等实现；生产部署可将其替换为独立 GPU 服务，
 * 并通过统一结构化结果进入后续切块与索引链路。</p>
 */
public interface MultimodalDocumentParser {

    boolean supports(DocumentInput input);

    ParsedDocument parse(DocumentInput input) throws IOException;
}
