package com.diit.ragkb.ragcore.parser;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.ParsedDocument;

import java.io.IOException;

/** 可插拔的文档格式解析器。 */
public interface DocumentParser {

    boolean supports(String contentType, String filename);

    ParsedDocument parse(DocumentInput input) throws IOException;
}
