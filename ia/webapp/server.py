from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_env_config
from ..analyzer.k2_client import K2Client
from ..orchestrator.pipeline import reanalyze_missing
from ..interfaces.http_utils import json_with_cache
from ..domain.models import DefectAnnotation


app = FastAPI(title="IA Service")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ARCHIVE_ROOT = os.environ.get("IA_ARCHIVE", "./archive")
os.makedirs(ARCHIVE_ROOT, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=2)

# 简易内存缓存（TTL）
_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL_SECONDS = 20


def _cache_get(key: str):
    import time as _t
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        if _t.time() - item.get("ts", 0) > _CACHE_TTL_SECONDS:
            _cache.pop(key, None)
            return None
        return item.get("val")


def _cache_set(key: str, val: Any):
    import time as _t
    with _cache_lock:
        _cache[key] = {"ts": _t.time(), "val": val}


def _start_job(fn, *args, **kwargs) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    def _run():
        try:
            res = fn(*args, **kwargs)
            with _jobs_lock:
                _jobs[job_id] = {"status": "completed", "result": res}
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {"status": "failed", "error": str(e)}

    _pool.submit(_run)
    return job_id


def _start_job_with_id(fn_with_job_id, *args, **kwargs) -> str:
    """启动一个可在执行过程中按 job_id 更新进度的任务。
    fn_with_job_id 接收第一个参数为 job_id。
    """
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "current": 0}

    def _run():
        try:
            res = fn_with_job_id(job_id, *args, **kwargs)
            with _jobs_lock:
                _jobs[job_id] = {"status": "completed", "result": res}
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {"status": "failed", "error": str(e)}

    _pool.submit(_run)
    return job_id


@app.post("/api/v1/actions/reanalyze-missing")
def action_reanalyze_missing(days: int = Query(3), no_fallback: bool = Query(True)):
    cfg = load_env_config(
        source_url=None, archive_root=ARCHIVE_ROOT, days=days)
    k2 = K2Client(cfg.model) if cfg.model.enabled else None
    if no_fallback and (not k2 or not k2.enabled()):
        return JSONResponse(status_code=400, content={"error": "严格K2模式需要提供OPENAI_*配置"})

    def _work():
        done = reanalyze_missing(ARCHIVE_ROOT, k2 if (k2 and k2.enabled()) else (
            None if not no_fallback else k2), days=days)
        # 仅前端渲染聚合报告：后端不再生成 dashboard.html
        return {"processed": len(done), "archive": ARCHIVE_ROOT}

    job_id = _start_job(_work)
    return {"job_id": job_id}


@app.post("/actions/reanalyze-missing")
def action_reanalyze_missing_legacy(days: int = Query(3), no_fallback: bool = Query(True)):
    # 兼容旧端点
    return action_reanalyze_missing(days, no_fallback)


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        j = _jobs.get(job_id)
    if not j:
        return JSONResponse(status_code=404, content={"error": "not found"})
    # 兼容旧状态字段
    if j.get("status") == "done":
        j = {**j, "status": "completed"}
    if j.get("status") == "error":
        j = {**j, "status": "failed"}
    return j


@app.get("/jobs/{job_id}")
def get_job_legacy(job_id: str):
    # 兼容旧端点
    return get_job(job_id)


# 已完成迁移，移除 legacy 端点 /api/runs


