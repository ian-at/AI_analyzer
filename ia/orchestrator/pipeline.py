from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

from ..analyzer.anomaly import heuristic_anomalies, load_history_for_keys, compute_entry_features
from ..analyzer.k2_client import K2Client
from ..analyzer.model_provider import K2ProviderAdapter
from ..analyzer.unit_test_analyzer import analyze_unit_test_anomalies
from ..parser.unit_test_parser import get_test_summary, get_failed_test_cases
from ..config import load_analysis_config
from ..fetcher.crawler import crawl_incremental
from ..parser.html_parser import parse_ub_html
from ..parser.unixbench_parser import parse_unixbench_pre_text
from ..parser.unit_test_parser import parse_unit_test_log
from ..reporting.report import generate_report
from ..utils.io import read_json, read_jsonl, write_json, write_jsonl
import glob
import time
from datetime import datetime, timedelta


def parse_run(run_dir: str) -> list[dict[str, Any]]:
    meta = read_json(os.path.join(run_dir, "meta.json"))
    test_type = meta.get("test_type", "unixbench")  # 默认为unixbench以保持向后兼容

    if test_type == "unit_test":
        # 解析单元测试日志
        log_path = os.path.join(run_dir, "raw_logs", meta["files"]["log"])
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_text = f.read()
        records = parse_unit_test_log(log_text)
        # 保存为unit.jsonl以区别于ub.jsonl
        write_jsonl(os.path.join(run_dir, "unit.jsonl"), records)
    elif test_type == "interface_test":
        # 解析接口测试日志
        from ..parser.interface_test_parser import parse_interface_test_log
        log_path = os.path.join(run_dir, "raw_logs", meta["files"]["log"])
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_text = f.read()
        records = parse_interface_test_log(log_text)
        # 保存为interface.jsonl
        write_jsonl(os.path.join(run_dir, "interface.jsonl"), records)
    else:
        # 解析UnixBench HTML (默认行为)
        html_path = os.path.join(run_dir, "raw_html", meta["files"]["html"])
        with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
            html_text = f.read()
        # 优先尝试 UnixBench <pre> 文本解析
        records = parse_unixbench_pre_text(html_text)
        if not records:
            # 回退到表格解析
            records = parse_ub_html(html_text)
        write_jsonl(os.path.join(run_dir, "ub.jsonl"), records)

    return records


def summarize(anomalies: list[dict[str, Any]]) -> dict:
    counts = Counter(a.get("severity", "") for a in anomalies)
    return {
        "total_anomalies": len(anomalies),
        "severity_counts": {
            "high": counts.get("high", 0),
            "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
        },
    }


def _normalize_confidence(conf: Any) -> float | None:
    try:
        if isinstance(conf, (int, float)):
            return float(conf) / 100.0 if float(conf) > 1.0 else float(conf)
        if isinstance(conf, str):
            s = conf.strip().lower()
            if s in ("high", "high-confidence"):
                return 0.9
            if s in ("medium", "mid", "moderate"):
                return 0.7
            if s in ("low",):
                return 0.5
            v = float(s)
            return v / 100.0 if v > 1.0 else v
    except Exception:
        return None
    return None


