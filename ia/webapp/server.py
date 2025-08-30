from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_env_config
from ..analyzer.k2_client import K2Client
from ..analyzer.progress_tracker import get_tracker
from ..orchestrator.pipeline import reanalyze_missing
from ..interfaces.http_utils import json_with_cache
from ..domain.models import DefectAnnotation
from ..webhook.handlers import WebhookHandler
from ..webhook.models import SimplifiedWebhookResponse


app = FastAPI(title="IA Service")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 从配置文件或环境变量加载ARCHIVE_ROOT


def _get_archive_root():
    # 优先使用环境变量，然后使用配置文件
    env_archive = os.environ.get("IA_ARCHIVE")
    if env_archive:
        return env_archive

    # 尝试从配置文件读取
    try:
        import json
        cfg_paths = ["./models_config.json",
                     "../models_config.json", "../../models_config.json"]
        for cfg_path in cfg_paths:
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    file_cfg = json.load(f)
                    return file_cfg.get("ARCHIVE_ROOT", "./archive/ub")
    except Exception:
        pass

    # 默认值
    return "./archive/ub"


ARCHIVE_ROOT = _get_archive_root()
os.makedirs(ARCHIVE_ROOT, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=24)

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


@app.get("/api/v1/unit/runs")
def api_unit_runs_v1(
    page: int = Query(1),
    page_size: int = Query(20),
    test_type: str = Query("unit"),
    start: str | None = Query(None),
    end: str | None = Query(None),
    failed_only: bool = Query(False),
    patch_id: str | None = Query(None)
):
    """获取单元测试运行列表"""
    from ..reporting.aggregate import collect_runs
    from ..parser.unit_test_parser import get_test_summary
    from ..utils.io import read_jsonl
    import os

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"
    runs = collect_runs(archive_root_unit, start, end)

    # 过滤和处理
    filtered_runs = []
    for run in runs:
        # 读取单元测试数据
        unit_file = os.path.join(run["run_dir"], "unit.jsonl")
        if os.path.exists(unit_file):
            records = read_jsonl(unit_file)
            summary = get_test_summary(records)

            # 应用过滤条件
            if failed_only and summary.get("failed", 0) == 0:
                continue
            if patch_id and run.get("patch_id") != patch_id:
                continue

            # 检查是否有分析结果
            anomaly_file = os.path.join(run["run_dir"], "anomalies.unit.jsonl")
            has_analysis = os.path.exists(
                anomaly_file) and os.path.getsize(anomaly_file) > 0

            # 读取meta.json获取首次下载时间
            meta_file = os.path.join(run["run_dir"], "meta.json")
            downloaded_at = run["date"]  # 默认使用索引中的日期
            if os.path.exists(meta_file):
                try:
                    from ..utils.io import read_json
                    meta = read_json(meta_file)
                    downloaded_at = meta.get("downloaded_at", run["date"])
                except Exception as e:
                    print(f"读取meta.json失败: {e}")
                    pass

            # 添加单元测试特定字段
            run["total_tests"] = summary.get("total", 0)
            run["passed_tests"] = summary.get("passed", 0)
            run["failed_tests"] = summary.get("failed", 0)
            run["success_rate"] = summary.get("success_rate", 0)
            run["has_analysis"] = has_analysis
            run["downloaded_at"] = downloaded_at  # 添加首次下载时间

            filtered_runs.append(run)

    # 分页
    total = len(filtered_runs)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_runs = filtered_runs[start_idx:end_idx]

    return {
        "runs": page_runs,
        "page": page,
        "page_size": page_size,
        "total": total
    }


@app.get("/api/v1/unit/summary")
def api_unit_summary():
    """获取单元测试汇总统计"""
    from ..reporting.aggregate import collect_runs
    from ..parser.unit_test_parser import get_test_summary
    from ..utils.io import read_jsonl
    import os

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"
    runs = collect_runs(archive_root_unit, None, None)

    total_runs_count = 0  # 运行记录总数
    total_test_cases_passed = 0  # 测试用例通过总数
    total_test_cases_failed = 0  # 测试用例失败总数
    success_rates = []

    for run in runs:
        unit_file = os.path.join(run["run_dir"], "unit.jsonl")
        if os.path.exists(unit_file):
            records = read_jsonl(unit_file)
            summary = get_test_summary(records)

            total_runs_count += 1
            total_test_cases_passed += summary.get("passed", 0)
            total_test_cases_failed += summary.get("failed", 0)
            success_rates.append(summary.get("success_rate", 0))

    # 修正：计算总体成功率 = 所有通过的测试用例数 / 所有测试用例总数
    total_test_cases = total_test_cases_passed + total_test_cases_failed
    avg_success_rate = round((total_test_cases_passed /
                              total_test_cases * 100), 2) if total_test_cases > 0 else 0

    # 判断趋势（简化版）
    recent_trend = "stable"
    if len(success_rates) >= 5:
        recent = success_rates[-5:]
        if recent[-1] > recent[0]:
            recent_trend = "improving"
        elif recent[-1] < recent[0]:
            recent_trend = "declining"

    return {
        "total_runs": total_runs_count,
        "total_passed": total_test_cases_passed,  # 现在是测试用例总数
        "total_failed": total_test_cases_failed,  # 现在是测试用例总数
        "average_success_rate": avg_success_rate,
        "recent_trend": recent_trend
    }


