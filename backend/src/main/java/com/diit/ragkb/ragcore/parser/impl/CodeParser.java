package com.diit.ragkb.ragcore.parser.impl;

import com.diit.ragkb.ragcore.model.DocumentInput;
import com.diit.ragkb.ragcore.model.DocumentSection;
import com.diit.ragkb.ragcore.model.ParsedDocument;
import com.diit.ragkb.ragcore.parser.DocumentParser;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * 源代码解析器。
 *
 * <p>识别 Java/Python/Go/JavaScript/TypeScript/Rust/C/C++/SQL/Bash/YAML/XML 等语言。
 * 不执行完整 AST 解析，而是按:
 * <ul>
 *   <li>package/import/namespace 声明</li>
 *   <li>类/接口/enum/struct/trait 定义</li>
 *   <li>方法/函数/构造函数</li>
 *   <li>代码块级联</li>
 * </ul>
 * 保留语言标识、文件路径和行号范围。</p>
 *
 * <p>复用来源：参考 rag2 的源码处理思路，完全自研 Java 实现。</p>
 */
public class CodeParser implements DocumentParser {

    private static final Set<String> CODE_EXTENSIONS = Set.of(
            "java", "py", "go", "js", "ts", "jsx", "tsx", "rs",
            "c", "cpp", "cc", "cxx", "h", "hpp",
            "sql", "bash", "sh", "zsh",
            "kt", "scala", "swift",
            "tf", "hcl",
            "dockerfile", "makefile", "cmake",
            "gradle", "groovy"
    );
    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "text/x-java-source", "text/x-python", "text/x-csrc",
            "application/x-javascript", "text/javascript"
    );

    private static final Map<String, String> EXT_TO_LANG = new HashMap<>();
    static {
        EXT_TO_LANG.put("java", "Java");   EXT_TO_LANG.put("py", "Python");
        EXT_TO_LANG.put("go", "Go");       EXT_TO_LANG.put("js", "JavaScript");
        EXT_TO_LANG.put("ts", "TypeScript"); EXT_TO_LANG.put("jsx", "JSX");
        EXT_TO_LANG.put("tsx", "TSX");     EXT_TO_LANG.put("rs", "Rust");
        EXT_TO_LANG.put("c", "C");         EXT_TO_LANG.put("cpp", "C++");
        EXT_TO_LANG.put("h", "C");         EXT_TO_LANG.put("hpp", "C++");
        EXT_TO_LANG.put("sql", "SQL");     EXT_TO_LANG.put("sh", "Bash");
        EXT_TO_LANG.put("kt", "Kotlin");   EXT_TO_LANG.put("swift", "Swift");
        EXT_TO_LANG.put("dockerfile", "Dockerfile"); EXT_TO_LANG.put("groovy", "Groovy");
    }

    @Override
    public boolean supports(String contentType, String filename) {
        if (contentType != null && SUPPORTED_TYPES.contains(contentType)) return true;
        if (filename != null) {
            String lower = filename.toLowerCase();
            if (lower.endsWith("dockerfile") || lower.equals("makefile") || lower.equals("cmake")) return true;
            String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
            return CODE_EXTENSIONS.contains(ext);
        }
        return false;
    }

    @Override
    public ParsedDocument parse(DocumentInput input) throws IOException {
        String language = detectLanguage(input.filename());
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input.openStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) lines.add(line);
        }

        List<DocumentSection> sections = new ArrayList<>();
        String currentHeading = input.filename();

        int i = 0;
        while (i < lines.size()) {
            String line = lines.get(i).strip();

            // package / import / namespace — treated as file-level metadata
            if (isPackageOrImport(line, language)) {
                i++;
                continue;
            }

            // class / interface / enum / struct / trait / function definition
            if (isTopLevelDef(line, language)) {
                currentHeading = extractName(line, language);
                int startLine = i + 1;
                int endLine = findBlockEnd(lines, i, language);
                String text = joinLines(lines, startLine - 1, endLine);
                sections.add(new DocumentSection(
                        text, List.of(currentHeading), null, startLine, endLine, Map.of("language", language)
                ));
                i = endLine;
                continue;
            }

            // non-empty line without top-level structure: accumulate
            if (!line.isBlank()) {
                int startLine = i + 1;
                StringBuilder buf = new StringBuilder(line);
                int j = i + 1;
                while (j < lines.size() && !isTopLevelDef(lines.get(j).strip(), language) && !lines.get(j).isBlank()) {
                    buf.append('\n').append(lines.get(j));
                    j++;
                }
                sections.add(new DocumentSection(
                        buf.toString(), List.of(currentHeading), null, startLine, j, Map.of("language", language)
                ));
                i = j;
                continue;
            }
            i++;
        }

        return new ParsedDocument(
                input.documentId(), input.contentType(), input.sourcePath(), sections,
                Map.of("format", "code", "language", language, "filename", input.filename())
        );
    }

    // ── helpers ──

    private String detectLanguage(String filename) {
        String lower = filename != null ? filename.toLowerCase() : "";
        if (lower.endsWith("dockerfile")) return "Dockerfile";
        if (lower.equals("makefile")) return "Makefile";
        if (lower.equals("cmake")) return "CMake";
        String ext = filename.contains(".") ? filename.substring(filename.lastIndexOf('.') + 1).toLowerCase() : "";
        return EXT_TO_LANG.getOrDefault(ext, ext);
    }

    private boolean isPackageOrImport(String line, String lang) {
        if (line.isBlank()) return false;
        return switch (lang) {
            case "Java" -> line.startsWith("package ") || line.startsWith("import ");
            case "Python" -> line.startsWith("from ") || line.startsWith("import ");
            case "Go" -> line.startsWith("package ") || line.startsWith("import ");
            case "Rust" -> line.startsWith("use ") || line.startsWith("mod ") || line.startsWith("extern ");
            case "JavaScript", "TypeScript" -> line.startsWith("import ") || line.startsWith("export ");
            case "C++" -> line.startsWith("#include ");
            default -> false;
        };
    }

    private boolean isTopLevelDef(String line, String lang) {
        if (line.isBlank() || line.startsWith("//") || line.startsWith("#") || line.startsWith("--")) return false;
        return switch (lang) {
            case "Java" -> line.matches("^public\\s+(class|interface|enum|record)\\s+\\w+.*")
                    || line.matches("^public\\s+(static\\s+)?[\\w<>\\[\\]]+\\s+\\w+\\s*\\(.*");
            case "Python" -> line.matches("^(class|def|async\\s+def)\\s+\\w+.*");
            case "Go" -> line.matches("^(func|type|var|const)\\s+.*");
            case "Rust" -> line.matches("^(pub\\s+)?(fn|struct|enum|trait|impl|mod)\\s+\\w+.*");
            case "JavaScript", "TypeScript" -> line.matches("^(export\\s+)?(class|function|const|let|var|async\\s+function)\\s+\\w+.*");
            case "C++" -> line.matches("^(class|struct|enum|template)\\s+\\w+.*")
                    || line.matches("^[\\w:<>*&\\s]+\\s+\\w+\\s*\\(.*");
            case "SQL" -> line.matches("(?i)^(CREATE|ALTER|DROP|SELECT)\\s+(TABLE|INDEX|VIEW|FUNCTION|PROCEDURE).*");
            case "Kotlin" -> line.matches("^(class|object|interface|fun|val|var)\\s+\\w+.*");
            default -> false;
        };
    }

    private String extractName(String line, String lang) {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile(
                "(?:class|interface|enum|record|struct|trait|def|func|fn|function)\\s+(\\w+)"
        ).matcher(line);
        return m.find() ? m.group(1) : line.substring(0, Math.min(line.length(), 40));
    }

    private int findBlockEnd(List<String> lines, int start, String lang) {
        // simple brace-based; for Python use indentation level
        if ("Python".equals(lang)) {
            int baseIndent = indent(lines.get(start));
            int i = start + 1;
            while (i < lines.size() && (lines.get(i).isBlank() || indent(lines.get(i)) > baseIndent)) i++;
            return i;
        }
        // brace-based
        int braceDepth = 0;
        for (int i = start; i < lines.size(); i++) {
            braceDepth += countChar(lines.get(i), '{') - countChar(lines.get(i), '}');
            if (braceDepth <= 0 && i > start) return i + 1;
        }
        return lines.size();
    }

    private int indent(String line) {
        int n = 0;
        while (n < line.length() && (line.charAt(n) == ' ' || line.charAt(n) == '\t')) n++;
        return n;
    }

    private int countChar(String s, char c) {
        return (int) s.chars().filter(ch -> ch == c).count();
    }

    private String joinLines(List<String> lines, int from, int to) {
        StringBuilder sb = new StringBuilder();
        for (int i = from; i < Math.min(to, lines.size()); i++) {
            sb.append(lines.get(i)).append('\n');
        }
        return sb.toString().stripTrailing();
    }
}
