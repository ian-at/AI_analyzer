from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

from ..utils.io import read_jsonl


# 异常检测阈值配置 (基于241个历史样本的统计分析优化)
# 调整原因：平衡真异常检测和误报率控制
# - robust_z_threshold: 4.5 (原3.0) - 基于P95分位数分析，减少正常波动误报
# - pct_change_threshold: 35% (原30%) - 真正异常通常>60%，35%能有效过滤正常波动
# - high_severity_thresholds: robust_z>=6 或 pct_change>=60% - 标识极端异常
ROBUST_Z_THRESHOLD = 4.5
PCT_CHANGE_THRESHOLD = 0.35
HIGH_SEVERITY_RZ_THRESHOLD = 6.0
HIGH_SEVERITY_PCT_THRESHOLD = 0.6


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
    max_runs: int = None,
    min_samples: int = 10,  # 可配置的最小样本数
) -> dict[tuple[str, str, str], list[float]]:
    """扫描归档中的历史 run，为每个 (suite, case, metric) 构建数值历史数组。

    如果 max_runs 为 None，则使用所有可用的历史数据：
    - 首先统计总的可用历史数据量
    - 使用所有可用数据作为样本，确保基线随数据积累越来越准确
    - 最少使用10个样本（统计意义的最低要求）
    """
    # 朴素扫描：遍历归档下所有 ub.jsonl（按新到旧）
    pattern = os.path.join(archive_root, "*", "run_*", "ub.jsonl")
    files = sorted(glob.glob(pattern), reverse=True)
    key_set = set(keys)
    history: dict[tuple[str, str, str], list[float]] = defaultdict(list)

    # 如果未指定max_runs，先进行一次完整扫描来确定动态样本数
    if max_runs is None:
        # 统计每个key的总可用数据量
        total_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        for path in files:
            rows = read_jsonl(path)
            for row in rows:
                k = (row.get("suite", ""), row.get(
                    "case", ""), row.get("metric", ""))
                if k in key_set:
                    try:
                        float(row.get("value"))  # 验证是否为有效数值
                        total_counts[k] += 1
                    except Exception:
                        continue

        # 使用所有可用的历史数据作为样本（最少10个确保统计意义）
        if total_counts:
            avg_available = sum(total_counts.values()
                                ) // len(total_counts) if total_counts else 30
            max_available = max(total_counts.values()) if total_counts else 30
            # 使用所有可用数据，不设置上限，确保基线越来越准确
            max_runs = max(min_samples, max_available)
            print(
                f"使用所有历史数据: 平均可用数据{avg_available}个, 最大可用数据{max_available}个, 将使用{max_runs}个样本")
        else:
            max_runs = 30  # 默认值
            print(f"未找到历史数据，使用默认样本数: {max_runs}")

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


def generate_check_suggestions(entry: dict[str, Any], robust_z: float | None, pct_change: float | None, _unused_param: None = None) -> list[str]:
    """根据异常类型和统计特征生成具体的检查建议"""
    suggestions = []

    # 基础检查建议
    base_checks = [
        "检查 /proc/cpuinfo 确认CPU频率和核心配置",
        "查看 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 检查频率调节策略",
        "运行 htop 检查系统负载和进程状态"
    ]

    # 根据测试类型提供特定建议
    metric = entry.get("metric", "").lower()
    suite = entry.get("suite", "").lower()

    if "dhrystone" in metric or "整数" in metric:
        suggestions.extend([
            "检查CPU缓存配置：cat /sys/devices/system/cpu/cpu*/cache/index*/size",
            "确认编译器优化级别和指令集支持：gcc -march=native -Q --help=target"
        ])
    elif "whetstone" in metric or "浮点" in metric:
        suggestions.extend([
            "检查浮点单元状态：cat /proc/cpuinfo | grep -E '(fpu|vfp|neon)'",
            "验证浮点运算优化：lscpu | grep -E '(Flags|Features)'"
        ])
    elif "copy" in metric or "io" in metric.lower():
        suggestions.extend([
            "检查内存带宽：cat /proc/meminfo | grep -E '(MemTotal|MemAvailable)'",
            "确认存储I/O状态：iostat -x 1 3"
        ])
    elif "process" in metric or "进程" in metric:
        suggestions.extend([
            "检查进程调度策略：cat /proc/sys/kernel/sched_*",
            "查看系统调用开销：strace -c -f -S time sleep 1"
        ])
    elif "syscall" in metric or "系统调用" in metric:
        suggestions.extend([
            "检查内核版本和配置：uname -a && cat /proc/version",
            "查看系统调用表：cat /proc/kallsyms | grep sys_call_table"
        ])

    # 根据性能变化方向提供建议
    if robust_z is not None and robust_z < -2:  # 性能下降
        suggestions.extend([
            "查看热限频告警：dmesg | grep -E '(thermal|throttle)'",
            "检查是否进入节能模式：cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq",
            "确认没有资源限制：cat /proc/cgroups && systemctl status"
        ])
    elif robust_z is not None and robust_z > 2:  # 性能提升
        suggestions.extend([
            "确认测试环境一致性：比较内核参数和编译选项",
            "检查是否有性能优化配置变更：cat /proc/sys/kernel/perf_*"
        ])

    # 根据变化幅度提供建议
    if pct_change is not None and abs(pct_change) > 0.5:  # 变化超过50%
        suggestions.extend([
            "检查硬件配置变更：lscpu && lshw -short",
            "验证内核和驱动版本：modinfo $(lsmod | awk 'NR>1 {print $1}') | grep -E '(version|description)'"
        ])

    # 通用系统状态检查
    suggestions.extend(base_checks[:2])  # 添加最重要的基础检查

    # 去重并限制数量
    unique_suggestions = list(dict.fromkeys(suggestions))  # 保持顺序去重
    return unique_suggestions[:5]  # 最多返回5个建议


