from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from ..utils.io import read_json, read_jsonl, write_text


def _parse_date(date_str: str) -> Optional[str]:
    try:
        # 验证 YYYY-MM-DD
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except Exception:
        return None


def _is_in_range(date_str: str, start: Optional[str], end: Optional[str]) -> bool:
    if start and date_str < start:
        return False
    if end and date_str > end:
        return False
    return True


def collect_runs(archive_root: str, start: Optional[str], end: Optional[str]) -> list[dict[str, Any]]:
    index_path = os.path.join(archive_root, "runs_index.jsonl")
    rows = read_jsonl(index_path)
    runs: list[dict[str, Any]] = []
    if rows:
        for row in rows:
            run_dir = row.get("run_dir")
            date_str = row.get("date")
            if not run_dir or not date_str:
                continue
            if not _is_in_range(date_str, start, end):
                continue
            try:
                meta = read_json(os.path.join(run_dir, "meta.json"))
                summ = read_json(os.path.join(run_dir, "summary.json")) if os.path.exists(
                    os.path.join(run_dir, "summary.json")) else {"total_anomalies": 0}
                anoms = read_jsonl(os.path.join(run_dir, "anomalies.k2.jsonl")) if os.path.exists(
                    os.path.join(run_dir, "anomalies.k2.jsonl")) else []
                ub = read_jsonl(os.path.join(run_dir, "ub.jsonl")) if os.path.exists(
                    os.path.join(run_dir, "ub.jsonl")) else []
                runs.append({
                    "run_dir": run_dir,
                    "rel_dir": os.path.relpath(run_dir, start=archive_root),
                    "date": date_str,
                    "patch_id": meta.get("patch_id"),
                    "patch_set": meta.get("patch_set"),
                    "summary": summ,
                    "anomalies": anoms,
                    "ub": ub,
                })
            except Exception:
                continue
    else:
        # 回退：直接扫描归档目录
        try:
            dates = sorted([d for d in os.listdir(archive_root)
                            if os.path.isdir(os.path.join(archive_root, d))])
        except Exception:
            dates = []
        for d in dates:
            if not _is_in_range(d, start, end):
                continue
            day_dir = os.path.join(archive_root, d)
            try:
                runs_in_day = sorted(
                    [r for r in os.listdir(day_dir) if r.startswith("run_")])
            except Exception:
                runs_in_day = []
            for rname in runs_in_day:
                run_dir = os.path.join(day_dir, rname)
                meta_path = os.path.join(run_dir, "meta.json")
                if not os.path.exists(meta_path):
                    continue
                try:
                    meta = read_json(meta_path)
                    summ = read_json(os.path.join(run_dir, "summary.json")) if os.path.exists(
                        os.path.join(run_dir, "summary.json")) else {"total_anomalies": 0}
                    anoms = read_jsonl(os.path.join(run_dir, "anomalies.k2.jsonl")) if os.path.exists(
                        os.path.join(run_dir, "anomalies.k2.jsonl")) else []
                    ub = read_jsonl(os.path.join(run_dir, "ub.jsonl")) if os.path.exists(
                        os.path.join(run_dir, "ub.jsonl")) else []
                    runs.append({
                        "run_dir": run_dir,
                        "rel_dir": os.path.relpath(run_dir, start=archive_root),
                        "date": d,
                        "patch_id": meta.get("patch_id"),
                        "patch_set": meta.get("patch_set"),
                        "summary": summ,
                        "anomalies": anoms,
                        "ub": ub,
                    })
                except Exception:
                    continue
    # 以日期排序（新到旧）
    runs.sort(key=lambda r: r.get("date", ""), reverse=True)
    return runs


def build_metric_series(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """构建按指标的历史序列：key = "suite::case::metric"。value 列表按时间升序。"""
    series: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        date_str = r.get("date")
        t = date_str
        for e in r.get("ub", []):
            try:
                v = float(e.get("value"))
            except Exception:
                continue
            key = "::".join([e.get("suite", ""), e.get(
                "case", ""), e.get("metric", "")])
            unit = e.get("unit")
            arr = series.setdefault(key, [])
            arr.append({"t": t, "value": v, "unit": unit,
                        "run_dir": r.get("run_dir")})
    # 时间升序
    for k in list(series.keys()):
        series[k].sort(key=lambda x: x["t"])
    return series


def _pick_total_score_key(series: dict[str, list[dict[str, Any]]]) -> str | None:
    # 优先匹配总分指标
    for key in series.keys():
        if key.endswith("System Benchmarks Index Score"):
            return key
    return None


def _html_dashboard(embed_json: str, title: str) -> str:
    # 已迁移到前端 React 渲染；此占位仅保留历史兼容，不再被调用
    return ""


def generate_dashboard(archive_root: str, out_path: str, start: Optional[str] = None, end: Optional[str] = None) -> str:
    # 兼容旧 CLI：返回空文件路径提示；不再生成 dashboard.html
    try:
        if not os.path.exists(out_path):
            write_text(out_path, "")
    except Exception:
        pass
    return out_path