def _normalize_k2_anomalies(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for a in items:
        current_value = a.get("current_value")
        if current_value is None and a.get("value") is not None:
            current_value = a.get("value")
        # 兜底：若K2未回填当前值，从deltas/或features中尝试恢复
        if current_value is None:
            dv = a.get("deltas") or {}
            if isinstance(dv, dict) and "current_value" in dv:
                current_value = dv.get("current_value")
        primary_reason = a.get("primary_reason") or a.get(
            "justification") or a.get("description") or ""
        confidence = _normalize_confidence(a.get("confidence"))
        normalized.append({
            "suite": a.get("suite"),
            "case": a.get("case"),
            "metric": a.get("metric"),
            "current_value": current_value,
            "unit": a.get("unit"),
            "severity": a.get("severity"),
            "confidence": confidence,
            "primary_reason": primary_reason,
            "deltas": a.get("deltas") or {},
            "root_causes": a.get("root_causes") or ([{"cause": a.get("root_cause"), "likelihood": None}] if a.get("root_cause") else []),
            "supporting_evidence": a.get("supporting_evidence") or {},
            "suggested_next_checks": a.get("suggested_next_checks") or [],
        })
    return normalized


def analyze_run(run_dir: str, k2: K2Client | None, archive_root: str, reuse_existing: bool = True, job_id: str = None) -> tuple[list[dict[str, Any]], dict]:
    meta = read_json(os.path.join(run_dir, "meta.json"))
    test_type = meta.get("test_type", "unixbench")

    # 根据测试类型选择不同的数据文件
    if test_type == "unit_test":
        entries = read_jsonl(os.path.join(run_dir, "unit.jsonl"))
        anomalies_file = "anomalies.unit.jsonl"
    else:
        entries = read_jsonl(os.path.join(run_dir, "ub.jsonl"))
        anomalies_file = "anomalies.k2.jsonl"

    # 加载分析配置
    analysis_cfg = load_analysis_config()
    min_samples = analysis_cfg.get("anomaly_detection", {}).get(
        "min_samples_for_anomaly", 10)
    min_history = analysis_cfg.get("anomaly_detection", {}).get(
        "min_samples_for_history", 10)

    # 构建 (suite, case, metric) 粒度的历史数据
    keys = [(e.get("suite", ""), e.get("case", ""), e.get("metric", ""))
            for e in entries]
    history = load_history_for_keys(
        archive_root, keys, min_samples=min_history)

    anomalies: list[dict[str, Any]] = []
    ai_analysis_failed = False  # 移到函数顶层，确保作用域正确

    # 单元测试使用专门的分析逻辑
    if test_type == "unit_test":
        # 若已有单元测试结果且非空，直接复用
        existing = read_jsonl(os.path.join(run_dir, anomalies_file))
        if reuse_existing and existing:
            # 复用时也需要根据当前配置确定分析引擎信息
            test_summary = get_test_summary(entries)
            failed_count = test_summary.get("failed", 0)

            # 确定分析引擎信息（与下面的逻辑保持一致）
            if failed_count > 0 and k2 and k2.enabled():
                # 检查现有结果是否包含AI分析
                has_ai_analysis = any(
                    any(rc.get("ai_enhanced", False)
                        for rc in anomaly.get("root_causes", []))
                    for anomaly in existing
                )
                if has_ai_analysis:
                    engine_name = k2.get_model_name()
                    degraded = False
                else:
                    engine_name = "unit_test_analyzer"
                    degraded = True
            else:
                engine_name = "unit_test_analyzer"
                degraded = False

            summ = summarize(existing)
            summ["analysis_engine"] = {
                "name": engine_name,
                "version": "1.0",
                "degraded": degraded,
            }
            summ["analysis_time"] = datetime.utcnow().isoformat() + "Z"
            write_json(os.path.join(run_dir, "summary.json"), summ)
            generate_report(run_dir, meta, existing, summ)
            return existing, summ

        # 执行单元测试分析
        test_summary = get_test_summary(entries)
        anomalies, analysis_info = analyze_unit_test_anomalies(
            entries, test_summary, k2)

        # 确定分析引擎信息
        failed_count = test_summary.get("failed", 0)
        if failed_count > 0 and k2 and k2.enabled():
            # 有失败测试且AI可用
            if analysis_info.get("ai_analysis_success", False):
                # AI分析成功，显示AI模型名称
                engine_name = k2.get_model_name()
                engine_version = "1.0"
                degraded = False
            else:
                # AI分析失败，降级到规则分析
                engine_name = "unit_test_analyzer"
                engine_version = "1.0"
                degraded = True
        else:
            # 无失败测试或AI不可用，使用规则分析
            engine_name = "unit_test_analyzer"
            engine_version = "1.0"
            degraded = False

        # 保存分析结果
        write_jsonl(os.path.join(run_dir, anomalies_file), anomalies)
        summ = summarize(anomalies)
        summ["analysis_engine"] = {
            "name": engine_name,
            "version": engine_version,
            "degraded": degraded,
        }
        summ["analysis_time"] = datetime.utcnow().isoformat() + "Z"
        write_json(os.path.join(run_dir, "summary.json"), summ)
        generate_report(run_dir, meta, anomalies, summ)
        return anomalies, summ

    # UB测试的原有逻辑
    # 若已有 K2 结果且非空，直接复用，避免重复调用
    existing = read_jsonl(os.path.join(run_dir, anomalies_file))
    if reuse_existing and existing:
        # 复用已有结果，但仍更新 summary.json 与 report.html，且回填引擎信息
        summ = summarize(existing)
        # 若存在 K2 结果文件，默认标记为 kimi-k2 引擎（无法确定版本时用 n/a）
        summ["analysis_engine"] = {
            "name": "kimi-k2",
            "version": "n/a",
            "degraded": False,
        }
        # 回填分析时间（UTC）
        summ["analysis_time"] = datetime.utcnow().isoformat() + "Z"
        write_json(os.path.join(run_dir, "summary.json"), summ)
        generate_report(run_dir, meta, existing, summ)
        return existing, summ
    provider = K2ProviderAdapter(k2) if k2 else None
    if provider and provider.enabled():
        # 按 suite 分组以控制单次请求载荷大小
        from collections import defaultdict
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for e in entries:
            g = e.get("suite") or "__default__"
            groups[g].append(e)
        for gid, ents in groups.items():
            # 准备该分组内每个条目的历史数组映射（key 以 :: 连接）
            hist_map: dict[str, list[float]] = {}
            for e in ents:
                k = (e.get("suite", ""), e.get("case", ""), e.get("metric", ""))
                hist_map["::".join(k)] = history.get(k, [])
            # 附加统计特征，帮助模型给出更具体的根因解释
            features = compute_entry_features(ents, history)
            # 降低并发：组与组之间小睡，降低触发限频的概率
            import time
            time.sleep(2.0)
            try:
                # 如果provider是K2Client，传递job_id
                if job_id and hasattr(provider, 'analyze'):
                    result = provider.analyze(
                        run_id=os.path.basename(run_dir),
                        group_id=str(gid),
                        entries=[{**e, "features": features.get("::".join(
                            [e.get("suite", ""), e.get("case", ""), e.get("metric", "")]))} for e in ents],
                        history=hist_map,
                        job_id=job_id
                    )
                else:
                    result = provider.analyze(
                        run_id=os.path.basename(run_dir),
                        group_id=str(gid),
                        entries=[{**e, "features": features.get("::".join(
                            [e.get("suite", ""), e.get("case", ""), e.get("metric", "")]))} for e in ents],
                        history=hist_map,
                    )
                anomalies.extend(_normalize_k2_anomalies(
                    result.get("anomalies", [])))
            except Exception as e:
                print(f"AI分析失败 (组 {gid}): {e}")
                ai_analysis_failed = True
                break  # 如果AI分析失败，跳出循环，使用启发式算法

        # 如果AI分析失败，fallback到启发式算法
        if ai_analysis_failed:
            print("AI分析失败，fallback到启发式算法")
            anomalies = heuristic_anomalies(
                entries, history, min_samples_for_anomaly=min_samples)
    else:
        anomalies = heuristic_anomalies(
            entries, history, min_samples_for_anomaly=min_samples)

    # 保存异常结果与汇总
    write_jsonl(os.path.join(run_dir, anomalies_file), anomalies)
    summ = summarize(anomalies)
    # 写入分析引擎元数据，便于前端展示/筛选
    enabled = bool(provider and provider.enabled())
    # 如果AI失败并fallback到启发式算法，标记为降级模式
    actual_degraded = (not enabled) or ai_analysis_failed

    # 从分析结果中获取实际使用的模型
    if anomalies and len(anomalies) > 0:
        # 检查是否有模型信息在结果中
        if hasattr(anomalies, '__iter__') and isinstance(anomalies[0], dict):
            # 从第一个异常中尝试获取模型信息（如果有的话）
            pass

    # 从summary中获取模型信息（如果存在）
    actual_model = summ.get("analysis_model", "")
    model_name = summ.get("model_name", "")

    if actual_model and actual_model != "heuristic":
        actual_engine = actual_model
        actual_version = model_name if model_name else actual_model
    elif actual_degraded:
        actual_engine = "heuristic"
        actual_version = "n/a"
    else:
        actual_engine = provider.name() if enabled else "heuristic"
        actual_version = provider.version() if enabled else "n/a"

    summ["analysis_engine"] = {
        "name": actual_engine,
        "version": actual_version,
        "degraded": actual_degraded,
    }
    # 写入分析时间（UTC）
    summ["analysis_time"] = datetime.utcnow().isoformat() + "Z"
    write_json(os.path.join(run_dir, "summary.json"), summ)
    # 生成静态报告页面
    generate_report(run_dir, meta, anomalies, summ)
    return anomalies, summ


def run_pipeline(source_url: str, archive_root: str, days: int, k2: K2Client | None) -> list[str]:
    new_runs = crawl_incremental(source_url, archive_root, days)
    processed: list[str] = []
    for run_dir in new_runs:
        records = parse_run(run_dir)
        _anoms, _summ = analyze_run(run_dir, k2, archive_root)
        processed.append(run_dir)
        # 降低K2限频概率：run 与 run 之间增加间隔
        time.sleep(3.0)
    return processed


def _pick_recent_runs_from_index(archive_root: str, limit: int) -> list[str]:
    index_path = os.path.join(archive_root, "runs_index.jsonl")
    rows = read_jsonl(index_path)
    if not rows:
        return []
    # 追加式索引，取末尾的最近 N 条（保持时间顺序从新到旧）
    selected = [row.get("run_dir") for row in rows if row.get("run_dir")]
    selected = [p for p in selected if isinstance(p, str)]
    unique: list[str] = []
    for p in selected:
        if p not in unique:
            unique.append(p)
    # unique 为追加顺序（旧->新）。取最近 N 个（尾部切片）。
    tail = unique[-limit:]
    return tail


def _pick_recent_runs_by_scan(archive_root: str, limit: int) -> list[str]:
    pattern = os.path.join(archive_root, "*", "run_*")
    paths = glob.glob(pattern)
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths[:limit]


def reanalyze_recent_runs(archive_root: str, limit: int, k2: K2Client | None, force: bool = False) -> list[str]:
    """对最近 N 个已有 run 进行复分析（不重新抓取）。
    优先依据 runs_index.jsonl 选取，若不存在则扫描目录按修改时间排序。
    若缺少 ub.jsonl，将先执行解析。
    """
    candidates = _pick_recent_runs_from_index(archive_root, limit)
    if not candidates:
        candidates = _pick_recent_runs_by_scan(archive_root, limit)
    processed: list[str] = []
    for run_dir in candidates:
        ub_path = os.path.join(run_dir, "ub.jsonl")
        need_parse = (not os.path.exists(ub_path)) or (
            os.path.exists(ub_path) and os.path.getsize(ub_path) == 0)
        if need_parse:
            parse_run(run_dir)
        analyze_run(run_dir, k2, archive_root, reuse_existing=not force)
        processed.append(run_dir)
    return processed


def reanalyze_missing(archive_root: str, k2: K2Client | None, max_runs: int | None = None, days: int | None = None) -> list[str]:
    """仅对缺少 K2 结果的 run 进行复分析。

    - 若 `anomalies.k2.jsonl` 不存在或文件大小为 0，则认为“未分析”。
    - 若 `ub.jsonl` 不存在或为空，将先执行解析。
    - 处理顺序按目录最近修改时间（新→旧）。
    - 每个 run 之间 sleep 以降低限频。
    """
    pattern = os.path.join(archive_root, "*", "run_*")
    paths = glob.glob(pattern)
    # 可选：仅筛选最近 N 天
    if days is not None and days > 0:
        cutoff = (datetime.utcnow() - timedelta(days=days-1)
                  ).strftime("%Y-%m-%d")
        filtered: list[str] = []
        for p in paths:
            date_dir = os.path.basename(os.path.dirname(p))
            if date_dir >= cutoff:
                filtered.append(p)
        paths = filtered
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    processed: list[str] = []
    for run_dir in paths:
        k2_path = os.path.join(run_dir, "anomalies.k2.jsonl")
        need_analyze = (not os.path.exists(k2_path)) or (
            os.path.exists(k2_path) and os.path.getsize(k2_path) == 0)
        if not need_analyze:
            continue
        ub_path = os.path.join(run_dir, "ub.jsonl")
        need_parse = (not os.path.exists(ub_path)) or (
            os.path.exists(ub_path) and os.path.getsize(ub_path) == 0)
        if need_parse:
            parse_run(run_dir)
        analyze_run(run_dir, k2, archive_root, reuse_existing=True)
        processed.append(run_dir)
        # 降低限频
        time.sleep(3.0)
        if max_runs is not None and len(processed) >= max_runs:
            break
    return processed


def reanalyze_runs_by_criteria(archive_root: str, runs: list, k2=None, force=False):
    """根据给定的runs列表进行重新分析"""
    processed = []
    for run_data in runs:
        rel = run_data.get("rel", "")
        if not rel:
            continue
        run_dir = os.path.join(archive_root, rel)
        if not os.path.isdir(run_dir):
            continue

        # 检查是否需要解析
        ub_path = os.path.join(run_dir, "ub.jsonl")
        need_parse = (not os.path.exists(ub_path)) or (
            os.path.exists(ub_path) and os.path.getsize(ub_path) == 0)
        if need_parse:
            parse_run(run_dir)

        # 执行分析 (force=True 强制重新分析)
        analyze_run(run_dir, k2, archive_root, reuse_existing=(not force))
        processed.append(rel)

        # 降低限频
        time.sleep(1.0)

    return processed
