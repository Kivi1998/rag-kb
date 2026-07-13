package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;
import com.diit.ragkb.ragcore.parser.MultimodalDocumentParser;
import com.diit.ragkb.ragcore.parser.NeedsMultimodalParsingException;
import com.diit.ragkb.ragcore.upload.UploadContentInspector;

import java.io.IOException;
import java.io.BufferedInputStream;
import java.util.ArrayList;
import java.util.List;

/**
 * 按注册顺序遍历所有解析器，返回第一个支持该格式的执行结果。
 *
 * <p>提供静态工厂方法 {@link #createDefault()} 注册全部内置解析器，
 * 也可由调用方自行传入自定义解析器列表。</p>
 *
 * <p>复用来源：参考 rag3 pipeline.py 的模块装配模式，自研 Java 实现。</p>
 */
public class DocumentParserFactory {

    private final List<DocumentParser> parsers;
    private final MultimodalDocumentParser multimodalParser;

    public DocumentParserFactory(List<DocumentParser> parsers) {
        this(parsers, null);
    }

    public DocumentParserFactory(List<DocumentParser> parsers, MultimodalDocumentParser multimodalParser) {
        this.parsers = List.copyOf(parsers);
        this.multimodalParser = multimodalParser;
    }

    /**
     * 创建包含全部内置解析器的工厂。
     * 顺序：代码 → Markdown → DOCX → PPTX → PDF → 字幕 → YAML/JSON/XML → TXT。
     */
    public static DocumentParserFactory createDefault() {
        return createDefault(null);
    }

    public static DocumentParserFactory createDefault(MultimodalDocumentParser multimodalParser) {
        List<DocumentParser> list = new ArrayList<>();
        list.add(new CodeParser());
        list.add(new MarkdownParser());
        list.add(new DocxParser());
        list.add(new PptxParser());
        list.add(new PdfParser());
        list.add(new SubtitleParser());
        list.add(new StructuredDataParser());
        list.add(new TextParser());
        return new DocumentParserFactory(list, multimodalParser);
    }

    /**
     * 解析文档，按注册顺序找到第一个 supports 的解析器执行。
     *
     * @throws IOException 如果没有任何解析器支持该格式或解析过程中出错
     */
    public ParsedDocument parse(DocumentInput input) throws IOException {
        verifySourceSignature(input);
        for (DocumentParser parser : parsers) {
            if (parser.supports(input.contentType(), input.filename())) {
                try {
                    return parser.parse(input);
                } catch (NeedsMultimodalParsingException ex) {
                    if (multimodalParser != null && multimodalParser.supports(input)) {
                        return multimodalParser.parse(input);
                    }
                    throw ex;
                }
            }
        }
        if (multimodalParser != null && multimodalParser.supports(input)) {
            return multimodalParser.parse(input);
        }
        throw new IOException(
                "不支持的文档格式: contentType=" + input.contentType()
                + ", filename=" + input.filename()
                + "。当前支持: Markdown, TXT, 源代码, YAML/JSON/XML, DOCX, PPTX, PDF（文本型）, SRT/VTT 字幕"
        );
    }

    /** 直传对象在进入任何高成本解析器之前先校验文件签名，阻断扩展名伪装。 */
    private void verifySourceSignature(DocumentInput input) throws IOException {
        try (BufferedInputStream stream = new BufferedInputStream(input.openStream())) {
            byte[] prefix = stream.readNBytes(8 * 1024);
            UploadContentInspector.inspect(input.filename(), prefix);
        } catch (IllegalArgumentException ex) {
            throw new IOException("源文件内容校验失败: " + ex.getMessage(), ex);
        }
    }
}
