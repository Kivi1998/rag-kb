"""所有上传入口共享的文件名、扩展名和大小策略。

对应 Java 版 `ragcore/upload/DocumentUploadPolicy.java`。
文件名长度上限 500,扩展名白名单覆盖 md/txt/pdf/docx/pptx/常见图像/代码/配置。
2026-09 已移除音视频(mp3/wav/mp4/mov/mkv)扩展名,当前业务不再需要音视频解析。
"""

from __future__ import annotations

from dataclasses import dataclass
from locale import LC_ALL, setlocale
from typing import Final

from app.core.config import Settings, settings as default_settings

ALLOWED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "md", "markdown", "txt", "pdf", "docx", "pptx", "srt", "vtt", "json",
        "yaml", "yml", "xml",
        "png", "jpg", "jpeg", "tif", "tiff",
        "java", "py", "js", "ts", "tsx", "jsx", "go", "rs", "sql", "sh", "bash",
        "properties", "conf", "ini", "gradle", "pom",
    }
)

MAX_FILE_NAME_LENGTH: Final[int] = 500


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    safe_file_name: str
    extension: str
    content_type: str
    size_bytes: int


def _expected_content_type(extension: str) -> str:
    table: dict[str, str] = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "md": "text/markdown",
        "markdown": "text/markdown",
        "json": "application/json",
        "yaml": "application/x-yaml",
        "yml": "application/x-yaml",
        "xml": "application/xml",
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }
    return table.get(extension, "text/plain")


class DocumentUploadPolicy:
    def __init__(
        self,
        cfg: Settings | None = None,
        max_size_bytes: int | None = None,
    ) -> None:
        cfg = cfg or default_settings
        max_size = max_size_bytes if max_size_bytes is not None else cfg.rag_upload_max_size_bytes
        if max_size <= 0:
            raise ValueError("rag.upload.max-size-bytes 必须大于 0")
        self._max_size_bytes = max_size

    @property
    def max_size_bytes(self) -> int:
        return self._max_size_bytes

    def validate(self, original_filename: str | None, size_bytes: int) -> ValidatedUpload:
        if size_bytes <= 0:
            raise ValueError("请选择非空文件")
        if size_bytes > self._max_size_bytes:
            raise ValueError("文件大小超过上传策略限制")
        if not original_filename or not original_filename.strip():
            raise ValueError("文件名不能为空")
        # 去除路径前缀与 NUL 字节
        normalized = original_filename.replace("\\", "/")
        safe_file_name = normalized[normalized.rfind("/") + 1 :].strip()
        if (
            not safe_file_name
            or len(safe_file_name) > MAX_FILE_NAME_LENGTH
            or "\x00" in safe_file_name
        ):
            raise ValueError("文件名不合法")
        dot = safe_file_name.rfind(".")
        if dot <= 0 or dot == len(safe_file_name) - 1:
            raise ValueError("文件必须带有受支持的扩展名")
        # 保留 locale-agnostic 小写
        try:
            setlocale(LC_ALL, "C")
        except Exception:  # noqa: BLE001 - locale 不可用时也能工作
            pass
        extension = safe_file_name[dot + 1 :].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {extension}")
        return ValidatedUpload(
            safe_file_name=safe_file_name,
            extension=extension,
            content_type=_expected_content_type(extension),
            size_bytes=size_bytes,
        )