@app.get("/api/v1/runs")
def api_runs_v1(
    request: Request,
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    sort_by: str = Query("date", pattern="^(date|total_anomalies|patch_id)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    abnormal_only: bool = Query(False),
    engine: Optional[str] = Query(None),
    patch_id: Optional[str] = Query(None),
    fields: Optional[str] = Query(None, description="逗号分隔的字段列表，用于字段裁剪"),
):
    from ..app.usecases import list_runs_usecase
    key = f"runs:{start}:{end}"
    cached = _cache_get(key)
    if cached is None:
        cached = list_runs_usecase(ARCHIVE_ROOT, start, end)
        _cache_set(key, cached)
    items = list(cached["items"])  # 基础列表（已按日期新→旧）
    # 筛选
    if abnormal_only:
        items = [r for r in items if (r.get("total_anomalies") or 0) > 0]
    if engine:
        items = [r for r in items if str(
            (r.get("engine") or {}).get("name", "")).lower() == engine.lower()]
    if patch_id:
        items = [r for r in items if str(
            r.get("patch_id", "")) == str(patch_id)]
    # 排序
    reverse = (order == "desc")
    if sort_by == "date":
        items.sort(key=lambda r: r.get("date", ""), reverse=reverse)
    elif sort_by == "total_anomalies":
        items.sort(key=lambda r: (
            r.get("total_anomalies") or 0), reverse=reverse)
    elif sort_by == "patch_id":
        items.sort(key=lambda r: (int(r.get("patch_id")) if str(
            r.get("patch_id", "")).isdigit() else -1), reverse=reverse)
    total = len(items)
    # 分页
    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, total)
    page_items = items[start_idx:end_idx]
    # 字段裁剪
    if fields:
        allow = {f.strip() for f in fields.split(",") if f.strip()}
        page_items = [{k: v for k, v in r.items() if k in allow}
                      for r in page_items]
    payload = {"runs": page_items, "page": page,
               "page_size": page_size, "total": total}
    return json_with_cache(request, payload)


# 已完成迁移，移除 legacy 端点 /api/dashboard/series


@app.get("/api/v1/dashboard/series")
def api_series_v1(request: Request, metric: str = Query("System Benchmarks Index Score")):
    from ..app.usecases import series_usecase
    cache_key = f"series:{metric}"
    cached = _cache_get(cache_key)
    if cached is None:
        cached = series_usecase(ARCHIVE_ROOT, metric)
        _cache_set(cache_key, cached)
    return json_with_cache(request, cached)


@app.get("/api/v1/metrics")
def api_metrics(request: Request):
    # 返回可用的 metric keys（suite::case::metric）。前端可基于末尾名称显示
    cache_key = "metrics:list"
    cached = _cache_get(cache_key)
    if cached is None:
        from ..reporting.aggregate import collect_runs, build_metric_series
        runs = collect_runs(ARCHIVE_ROOT, None, None)
        series = build_metric_series(runs)
        keys = sorted(series.keys())
        # 限制最多 500 以避免响应过大
        cached = {"metrics": keys[:500]}
        _cache_set(cache_key, cached)
    return json_with_cache(request, cached)


@app.get("/api/v1/series")
def api_series_alias(request: Request, metric: str = Query("System Benchmarks Index Score")):
    # 兼容提议中的更短路径
    return api_series_v1(request, metric)


# 已完成迁移，移除 legacy 端点 /api/anomalies/summary


@app.get("/api/v1/anomalies/summary")
def api_anom_summary_v1(request: Request):
    from ..reporting.aggregate import collect_runs
    cache_key = "anom:summary"
    cached = _cache_get(cache_key)
    if cached is None:
        runs = collect_runs(ARCHIVE_ROOT, None, None)
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
        cached = {"total_anomalies": total, "severity_counts": sev,
                  "abnormal_runs": abnormal, "total_runs": len(runs)}
        _cache_set(cache_key, cached)
    return json_with_cache(request, cached)


# 已完成迁移，移除 legacy 端点 /api/dashboard/top-drifts


@app.get("/api/v1/dashboard/top-drifts")
def api_top_drifts_v1(request: Request, window: int = Query(5, ge=1, le=50), limit: int = Query(10, ge=1, le=50)):
    from ..app.usecases import top_drifts_usecase
    cache_key = f"top:{window}:{limit}"
    cached = _cache_get(cache_key)
    if cached is None:
        cached = top_drifts_usecase(ARCHIVE_ROOT, window, limit)
        _cache_set(cache_key, cached)
    return json_with_cache(request, cached)


@app.get("/api/v1/top-drifts")
def api_top_drifts_alias(request: Request, window: int = Query(5, ge=1, le=50), limit: int = Query(10, ge=1, le=50)):
    # 兼容提议中的更短路径
    return api_top_drifts_v1(request, window, limit)


# 已完成迁移，移除 legacy 端点 /api/anomalies/timeline


@app.get("/api/v1/anomalies/timeline")
def api_anom_timeline_v1(request: Request):
    from ..reporting.aggregate import collect_runs
    from collections import defaultdict
    cache_key = "timeline"
    cached = _cache_get(cache_key)
    if cached is None:
        runs = collect_runs(ARCHIVE_ROOT, None, None)
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
        cached = {"items": out}
        _cache_set(cache_key, cached)
    return json_with_cache(request, cached)


