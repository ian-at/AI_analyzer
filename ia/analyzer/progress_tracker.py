"""
分析进度跟踪器
用于跟踪和报告AI分析的实时进度
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
import os


@dataclass
class ProgressInfo:
    """进度信息"""
    job_id: str
    status: str = "pending"  # pending, running, completed, failed
    current_batch: int = 0
    total_batches: int = 0
    current_model: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    error_message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def progress_percentage(self) -> float:
        """计算进度百分比"""
        if self.total_batches == 0:
            return 0.0
        return (self.current_batch / self.total_batches) * 100

    @property
    def elapsed_time(self) -> float:
        """计算已用时间"""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    @property
    def estimated_remaining(self) -> Optional[float]:
        """估算剩余时间"""
        if self.current_batch == 0 or self.total_batches == 0:
            return None
        avg_time_per_batch = self.elapsed_time / self.current_batch
        remaining_batches = self.total_batches - self.current_batch
        return avg_time_per_batch * remaining_batches

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "current_batch": self.current_batch,
            "total_batches": self.total_batches,
            "progress_percentage": round(self.progress_percentage, 1),
            "current_model": self.current_model,
            "elapsed_time": round(self.elapsed_time, 1),
            "estimated_remaining": round(self.estimated_remaining, 1) if self.estimated_remaining else None,
            "error_message": self.error_message,
            "details": self.details,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "end_time": datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None
        }


class ProgressTracker:
    """全局进度跟踪器"""

    def __init__(self):
        self._progress: Dict[str, ProgressInfo] = {}
        self._lock = threading.Lock()
        self._callbacks: Dict[str, Callable] = {}
        self._persist_file = "./cache/progress.json"
        self._load_persisted()

    def _load_persisted(self):
        """加载持久化的进度信息"""
        if os.path.exists(self._persist_file):
            try:
                with open(self._persist_file, "r") as f:
                    data = json.load(f)
                    # 只加载最近1小时内的任务
                    cutoff = time.time() - 3600
                    for job_id, info in data.items():
                        if info.get("start_time", 0) > cutoff:
                            self._progress[job_id] = ProgressInfo(
                                job_id=job_id,
                                status=info.get("status", "unknown"),
                                current_batch=info.get("current_batch", 0),
                                total_batches=info.get("total_batches", 0),
                                current_model=info.get("current_model", ""),
                                error_message=info.get("error_message", ""),
                                details=info.get("details", {})
                            )
            except Exception:
                pass

    def _persist(self):
        """持久化进度信息"""
        try:
            os.makedirs(os.path.dirname(self._persist_file), exist_ok=True)
            data = {job_id: info.to_dict()
                    for job_id, info in self._progress.items()}
            with open(self._persist_file, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def create_job(self, job_id: str, total_batches: int = 0) -> ProgressInfo:
        """创建新的分析任务"""
        with self._lock:
            info = ProgressInfo(
                job_id=job_id,
                total_batches=total_batches,
                status="pending"
            )
            self._progress[job_id] = info
            self._persist()
            self._notify(job_id)
            return info

    def update_progress(self, job_id: str,
                        current_batch: Optional[int] = None,
                        total_batches: Optional[int] = None,
                        status: Optional[str] = None,
                        current_model: Optional[str] = None,
                        error_message: Optional[str] = None,
                        details: Optional[dict] = None) -> Optional[ProgressInfo]:
        """更新进度信息"""
        with self._lock:
            if job_id not in self._progress:
                return None

            info = self._progress[job_id]

            if current_batch is not None:
                info.current_batch = current_batch
            if total_batches is not None:
                info.total_batches = total_batches
            if status is not None:
                info.status = status
                if status in ["completed", "failed"]:
                    info.end_time = time.time()
            if current_model is not None:
                info.current_model = current_model
            if error_message is not None:
                info.error_message = error_message
            if details is not None:
                info.details.update(details)

            self._persist()
            self._notify(job_id)
            return info

    def get_progress(self, job_id: str) -> Optional[ProgressInfo]:
        """获取进度信息"""
        with self._lock:
            return self._progress.get(job_id)

    def get_all_progress(self) -> Dict[str, ProgressInfo]:
        """获取所有进度信息"""
        with self._lock:
            return dict(self._progress)

    def register_callback(self, job_id: str, callback: Callable):
        """注册进度更新回调"""
        self._callbacks[job_id] = callback

    def _notify(self, job_id: str):
        """通知进度更新"""
        if job_id in self._callbacks:
            try:
                self._callbacks[job_id](self._progress[job_id])
            except Exception:
                pass

    def cleanup_old(self, max_age_seconds: int = 3600):
        """清理旧的进度记录"""
        with self._lock:
            cutoff = time.time() - max_age_seconds
            to_remove = []
            for job_id, info in self._progress.items():
                if info.start_time < cutoff:
                    to_remove.append(job_id)

            for job_id in to_remove:
                del self._progress[job_id]
                if job_id in self._callbacks:
                    del self._callbacks[job_id]

            if to_remove:
                self._persist()


# 全局进度跟踪器实例
_global_tracker = ProgressTracker()


def get_tracker() -> ProgressTracker:
    """获取全局进度跟踪器"""
    return _global_tracker
