package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;

import java.io.IOException;
import java.io.InputStream;
import java.util.*;

/**
 * 文本型 PDF 解析器。
 *
 * <p>使用 Apache PDFBox 提取正文，保留页码信息。
 * 仅在 PDF 可以提取足够文本时标记为成功；扫描型/纯图片 PDF 标记为不能解析
 * （通过检测提取文本量与文件页数的比例判断质量）。</p>
 *
 * <p>扫描 PDF 不静默成功：文本量不足时抛出 IOException 并写明原因。</p>
 *
 * <p>依赖：Apache PDFBox。</p>
 * <p>复用来源：参考 rag2 deepdoc/parser/pdf_parser.py 的 PDF 解析策略与上限认知，
 * 完全自研 Java 实现。</p>
 */
public class PdfParser implements DocumentParser {

    private static final Set<String> SUPPORTED_TYPES = Set.of("application/pdf");
    private static final Set<String> PDF_EXTENSIONS = Set.of("pdf");

    /** 每页最少平均字符数，低于此值认为是扫描 PDF */
    private static final double MIN_CHARS_PER_PAGE = 100;

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType.toLowerCase())) return true;
        if (filename != null) {
            String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
            return PDF_EXTENSIONS.contains(ext);
        }
        return false;
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        try (InputStream stream = input.openStream();
             PDDocument pdDoc = Loader.loadPDF(stream.readAllBytes())) {
            int numPages = pdDoc.getNumberOfPages();
            if (numPages == 0) {
                throw new IOException("PDF 文件无页面");
            }

            // Extract text page by page to preserve page boundaries
            List<DocumentSection> sections = new ArrayList<>();

            // First pass: extract all text to check quality
            PDFTextStripper fullStripper = new PDFTextStripper();
            String fullText = fullStripper.getText(pdDoc);

            double avgCharsPerPage = (double) fullText.length() / numPages;
            if (avgCharsPerPage < MIN_CHARS_PER_PAGE) {
                throw new IOException(
                        "PDF 文本量过低（平均每页 " + String.format("%.0f", avgCharsPerPage)
                        + " 字符），可能为扫描件或纯图片 PDF，当前不支持解析"
                );
            }

            // Second pass: extract per-page
            for (int pageNo = 1; pageNo <= numPages; pageNo++) {
                PDFTextStripper pageStripper = new PDFTextStripper();
                pageStripper.setStartPage(pageNo);
                pageStripper.setEndPage(pageNo);
                String pageText = pageStripper.getText(pdDoc).strip();

                if (pageText.isEmpty()) continue;

                // Split page into paragraph blocks
                String[] paragraphs = pageText.split("\n\n+");
                for (String para : paragraphs) {
                    String trimmed = para.strip();
                    if (trimmed.length() < 5) continue;

                    // Try to detect headings (all-uppercase short lines, or lines ending without punctuation)
                    List<String> headingPath = detectHeading(trimmed);

                    sections.add(new DocumentSection(
                            trimmed, headingPath, pageNo, null, null, Map.of()
                    ));
                }
            }

            return new ParsedDocument(
                    input.documentId(), input.contentType(), input.sourcePath(),
                    sections, Map.of("format", "pdf", "numPages", String.valueOf(numPages))
            );
        }
    }

    private List<String> detectHeading(String text) {
        // simple heuristic: first line is short, all-uppercase, or ends with 第X章
        String firstLine = text.split("\n")[0].strip();
        if (firstLine.length() <= 80 && (
                firstLine.equals(firstLine.toUpperCase())
                || firstLine.matches(".*第[一二三四五六七八九十\\d]+[章节条].*")
                || firstLine.matches("^[一二三四五六七八九十\\d]+[、.．].*")
        )) {
            return List.of(firstLine);
        }
        return List.of();
    }
}