# 已完成迁移，移除 legacy 端点 /api/run/{rel}


@app.get("/api/v1/run/{rel_path:path}")
def api_run_detail_v1(request: Request, rel_path: str):
    # 读取单个 run 的 meta/summary/anomalies/ub
    # 安全限制：不得跳出 archive 根目录
    # 规范化并进行基于绝对路径的安全校验，防止目录穿越
    abs_root = os.path.abspath(ARCHIVE_ROOT)
    norm = os.path.normpath("/" + rel_path).lstrip("/")
    run_dir = os.path.abspath(os.path.join(abs_root, norm))
    try:
        # 要求 run_dir 必须在 abs_root 之内
        if os.path.commonpath([abs_root, run_dir]) != abs_root:
            return JSONResponse(status_code=400, content={"error": "bad path", "abs_root": abs_root, "run_dir": run_dir, "rel": norm})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": "bad path", "reason": str(e), "abs_root": abs_root, "run_dir": run_dir, "rel": norm})
    meta_path = os.path.join(run_dir, "meta.json")
    if not os.path.exists(meta_path):
        return JSONResponse(status_code=404, content={"error": "run not found"})
    from ..utils.io import read_json, read_jsonl
    meta = read_json(meta_path)
    summary = read_json(os.path.join(run_dir, "summary.json")) if os.path.exists(
        os.path.join(run_dir, "summary.json")) else {"total_anomalies": 0}
    anomalies = read_jsonl(os.path.join(run_dir, "anomalies.k2.jsonl")) if os.path.exists(
        os.path.join(run_dir, "anomalies.k2.jsonl")) else []
    ub = read_jsonl(os.path.join(run_dir, "ub.jsonl")) if os.path.exists(
        os.path.join(run_dir, "ub.jsonl")) else []
    payload = {"run_dir": run_dir, "rel": norm, "meta": meta,
               "summary": summary, "anomalies": anomalies, "ub": ub}
    return json_with_cache(request, payload)


@app.get("/api/v1/runs/{rel_path:path}")
def api_run_detail_alias(request: Request, rel_path: str):
    # 兼容资源命名复数形式
    return api_run_detail_v1(request, rel_path)


@app.post("/api/v1/run/{rel_path:path}/defect")
def annotate_defect(rel_path: str, body: DefectAnnotation):
    # 保存人工标注/备注
    norm = os.path.normpath(rel_path).lstrip("/")
    run_dir = os.path.join(ARCHIVE_ROOT, norm)
    if not os.path.exists(os.path.join(run_dir, "meta.json")):
        return JSONResponse(status_code=404, content={"error": "run not found"})
    from ..utils.io import write_json, read_json
    import time as _t
    path = os.path.join(run_dir, "defect.json")
    payload = {**body.model_dump(exclude_none=True),
               "updated_at": int(_t.time())}
    try:
        # 合并原有标注
        if os.path.exists(path):
            old = read_json(path) or {}
        else:
            old = {}
        old.update(payload)
        write_json(path, old)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"ok": True, "path": path}


@app.post("/api/v1/runs/{rel_path:path}/defect")
def annotate_defect_alias(rel_path: str, body: DefectAnnotation):
    # 复数路径别名
    return annotate_defect(rel_path, body)


# 静态托管 archive 目录供前端直接访问 report.html/dashboard.html
app.mount("/files", StaticFiles(directory=ARCHIVE_ROOT), name="files")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index_redirect():
    # 优先跳转到新 React UI，如不存在则回退到旧静态页
    ui_index = os.path.join(STATIC_DIR, "ui", "index.html")
    if os.path.exists(ui_index):
        return RedirectResponse(url="/static/ui/index.html")
    return RedirectResponse(url="/static/index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/v1/actions/reanalyze-recent")
