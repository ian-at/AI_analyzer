from __future__ import annotations

from typing import Optional, Dict, Any, List

from ..reporting.aggregate import collect_runs, build_metric_series


def list_runs_usecase(
    archive_root: str,
    start: Optional[str],
    end: Optional[str],
) -> Dict[str, Any]:
    runs = collect_runs(archive_root, start, end)
    items: List[Dict[str, Any]] = []
    for r in runs:
        s = r.get("summary", {}) or {}
        sc = s.get("severity_counts", {}) or {}
        items.append({
            "run_dir": r.get("run_dir"),
            "rel": r.get("rel_dir"),
            "date": r.get("date"),
            "patch_id": r.get("patch_id"),
            "patch_set": r.get("patch_set"),
            "total_anomalies": s.get("total_anomalies", 0),
            "high": sc.get("high", 0),
            "medium": sc.get("medium", 0),
            "low": sc.get("low", 0),
            "engine": (s.get("analysis_engine") or {}),
            "analysis_time": s.get("analysis_time"),
        })
    return {"items": items, "total": len(items)}


def series_usecase(archive_root: str, metric: str) -> Dict[str, Any]:
    runs = collect_runs(archive_root, None, None)
    series = build_metric_series(runs)
    picked = None
    for k in series.keys():
        if k.endswith(metric):
            picked = k
            break
    arr = series.get(picked, []) if picked else []
    out = {"metric": metric, "series": [
        {"date": i["t"], "value": i["value"], "run_dir": i["run_dir"]} for i in arr
    ]}
    return out


def top_drifts_usecase(archive_root: str, window: int, limit: int) -> Dict[str, Any]:
    import statistics as _stat
    runs = collect_runs(archive_root, None, None)
    series = build_metric_series(runs)
    rows = []
    for metric_key, arr in series.items():
        if len(arr) < window + 1:
            continue
        vals = [x["value"]
                for x in arr if isinstance(x.get("value"), (int, float))]
        if len(vals) < window + 1:
            continue
        last = vals[-1]
        prev = vals[-(window+1):-1]
        if not prev:
            continue
        mean_prev = _stat.mean(prev)
        if mean_prev == 0:
            continue
        pct = (last - mean_prev) / abs(mean_prev)
        rows.append({"metric": metric_key, "last_value": last,
                     "mean_prev": mean_prev, "pct_change": pct})
    rows.sort(key=lambda x: abs(x["pct_change"]), reverse=True)
    out = {"items": rows[:limit]}
    return out