@app.get("/api/v1/unit/trend")
def api_unit_trend():
    """获取单元测试成功率趋势"""
    from ..reporting.aggregate import collect_runs
    from ..parser.unit_test_parser import get_test_summary
    from ..utils.io import read_jsonl
    import os
    from datetime import datetime, timedelta

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"

    # 获取最近30天的数据
    cutoff = datetime.now() - timedelta(days=30)
    runs = collect_runs(archive_root_unit, cutoff.strftime('%Y-%m-%d'), None)

    # 按日期分组
    daily_stats = {}
    for run in runs:
        date = run.get("date", "").split("T")[0]  # 获取日期部分
        if not date:
            continue

        unit_file = os.path.join(run["run_dir"], "unit.jsonl")
        if os.path.exists(unit_file):
            records = read_jsonl(unit_file)
            summary = get_test_summary(records)

            if date not in daily_stats:
                daily_stats[date] = {
                    "success_rates": [],
                    "failed_counts": [],
                    "total_counts": [],
                    "passed_counts": []
                }

            daily_stats[date]["success_rates"].append(
                summary.get("success_rate", 0))
            daily_stats[date]["failed_counts"].append(summary.get("failed", 0))
            daily_stats[date]["total_counts"].append(summary.get("total", 0))
            daily_stats[date]["passed_counts"].append(summary.get("passed", 0))

    # 计算每天的平均值
    dates = sorted(daily_stats.keys())
    success_rates = []
    failed_counts = []
    total_counts = []
    passed_counts = []

    for date in dates:
        rates = daily_stats[date]["success_rates"]
        fails = daily_stats[date]["failed_counts"]
        totals = daily_stats[date]["total_counts"]
        passeds = daily_stats[date]["passed_counts"]

        # 修正：计算当日真实成功率 = 当日通过测试用例数 / 当日总测试用例数
        total_fails = sum(fails)
        total_tests = sum(totals)
        total_passed = sum(passeds)

        # 使用当日实际的通过率，而不是平均各个运行的成功率
        daily_success_rate = round((total_passed / total_tests *
                                    100), 2) if total_tests > 0 else 0

        success_rates.append(daily_success_rate)
        failed_counts.append(total_fails)
        total_counts.append(total_tests)
        passed_counts.append(total_passed)

    return {
        "dates": dates,
        "success_rates": success_rates,
        "failed_counts": failed_counts,
        "total_tests": total_counts,
        "passed_tests": passed_counts
    }


@app.get("/api/v1/unit/heatmap")
def api_unit_heatmap():
    """获取单元测试热力图数据（日期×成功率区间）"""
    from ..reporting.aggregate import collect_runs
    from ..parser.unit_test_parser import get_test_summary
    from ..utils.io import read_jsonl
    import os
    from datetime import datetime, timedelta

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"

    # 获取最近30天的数据
    cutoff = datetime.now() - timedelta(days=30)
    runs = collect_runs(archive_root_unit, cutoff.strftime('%Y-%m-%d'), None)

    # 按日期分组统计
    daily_stats = {}
    for run in runs:
        date = run.get("date", "").split("T")[0]  # 获取日期部分
        if not date:
            continue

        unit_file = os.path.join(run["run_dir"], "unit.jsonl")
        if os.path.exists(unit_file):
            records = read_jsonl(unit_file)
            summary = get_test_summary(records)
            rate = summary.get("success_rate", 0)

            if date not in daily_stats:
                daily_stats[date] = {
                    "excellent": 0,  # 优秀 ≥95%
                    "good": 0,       # 良好 90-95%
                    "fair": 0,       # 一般 80-90%
                    "poor": 0        # 较差 <80%
                }

            # 根据成功率分类
            if rate >= 95:
                daily_stats[date]["excellent"] += 1
            elif rate >= 90:
                daily_stats[date]["good"] += 1
            elif rate >= 80:
                daily_stats[date]["fair"] += 1
            else:
                daily_stats[date]["poor"] += 1

    # 生成结果
    items = []
    for date in sorted(daily_stats.keys()):
        stats = daily_stats[date]
        items.append({
            "date": date,
            "excellent": stats["excellent"],
            "good": stats["good"],
            "fair": stats["fair"],
            "poor": stats["poor"]
        })

    return {"items": items}


