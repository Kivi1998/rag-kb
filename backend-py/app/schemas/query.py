"""问答请求 DTO。对应 Java 版 QueryController 内嵌的 QueryRequest record。"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., description="问题不能为空；空问题由 Retriever 走正常 refusal SSE，而不是 HTTP 400")
    session_id: UUID = Field(
        ...,
        alias="sessionId",
        description="多轮对话会话标识，须由 POST .../sessions 预先创建；缺失或不属于当前成员 → 400/404",
    )

    model_config = {"populate_by_name": True}
