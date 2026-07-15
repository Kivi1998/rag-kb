from __future__ import annotations

import asyncio
import hmac
import os
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote_plus

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from .parsers import (ParseError, ParserUnavailableError, asr_is_loaded, ensure_asr_ready,
                      ensure_ocr_ready, ocr_is_loaded, parse_document)


REQUESTS = Counter("rag_parser_requests_total", "Parser requests", ["format", "outcome"])
DURATION = Histogram("rag_parser_duration_seconds", "Parser duration", ["format"])
BYTES = Counter("rag_parser_input_bytes_total", "Parser input bytes", ["format"])
IN_PROGRESS = Gauge("rag_parser_in_progress", "Documents currently parsed")
READINESS = Gauge("rag_parser_dependency_ready", "Parser dependency readiness", ["dependency"])
SUPPORTED_SUFFIXES = {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
                      ".mp3", ".wav", ".mp4", ".mov", ".mkv"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not API_KEY:
        raise RuntimeError("PARSER_API_KEY is required")
    if not METRICS_KEY:
        raise RuntimeError("PARSER_METRICS_KEY is required")
    if MAX_FILE_BYTES < 1 or MAX_CONCURRENCY < 1:
        raise RuntimeError("PARSER_MAX_FILE_BYTES and PARSER_MAX_CONCURRENCY must be positive")
    if os.getenv("PARSER_PRELOAD_WHISPER", "false").lower() == "true":
        await asyncio.to_thread(ensure_asr_ready)
    if os.getenv("PARSER_PRELOAD_OCR", "false").lower() == "true":
        await asyncio.to_thread(ensure_ocr_ready)
    yield


app = FastAPI(title="RAG Multimodal Parser Gateway", version="1.0.0", lifespan=lifespan)

MAX_FILE_BYTES = int(os.getenv("PARSER_MAX_FILE_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_CONCURRENCY = int(os.getenv("PARSER_MAX_CONCURRENCY", "2"))
API_KEY = os.getenv("PARSER_API_KEY", "")
METRICS_KEY = os.getenv("PARSER_METRICS_KEY", "")
_slots = asyncio.Semaphore(MAX_CONCURRENCY)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/ready")
def ready() -> JSONResponse:
    require_asr = os.getenv("PARSER_REQUIRE_ASR_READY", "false").lower() == "true"
    require_ocr = os.getenv("PARSER_REQUIRE_OCR_READY", "false").lower() == "true"
    asr_loaded = asr_is_loaded()
    ocr_loaded = ocr_is_loaded()
    READINESS.labels("asr").set(1 if asr_loaded else 0)
    READINESS.labels("ocr").set(1 if ocr_loaded else 0)
    available = (asr_loaded or not require_asr) and (ocr_loaded or not require_ocr)
    body = {"status": "UP" if available else "DOWN", "asrLoaded": asr_loaded, "ocrLoaded": ocr_loaded}
    return JSONResponse(body, status_code=200 if body["status"] == "UP" else 503)


@app.get("/metrics")
def metrics(x_metrics_key: str | None = Header(default=None, alias="X-Metrics-Key")) -> Response:
    if x_metrics_key is None or not hmac.compare_digest(x_metrics_key, METRICS_KEY):
        raise HTTPException(status_code=401, detail="invalid metrics credential")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def decode_filename_header(value: str) -> str:
    """Java 端 HttpRequest 的 header 值只接受 ASCII 可见字符；中文等非 ASCII
    文件名在发送前做了 application/x-www-form-urlencoded 百分号编码
    （见 backend HttpMultimodalDocumentParser.buildRequest），这里对称解码还原。"""
    return unquote_plus(value)


@app.post("/v1/parse")
async def parse(
    request: Request,
    authorization: str | None = Header(default=None),
    x_document_id: str = Header(alias="X-Document-Id"),
    x_document_filename: str = Header(alias="X-Document-Filename"),
    x_source_path: str | None = Header(default=None, alias="X-Source-Path"),
) -> JSONResponse:
    started = time.perf_counter()
    x_document_filename = decode_filename_header(x_document_filename)
    suffix = Path(x_document_filename).suffix.lower()
    metric_format = suffix.lstrip(".") if suffix in SUPPORTED_SUFFIXES else "unsupported"
    outcome = "500"
    size = 0
    temp_path: Path | None = None
    slot_acquired = False
    IN_PROGRESS.inc()
    try:
        _require_auth(authorization)
        safe_name = Path(x_document_filename).name
        if not safe_name or len(safe_name) > 500 or safe_name != x_document_filename or "\x00" in safe_name:
            raise HTTPException(status_code=400, detail="invalid filename")

        if suffix not in SUPPORTED_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"unsupported format: {suffix}")

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="invalid content-length") from exc
            if declared_size < 1:
                raise HTTPException(status_code=400, detail="empty file")
            if declared_size > MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail="file exceeds parser limit")

        await _slots.acquire()
        slot_acquired = True
        with tempfile.NamedTemporaryFile(prefix="rag-parse-", suffix=suffix, delete=False) as target:
            temp_path = Path(target.name)
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="file exceeds parser limit")
                target.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="empty file")

        result = await asyncio.to_thread(parse_document, temp_path, safe_name)
        result.setdefault("metadata", {})
        result["metadata"].update({
            "parser": "rag-multimodal-gateway",
            "parserVersion": app.version,
            "documentId": x_document_id,
            "sourcePath": x_source_path or "",
        })
        outcome = "success"
        return JSONResponse(result)
    except HTTPException as exc:
        outcome = str(exc.status_code)
        raise
    except ParseError as exc:
        outcome = "422"
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ParserUnavailableError as exc:
        outcome = "503"
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        if slot_acquired:
            _slots.release()
        IN_PROGRESS.dec()
        BYTES.labels(metric_format).inc(size)
        REQUESTS.labels(metric_format, outcome).inc()
        DURATION.labels(metric_format).observe(time.perf_counter() - started)


def _require_auth(authorization: str | None) -> None:
    expected = f"Bearer {API_KEY}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="invalid parser credential")