@app.get("/api/v1/unit/failure-distribution")
def api_unit_failure_distribution():
    """获取单元测试失败分布"""
    from ..reporting.aggregate import collect_runs
    from ..utils.io import read_jsonl
    import os
    from collections import Counter

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"

    # 获取最近7天的数据
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=7)
    runs = collect_runs(archive_root_unit, cutoff.strftime('%Y-%m-%d'), None)

    # 统计失败测试的分类
    failure_categories = Counter()

    for run in runs:
        anomalies_file = os.path.join(run["run_dir"], "anomalies.unit.jsonl")
        if os.path.exists(anomalies_file):
            anomalies = read_jsonl(anomalies_file)
            for anomaly in anomalies:
                # 从支持证据中获取测试分类
                evidence = anomaly.get("supporting_evidence", {})
                category = evidence.get("test_category", {})
                component = category.get("component", "unknown")
                failure_categories[component] += 1

    # 转换为百分比
    total = sum(failure_categories.values())
    categories = []

    for name, count in failure_categories.most_common(10):  # 只显示前10个
        percentage = (count / total * 100) if total > 0 else 0
        categories.append({
            "name": name,
            "count": count,
            "percentage": round(percentage, 1)
        })

    return {
        "categories": categories
    }


@app.post("/api/v1/unit/crawl")
def api_unit_crawl(request: dict):
    """触发单元测试数据获取"""
    from ..config import load_env_config
    from ..fetcher.unit_test_crawler import crawl_unit_test_incremental
    import uuid

    days = request.get("days", 7)
    patch_id = request.get("patch_id")

    job_id = str(uuid.uuid4())

    def run_crawl():
        try:
            cfg = load_env_config(source_url=None, archive_root=None)
            if not cfg.source_url_unit:
                raise ValueError("Unit test source URL not configured")

            # 执行爬取
            new_runs = crawl_unit_test_incremental(
                cfg.source_url_unit,
                cfg.archive_root_unit,
                days
            )

            # 解析爬取的数据
            from ..orchestrator.pipeline import parse_run
            parsed_count = 0
            for run_dir in new_runs:
                try:
                    parse_run(run_dir)
                    parsed_count += 1
                except Exception as e:
                    print(f"解析失败 {run_dir}: {e}")

            # 更新任务状态
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "completed",
                    "result": f"获取了 {len(new_runs)} 个新的测试运行，解析了 {parsed_count} 个"
                }
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": str(e)
                }

    # 在后台执行
    _pool.submit(run_crawl)
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    return {"job_id": job_id}


@app.post("/api/v1/unit/analyze")
def api_unit_analyze(request: dict):
    """触发单元测试AI分析"""
    from ..config import load_env_config
    from ..orchestrator.pipeline import parse_run, analyze_run
    from ..analyzer.k2_client import K2Client
    from ..reporting.aggregate import collect_runs
    import uuid
    import os

    days = request.get("days", 7)
    force = request.get("force", False)

    job_id = str(uuid.uuid4())

    def run_analysis():
        try:
            cfg = load_env_config(source_url=None, archive_root=None)
            archive_root_unit = cfg.archive_root_unit or "./archive/unit"

            # 获取需要分析的运行
            from datetime import datetime, timedelta
            cutoff = datetime.now() - timedelta(days=days)
            runs = collect_runs(archive_root_unit,
                                cutoff.strftime('%Y-%m-%d'), None)

            analyzed_count = 0
            for run in runs:
                run_dir = run["run_dir"]

                # 检查是否需要分析
                anomalies_file = os.path.join(run_dir, "anomalies.unit.jsonl")
                if not force and os.path.exists(anomalies_file):
                    continue  # 已分析，跳过

                # 解析和分析
                parse_run(run_dir)
                k2 = K2Client(
                    cfg.model) if cfg.model and cfg.model.enabled else None
                analyze_run(run_dir, k2, archive_root_unit,
                            reuse_existing=True)
                analyzed_count += 1

            _jobs[job_id] = {
                "status": "completed",
                "result": f"分析了 {analyzed_count} 个测试运行"
            }
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": str(e)
                }

    # 在后台执行
    _pool.submit(run_analysis)
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    return {"job_id": job_id}