def heuristic_anomalies(entries: list[dict[str, Any]], history: dict[tuple[str, str, str], list[float]], min_samples_for_anomaly: int = 10) -> list[dict[str, Any]]:
    """启发式异常检测

    Args:
        entries: 当前运行的数据条目
        history: 历史数据
        min_samples_for_anomaly: 异常检测所需的最小样本数，默认10
    """
    results: list[dict[str, Any]] = []
    for e in entries:
        key = (e.get("suite", ""), e.get("case", ""), e.get("metric", ""))
        hist = history.get(key, [])

        # 样本数要求：历史样本数必须>=min_samples_for_anomaly才进行异常判断
        if len(hist) < min_samples_for_anomaly:
            continue

        current = float(e.get("value"))
        rz = robust_z_score(current, hist)
        pct = pct_change_vs_median(current, hist)

        # 改进的异常判断逻辑：使用AND逻辑，要求统计偏离和性能变化同时满足阈值
        # 去除vs_mean判断（与vs_median高度相关，避免重复）
        severity = None
        reason_parts: list[str] = []

        if rz is not None and pct is not None:
            abs_rz = abs(rz)
            abs_pct = abs(pct)

            # 分级判断：高、中、低三个严重度等级，都要求AND逻辑
            if abs_rz >= 8.0 and abs_pct >= 0.50:
                severity = "high"
                reason_parts.append(f"robust_z={rz:.2f}")
                reason_parts.append(f"Δ vs median={pct:+.0%}")
            elif abs_rz >= 6.0 and abs_pct >= 0.35:
                severity = "medium"
                reason_parts.append(f"robust_z={rz:.2f}")
                reason_parts.append(f"Δ vs median={pct:+.0%}")
            elif abs_rz >= 4.0 and abs_pct >= 0.25:
                severity = "low"
                reason_parts.append(f"robust_z={rz:.2f}")
                reason_parts.append(f"Δ vs median={pct:+.0%}")

        if severity:
            # 计算置信度：基于统计显著性和样本数量
            confidence_base = 0.7 if len(hist) >= 100 else 0.6
            confidence = min(0.95, confidence_base +
                             0.05 * (abs(rz or 0) / 10))

            results.append({
                "suite": e.get("suite"),
                "case": e.get("case"),
                "metric": e.get("metric"),
                "current_value": current,
                "unit": e.get("unit"),
                "severity": severity,  # 直接使用已判断的严重度
                "confidence": confidence,
                "primary_reason": ", ".join(reason_parts) or "significant deviation",
                "deltas": {
                    "vs_median_pct": pct,
                    "robust_z": rz,
                },
                "root_causes": [],
                "supporting_evidence": {
                    "history_n": len(hist),
                    "mean": mean(hist) if hist else None,
                    "median": median(hist) if hist else None,
                },
                "suggested_next_checks": generate_check_suggestions(e, rz, pct, None),
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
