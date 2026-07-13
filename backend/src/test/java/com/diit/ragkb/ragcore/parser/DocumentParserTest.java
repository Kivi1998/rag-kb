package com.diit.ragkb.ragcore.parser;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.MultimodalDocumentParser;
import com.diit.ragkb.ragcore.parser.NeedsMultimodalParsingException;
import com.diit.ragkb.ragcore.parser.impl.*;
import org.apache.poi.xslf.usermodel.XMLSlideShow;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("技术文档 Parser 集成测试")
class DocumentParserTest {

    // ── helper ──

    static DocumentInput inputOf(String filename, String contentType, String content) {
        return inputOfBytes(filename, contentType, content.getBytes(StandardCharsets.UTF_8));
    }

    static DocumentInput inputOfBytes(String filename, String contentType, byte[] bytes) {
        return new DocumentInput() {
            @Override public UUID documentId() { return UUID.randomUUID(); }
            @Override public String filename() { return filename; }
            @Override public String contentType() { return contentType; }
            @Override public String sourcePath() { return "test/" + filename; }
            @Override public InputStream openStream() { return new ByteArrayInputStream(bytes); }
        };
    }

    static void assertHasContent(ParsedDocument doc) {
        assertNotNull(doc);
        assertNotNull(doc.sections());
        assertFalse(doc.sections().isEmpty(), "解析结果不应为空");
        long totalChars = doc.sections().stream().mapToLong(s -> s.text().length()).sum();
        assertTrue(totalChars > 10, "解析后总字符数应 > 10, 实际: " + totalChars);
    }

    static final class CloseTrackingInputStream extends ByteArrayInputStream {
        private boolean closed;

        CloseTrackingInputStream(byte[] bytes) {
            super(bytes);
        }

        @Override
        public void close() throws IOException {
            closed = true;
            super.close();
        }
    }

    // ── MarkdownParser ──

    @Test
    @DisplayName("解析 Markdown 文档，保留标题层级和代码块")
    void markdownParser() throws IOException {
        String md = """
                # 系统架构设计

                本文档描述整体架构。

                ## 模块划分

                系统分为三层。

                ### 数据层

                ```java
                public class Main {}
                ```

                ## 部署方案

                使用 Docker Compose。
                """;
        MarkdownParser parser = new MarkdownParser();
        assertTrue(parser.supports("text/markdown", "doc.md"));

        ParsedDocument doc = parser.parse(inputOf("arch.md", "text/markdown", md));
        assertHasContent(doc);

        // should have headings: 系统架构设计 → 模块划分 → 数据层 / 部署方案
        boolean hasHeading = doc.sections().stream()
                .anyMatch(s -> s.headingPath().contains("系统架构设计"));
        assertTrue(hasHeading, "应包含一级标题");

        boolean hasCode = doc.sections().stream()
                .anyMatch(s -> s.text().contains("```java"));
        assertTrue(hasCode, "应保留代码块");
    }

    @Test
    @DisplayName("MarkdownParser 根据扩展名判断支持")
    void markdownParserSupportsByExtension() {
        MarkdownParser parser = new MarkdownParser();
        assertTrue(parser.supports(null, "readme.md"));
        assertTrue(parser.supports(null, "doc.mdown"));
        assertFalse(parser.supports(null, "data.json"));
    }

    @Test
    @DisplayName("Markdown 标题层级回退时不保留已结束的子标题")
    void markdownParserTracksHeadingLevels() throws IOException {
        String markdown = "# 根标题\n\n根内容。\n\n### 深层标题\n\n深层内容。\n\n## 同级标题\n\n同级内容。";
        ParsedDocument doc = new MarkdownParser().parse(inputOf("levels.md", "text/markdown", markdown));

        DocumentSection siblingSection = doc.sections().stream()
                .filter(section -> section.text().contains("同级内容"))
                .findFirst()
                .orElseThrow();
        assertEquals(List.of("根标题", "同级标题"), siblingSection.headingPath());
    }

    // ── TextParser ──

    @Test
    @DisplayName("解析纯文本，按空行分块")
    void textParser() throws IOException {
        String txt = "第一段内容。\n\n第二段内容。\n这是第二段的延续。\n\n第三段。";
        TextParser parser = new TextParser();
        assertTrue(parser.supports("text/plain", "log.txt"));

        ParsedDocument doc = parser.parse(inputOf("log.txt", "text/plain", txt));
        assertHasContent(doc);

        // should have 3 paragraphs
        assertEquals(3, doc.sections().size(), "应按空行分为 3 个段落");
    }