@app.get("/api/v1/unit/detail/{rel_path:path}")
def api_unit_detail(rel_path: str):
    """获取单元测试详情"""
    from ..parser.unit_test_parser import get_test_summary, get_failed_test_cases
    from ..utils.io import read_json, read_jsonl
    import os

    # 从配置获取正确的archive_root_unit
    cfg = load_env_config(source_url=None, archive_root=None)
    archive_root_unit = cfg.archive_root_unit or "./archive/unit"
    run_dir = os.path.join(archive_root_unit, rel_path)

    if not os.path.exists(run_dir):
        return JSONResponse(status_code=404, content={"error": "Run not found"})

    # 读取各种数据文件
    meta = read_json(os.path.join(run_dir, "meta.json"))
    summary = read_json(os.path.join(run_dir, "summary.json")) if os.path.exists(
        os.path.join(run_dir, "summary.json")) else {}

    # 读取测试结果
    unit_file = os.path.join(run_dir, "unit.jsonl")
    test_results = []
    test_summary = {}

    if os.path.exists(unit_file):
        records = read_jsonl(unit_file)
        test_summary = get_test_summary(records)

        # 提取测试用例结果
        for record in records:
            if record.get("case"):  # 只包含具体的测试用例
                test_results.append({
                    "case": record.get("case"),
                    "status": record.get("status"),
                    "value": record.get("value")
                })

    # 读取异常分析结果
    anomalies = []
    anomalies_file = os.path.join(run_dir, "anomalies.unit.jsonl")
    if os.path.exists(anomalies_file):
        anomalies = read_jsonl(anomalies_file)

    return {
        "run_dir": run_dir,
        "rel": rel_path,
        "meta": meta,
        "summary": summary,
        "test_results": test_results,
        "test_summary": test_summary,
        "anomalies": anomalies
    }


@app.post("/api/v1/unit/runs/{rel_path:path}/analyze")
def api_unit_analyze_single(rel_path: str):
    """分析单个单元测试运行（如果已分析则跳过）"""
    from ..orchestrator.pipeline import analyze_run
    from ..analyzer.k2_client import K2Client
    import uuid
    import os

    job_id = str(uuid.uuid4())

    def run_analysis():
        try:
            cfg = load_env_config(source_url=None, archive_root=None)
            archive_root_unit = cfg.archive_root_unit or "./archive/unit"

            # 构建完整路径
            run_dir = os.path.join(archive_root_unit, rel_path)

            if not os.path.exists(run_dir):
                raise ValueError(f"Run directory not found: {run_dir}")

            # 执行分析（需要K2客户端和archive_root）
            k2 = K2Client(
                cfg.model) if cfg.model and cfg.model.enabled else None
            analyze_run(run_dir, k2, archive_root_unit, reuse_existing=True)

            # 更新任务状态
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "completed",
                    "result": "分析完成"
                }
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": error_msg
                }

    # 在后台执行
    _pool.submit(run_analysis)
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    return {"job_id": job_id}


@app.post("/api/v1/unit/runs/{rel_path:path}/reanalyze")
def api_unit_reanalyze_single(rel_path: str):
    """重新分析单个单元测试运行（强制重新分析，覆盖已有结果）"""
    from ..orchestrator.pipeline import analyze_run
    from ..analyzer.k2_client import K2Client
    import uuid
    import os

    job_id = str(uuid.uuid4())

    def run_reanalysis():
        try:
            cfg = load_env_config(source_url=None, archive_root=None)
            archive_root_unit = cfg.archive_root_unit or "./archive/unit"

            # 构建完整路径
            run_dir = os.path.join(archive_root_unit, rel_path)

            if not os.path.exists(run_dir):
                raise ValueError(f"Run directory not found: {run_dir}")

            # 执行强制重新分析（需要K2客户端和archive_root）
            k2 = K2Client(
                cfg.model) if cfg.model and cfg.model.enabled else None
            analyze_run(run_dir, k2, archive_root_unit, reuse_existing=False)

            # 更新任务状态
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "completed",
                    "result": "重新分析完成"
                }

        except Exception as e:
            import traceback
            error_msg = f"重新分析失败: {str(e)}"
            print(f"重新分析错误: {error_msg}")
            traceback.print_exc()

            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": error_msg
                }

    # 在后台执行
    _pool.submit(run_reanalysis)
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    return {"job_id": job_id}


