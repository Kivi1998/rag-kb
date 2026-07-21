#!/usr/bin/env python3
"""从真实 HTTP 直传入口到解析产物和 ES 写入的 5000 份生产同构验收。"""

from __future__ import annotations

import json
import math
import os
import platform
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import psycopg
import requests
from minio import Minio


API_BASE = os.getenv("ACCEPTANCE_API_BASE", "http://api:8090")
DB_URL = os.getenv("ACCEPTANCE_DB_URL", "postgresql://ragkb:ragkb-acceptance@postgres:5432/ragkb")
MINIO_ENDPOINT = os.getenv("ACCEPTANCE_MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("ACCEPTANCE_MINIO_ACCESS_KEY", "ragacceptance")
MINIO_SECRET_KEY = os.getenv("ACCEPTANCE_MINIO_SECRET_KEY", "ragacceptance-secret")
MINIO_BUCKET = os.getenv("ACCEPTANCE_MINIO_BUCKET", "rag-kb")
ES_ENDPOINT = os.getenv("ACCEPTANCE_ES_ENDPOINT", "http://elasticsearch:9200")
ES_INDEX = os.getenv("ACCEPTANCE_ES_INDEX", "rag_chunks_acceptance")
FIXTURE_ROOT = Path(os.getenv("ACCEPTANCE_FIXTURE_ROOT", "/fixtures"))
REPORT_PATH = Path(os.getenv("ACCEPTANCE_REPORT_PATH", "/reports/acceptance-report.json"))
CONCURRENCY = int(os.getenv("ACCEPTANCE_UPLOAD_CONCURRENCY", "24"))
TIMEOUT_SECONDS = int(os.getenv("ACCEPTANCE_TIMEOUT_SECONDS", "3600"))
HTTP_TIMEOUT = float(os.getenv("ACCEPTANCE_HTTP_TIMEOUT_SECONDS", "120"))
MODE = os.getenv("ACCEPTANCE_MODE", "full").strip().lower()
if MODE not in {"full", "smoke"}:
    raise RuntimeError("ACCEPTANCE_MODE 只能是 full 或 smoke")
EXPECTED_TOTAL = 0 if MODE == "smoke" else int(os.getenv("ACCEPTANCE_DOCUMENT_COUNT", "5000"))

_thread_local = threading.local()


def session() -> requests.Session:
    value = getattr(_thread_local, "session", None)
    if value is None:
        value = requests.Session()
        _thread_local.session = value
    return value


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, math.floor((len(ordered) - 1) * fraction))]


def api(method: str, path: str, *, token: str | None = None, org_id: str | None = None,
        headers: dict[str, str] | None = None, payload: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201)) -> dict[str, Any]:
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if org_id:
        request_headers["X-Org-Id"] = org_id
    response = session().request(method, API_BASE + path, headers=request_headers, json=payload,
                                 timeout=HTTP_TIMEOUT)
    if response.status_code not in expected:
        raise RuntimeError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
    body = response.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{method} {path} business error: {body}")
    return body.get("data")


def wait_ready(url: str, timeout: int = 600) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=5)
            last = response.text
            if response.status_code == 200:
                return response.json()
        except requests.RequestException as exc:
            last = str(exc)
        time.sleep(2)
    raise RuntimeError(f"服务未就绪: {url}: {last}")


def bootstrap() -> tuple[str, str, str]:
    run_id = uuid.uuid4().hex[:10]
    email = f"acceptance-{run_id}@example.com"
    registration = api("POST", "/api/v1/auth/register", payload={
        "email": email, "password": "Acceptance2026!", "displayName": "Acceptance Runner"
    })
    token = registration["token"]
    organization = api("POST", "/api/v1/organizations", token=token,
                       payload={"name": f"Production Acceptance {run_id}"})
    org_id = organization["id"]
    knowledge_base = api("POST", "/api/v1/knowledge-bases", token=token, org_id=org_id,
                         payload={"name": f"Multimodal 5000 {run_id}"})
    return token, org_id, knowledge_base["id"]


def unique_payload(base: bytes, index: int, kind: str) -> bytes:
    marker = f"RAG-ACCEPTANCE-ID:{kind}:{index:05d}"
    if kind == "structured":
        # JSON 语法严格,不能像文本/代码文件那样直接在末尾追加一行——那样会破坏
        # 闭合结构,导致 json.loads() 抛 "Extra data" 而不是产出唯一内容。往顶层
        # 对象里加一个字段,保持语法合法,同时仍然带上唯一标记。
        payload = json.loads(base)
        if isinstance(payload, dict):
            payload["acceptanceMarker"] = marker
            return json.dumps(payload).encode()
    return base + f"\n{marker}\n".encode()


