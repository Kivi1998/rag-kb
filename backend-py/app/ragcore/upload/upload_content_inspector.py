"""上传文件的轻量内容嗅探。

对应 Java 版 `ragcore/upload/UploadContentInspector.java`。
不依赖客户端 MIME,先拒绝与扩展名明显不符的二进制伪装文件;深层格式校验仍由
对应 Parser 负责,避免在 HTTP 请求内执行高成本 Office/PDF 解析。

公共 API 是 `UploadContentInspector.inspect(filename, prefix)`,与 `ragcore.upload.__init__`
里文档字符串保持一致。模块内同时保留 `inspect()` 顶层函数作为底层实现,以及供
`ragcore.upload.__init__` 重新导出为 `inspect_content` 使用。
"""

from __future__ import annotations

from typing import Final

_TEXTUAL_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "md", "markdown", "txt", "srt", "vtt", "json", "yaml", "yml", "xml",
        "java", "py", "js", "ts", "tsx", "jsx", "go", "rs", "sql", "sh", "bash",
        "properties", "conf", "ini", "gradle", "pom",
    }
)


def _extension_of(filename: str | None) -> str:
    if not filename:
        return ""
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot + 1 :].lower()


def _starts_with(value: bytes, expected: bytes) -> bool:
    if len(value) < len(expected):
        return False
    return value[: len(expected)] == expected


def _contains_nul(value: bytes) -> bool:
    return any(b == 0 for b in value)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_zip(prefix: bytes) -> bool:
    return (
        len(prefix) >= 4
        and prefix[0] == ord("P")
        and prefix[1] == ord("K")
        and ((prefix[2] == 3 and prefix[3] == 4) or (prefix[2] == 5 and prefix[3] == 6))
    )


def inspect(filename: str, prefix: bytes) -> str:
    """按文件名扩展名嗅探文件头,不一致时抛 ValueError;返回与扩展名匹配的标准 MIME。"""
    extension = _extension_of(filename)
    if extension == "pdf":
        _require(_starts_with(prefix, b"%PDF-"), "PDF 文件头无效")
        return "application/pdf"
    if extension == "docx":
        _require(_is_zip(prefix), "DOCX 必须是有效的 OOXML ZIP 文件")
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if extension == "pptx":
        _require(_is_zip(prefix), "PPTX 必须是有效的 OOXML ZIP 文件")
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if extension == "png":
        _require(_starts_with(prefix, b"\x89PNG"), "PNG 文件头无效")
        return "image/png"
    if extension in {"jpg", "jpeg"}:
        _require(_starts_with(prefix, b"\xff\xd8\xff"), "JPEG 文件头无效")
        return "image/jpeg"
    if extension in {"tif", "tiff"}:
        little_endian = _starts_with(prefix, b"II\x2a\x00")
        big_endian = _starts_with(prefix, b"MM\x00\x2a")
        _require(little_endian or big_endian, "TIFF 文件头无效")
        return "image/tiff"
    if extension == "wav":
        _require(
            len(prefix) >= 12
            and _starts_with(prefix, b"RIFF")
            and prefix[8:12] == b"WAVE",
            "WAV 文件头无效",
        )
        return "audio/wav"
    if extension == "mp3":
        id3 = _starts_with(prefix, b"ID3")
        frame = len(prefix) >= 2 and (prefix[0] & 0xFF) == 0xFF and ((prefix[1] & 0xE0) == 0xE0)
        _require(id3 or frame, "MP3 文件头无效")
        return "audio/mpeg"
    if extension in {"mp4", "mov"}:
        _require(
            len(prefix) >= 12 and prefix[4:8] == b"ftyp",
            "MP4/MOV 文件头无效",
        )
        return "video/quicktime" if extension == "mov" else "video/mp4"
    if extension == "mkv":
        _require(_starts_with(prefix, b"\x1a\x45\xdf\xa3"), "MKV 文件头无效")
        return "video/x-matroska"
    if extension in _TEXTUAL_EXTENSIONS:
        _require(not _contains_nul(prefix), "文本或代码文件包含二进制空字节")
        return {
            "md": "text/markdown",
            "markdown": "text/markdown",
            "json": "application/json",
            "yaml": "application/x-yaml",
            "yml": "application/x-yaml",
            "xml": "application/xml",
            "srt": "application/x-subrip",
            "vtt": "text/vtt",
        }.get(extension, "text/plain")
    raise ValueError(f"不支持的文件类型: {extension}")


class UploadContentInspector:
    """对应 Java 版 `ragcore/upload/UploadContentInspector.java`。

    业务调用方(`DocumentDirectUploadService` / `DocumentIngestionService`)统一以
    `UploadContentInspector.inspect(filename, prefix)` 的类-方法形式调用,与
    `ragcore.upload` 子包文档保持一致。底层实现走模块级 `inspect()` 顶层函数,
    顶层函数同时也被 `ragcore.upload.__init__` 重新导出为 `inspect_content`,
    因此本次只加包装类、保持 `inspect()` 函数不动,把所有调用方的影响降到零。
    """

    @staticmethod
    def inspect(filename: str, prefix: bytes) -> str:
        """嗅探文件头并返回标准 MIME;与底层 `inspect()` 函数行为完全一致。"""
        return inspect(filename, prefix)
