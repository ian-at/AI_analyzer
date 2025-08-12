from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

from ..utils.io import read_jsonl


def median_absolute_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    med = median(values)
    deviations = [abs(v - med) for v in values]
    return median(deviations) or 0.0


def mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def robust_z_score(current: float, history: list[float]) -> float | None:
    if not history:
        return None
    med = median(history)
    mad = median_absolute_deviation(history)
    if mad == 0:
        return None
    return (current - med) / (1.4826 * mad)


def pct_change_vs_median(current: float, history: list[float]) -> float | None:
    if not history:
        return None
    med = median(history)
    if med == 0:
        return None
    return (current - med) / med


def pct_change_vs_mean(current: float, history: list[float]) -> float | None:
    if not history:
        return None
    mu = mean(history)
    if mu == 0:
        return None
    return (current - mu) / mu


def load_history_for_keys(
    archive_root: str,
    keys: list[tuple[str, str, str]],
    max_runs: int = 20,
) -> dict[tuple[str, str, str], list[float]]:
    """扫描归档中的历史 run，为每个 (suite, case, metric) 构建数值历史数组。"""
    # 朴素扫描：遍历归档下所有 ub.jsonl（按新到旧）
    pattern = os.path.join(archive_root, "*", "run_*", "ub.jsonl")
    files = sorted(glob.glob(pattern), reverse=True)
    key_set = set(keys)
    history: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    for path in files:
        rows = read_jsonl(path)
        for row in rows:
            k = (row.get("suite", ""), row.get(
                "case", ""), row.get("metric", ""))
            if k in key_set:
                try:
                    v = float(row.get("value"))
                except Exception:
                    continue
                arr = history[k]
                if len(arr) < max_runs:
                    arr.append(v)
        # Early exit if all keys have enough history
        if all(len(history[k]) >= max_runs for k in key_set):
            break
    return history


def heuristic_anomalies(entries: list[dict[str, Any]], history: dict[tuple[str, str, str], list[float]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for e in entries:
        key = (e.get("suite", ""), e.get("case", ""), e.get("metric", ""))
        hist = history.get(key, [])
        current = float(e.get("value"))
        rz = robust_z_score(current, hist)
        pct = pct_change_vs_median(current, hist)
        pct_mean = pct_change_vs_mean(current, hist)
        is_anom = False
        reason_parts: list[str] = []
        # 以历史均值与稳健统计为依据，动态阈值（每次执行时重算）
        if rz is not None and abs(rz) >= 3:
            is_anom = True
            reason_parts.append(f"robust_z={rz:.2f}")
        if pct is not None and abs(pct) >= 0.3:
            is_anom = True
            reason_parts.append(f"Δ vs median={pct:+.0%}")
        if pct_mean is not None and abs(pct_mean) >= 0.3:
            is_anom = True
            reason_parts.append(f"Δ vs mean={pct_mean:+.0%}")
        if is_anom:
            results.append({
                "suite": e.get("suite"),
                "case": e.get("case"),
                "metric": e.get("metric"),
                "current_value": current,
                "unit": e.get("unit"),
                "severity": "high" if (abs(rz or 0) >= 4 or abs(pct or 0) >= 0.5) else "medium",
                "confidence": min(0.95, 0.6 + 0.1 * (abs(rz or 0))),
                "primary_reason": ", ".join(reason_parts) or "significant deviation",
                "deltas": {
                    "vs_median_pct": pct,
                    "vs_mean_pct": pct_mean,
                    "robust_z": rz,
                },
                "root_causes": [],
                "supporting_evidence": {
                    "history_n": len(hist),
                    "mean": mean(hist) if hist else None,
                    "median": median(hist) if hist else None,
                },
                "suggested_next_checks": [],
            })
    return results


def compute_entry_features(entries: list[dict[str, Any]], history: dict[tuple[str, str, str], list[float]]) -> dict[str, dict[str, Any]]:
    """计算每条 entry 的统计特征，键为 "suite::case::metric"。"""
    feats: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = (e.get("suite", ""), e.get("case", ""), e.get("metric", ""))
        hist = history.get(key, [])
        try:
            current = float(e.get("value"))
        except Exception:
            continue
        rz = robust_z_score(current, hist)
        pct = pct_change_vs_median(current, hist)
        pct_m = pct_change_vs_mean(current, hist)
        feats["::".join(key)] = {
            "current_value": current,
            "history_n": len(hist),
            "mean": mean(hist) if hist else None,
            "median": median(hist) if hist else None,
            "robust_z": rz,
            "pct_change_vs_median": pct,
            "pct_change_vs_mean": pct_m,
        }
    return feats
