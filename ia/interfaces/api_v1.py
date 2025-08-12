from __future__ import annotations

import os
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..domain.models import (
    RunsResponse, SeriesResponse, TopDriftsResponse,
    AnomalySummary, AnomalyTimelineResponse, RunDetailResponse,
)
from ..app.usecases import (
    list_runs_usecase, series_usecase, top_drifts_usecase,
)
from ..utils.io import read_json, read_jsonl


def create_api_router(archive_root: str):
    router = APIRouter(prefix="/api/v1")

    @router.get("/runs", response_model=RunsResponse)
    def runs(start: Optional[str] = Query(None), end: Optional[str] = Query(None), page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)):
        data = list_runs_usecase(archive_root, start, end)
        total = data["total"]
        start_idx = (page - 1) * page_size
        end_idx = min(start_idx + page_size, total)
        page_items = data["items"][start_idx:end_idx]
        return {"runs": page_items, "page": page, "page_size": page_size, "total": total}

    @router.get("/dashboard/series", response_model=SeriesResponse)
    def series(metric: str = Query("System Benchmarks Index Score")):
        return series_usecase(archive_root, metric)

    @router.get("/dashboard/top-drifts", response_model=TopDriftsResponse)
    def top_drifts(window: int = Query(5, ge=1, le=50), limit: int = Query(10, ge=1, le=50)):
        return top_drifts_usecase(archive_root, window, limit)

    @router.get("/anomalies/summary", response_model=AnomalySummary)
    def anomalies_summary():
        from ..reporting.aggregate import collect_runs
        runs = collect_runs(archive_root, None, None)
        total = 0
        sev = {"high": 0, "medium": 0, "low": 0}
        abnormal = 0
        for r in runs:
            s = r.get("summary", {}) or {}
            sc = s.get("severity_counts", {}) or {}
            total += s.get("total_anomalies", 0)
            for k in ("high", "medium", "low"):
                sev[k] += sc.get(k, 0)
            if s.get("total_anomalies", 0) > 0:
                abnormal += 1
        return {"total_anomalies": total, "severity_counts": sev, "abnormal_runs": abnormal, "total_runs": len(runs)}

    @router.get("/anomalies/timeline", response_model=AnomalyTimelineResponse)
    def anomalies_timeline():
        from ..reporting.aggregate import collect_runs
        from collections import defaultdict
        runs = collect_runs(archive_root, None, None)
        m = defaultdict(lambda: {"total": 0, "high": 0, "medium": 0, "low": 0})
        for r in runs:
            d = r.get("date")
            s = r.get("summary", {}) or {}
            sc = s.get("severity_counts", {}) or {}
            m[d]["total"] += s.get("total_anomalies", 0)
            m[d]["high"] += sc.get("high", 0)
            m[d]["medium"] += sc.get("medium", 0)
            m[d]["low"] += sc.get("low", 0)
        out = []
        for d in sorted(m.keys()):
            out.append({"date": d, **m[d]})
        return {"items": out}

    @router.get("/run/{rel_path:path}", response_model=RunDetailResponse)
    def run_detail(rel_path: str):
        norm = os.path.normpath(rel_path).lstrip("/")
        run_dir = os.path.join(archive_root, norm)
        if not run_dir.startswith(os.path.abspath(archive_root)) and not os.path.isabs(norm):
            return JSONResponse(status_code=400, content={"error": "bad path"})
        meta_path = os.path.join(run_dir, "meta.json")
        if not os.path.exists(meta_path):
            return JSONResponse(status_code=404, content={"error": "run not found"})
        meta = read_json(meta_path)
        summary = read_json(os.path.join(run_dir, "summary.json")) if os.path.exists(
            os.path.join(run_dir, "summary.json")) else {"total_anomalies": 0}
        anomalies = read_jsonl(os.path.join(run_dir, "anomalies.k2.jsonl")) if os.path.exists(
            os.path.join(run_dir, "anomalies.k2.jsonl")) else []
        ub = read_jsonl(os.path.join(run_dir, "ub.jsonl")) if os.path.exists(
            os.path.join(run_dir, "ub.jsonl")) else []
        return {"run_dir": run_dir, "rel": norm, "meta": meta, "summary": summary, "anomalies": anomalies, "ub": ub}

    return router
