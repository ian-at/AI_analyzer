from __future__ import annotations

import hashlib
import json
from typing import Any, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse, Response


def _compute_etag(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    h = hashlib.sha1(data).hexdigest()
    return 'W/"' + h + '"'


def json_with_cache(request: Request, payload: Any, max_age: int = 20) -> JSONResponse:
    etag = _compute_etag(payload)
    inm = request.headers.get("If-None-Match")
    if inm and inm == etag:
        # 304 Not Modified；必须返回裸 Response，且不携带 body，避免 gzip 引发 Content-Length 冲突
        resp = Response(status_code=304)
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = f"public, max-age={max_age}"
        return resp
    resp = JSONResponse(content=payload)
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = f"public, max-age={max_age}"
    return resp