def upload_one(index: int, fixture: dict[str, Any], base: bytes,
               token: str, org_id: str, kb_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    original = Path(fixture["name"])
    filename = f"{original.stem}-{index:05d}{original.suffix}"
    payload = unique_payload(base, index, fixture["kind"])
    initiated = api("POST", "/api/v1/documents/uploads", token=token, org_id=org_id,
                    headers={"Idempotency-Key": f"acceptance-{index:05d}-{fixture['kind']}"},
                    payload={"kbId": kb_id, "fileName": filename, "sizeBytes": len(payload)})
    put = session().put(initiated["uploadUrl"], headers=initiated.get("headers") or {}, data=payload,
                        timeout=HTTP_TIMEOUT)
    if put.status_code < 200 or put.status_code >= 300:
        raise RuntimeError(f"PUT {filename} -> {put.status_code}: {put.text[:200]}")
    completed = api("POST", f"/api/v1/documents/uploads/{initiated['sessionId']}/complete",
                    token=token, org_id=org_id)
    return {
        "index": index,
        "kind": fixture["kind"],
        "expected": fixture["expected"],
        "filename": filename,
        "documentId": completed["documentId"],
        "jobId": completed["jobId"],
        "latencySeconds": time.perf_counter() - started,
    }


def build_workload(fixtures: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    workload: list[tuple[int, dict[str, Any]]] = []
    index = 0
    for fixture in fixtures:
        repetitions = 1 if MODE == "smoke" else int(fixture["weight"])
        for _ in range(repetitions):
            workload.append((index, fixture))
            index += 1
    if len(workload) != EXPECTED_TOTAL:
        raise RuntimeError(f"样本权重总数 {len(workload)} != {EXPECTED_TOTAL}")
    return workload


def status_counts(kb_id: str) -> dict[str, int]:
    with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
        cursor.execute("select status, count(*) from document where kb_id = %s group by status", (kb_id,))
        return {status: count for status, count in cursor.fetchall()}


def wait_ingestion(kb_id: str) -> tuple[dict[str, int], float]:
    started = time.monotonic()
    deadline = started + TIMEOUT_SECONDS
    last: dict[str, int] = {}
    while time.monotonic() < deadline:
        last = status_counts(kb_id)
        terminal = last.get("READY", 0) + last.get("FAILED", 0)
        print(json.dumps({"event": "ingestion_progress", "counts": last}, ensure_ascii=False), flush=True)
        if terminal == EXPECTED_TOTAL:
            return last, time.monotonic() - started
        time.sleep(5)
    raise RuntimeError(f"摄取超时: {last}")


def verify_database(kb_id: str) -> dict[str, Any]:
    with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
        cursor.execute("""
            select count(*), count(distinct content_sha256),
                   count(*) filter (where parse_artifact_path is not null),
                   count(*) filter (where parsed_at is not null),
                   count(*) filter (where status = 'FAILED')
              from document where kb_id = %s
        """, (kb_id,))
        total, hashes, artifacts, parsed, failed = cursor.fetchone()
        cursor.execute("select version from flyway_schema_history order by installed_rank desc limit 1")
        migration = cursor.fetchone()[0]
        cursor.execute("""
            select coalesce(max(attempt), 0), count(*) filter (where attempt > 1)
              from ingestion_job where kb_id = %s
        """, (kb_id,))
        max_attempt, retried_jobs = cursor.fetchone()
    result = {"documents": total, "uniqueHashes": hashes, "artifactPaths": artifacts,
              "parsedTimestamps": parsed, "failed": failed, "flywayVersion": migration,
              "maxAttempt": max_attempt, "retriedJobs": retried_jobs}
    core_values = (total, hashes, artifacts, parsed, failed)
    # 迁移脚本已从 V001 增长到 V015(编写本检查时只有到 V011;Java 退役后 backend-py
    # 借用同一套 Flyway 脚本执行建表,见 backend-py/db/migration/),这里同步更新到
    # 当前实际的最新版本号,而不是继续断言一个已经过时的历史值。
    migration_is_current = str(migration).lstrip("0") == "15"
    if core_values != (EXPECTED_TOTAL, EXPECTED_TOTAL, EXPECTED_TOTAL, EXPECTED_TOTAL, 0) \
            or not migration_is_current:
        raise RuntimeError(f"数据库验收失败: {result}")
    return result


def representative_rows(kb_id: str, representatives: dict[str, dict[str, Any]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
        for kind, item in representatives.items():
            cursor.execute("select parse_artifact_path, parser_name from document where id = %s and kb_id = %s",
                           (item["documentId"], kb_id))
            row = cursor.fetchone()
            if row is None or row[0] is None:
                raise RuntimeError(f"缺少代表样本解析产物: {kind}")
            result[kind] = (row[0], row[1])
    return result


def verify_artifacts(kb_id: str, representatives: dict[str, dict[str, Any]]) -> dict[str, Any]:
    client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False)
    rows = representative_rows(kb_id, representatives)
    evidence: dict[str, Any] = {}
    for kind, (object_key, parser_name) in rows.items():
        response = client.get_object(MINIO_BUCKET, object_key)
        try:
            parsed = json.loads(response.read())
        finally:
            response.close()
            response.release_conn()
        text = "\n".join(section.get("text", "") for section in parsed.get("sections", []))
        expected = representatives[kind]["expected"]
        if expected.lower() not in text.lower():
            raise RuntimeError(f"{kind} 解析内容缺少标记: expected={expected!r}, text={text[:300]!r}")
        metadata = parsed.get("metadata", {})
        if kind in {"pdf-ocr", "pptx-ocr", "docx-ocr", "image-png", "image-jpg", "image-tiff"}:
            ocr_count = int(metadata.get("ocrPageCount", metadata.get("ocrImageCount", "0")))
            if ocr_count < 1:
                raise RuntimeError(f"{kind} 未提供 OCR 证据: {metadata}")
        if kind.startswith("audio-") or kind.startswith("video-"):
            if not any(section.get("metadata", {}).get("timeRange") for section in parsed.get("sections", [])):
                raise RuntimeError(f"{kind} 缺少字幕时间戳")
        evidence[kind] = {"parser": parser_name, "sections": len(parsed.get("sections", [])),
                          "metadata": metadata}
    object_count = sum(1 for _ in client.list_objects(MINIO_BUCKET, recursive=True))
    if object_count < EXPECTED_TOTAL * 2:
        raise RuntimeError(f"MinIO 对象数不足: {object_count}")
    return {"representatives": evidence, "objectCount": object_count}


def verify_elasticsearch() -> dict[str, int]:
    response = requests.get(f"{ES_ENDPOINT}/{ES_INDEX}/_count", timeout=30)
    response.raise_for_status()
    count = int(response.json()["count"])
    if count < EXPECTED_TOTAL:
        raise RuntimeError(f"ES chunk 数量不足: {count} < {EXPECTED_TOTAL}")
    return {"chunks": count}


def main() -> None:
    global EXPECTED_TOTAL
    overall_started = time.perf_counter()
    wait_ready(API_BASE + "/health")
    wait_ready("http://model-stub:8082/health")
    wait_ready(ES_ENDPOINT)
    fixtures = json.loads((FIXTURE_ROOT / "fixtures.json").read_text(encoding="utf-8"))
    if MODE == "smoke":
        EXPECTED_TOTAL = len(fixtures)
    workload = build_workload(fixtures)
    fixture_bytes = {item["name"]: (FIXTURE_ROOT / item["name"]).read_bytes() for item in fixtures}
    token, org_id, kb_id = bootstrap()

    uploaded: list[dict[str, Any]] = []
    failures: list[str] = []
    upload_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(upload_one, index, fixture, fixture_bytes[fixture["name"]], token, org_id, kb_id)
                   for index, fixture in workload]
        for completed, future in enumerate(as_completed(futures), start=1):
            try:
                uploaded.append(future.result())
            except Exception as exc:  # 验收报告需聚合所有失败而不是首错退出
                failures.append(str(exc))
            if completed % 250 == 0:
                print(json.dumps({"event": "upload_progress", "completed": completed,
                                  "failed": len(failures)}, ensure_ascii=False), flush=True)
    upload_elapsed = time.perf_counter() - upload_started
    if failures or len(uploaded) != EXPECTED_TOTAL:
        raise RuntimeError(f"上传失败 {len(failures)}/{EXPECTED_TOTAL}: {failures[:10]}")

    representatives: dict[str, dict[str, Any]] = {}
    for item in uploaded:
        representatives.setdefault(item["kind"], item)
    counts, ingestion_elapsed = wait_ingestion(kb_id)
    if counts != {"READY": EXPECTED_TOTAL}:
        with psycopg.connect(DB_URL) as connection, connection.cursor() as cursor:
            cursor.execute("select id, name, status, last_error from document where kb_id=%s and status <> 'READY' limit 20",
                           (kb_id,))
            errors = cursor.fetchall()
        raise RuntimeError(f"未全部 READY: counts={counts}, sample={errors}")

    database = verify_database(kb_id)
    artifacts = verify_artifacts(kb_id, representatives)
    elasticsearch = verify_elasticsearch()
    latencies = [item["latencySeconds"] for item in uploaded]
    report = {
        "result": "PASS",
        "mode": MODE,
        "scope": "HTTP initiate -> presigned PUT -> complete -> PostgreSQL worker -> parser -> artifact -> embedding protocol -> Elasticsearch",
        "documents": EXPECTED_TOTAL,
        "formats": {fixture["kind"]: (1 if MODE == "smoke" else fixture["weight"])
                    for fixture in fixtures},
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "uploadConcurrency": CONCURRENCY},
        "upload": {"success": len(uploaded), "failed": 0, "elapsedSeconds": round(upload_elapsed, 3),
                   "documentsPerSecond": round(EXPECTED_TOTAL / upload_elapsed, 3),
                   "latencyMs": {"mean": round(statistics.fmean(latencies) * 1000, 3),
                                 "p95": round(percentile(latencies, 0.95) * 1000, 3),
                                 "p99": round(percentile(latencies, 0.99) * 1000, 3),
                                 "max": round(max(latencies) * 1000, 3)}},
        "ingestion": {"counts": counts, "waitSecondsAfterUpload": round(ingestion_elapsed, 3)},
        "database": database,
        "artifacts": artifacts,
        "elasticsearch": elasticsearch,
        "totalElapsedSeconds": round(time.perf_counter() - overall_started, 3),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