@app.post("/api/v1/unit/webhook")
async def api_unit_webhook(request: Request):
    """单元测试Webhook接口

    触发单元测试数据的获取、解析和AI分析
    """
    from ..config import load_env_config
    from ..fetcher.unit_test_crawler import crawl_unit_test_incremental
    from ..orchestrator.pipeline import parse_run, analyze_run
    from ..analyzer.k2_client import K2Client
    import uuid
    import os

    try:
        body = await request.json()
    except:
        body = {}

    # 获取参数
    patch_id = body.get("patch_id")
    patch_set = body.get("patch_set")
    days = body.get("days", 1)  # 默认只获取最近1天

    job_id = str(uuid.uuid4())

    def run_webhook():
        try:
            cfg = load_env_config(source_url=None, archive_root=None)
            if not cfg.source_url_unit:
                raise ValueError("Unit test source URL not configured")

            # 1. 获取数据
            new_runs = crawl_unit_test_incremental(
                cfg.source_url_unit,
                cfg.archive_root_unit,
                days
            )

            # 2. 筛选特定的patch
            target_runs = []
            if patch_id:
                for run_path in new_runs:
                    # 从路径中提取patch信息
                    if f"_p{patch_id}" in run_path:
                        if not patch_set or f"_ps{patch_set}" in run_path:
                            target_runs.append(run_path)
            else:
                target_runs = new_runs

            # 3. 解析和分析
            analyzed_count = 0
            for run_dir in target_runs:
                # 解析
                parse_run(run_dir)
                # AI分析
                k2 = K2Client(
                    cfg.model) if cfg.model and cfg.model.enabled else None
                analyze_run(run_dir, k2, cfg.archive_root_unit,
                            reuse_existing=True)
                analyzed_count += 1

            _jobs[job_id] = {
                "status": "completed",
                "result": {
                    "downloaded": len(new_runs),
                    "analyzed": analyzed_count,
                    "patch_id": patch_id,
                    "patch_set": patch_set
                }
            }
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": str(e)
                }

    # 在后台执行
    _pool.submit(run_webhook)
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    return {
        "job_id": job_id,
        "message": "Unit test analysis started",
        "patch_id": patch_id,
        "patch_set": patch_set
    }