def action_reanalyze_recent(limit: int = Query(10), no_fallback: bool = Query(False)):
    """主动触发：对最近 N 个 run 执行解析+分析（K2 或启发式）并刷新 summary，引擎信息写入 summary.analysis_engine。"""
    cfg = load_env_config(
        source_url=None, archive_root=ARCHIVE_ROOT, days=None)
    k2 = K2Client(cfg.model) if cfg.model.enabled else None
    if no_fallback and (not k2 or not k2.enabled()):
        return JSONResponse(status_code=400, content={"error": "严格K2模式需要提供OPENAI_*配置"})

    def _work():
        from ..orchestrator.pipeline import reanalyze_recent_runs
        import requests

        done = reanalyze_recent_runs(ARCHIVE_ROOT, limit=limit, k2=(
            k2 if (k2 and k2.enabled()) else (None if no_fallback else k2)), force=False)

        # 更新分析状态
        try:
            engine_name = "K2" if (k2 and k2.enabled()) else (
                "Heuristic" if no_fallback else "Auto")
            status_data = {
                "last_analysis_engine": engine_name,
                "last_analysis_count": len(done),
                "last_analysis_criteria": f"最近{limit}个运行"
            }
            requests.post(
                "http://localhost:8000/api/v1/analysis/status", json=status_data)
        except:
            pass

        return {"processed": len(done), "runs": done}

    job_id = _start_job(_work)
    return {"job_id": job_id}


@app.post("/api/v1/actions/reanalyze")
def action_reanalyze_custom(
    start_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: Optional[int] = Query(None, description="限制数量"),
    engine: str = Query("auto", description="分析引擎: auto|k2|heuristic"),
    patch_ids: Optional[str] = Query(None, description="指定patch_id列表，逗号分隔")
):
    """增强的分析接口：支持时间范围、引擎选择、指定run等"""
    from datetime import datetime
    from ..reporting.aggregate import collect_runs

    cfg = load_env_config(
        source_url=None, archive_root=ARCHIVE_ROOT, days=None)
    k2 = K2Client(cfg.model) if cfg.model.enabled else None

    # 引擎选择逻辑
    use_k2 = None
    no_fallback = False
    if engine == "k2":
        if not k2 or not k2.enabled():
            return JSONResponse(status_code=400, content={"error": "K2引擎需要配置OPENAI_*环境变量"})
        use_k2 = k2
        no_fallback = True
    elif engine == "heuristic":
        use_k2 = None
        no_fallback = True
    else:  # auto
        use_k2 = k2 if (k2 and k2.enabled()) else None
        no_fallback = False

    def _work():
        from ..orchestrator.pipeline import reanalyze_runs_by_criteria
        import requests

        # 收集符合条件的runs
        all_runs = collect_runs(ARCHIVE_ROOT, None, None)
        filtered_runs = []

        for run in all_runs:
            # 时间过滤
            if start_date or end_date:
                run_date = run.get("date", "")
                if start_date and run_date < start_date:
                    continue
                if end_date and run_date > end_date:
                    continue

            # patch_id过滤 - 支持两种格式：patch_id 或 patch_id/patch_set
            if patch_ids:
                target_patches = [p.strip()
                                  for p in patch_ids.split(",") if p.strip()]
                run_patch_id = run.get("patch_id", "")
                run_patch_set = run.get("patch_set", "")
                run_full_patch = f"{run_patch_id}/{run_patch_set}" if run_patch_id and run_patch_set else run_patch_id

                # 检查是否匹配任何目标patch
                match_found = False
                for target_patch in target_patches:
                    if "/" in target_patch:
                        # 完整格式匹配：patch_id/patch_set
                        if run_full_patch == target_patch:
                            match_found = True
                            break
                    else:
                        # 只匹配patch_id
                        if run_patch_id == target_patch:
                            match_found = True
                            break

                if not match_found:
                    continue

            filtered_runs.append(run)

        # 限制数量
        if limit:
            filtered_runs = filtered_runs[:limit]

        # 执行分析
        done = reanalyze_runs_by_criteria(
            ARCHIVE_ROOT,
            runs=filtered_runs,
            k2=use_k2,
            force=True
        )

        # 更新分析状态
        try:
            criteria_desc = []
            if start_date or end_date:
                criteria_desc.append(
                    f"时间:{start_date or '*'} 到 {end_date or '*'}")
            if patch_ids:
                criteria_desc.append(f"patch:{patch_ids}")
            if limit:
                criteria_desc.append(f"限制:{limit}个")
            criteria_str = "; ".join(
                criteria_desc) if criteria_desc else "自定义条件"

            status_data = {
                "last_analysis_engine": engine.upper(),
                "last_analysis_count": len(done),
                "last_analysis_criteria": criteria_str
            }
            requests.post(
                "http://localhost:8000/api/v1/analysis/status", json=status_data)
        except:
            pass

        return {
            "processed": len(done),
            "runs": done,
            "criteria": {
                "start_date": start_date,
                "end_date": end_date,
                "limit": limit,
                "engine": engine,
                "patch_ids": patch_ids
            }
        }

    job_id = _start_job(_work)
    return {"job_id": job_id}


