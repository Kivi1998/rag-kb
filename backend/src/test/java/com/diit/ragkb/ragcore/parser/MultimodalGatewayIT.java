package com.diit.ragkb.ragcore.parser;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.impl.HttpMultimodalDocumentParser;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.graphics.image.PDImageXObject;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

/** 真实容器联调；默认跳过，设置 RAG_MULTIMODAL_TEST_ENDPOINT 后显式运行。 */
class MultimodalGatewayIT {

    @Test
    @DisplayName("Java 编排端调用真实网关解析扫描 PDF")
    void parsesScannedPdfThroughRealGateway() throws Exception {
        String endpoint = System.getenv("RAG_MULTIMODAL_TEST_ENDPOINT");
        Assumptions.assumeTrue(endpoint != null && !endpoint.isBlank(), "未配置真实解析网关");
        String apiKey = System.getenv().getOrDefault("RAG_MULTIMODAL_TEST_API_KEY", "");
        byte[] pdf = scannedPdf("JAVA GATEWAY OCR ACCEPTANCE 2026");

        HttpMultimodalDocumentParser parser = new HttpMultimodalDocumentParser(
                new ObjectMapper(), endpoint, apiKey, 120_000);
        ParsedDocument parsed = parser.parse(input(pdf));

        assertFalse(parsed.sections().isEmpty());
        assertTrue(parsed.sections().stream().anyMatch(section -> section.text().contains("OCR ACCEPTANCE")));
        assertEquals("rag-multimodal-gateway", parsed.metadata().get("parser"));
        assertEquals("1", parsed.metadata().get("ocrPageCount"));
    }

    private DocumentInput input(byte[] content) {
        return new DocumentInput() {
            @Override public UUID documentId() { return UUID.fromString("00000000-0000-0000-0000-000000000004"); }
            @Override public String filename() { return "java-scan.pdf"; }
            @Override public String contentType() { return "application/pdf"; }
            @Override public String sourcePath() { return "acceptance/java-scan.pdf"; }
            @Override public InputStream openStream() { return new ByteArrayInputStream(content); }
        };
    }

    private byte[] scannedPdf(String text) throws IOException {
        BufferedImage image = new BufferedImage(1800, 500, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = image.createGraphics();
        graphics.setColor(Color.WHITE);
        graphics.fillRect(0, 0, image.getWidth(), image.getHeight());
        graphics.setColor(Color.BLACK);
        graphics.setFont(new Font(Font.SANS_SERIF, Font.BOLD, 72));
        graphics.drawString(text, 60, 280);
        graphics.dispose();
        ByteArrayOutputStream imageBytes = new ByteArrayOutputStream();
        ImageIO.write(image, "png", imageBytes);

        try (PDDocument document = new PDDocument(); ByteArrayOutputStream pdfBytes = new ByteArrayOutputStream()) {
            PDPage page = new PDPage(new PDRectangle(900, 250));
            document.addPage(page);
            PDImageXObject pdfImage = PDImageXObject.createFromByteArray(document, imageBytes.toByteArray(), "scan");
            try (PDPageContentStream stream = new PDPageContentStream(document, page)) {
                stream.drawImage(pdfImage, 0, 0, 900, 250);
            }
            document.save(pdfBytes);
            return pdfBytes.toByteArray();
        }
    }
}