@app.post("/api/v1/webhook/analyze-unit-patch", response_model=SimplifiedWebhookResponse)
@app.get("/api/v1/webhook/analyze-unit-patch", response_model=SimplifiedWebhookResponse)
async def webhook_analyze_unit_patch(
    patch_id: str = Query(..., description="补丁ID"),
    patch_set: str = Query(..., description="补丁集"),
    force_refetch: bool = Query(False, description="是否强制重新获取"),
    force_reanalyze: bool = Query(True, description="是否强制重新分析"),
    max_search_days: int | None = Query(None, description="最大搜索天数，不设置则搜索所有日期")
):
    """
    单元测试的简化Webhook接口 - 根据patch_id和patch_set获取并分析单元测试数据
    支持GET和POST方法
    """
    from ..config import load_env_config
    from ..fetcher.unit_test_crawler import crawl_unit_test_incremental
    from ..orchestrator.pipeline import parse_run, analyze_run
    from ..analyzer.k2_client import K2Client
    from ..reporting.aggregate import collect_runs
    from datetime import datetime, timedelta
    import uuid
    import os

    # 生成任务ID
    job_id = uuid.uuid4().hex[:12]

    try:
        cfg = load_env_config(source_url=None, archive_root=None)
        if not cfg.source_url_unit:
            return SimplifiedWebhookResponse(
                success=False,
                patch=f"{patch_id}/{patch_set}",
                message="单元测试源URL未配置",
                engine="unit_test_analyzer",
                ai_model_configured="not_configured",
                force_refetch=force_refetch,
                force_reanalyze=force_reanalyze,
                max_search_days=max_search_days,
                error="Unit test source URL not configured"
            )

        # 先检查本地数据是否已存在
        if max_search_days:
            cutoff = datetime.now() - timedelta(days=max_search_days)
            runs = collect_runs(cfg.archive_root_unit,
                                cutoff.strftime('%Y-%m-%d'), None)
        else:
            # 搜索所有本地数据
            runs = collect_runs(cfg.archive_root_unit, None, None)

        found_run = None
        for run in runs:
            if (str(run.get("patch_id")) == str(patch_id) and
                    str(run.get("patch_set")) == str(patch_set)):
                found_run = run
                break

        # 如果本地没找到，检查远程是否存在
        data_exists = found_run is not None
        remote_exists = False

        if not data_exists:
            # 检查远程数据是否存在
            try:
                from ..utils.io import list_remote_date_dirs, list_remote_logs
                import requests

                # 获取远程日期目录
                remote_dates = list_remote_date_dirs(cfg.source_url_unit)

                # 根据max_search_days限制搜索范围
                if max_search_days:
                    search_dates = remote_dates[-max_search_days:]
                else:
                    search_dates = remote_dates

                # 在指定日期范围中查找目标patch
                for day_url in search_dates:
                    try:
                        remote_logs = list_remote_logs(day_url)
                        for log in remote_logs:
                            if (str(log.patch_id) == str(patch_id) and
                                    str(log.patch_set) == str(patch_set)):
                                remote_exists = True
                                data_exists = True
                                print(f"在远程找到数据: {log.name}")
                                break
                        if remote_exists:
                            break
                    except Exception as ex:
                        print(f"检查远程目录 {day_url} 时出错: {ex}")
                        continue
            except Exception as e:
                print(f"检查远程数据时出错: {e}")

        # 获取模型信息
        k2 = K2Client(cfg.model) if cfg.model and cfg.model.enabled else None
        engine_name = k2.get_model_name() if k2 and k2.enabled() else "unit_test_analyzer"
        ai_configured = "configured" if k2 and k2.enabled() else "not_configured"

        # 如果本地和远程都没找到数据，直接返回失败
        if not data_exists:
            search_scope = f"最近{max_search_days}天" if max_search_days else "所有日期"
            return SimplifiedWebhookResponse(
                success=False,
                patch=f"{patch_id}/{patch_set}",
                message=f"未找到 patch {patch_id}/{patch_set} 的单元测试数据（搜索了{search_scope}）",
                engine=engine_name,
                ai_model_configured=ai_configured,
                force_refetch=force_refetch,
                force_reanalyze=force_reanalyze,
                max_search_days=max_search_days,
                error=f"No unit test data found for patch {patch_id}/{patch_set}"
            )

        def _async_process():
            with _jobs_lock:
                _jobs[job_id] = {"status": "running",
                                 "progress": 10, "message": "开始处理单元测试数据"}

            try:
                current_found_run = found_run

                # 1. 获取数据（如果本地没有或强制重新获取）
                if not current_found_run or force_refetch:
                    with _jobs_lock:
                        _jobs[job_id]["progress"] = 30
                        _jobs[job_id]["message"] = "获取单元测试数据"

                    new_runs = crawl_unit_test_incremental(
                        cfg.source_url_unit,
                        cfg.archive_root_unit,
                        max_search_days
                    )

                    # 查找目标run
                    for run_path in new_runs:
                        if f"_p{patch_id}" in run_path and f"_ps{patch_set}" in run_path:
                            current_found_run = {"run_dir": run_path}
                            break

                    # 如果还是没找到，重新收集本地runs
                    if not current_found_run:
                        runs = collect_runs(
                            cfg.archive_root_unit, cutoff.strftime('%Y-%m-%d'), None)
                        for run in runs:
                            if (str(run.get("patch_id")) == str(patch_id) and
                                    str(run.get("patch_set")) == str(patch_set)):
                                current_found_run = run
                                break

                if not current_found_run:
                    with _jobs_lock:
                        _jobs[job_id] = {
                            "status": "failed",
                            "error": f"未找到 patch {patch_id}/{patch_set} 的单元测试数据"
                        }
                    return

                run_dir = current_found_run["run_dir"]

                # 2. 解析数据
                with _jobs_lock:
                    _jobs[job_id]["progress"] = 60
                    _jobs[job_id]["message"] = "解析单元测试数据"

                parse_run(run_dir)

                # 检查测试结果，决定是否需要AI分析
                from ..parser.unit_test_parser import get_test_summary
                from ..utils.io import read_jsonl

                unit_file = os.path.join(run_dir, "unit.jsonl")
                need_ai_analysis = False
                analysis_message = "单元测试分析完成"

                if os.path.exists(unit_file):
                    records = read_jsonl(unit_file)
                    summary = get_test_summary(records)
                    failed_count = summary.get("failed", 0)
                    success_rate = summary.get("success_rate", 0)

                    if failed_count > 0 and success_rate < 100:
                        need_ai_analysis = True
                        analysis_message = "单元测试AI分析完成"
                    else:
                        analysis_message = "单元测试全部通过，无需AI分析"

                # 3. AI分析（仅在有失败测试时执行）
                if need_ai_analysis:
                    with _jobs_lock:
                        _jobs[job_id]["progress"] = 80
                        _jobs[job_id]["message"] = "执行AI分析"

                    analyze_run(run_dir, k2, cfg.archive_root_unit,
                                reuse_existing=not force_reanalyze)
                else:
                    with _jobs_lock:
                        _jobs[job_id]["progress"] = 90
                        _jobs[job_id]["message"] = "跳过AI分析（全部通过）"

                # 4. 完成
                with _jobs_lock:
                    _jobs[job_id] = {
                        "status": "completed",
                        "progress": 100,
                        "result": {
                            "patch_id": patch_id,
                            "patch_set": patch_set,
                            "run_dir": run_dir,
                            "analysis_engine": engine_name if need_ai_analysis else "unit_test_analyzer",
                            "ai_analysis_performed": need_ai_analysis,
                            "message": analysis_message
                        }
                    }

            except Exception as e:
                with _jobs_lock:
                    _jobs[job_id] = {
                        "status": "failed",
                        "error": str(e)
                    }

        # 启动异步处理
        _pool.submit(_async_process)
        with _jobs_lock:
            _jobs[job_id] = {"status": "running",
                             "progress": 5, "message": "初始化"}

        return SimplifiedWebhookResponse(
            success=True,
            job_id=job_id,
            patch=f"{patch_id}/{patch_set}",
            message="单元测试分析任务已启动",
            engine=engine_name,
            ai_model_configured=ai_configured,
            force_refetch=force_refetch,
            force_reanalyze=force_reanalyze,
            max_search_days=max_search_days,
            status_url=f"/api/v1/jobs/{job_id}",
            estimated_time="1-3分钟",
            process_flow=["获取数据", "解析测试结果", "AI根因分析", "生成报告"]
        )

    except Exception as e:
        return SimplifiedWebhookResponse(
            success=False,
            patch=f"{patch_id}/{patch_set}",
            message=f"单元测试分析失败: {str(e)}",
            engine="unit_test_analyzer",
            ai_model_configured="unknown",
            force_refetch=force_refetch,
            force_reanalyze=force_reanalyze,
            max_search_days=max_search_days,
            error=str(e)
        )


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


