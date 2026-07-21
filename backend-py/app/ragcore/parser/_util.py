"""解析器内部共享的小工具函数。

Java 版每个 Parser 都各自复制了一份「取扩展名」逻辑；这里抽成一个小函数避免
散落的重复实现漂移，行为与 Java 版逐字节保持一致(取最后一个 `.` 之后的部分，
转小写)。
"""

from __future__ import annotations


def extension_of(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()
