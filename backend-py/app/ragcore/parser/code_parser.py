"""源代码解析器。对应 CodeParser.java。

识别 Java/Python/Go/JavaScript/TypeScript/Rust/C/C++/SQL/Bash/YAML/XML 等语言。
不执行完整 AST 解析，而是按：
- package/import/namespace 声明
- 类/接口/enum/struct/trait 定义
- 方法/函数/构造函数
- 代码块级联
保留语言标识、文件路径和行号范围。
"""

from __future__ import annotations

import re

from app.ragcore.models import DocumentInput, DocumentSection, ParsedDocument
from app.ragcore.parser._util import extension_of
from app.ragcore.parser.base import DocumentParser

_CODE_EXTENSIONS = {
    "java", "py", "go", "js", "ts", "jsx", "tsx", "rs",
    "c", "cpp", "cc", "cxx", "h", "hpp",
    "sql", "bash", "sh", "zsh",
    "kt", "scala", "swift",
    "tf", "hcl",
    "dockerfile", "makefile", "cmake",
    "gradle", "groovy",
}
_SUPPORTED_TYPES = {
    "text/x-java-source", "text/x-python", "text/x-csrc",
    "application/x-javascript", "text/javascript",
}
_EXT_TO_LANG = {
    "java": "Java", "py": "Python",
    "go": "Go", "js": "JavaScript",
    "ts": "TypeScript", "jsx": "JSX",
    "tsx": "TSX", "rs": "Rust",
    "c": "C", "cpp": "C++",
    "h": "C", "hpp": "C++",
    "sql": "SQL", "sh": "Bash",
    "kt": "Kotlin", "swift": "Swift",
    "dockerfile": "Dockerfile", "groovy": "Groovy",
}

_NAME_RE = re.compile(r"(?:class|interface|enum|record|struct|trait|def|func|fn|function)\s+(\w+)")

_TOP_LEVEL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "Java": [
        re.compile(r"^public\s+(class|interface|enum|record)\s+\w+.*"),
        re.compile(r"^public\s+(static\s+)?[\w<>\[\]]+\s+\w+\s*\(.*"),
    ],
    "Python": [re.compile(r"^(class|def|async\s+def)\s+\w+.*")],
    "Go": [re.compile(r"^(func|type|var|const)\s+.*")],
    "Rust": [re.compile(r"^(pub\s+)?(fn|struct|enum|trait|impl|mod)\s+\w+.*")],
    "JavaScript": [re.compile(r"^(export\s+)?(class|function|const|let|var|async\s+function)\s+\w+.*")],
    "TypeScript": [re.compile(r"^(export\s+)?(class|function|const|let|var|async\s+function)\s+\w+.*")],
    "C++": [
        re.compile(r"^(class|struct|enum|template)\s+\w+.*"),
        re.compile(r"^[\w:<>*&\s]+\s+\w+\s*\(.*"),
    ],
    "SQL": [re.compile(r"(?i)^(CREATE|ALTER|DROP|SELECT)\s+(TABLE|INDEX|VIEW|FUNCTION|PROCEDURE).*")],
    "Kotlin": [re.compile(r"^(class|object|interface|fun|val|var)\s+\w+.*")],
}


class CodeParser(DocumentParser):
    def supports(self, content_type: str | None, filename: str | None) -> bool:
        if content_type in _SUPPORTED_TYPES:
            return True
        if filename:
            lower = filename.lower()
            if lower.endswith("dockerfile") or lower == "makefile" or lower == "cmake":
                return True
            return extension_of(filename) in _CODE_EXTENSIONS
        return False

    def parse(self, document_input: DocumentInput) -> ParsedDocument:
        language = self._detect_language(document_input.filename())
        stream = document_input.open_stream()
        try:
            raw = stream.read()
        finally:
            stream.close()
        lines = raw.decode("utf-8").splitlines()

        sections: list[DocumentSection] = []
        current_heading = document_input.filename() or ""

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i].strip()

            if self._is_package_or_import(line, language):
                i += 1
                continue

            if self._is_top_level_def(line, language):
                current_heading = self._extract_name(line)
                start_line = i + 1
                end_line = self._find_block_end(lines, i, language)
                text = self._join_lines(lines, start_line - 1, end_line)
                sections.append(DocumentSection(
                    text=text, heading_path=(current_heading,), page_no=None,
                    line_start=start_line, line_end=end_line, metadata={"language": language},
                ))
                i = end_line
                continue

            if line:
                start_line = i + 1
                buf = [line]
                j = i + 1
                while j < n and not self._is_top_level_def(lines[j].strip(), language) and lines[j].strip():
                    buf.append(lines[j])
                    j += 1
                sections.append(DocumentSection(
                    text="\n".join(buf), heading_path=(current_heading,), page_no=None,
                    line_start=start_line, line_end=j, metadata={"language": language},
                ))
                i = j
                continue
            i += 1

        return ParsedDocument(
            document_id=document_input.document_id(),
            content_type=document_input.content_type(),
            source_path=document_input.source_path(),
            sections=tuple(sections),
            metadata={"format": "code", "language": language, "filename": document_input.filename() or ""},
        )

    # ── helpers ──

    def _detect_language(self, filename: str | None) -> str:
        lower = (filename or "").lower()
        if lower.endswith("dockerfile"):
            return "Dockerfile"
        if lower == "makefile":
            return "Makefile"
        if lower == "cmake":
            return "CMake"
        ext = extension_of(filename)
        return _EXT_TO_LANG.get(ext, ext)

    def _is_package_or_import(self, line: str, lang: str) -> bool:
        if not line:
            return False
        if lang == "Java":
            return line.startswith("package ") or line.startswith("import ")
        if lang == "Python":
            return line.startswith("from ") or line.startswith("import ")
        if lang == "Go":
            return line.startswith("package ") or line.startswith("import ")
        if lang == "Rust":
            return line.startswith("use ") or line.startswith("mod ") or line.startswith("extern ")
        if lang in ("JavaScript", "TypeScript"):
            return line.startswith("import ") or line.startswith("export ")
        if lang == "C++":
            return line.startswith("#include ")
        return False

    def _is_top_level_def(self, line: str, lang: str) -> bool:
        if not line or line.startswith("//") or line.startswith("#") or line.startswith("--"):
            return False
        patterns = _TOP_LEVEL_PATTERNS.get(lang)
        if not patterns:
            return False
        return any(p.match(line) for p in patterns)

    def _extract_name(self, line: str) -> str:
        m = _NAME_RE.search(line)
        return m.group(1) if m else line[:40]

    def _find_block_end(self, lines: list[str], start: int, lang: str) -> int:
        if lang == "Python":
            base_indent = self._indent(lines[start])
            i = start + 1
            while i < len(lines) and (not lines[i].strip() or self._indent(lines[i]) > base_indent):
                i += 1
            return i
        brace_depth = 0
        for i in range(start, len(lines)):
            brace_depth += lines[i].count("{") - lines[i].count("}")
            if brace_depth <= 0 and i > start:
                return i + 1
        return len(lines)

    def _indent(self, line: str) -> int:
        n = 0
        while n < len(line) and line[n] in (" ", "\t"):
            n += 1
        return n

    def _join_lines(self, lines: list[str], frm: int, to: int) -> str:
        return "\n".join(lines[frm:min(to, len(lines))]).rstrip()