@app.get("/api/v1/progress/{job_id}")
def api_get_progress(job_id: str):
    """获取分析任务进度"""
    tracker = get_tracker()
    progress = tracker.get_progress(job_id)

    if not progress:
        return JSONResponse(
            status_code=404,
            content={"error": "Job not found", "job_id": job_id}
        )

    return JSONResponse(content=progress.to_dict())


@app.get("/api/v1/progress")
def api_list_progress():
    """获取所有活动任务的进度"""
    tracker = get_tracker()
    all_progress = tracker.get_all_progress()

    # 清理旧任务
    tracker.cleanup_old(max_age_seconds=3600)

    # 转换为列表格式
    progress_list = [info.to_dict() for info in all_progress.values()]

    return JSONResponse(content={
        "jobs": progress_list,
        "total": len(progress_list)
    })


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


@app.get("/api/v1/ui-config")
def api_ui_config():
    """获取UI配置"""
    from ..utils.io import read_json
    import os

    config_file = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(__file__))), "models_config.json")

    try:
        config = read_json(config_file)
        ui_config = config.get("ui", {})
        return {
            "show_config_menu": ui_config.get("show_config_menu", False)
        }
    except Exception as e:
        # 如果配置读取失败，默认不显示配置菜单
        return {
            "show_config_menu": False
        }


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

    def _work_with_progress(job_id):
        from ..orchestrator.pipeline import analyze_run, parse_run
        from ..analyzer.progress_tracker import get_tracker
        import requests
        import os

        # 检查运行是否存在
        run_dir = os.path.join(ARCHIVE_ROOT, rel_path)
        if not os.path.isdir(run_dir):
            return {"error": f"运行不存在: {rel_path}"}

        # 更新进度状态
        tracker = get_tracker()
        tracker.update_progress(job_id, status="running",
                                details={"run": rel_path, "engine": engine})

        try:
            # 检查是否需要解析
            ub_path = os.path.join(run_dir, "ub.jsonl")
            if not os.path.exists(ub_path) or os.path.getsize(ub_path) == 0:
                parse_run(run_dir)

            # 执行分析，传递job_id
            analyze_run(run_dir, use_k2, ARCHIVE_ROOT,
                        reuse_existing=False, job_id=job_id)

            done = [rel_path]

            # 更新进度为完成
            tracker.update_progress(job_id, status="completed",
                                    current_batch=1, total_batches=1)
        except Exception as e:
            # 更新进度为失败
            tracker.update_progress(job_id, status="failed",
                                    error_message=str(e))
            done = []

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

    # 创建进度跟踪
    import uuid
    from ..analyzer.progress_tracker import get_tracker
    tracker = get_tracker()
    job_id = uuid.uuid4().hex[:12]
    progress_info = tracker.create_job(job_id, total_batches=1)
    print(f"Created job {job_id} with progress tracking")

    # 启动任务
    _pool.submit(_work_with_progress, job_id)

    return {"job_id": job_id, "rel": rel_path, "progress_url": f"/api/v1/progress/{job_id}"}


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


