"""会话内临时文档 DTO。对应 Java 版 QuickDocumentController 内嵌的 QuickDocumentSummary record。

不回传 content——前端只需要展示文件名/字符数,没必要把全文传回浏览器。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class QuickDocumentSummary(BaseModel):
    doc_id: UUID = Field(..., alias="docId")
    filename: str
    character_count: int = Field(..., alias="characterCount")

    model_config = {"populate_by_name": True}
