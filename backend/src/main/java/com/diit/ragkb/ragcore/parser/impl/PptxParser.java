package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;
import com.diit.ragkb.ragcore.parser.NeedsMultimodalParsingException;
import org.apache.poi.xslf.usermodel.XSLFShape;
import org.apache.poi.xslf.usermodel.XSLFSlide;
import org.apache.poi.xslf.usermodel.XMLSlideShow;
import org.apache.poi.xslf.usermodel.XSLFTextShape;

import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * PPTX 技术演示文稿解析器。
 *
 * <p>提取每页的可见文本，使用第一个短文本框作为页标题，并把页号写入结构化元数据。
 * 图表、图片、扫描页中的文字由可选的多模态解析服务补充，本解析器不会伪造 OCR 结果。</p>
 */
public class PptxParser implements DocumentParser {

    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    );

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType.toLowerCase(Locale.ROOT))) {
            return true;
        }
        return filename != null && filename.toLowerCase(Locale.ROOT).endsWith(".pptx");
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        try (InputStream stream = input.openStream(); XMLSlideShow show = new XMLSlideShow(stream)) {
            List<DocumentSection> sections = new ArrayList<>();
            int slideNo = 0;
            for (XSLFSlide slide : show.getSlides()) {
                slideNo++;
                List<String> lines = new ArrayList<>();
                for (XSLFShape shape : slide.getShapes()) {
                    if (shape instanceof XSLFTextShape textShape) {
                        String text = textShape.getText();
                        if (text != null && !text.isBlank()) {
                            lines.add(text.strip());
                        }
                    }
                }
                if (lines.isEmpty()) {
                    continue;
                }
                String title = lines.stream().filter(line -> line.length() <= 120).findFirst().orElse("第 " + slideNo + " 页");
                sections.add(new DocumentSection(String.join("\n", lines), List.of(title), slideNo,
                        null, null, Map.of("type", "slide", "slideNo", String.valueOf(slideNo))));
            }
            if (sections.isEmpty()) {
                throw new NeedsMultimodalParsingException("PPTX 中未提取到可索引文本；需要 OCR 或版面解析服务");
            }
            return new ParsedDocument(input.documentId(), input.contentType(), input.sourcePath(), sections,
                    Map.of("format", "pptx", "slideCount", String.valueOf(show.getSlides().size())));
        }
    }
}
