from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .parsers import ParseError, ParserUnavailableError, asr_is_loaded, ensure_asr_ready, parse_document


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not API_KEY:
        raise RuntimeError("PARSER_API_KEY is required")
    if MAX_FILE_BYTES < 1 or MAX_CONCURRENCY < 1:
        raise RuntimeError("PARSER_MAX_FILE_BYTES and PARSER_MAX_CONCURRENCY must be positive")
    if os.getenv("PARSER_PRELOAD_WHISPER", "false").lower() == "true":
        await asyncio.to_thread(ensure_asr_ready)
    yield


app = FastAPI(title="RAG Multimodal Parser Gateway", version="1.0.0", lifespan=lifespan)

MAX_FILE_BYTES = int(os.getenv("PARSER_MAX_FILE_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_CONCURRENCY = int(os.getenv("PARSER_MAX_CONCURRENCY", "2"))
API_KEY = os.getenv("PARSER_API_KEY", "")
_slots = asyncio.Semaphore(MAX_CONCURRENCY)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/ready")
def ready() -> JSONResponse:
    require_asr = os.getenv("PARSER_REQUIRE_ASR_READY", "false").lower() == "true"
    loaded = asr_is_loaded()
    body = {"status": "UP" if (loaded or not require_asr) else "DOWN", "asrLoaded": loaded}
    return JSONResponse(body, status_code=200 if body["status"] == "UP" else 503)


@app.post("/v1/parse")
async def parse(
    request: Request,
    authorization: str | None = Header(default=None),
    x_document_id: str = Header(alias="X-Document-Id"),
    x_document_filename: str = Header(alias="X-Document-Filename"),
    x_source_path: str | None = Header(default=None, alias="X-Source-Path"),
) -> JSONResponse:
    _require_auth(authorization)
    safe_name = Path(x_document_filename).name
    if not safe_name or safe_name != x_document_filename or "\x00" in safe_name:
        raise HTTPException(status_code=400, detail="invalid filename")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
                      ".mp3", ".wav", ".mp4", ".mov", ".mkv"}:
        raise HTTPException(status_code=415, detail=f"unsupported format: {suffix}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="rag-parse-", suffix=suffix, delete=False) as target:
            temp_path = Path(target.name)
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="file exceeds parser limit")
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="empty file")

        async with _slots:
            result = await asyncio.to_thread(parse_document, temp_path, safe_name)
        result.setdefault("metadata", {})
        result["metadata"].update({
            "parser": "rag-multimodal-gateway",
            "parserVersion": app.version,
            "documentId": x_document_id,
            "sourcePath": x_source_path or "",
        })
        return JSONResponse(result)
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ParserUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _require_auth(authorization: str | None) -> None:
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="invalid parser credential")