@app.post("/api/v1/actions/reanalyze-all-missing")
def action_reanalyze_all_missing(engine: str = Query("auto", description="分析引擎: auto|k2|heuristic")):
    """对归档中的所有运行执行分析，但仅处理尚未分析过的（anomalies.k2.jsonl 不存在或为空）。
    已分析过的将跳过，不会复分析。实时返回任务进度。"""
    from ..orchestrator.pipeline import parse_run, analyze_run
    from ..utils.io import read_jsonl
    import glob
    import requests

    cfg = load_env_config(
        source_url=None, archive_root=ARCHIVE_ROOT, days=None)
    k2 = K2Client(cfg.model) if cfg.model.enabled else None

    # 引擎选择
    use_k2 = None
    if engine == "k2":
        if not k2 or not k2.enabled():
            return JSONResponse(status_code=400, content={"error": "K2引擎需要配置OPENAI_*环境变量"})
        use_k2 = k2
    elif engine == "heuristic":
        use_k2 = None
    else:  # auto
        use_k2 = k2 if (k2 and k2.enabled()) else None

    def _work(job_id: str):
        pattern = os.path.join(ARCHIVE_ROOT, "*", "run_*")
        paths = glob.glob(pattern)
        # 仅筛选未分析的
        to_process: list[str] = []
        for run_dir in sorted(paths, key=lambda p: os.path.getmtime(p), reverse=True):
            k2_path = os.path.join(run_dir, "anomalies.k2.jsonl")
            need_analyze = (not os.path.exists(k2_path)) or (
                os.path.exists(k2_path) and os.path.getsize(k2_path) == 0)
            if need_analyze:
                to_process.append(run_dir)

        total = len(to_process)
        processed: list[str] = []
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "current": 0,
                             "total": total, "message": "开始分析未分析的运行"}

        for idx, run_dir in enumerate(to_process, start=1):
            try:
                ub_path = os.path.join(run_dir, "ub.jsonl")
                if (not os.path.exists(ub_path)) or (os.path.exists(ub_path) and os.path.getsize(ub_path) == 0):
                    parse_run(run_dir)

                # 若已有结果且非空，则跳过（安全起见再次判断）
                k2_path = os.path.join(run_dir, "anomalies.k2.jsonl")
                if os.path.exists(k2_path) and os.path.getsize(k2_path) > 0 and read_jsonl(k2_path):
                    pass
                else:
                    analyze_run(run_dir, use_k2, ARCHIVE_ROOT,
                                reuse_existing=True)
                processed.append(run_dir)
                with _jobs_lock:
                    _jobs[job_id] = {
                        "status": "running",
                        "current": idx,
                        "total": total,
                        "message": f"处理 {os.path.basename(run_dir)} ({idx}/{total})"
                    }
            except Exception as e:
                with _jobs_lock:
                    _jobs[job_id] = {
                        "status": "running",
                        "current": idx,
                        "total": total,
                        "message": f"失败 {os.path.basename(run_dir)}: {e}"
                    }

        # 更新分析状态
        try:
            engine_name = ("K2" if (use_k2 and use_k2.enabled()) else (
                "Heuristic" if engine == "heuristic" else "Auto")).upper()
            status_data = {
                "last_analysis_engine": engine_name,
                "last_analysis_count": len(processed),
                "last_analysis_criteria": "分析所有未分析"
            }
            requests.post(
                "http://localhost:8000/api/v1/analysis/status", json=status_data)
        except Exception:
            pass

        return {"processed": processed, "total": total}

    job_id = _start_job_with_id(_work)
    return {"job_id": job_id}


