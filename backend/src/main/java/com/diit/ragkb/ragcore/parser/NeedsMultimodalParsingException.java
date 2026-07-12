package com.diit.ragkb.ragcore.parser;

import java.io.IOException;

/** 本地解析器确认文档需要 OCR、版面理解或语音转写时抛出，由多模态网关接管。 */
public class NeedsMultimodalParsingException extends IOException {

    public NeedsMultimodalParsingException(String message) {
        super(message);
    }
}
