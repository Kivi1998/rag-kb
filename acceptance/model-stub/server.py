#!/usr/bin/env python3
"""生产验收栈专用的确定性 Embedding 协议替身。

它只验证 RAG 摄取的 HTTP 协议、分批、维度和 ES 写入，不用于检索质量签字。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DIMENSIONS = 8
FAIL_FIRST_N = int(os.getenv("MODEL_STUB_FAIL_FIRST_N", "0"))
_request_count = 0
_request_lock = threading.Lock()


def vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [((digest[index] / 255.0) * 2.0) - 1.0 for index in range(DIMENSIONS)]
    norm = sum(value * value for value in values) ** 0.5 or 1.0
    return [round(value / norm, 7) for value in values]


class Handler(BaseHTTPRequestHandler):
    server_version = "rag-acceptance-model/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "UP", "dimensions": DIMENSIONS})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/embeddings":
            self._json(404, {"error": "not found"})
            return
        global _request_count
        with _request_lock:
            _request_count += 1
            request_number = _request_count
        if request_number <= FAIL_FIRST_N:
            self._json(503, {"error": "intentional transient acceptance failure",
                             "requestNumber": request_number})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(size))
            inputs = request.get("input")
            if not isinstance(inputs, list) or not all(isinstance(item, str) and item for item in inputs):
                raise ValueError("input must be a non-empty string list")
            data = [{"index": index, "embedding": vector(text)} for index, text in enumerate(inputs)]
            self._json(200, {"object": "list", "model": "acceptance-embedding-v1", "data": data})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, message: str, *args: object) -> None:
        print(json.dumps({"event": "model_request", "message": message % args}, ensure_ascii=False), flush=True)

    def _json(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8082), Handler).serve_forever()
