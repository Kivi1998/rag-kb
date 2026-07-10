package com.diit.ragkb.ragcore.parser;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.impl.*;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("技术文档 Parser 集成测试")
class DocumentParserTest {

    // ── helper ──

    static DocumentInput inputOf(String filename, String contentType, String content) {
        byte[] bytes = content.getBytes(StandardCharsets.UTF_8);
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
    }

    // ── DocxParser ──

    @Test
    @DisplayName("DocxParser 根据扩展名判断支持")
    void docxParserSupports() {
        DocxParser parser = new DocxParser();
        assertTrue(parser.supports("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc.docx"));
        assertTrue(parser.supports(null, "report.doc"));
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