@app.get("/api/v1/analysis/status")
def get_analysis_status():
    """获取最后分析状态信息"""
    status_file = os.path.join(ARCHIVE_ROOT, ".analysis_status")
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                import json
                return json.load(f)
        except:
            pass
    return {
        "last_analysis_time": None,
        "last_analysis_engine": None,
        "last_analysis_count": 0,
        "last_analysis_criteria": None
    }


@app.post("/api/v1/analysis/status")
def update_analysis_status(data: dict):
    """更新分析状态（内部使用）"""
    status_file = os.path.join(ARCHIVE_ROOT, ".analysis_status")
    try:
        import json
        from datetime import datetime
        data["last_analysis_time"] = datetime.now().isoformat()
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/v1/runs/{rel_path:path}/reanalyze")
def reanalyze_single_run(
    rel_path: str,
    engine: str = Query("auto", description="分析引擎: auto|k2|heuristic")
):
    """重新分析单个运行"""
    from ..reporting.aggregate import collect_runs

    cfg = load_env_config(
        source_url=None, archive_root=ARCHIVE_ROOT, days=None)
    k2 = K2Client(cfg.model) if cfg.model.enabled else None

    # 引擎选择逻辑
    use_k2 = None
    no_fallback = False
    if engine == "k2":
        if not k2 or not k2.enabled():
            return JSONResponse(status_code=400, content={"error": "K2引擎需要配置OPENAI_*环境变量"})
        use_k2 = k2
        no_fallback = True
    elif engine == "heuristic":
        use_k2 = None
        no_fallback = True
    else:  # auto
        use_k2 = k2 if (k2 and k2.enabled()) else None
        no_fallback = False

    def _work():
        from ..orchestrator.pipeline import reanalyze_runs_by_criteria
        import requests
        import os

        # 检查运行是否存在
        run_dir = os.path.join(ARCHIVE_ROOT, rel_path)
        if not os.path.isdir(run_dir):
            return {"error": f"运行不存在: {rel_path}"}

        # 构造单个运行的数据
        run_data = {"rel": rel_path}

        # 执行分析
        done = reanalyze_runs_by_criteria(
            ARCHIVE_ROOT,
            runs=[run_data],
            k2=use_k2,
            force=True
        )

        # 更新分析状态
        try:
            status_data = {
                "last_analysis_engine": engine.upper(),
                "last_analysis_count": len(done),
                "last_analysis_criteria": f"单个运行: {rel_path}"
            }
            requests.post(
                "http://localhost:8000/api/v1/analysis/status", json=status_data)
        except:
            pass

        return {"processed": len(done), "runs": done, "rel": rel_path}

    job_id = _start_job(_work)
    return {"job_id": job_id, "rel": rel_path}


@app.post("/api/v1/actions/crawl-data")
def action_crawl_data(
    days: int = Query(7, description="爬取最近N天的数据"),
    force: bool = Query(False, description="强制重新爬取已存在的数据")
):
    """主动触发数据爬取与解析（不触发分析）。"""
    def _work():
        from ..fetcher.crawler import crawl_incremental
        from ..orchestrator.pipeline import parse_run
        import requests

        cfg = load_env_config(
            source_url=None, archive_root=ARCHIVE_ROOT, days=days)

        # 抓取
        new_runs = crawl_incremental(
            cfg.source_url, cfg.archive_root, days=days)
        # 解析（可选强制重解析）
        processed = []
        for run_dir in new_runs:
            try:
                if force:
                    parse_run(run_dir)
                else:
                    ub_path = os.path.join(run_dir, "ub.jsonl")
                    if (not os.path.exists(ub_path)) or os.path.getsize(ub_path) == 0:
                        parse_run(run_dir)
                processed.append(run_dir)
            except Exception:
                continue

        # 更新状态
        try:
            status_data = {
                "last_analysis_engine": "CRAWL",
                "last_analysis_count": len(processed),
                "last_analysis_criteria": f"爬取最近{days}天数据"
            }
            requests.post(
                "http://localhost:8000/api/v1/analysis/status", json=status_data)
        except Exception:
            pass

        return {"processed": processed}

    job_id = _start_job(_work)
    return {"job_id": job_id}

# 注意：此文件已直接实现 v1 路由，保留 legacy 端点以平滑迁移


@app.get("/api/v1/config/prompt")
def get_prompt_config():
    """获取当前提示词配置"""
    from ..analyzer.k2_client import PROMPT_SYSTEM
    return {"system_prompt": PROMPT_SYSTEM}