# ============= Webhook API端点 =============

@app.post("/api/v1/webhook/analyze-patch", response_model=SimplifiedWebhookResponse)
async def webhook_analyze_patch(
    patch_id: str = Query(..., description="补丁ID"),
    patch_set: str = Query(..., description="补丁集"),
    force_refetch: bool = Query(False, description="是否强制重新获取"),
    force_reanalyze: bool = Query(True, description="是否强制重新分析"),
    max_search_days: int = Query(7, description="最大搜索天数")
):
    """
    简化的Webhook接口 - 根据patch_id和patch_set获取并分析数据
    支持GET和POST方法
    """
    # 创建处理器
    handler = WebhookHandler(archive_root=ARCHIVE_ROOT)

    # 生成任务ID
    job_id = uuid.uuid4().hex[:12]

    # 先获取模型信息
    engine, model = handler.get_model_info()
    patch_str = f"{patch_id}/{patch_set}"

    # 首先快速检查数据是否存在
    found, date_str, run_dir = handler.search_patch_data(
        patch_id, patch_set, max_search_days)

    if not found:
        # 数据不存在，直接返回失败
        return SimplifiedWebhookResponse(
            success=False,
            patch=patch_str,
            message=f"未找到 patch {patch_str} 的UB数据（搜索了最近{max_search_days}天）",
            engine=engine,
            ai_model_configured=model,
            force_refetch=force_refetch,
            force_reanalyze=force_reanalyze,
            max_search_days=max_search_days,
            error=f"No data found for patch {patch_str}"
        )

    # 数据存在，启动异步处理
    def _async_process():
        with _jobs_lock:
            _jobs[job_id] = {"status": "running",
                             "progress": 10, "message": "开始处理"}
        try:
            # 执行完整的处理流程
            result = handler.process_webhook_simplified(
                patch_id=patch_id,
                patch_set=patch_set,
                force_refetch=force_refetch,
                force_reanalyze=force_reanalyze,
                max_search_days=max_search_days,
                job_id=job_id
            )
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "completed",
                    "result": result.dict(),
                    "progress": 100,
                    "message": "处理完成"
                }
            return result
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id] = {
                    "status": "failed",
                    "error": str(e),
                    "progress": 0,
                    "message": f"处理失败: {str(e)}"
                }
            raise

    # 启动异步任务，不等待
    _pool.submit(_async_process)

    # 立即返回成功响应（因为已确认数据存在）
    return SimplifiedWebhookResponse(
        success=True,
        job_id=job_id,
        patch=patch_str,
        message=f"已开始获取和分析 patch {patch_str}，请使用 job_id 查询进度",
        engine=engine,
        ai_model_configured=model,
        force_refetch=force_refetch,
        force_reanalyze=force_reanalyze,
        max_search_days=max_search_days,
        status_url=f"/api/v1/jobs/{job_id}",
        estimated_time="正在分析，请稍后查询",
        process_flow=[
            "1. 检查本地是否有数据",
            "2. 如需要，从远程获取UB数据",
            "3. 解析HTML生成ub.jsonl",
            f"4. 执行AI异常分析（使用config.json配置的模型: {model}）",
            "5. 生成分析报告"
        ]
    )

# 支持GET方法
@app.get("/api/v1/webhook/analyze-patch", response_model=SimplifiedWebhookResponse)
async def webhook_analyze_patch_get(
    patch_id: str = Query(..., description="补丁ID"),
    patch_set: str = Query(..., description="补丁集"),
    force_refetch: bool = Query(False, description="是否强制重新获取"),
    force_reanalyze: bool = Query(True, description="是否强制重新分析"),
    max_search_days: int = Query(7, description="最大搜索天数")
):
    """GET方法的webhook接口"""
    return await webhook_analyze_patch(
        patch_id=patch_id,
        patch_set=patch_set,
        force_refetch=force_refetch,
        force_reanalyze=force_reanalyze,
        max_search_days=max_search_days
    )