    @Test
    @DisplayName("解析超长文本，在句子边界二次切分")
    void textParserLongText() throws IOException {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 500; i++) {
            sb.append("这是第").append(i).append("句话。");
        }
        TextParser parser = new TextParser();
        ParsedDocument doc = parser.parse(inputOf("long.txt", "text/plain", sb.toString()));
        assertHasContent(doc);
        assertTrue(doc.sections().size() > 1, "超长文本应被切为多块");
    }

    @Test
    @DisplayName("TextParser 不支持的格式返回 false")
    void textParserUnsupported() {
        TextParser parser = new TextParser();
        assertFalse(parser.supports("application/pdf", "doc.pdf"));
    }

    // ── SubtitleParser ──

    @Test
    @DisplayName("解析 SRT 字幕，保留时间范围元数据")
    void subtitleParserSrt() throws IOException {
        String srt = """
                1
                00:00:01,000 --> 00:00:04,000
                欢迎使用知识库。

                2
                00:00:04,500 --> 00:00:08,000
                本节介绍文档摄取流程。
                """;
        ParsedDocument doc = new SubtitleParser().parse(inputOf("demo.srt", "application/x-subrip", srt));

        assertEquals(2, doc.sections().size());
        assertEquals("00:00:01,000 --> 00:00:04,000", doc.sections().get(0).metadata().get("timeRange"));
        assertTrue(doc.sections().get(1).text().contains("摄取流程"));
    }

    @Test
    @DisplayName("解析 WebVTT 字幕，忽略文件头")
    void subtitleParserVtt() throws IOException {
        String vtt = """
                WEBVTT

                00:00:01.000 --> 00:00:04.000
                视频开场内容。
                """;
        ParsedDocument doc = new SubtitleParser().parse(inputOf("demo.vtt", "text/vtt", vtt));

        assertEquals("vtt", doc.metadata().get("format"));
        assertEquals("视频开场内容。", doc.sections().get(0).text());
    }

    // ── PptxParser ──

    @Test
    @DisplayName("解析 PPTX 幻灯片，保留页码和标题")
    void pptxParser() throws IOException {
        byte[] bytes;
        try (XMLSlideShow show = new XMLSlideShow(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            var slide = show.createSlide();
            var title = slide.createTextBox();
            title.setText("RAG 摄取架构");
            var body = slide.createTextBox();
            body.setText("上传、解析、切块与索引四个阶段。");
            show.write(out);
            bytes = out.toByteArray();
        }
        PptxParser parser = new PptxParser();
        assertTrue(parser.supports(null, "architecture.pptx"));
        ParsedDocument doc = parser.parse(inputOfBytes("architecture.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation", bytes));

        assertEquals("pptx", doc.metadata().get("format"));
        assertEquals(1, doc.sections().size());
        assertEquals(1, doc.sections().get(0).pageNo());
        assertTrue(doc.sections().get(0).text().contains("RAG 摄取架构"));
    }

    @Test
    @DisplayName("扫描件需要多模态能力时，Parser 工厂交由网关适配器处理")
    void parserFactoryFallsBackToMultimodalGateway() throws IOException {
        var localParser = new com.diit.ragkb.ragcore.parser.DocumentParser() {
            @Override public boolean supports(String contentType, String filename) { return true; }
            @Override public ParsedDocument parse(DocumentInput input) throws IOException {
                throw new NeedsMultimodalParsingException("需要 OCR");
            }
        };
        MultimodalDocumentParser gateway = new MultimodalDocumentParser() {
            @Override public boolean supports(DocumentInput input) { return true; }
            @Override public ParsedDocument parse(DocumentInput input) {
                return new ParsedDocument(input.documentId(), input.contentType(), input.sourcePath(),
                        List.of(new DocumentSection("OCR 识别到的正文", List.of("第一页"), 1, null, null, Map.of("ocr", "true"))),
                        Map.of("parser", "multimodal-gateway"));
            }
        };

        ParsedDocument parsed = new DocumentParserFactory(List.of(localParser), gateway)
                .parse(inputOf("scan.pdf", "application/pdf", "%PDF-placeholder"));

        assertEquals("OCR 识别到的正文", parsed.sections().get(0).text());
        assertEquals("multimodal-gateway", parsed.metadata().get("parser"));
    }

    // ── CodeParser ──

    @Test
    @DisplayName("解析 Java 源码，识别类和方法定义")
    void codeParserJava() throws IOException {
        String java = """
                package com.example;

                import java.util.List;

                /**
                 * A sample service.
                 */
                public class UserService {

                    private final UserRepo repo;

                    public UserService(UserRepo repo) {
                        this.repo = repo;
                    }

                    public User findById(Long id) {
                        return repo.findById(id).orElse(null);
                    }

                    public List<User> listAll() {
                        return repo.findAll();
                    }
                }
                """;
        CodeParser parser = new CodeParser();
        assertTrue(parser.supports(null, "UserService.java"));

        ParsedDocument doc = parser.parse(inputOf("UserService.java", "text/x-java-source", java));
        assertHasContent(doc);

        // should detect class heading
        boolean hasClassHeading = doc.sections().stream()
                .anyMatch(s -> s.headingPath().contains("UserService"));
        assertTrue(hasClassHeading, "应检测到类名作为 heading");

        assertEquals("Java", doc.metadata().get("language"));
    }

    @Test
    @DisplayName("解析 Python 源码，识别函数定义")
    void codeParserPython() throws IOException {
        String python = """
                def hello():
                    print("hello")

                class Calculator:
                    def add(self, a, b):
                        return a + b
                """;
        CodeParser parser = new CodeParser();
        assertTrue(parser.supports(null, "calc.py"));

        ParsedDocument doc = parser.parse(inputOf("calc.py", "text/x-python", python));
        assertHasContent(doc);
        assertTrue(doc.sections().stream().anyMatch(s -> s.headingPath().contains("Calculator")),
                "应检测到类名");
    }

    @Test
    @DisplayName("CodeParser 不支持 Word 文档")
    void codeParserUnsupported() {
        CodeParser parser = new CodeParser();
        assertFalse(parser.supports(null, "report.docx"));
    }

    // ── StructuredDataParser ──

    @Test
    @DisplayName("解析 JSON 配置，保留键路径")
    void structuredDataParserJson() throws IOException {
        String json = """
                {
                  "server": {
                    "port": 8080,
                    "host": "localhost"
                  },
                  "database": {
                    "url": "jdbc:postgresql://localhost/db",
                    "pool": {
                      "max": 20,
                      "min": 5
                    }
                  }
                }
                """;
        StructuredDataParser parser = new StructuredDataParser();
        assertTrue(parser.supports("application/json", "config.json"));

        ParsedDocument doc = parser.parse(inputOf("config.json", "application/json", json));
        assertHasContent(doc);

        // should have sections with jsonPath metadata
        boolean hasServerPath = doc.sections().stream()
                .anyMatch(s -> s.metadata().getOrDefault("jsonPath", "").contains("server"));
        assertTrue(hasServerPath, "应包含 server 键路径");
    }

    @Test
    @DisplayName("解析 YAML 配置")
    void structuredDataParserYaml() throws IOException {
        String yaml = """
                spring:
                  datasource:
                    url: jdbc:postgresql://localhost/db
                    username: admin
                  jpa:
                    hibernate:
                      ddl-auto: validate
                """;
        StructuredDataParser parser = new StructuredDataParser();
        assertTrue(parser.supports(null, "application.yml"));

        ParsedDocument doc = parser.parse(inputOf("application.yml", "text/yaml", yaml));
        assertHasContent(doc);
    }

    @Test
    @DisplayName("StructuredDataParser 不支持的格式")
    void structuredDataParserUnsupported() {
        StructuredDataParser parser = new StructuredDataParser();
        assertFalse(parser.supports("application/pdf", "doc.pdf"));
        assertFalse(parser.supports(null, "config.toml"));
    }

    @Test
    @DisplayName("StructuredDataParser 关闭调用方提供的输入流")
    void structuredDataParserClosesInputStream() throws IOException {
        CloseTrackingInputStream stream = new CloseTrackingInputStream("{\"key\": \"value\"}".getBytes(StandardCharsets.UTF_8));
        DocumentInput input = new DocumentInput() {
            @Override public UUID documentId() { return UUID.randomUUID(); }
            @Override public String filename() { return "config.json"; }
            @Override public String contentType() { return "application/json"; }
            @Override public String sourcePath() { return "test/config.json"; }
            @Override public InputStream openStream() { return stream; }
        };

        new StructuredDataParser().parse(input);

        assertTrue(stream.closed, "解析器必须关闭 DocumentInput 打开的输入流");
    }

    // ── DocxParser ──

    @Test
    @DisplayName("DocxParser 根据扩展名判断支持")
    void docxParserSupports() {
        DocxParser parser = new DocxParser();
        assertTrue(parser.supports("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc.docx"));
        assertFalse(parser.supports(null, "report.doc"));
        assertFalse(parser.supports(null, "data.json"));
    }

    // ── PdfParser ──

    @Test
    @DisplayName("PdfParser 根据扩展名判断支持")
    void pdfParserSupports() {
        PdfParser parser = new PdfParser();
        assertTrue(parser.supports("application/pdf", "doc.pdf"));
        assertTrue(parser.supports(null, "manual.PDF"));
        assertFalse(parser.supports(null, "readme.md"));
    }

    // ── DocumentParserFactory ──

    @Test
    @DisplayName("工厂按顺序选择正确的解析器")
    void factorySelectsCorrectParser() throws IOException {
        DocumentParserFactory factory = DocumentParserFactory.createDefault();

        ParsedDocument mdDoc = factory.parse(inputOf("readme.md", "text/markdown", "# Title\n\nContent"));
        assertEquals("markdown", mdDoc.metadata().get("format"));

        ParsedDocument txtDoc = factory.parse(inputOf("notes.txt", "text/plain", "Hello world"));
        assertEquals("text", txtDoc.metadata().get("format"));

        ParsedDocument codeDoc = factory.parse(inputOf("Main.java", "text/x-java-source",
                "public class Main {}"));
        assertEquals("code", codeDoc.metadata().get("format"));

        ParsedDocument jsonDoc = factory.parse(inputOf("config.json", "application/json",
                "{\"key\": \"value\"}"));
        assertEquals("json", jsonDoc.metadata().get("format"));
    }

    @Test
    @DisplayName("工厂对不支持格式抛出 IOException")
    void factoryThrowsForUnknownFormat() {
        DocumentParserFactory factory = DocumentParserFactory.createDefault();
        assertThrows(IOException.class, () ->
                factory.parse(inputOf("image.png", "image/png", "binary"))
        );
    }
}