@app.post("/api/v1/config/prompt")
async def update_prompt_config(request: Request):
    """更新提示词配置（注意：这是运行时更新，重启后会重置）"""
    import json
    body_bytes = await request.body()
    body = json.loads(body_bytes.decode('utf-8'))
    new_prompt = body.get("system_prompt", "").strip()
    if not new_prompt:
        return JSONResponse({"error": "提示词不能为空"}, status_code=400)

    # 运行时修改（重启后重置）
    from ..analyzer import k2_client
    k2_client.PROMPT_SYSTEM = new_prompt
    return {"success": True, "message": "提示词已更新（重启后重置）"}


@app.get("/api/v1/config/thresholds")
def get_threshold_config():
    """获取当前阈值配置"""
    # 获取常量（如果模块中有定义的话）
    robust_z_threshold = 3.0  # 默认值
    pct_change_threshold = 0.3  # 默认值

    try:
        from ..analyzer.anomaly import robust_z_threshold as rzt, pct_change_threshold as pct
        robust_z_threshold = rzt if hasattr(rzt, '__float__') else 3.0
        pct_change_threshold = pct if hasattr(pct, '__float__') else 0.3
    except:
        pass

    return {
        "robust_z_threshold": robust_z_threshold,
        "pct_change_threshold": pct_change_threshold,
        "metrics_info": [
            {"name": "System Benchmarks Index Score",
                "unit": "score", "description": "UnixBench综合评分"},
            {"name": "Dhrystone 2 using register variables",
                "unit": "lps", "description": "寄存器变量Dhrystone测试"},
            {"name": "Double-Precision Whetstone",
                "unit": "MWIPS", "description": "双精度Whetstone测试"},
            {"name": "File Copy 1024 bufsize 2000 maxblocks",
                "unit": "KBps", "description": "文件拷贝测试(1024)"},
            {"name": "File Copy 256 bufsize 500 maxblocks",
                "unit": "KBps", "description": "文件拷贝测试(256)"},
            {"name": "File Copy 4096 bufsize 8000 maxblocks",
                "unit": "KBps", "description": "文件拷贝测试(4096)"},
            {"name": "Pipe Throughput", "unit": "lps", "description": "管道吞吐量测试"},
            {"name": "Pipe-based Context Switching",
                "unit": "lps", "description": "基于管道的上下文切换"},
            {"name": "Process Creation", "unit": "lps", "description": "进程创建测试"},
            {"name": "Shell Scripts (1 concurrent)",
             "unit": "lpm", "description": "单并发Shell脚本"},
            {"name": "Shell Scripts (8 concurrent)",
             "unit": "lpm", "description": "8并发Shell脚本"},
            {"name": "System Call Overhead", "unit": "lps", "description": "系统调用开销测试"}
        ]
    }


@app.post("/api/v1/config/thresholds")
async def update_threshold_config(request: Request):
    """更新阈值配置（注意：这是运行时更新，重启后会重置）"""
    import json
    body_bytes = await request.body()
    body = json.loads(body_bytes.decode('utf-8'))

    robust_z = body.get("robust_z_threshold")
    pct_change = body.get("pct_change_threshold")

    if robust_z is not None:
        if not isinstance(robust_z, (int, float)) or robust_z <= 0:
            return JSONResponse({"error": "robust_z_threshold 必须是正数"}, status_code=400)
        try:
            from ..analyzer import anomaly
            # 尝试设置模块级变量（如果存在的话）
            if hasattr(anomaly, 'ROBUST_Z_THRESHOLD'):
                anomaly.ROBUST_Z_THRESHOLD = float(robust_z)
        except:
            pass

    if pct_change is not None:
        if not isinstance(pct_change, (int, float)) or pct_change <= 0 or pct_change > 1:
            return JSONResponse({"error": "pct_change_threshold 必须在(0,1]范围内"}, status_code=400)
        try:
            from ..analyzer import anomaly
            # 尝试设置模块级变量（如果存在的话）
            if hasattr(anomaly, 'PCT_CHANGE_THRESHOLD'):
                anomaly.PCT_CHANGE_THRESHOLD = float(pct_change)
        except:
            pass

    return {"success": True, "message": "阈值已更新（重启后重置）"}
