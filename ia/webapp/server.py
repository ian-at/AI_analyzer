"""
故障诊断AI平台 - Web服务器
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from ..diagnosis.api import create_diagnosis_router


# 创建FastAPI应用
app = FastAPI(title="故障诊断AI平台", description="基于AI的计算机故障诊断平台")

# 添加中间件
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 任务管理（用于异步任务）
_jobs_lock = threading.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}
_pool = ThreadPoolExecutor(max_workers=10)


def _start_job(fn, *args, **kwargs) -> str:
    """启动异步任务"""
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


# ==================== 故障诊断API路由 ====================
diagnosis_archive_root = os.environ.get("IA_ARCHIVE_DIAGNOSIS", "./archive/diagnosis")
os.makedirs(diagnosis_archive_root, exist_ok=True)
diagnosis_router = create_diagnosis_router(diagnosis_archive_root)
app.include_router(diagnosis_router)


# ==================== 基础API ====================

@app.get("/")
def index():
    """根路径重定向到API文档"""
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok", "service": "故障诊断AI平台"}


@app.get("/api/v1/health")
def health_check():
    """健康检查API"""
    return {"status": "ok", "service": "故障诊断AI平台", "version": "1.0"}


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    """获取任务状态"""
        with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "任务不存在"})
    return job


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)