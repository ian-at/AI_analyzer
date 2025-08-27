"""
批量异常分析优化器
针对大量异常点的场景进行优化，实现智能分组、并发处理、缓存等功能
"""

from __future__ import annotations

import json
import hashlib
import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import logging
import pickle
import os

from .anomaly import compute_entry_features, heuristic_anomalies


@dataclass
class AnalysisBatch:
    """分析批次"""
    batch_id: str
    entries: List[dict]
    features: dict
    priority: int = 1  # 优先级
    size: int = 0  # 批次大小


class BatchOptimizer:
    """批量处理优化器"""

    def __init__(self, cache_dir: str = None, max_batch_size: int = 10):
        self.logger = logging.getLogger(__name__)
        self.cache_dir = cache_dir or "./cache"
        self.max_batch_size = max_batch_size
        self.min_batch_size = 3

        # 创建缓存目录
        os.makedirs(self.cache_dir, exist_ok=True)

        # 缓存配置
        self.cache_ttl = 3600 * 24  # 24小时
        self.feature_cache = {}  # 特征缓存
        self.result_cache = {}   # 结果缓存

    def optimize_batches(self, entries: List[dict], history: dict) -> List[AnalysisBatch]:
        """
        优化批次分组
        根据异常点数量和类型智能分组，避免单个批次过大
        """
        batches = []

        # 计算所有条目的特征
        features = compute_entry_features(entries, history)

        # 按测试套件和严重程度分组
        groups = self._group_entries(entries, features, history)

        # 为每个组创建批次
        for group_key, group_entries in groups.items():
            # 如果组太大，进一步拆分
            if len(group_entries) > self.max_batch_size:
                sub_batches = self._split_large_group(group_entries, features)
                batches.extend(sub_batches)
            else:
                batch = self._create_batch(group_entries, features)
                batches.append(batch)

        # 按优先级排序
        batches.sort(key=lambda x: x.priority)

        return batches

    def _group_entries(self, entries: List[dict], features: dict,
                       history: dict) -> Dict[str, List[dict]]:
        """按套件和异常严重程度分组"""
        groups = defaultdict(list)

        for entry in entries:
            key = f"{entry.get('suite', '')}::{entry.get('case', '')}::{entry.get('metric', '')}"
            feature = features.get(key, {})

            # 评估严重程度
            severity = self._evaluate_severity(entry, feature, history)

            # 分组键：套件_严重程度
            group_key = f"{entry.get('suite', 'unknown')}_{severity}"
            groups[group_key].append(entry)

        return groups

    def _evaluate_severity(self, entry: dict, feature: dict, history: dict) -> str:
        """评估条目的异常严重程度"""
        key = (entry.get("suite", ""), entry.get(
            "case", ""), entry.get("metric", ""))
        hist = history.get(key, [])

        if len(hist) < 20:
            return "normal"

        robust_z = feature.get("robust_z")
        pct_change = feature.get("pct_change_vs_median")

        if robust_z is None or pct_change is None:
            return "normal"

        abs_rz = abs(robust_z)
        abs_pct = abs(pct_change)

        # 使用与anomaly.py相同的阈值
        if abs_rz >= 8.0 and abs_pct >= 0.50:
            return "high"
        elif abs_rz >= 6.0 and abs_pct >= 0.35:
            return "medium"
        elif abs_rz >= 4.0 and abs_pct >= 0.25:
            return "low"
        else:
            return "normal"

    def _split_large_group(self, entries: List[dict], features: dict) -> List[AnalysisBatch]:
        """拆分大型组为多个批次"""
        batches = []

        # 按指标类型进一步细分
        metric_groups = defaultdict(list)
        for entry in entries:
            metric_type = self._get_metric_type(entry.get("metric", ""))
            metric_groups[metric_type].append(entry)

        for metric_type, metric_entries in metric_groups.items():
            # 按max_batch_size分批
            for i in range(0, len(metric_entries), self.max_batch_size):
                batch_entries = metric_entries[i:i + self.max_batch_size]
                if len(batch_entries) >= self.min_batch_size or i == 0:
                    batch = self._create_batch(batch_entries, features)
                    batches.append(batch)
                else:
                    # 太小的批次合并到前一个
                    if batches:
                        batches[-1].entries.extend(batch_entries)
                        batches[-1].size = len(batches[-1].entries)

        return batches

    def _get_metric_type(self, metric: str) -> str:
        """获取指标类型分类"""
        metric_lower = metric.lower()

        if "dhrystone" in metric_lower or "整数" in metric_lower:
            return "integer"
        elif "whetstone" in metric_lower or "浮点" in metric_lower:
            return "float"
        elif "copy" in metric_lower or "io" in metric_lower:
            return "io"
        elif "process" in metric_lower or "进程" in metric_lower:
            return "process"
        elif "syscall" in metric_lower or "系统调用" in metric_lower:
            return "syscall"
        elif "pipe" in metric_lower:
            return "pipe"
        elif "shell" in metric_lower:
            return "shell"
        elif "index" in metric_lower or "score" in metric_lower:
            return "index"
        else:
            return "other"

    def _create_batch(self, entries: List[dict], features: dict) -> AnalysisBatch:
        """创建分析批次"""
        batch_id = self._generate_batch_id(entries)

        # 提取批次相关的特征
        batch_features = {}
        for entry in entries:
            key = f"{entry.get('suite', '')}::{entry.get('case', '')}::{entry.get('metric', '')}"
            if key in features:
                batch_features[key] = features[key]

        # 计算优先级（异常越严重优先级越高）
        priority = self._calculate_priority(entries, batch_features)

        return AnalysisBatch(
            batch_id=batch_id,
            entries=entries,
            features=batch_features,
            priority=priority,
            size=len(entries)
        )

    def _generate_batch_id(self, entries: List[dict]) -> str:
        """生成批次ID"""
        # 基于条目内容生成唯一ID
        content = json.dumps([{
            "suite": e.get("suite"),
            "case": e.get("case"),
            "metric": e.get("metric"),
            "value": e.get("value")
        } for e in entries], sort_keys=True)

        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _calculate_priority(self, entries: List[dict], features: dict) -> int:
        """计算批次优先级（数字越小优先级越高）"""
        max_severity = 100

        for entry in entries:
            key = f"{entry.get('suite', '')}::{entry.get('case', '')}::{entry.get('metric', '')}"
            feature = features.get(key, {})

            robust_z = feature.get("robust_z")
            if robust_z is not None:
                # Z分数越大，优先级越高
                severity = int(100 - min(abs(robust_z), 100))
                max_severity = min(max_severity, severity)

        return max_severity

    def get_cached_result(self, batch_id: str) -> Optional[dict]:
        """获取缓存的分析结果"""
        cache_file = os.path.join(self.cache_dir, f"{batch_id}.pkl")

        if not os.path.exists(cache_file):
            return None

        try:
            # 检查缓存是否过期
            if time.time() - os.path.getmtime(cache_file) > self.cache_ttl:
                os.remove(cache_file)
                return None

            with open(cache_file, "rb") as f:
                return pickle.load(f)
        except Exception as e:
            self.logger.warning(f"读取缓存失败: {e}")
            return None

    def save_cached_result(self, batch_id: str, result: dict):
        """保存分析结果到缓存"""
        cache_file = os.path.join(self.cache_dir, f"{batch_id}.pkl")

        try:
            with open(cache_file, "wb") as f:
                pickle.dump(result, f)
        except Exception as e:
            self.logger.warning(f"保存缓存失败: {e}")

    def merge_batch_results(self, batch_results: List[dict]) -> dict:
        """合并多个批次的分析结果"""
        all_anomalies = []

        for result in batch_results:
            if "anomalies" in result:
                all_anomalies.extend(result["anomalies"])

        # 去重（基于suite+case+metric）
        unique_anomalies = {}
        for anomaly in all_anomalies:
            key = f"{anomaly.get('suite')}::{anomaly.get('case')}::{anomaly.get('metric')}"
            if key not in unique_anomalies:
                unique_anomalies[key] = anomaly
            else:
                # 如果有重复，选择置信度更高的
                if anomaly.get("confidence", 0) > unique_anomalies[key].get("confidence", 0):
                    unique_anomalies[key] = anomaly

        anomalies = list(unique_anomalies.values())

        # 计算汇总信息
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for anomaly in anomalies:
            severity = anomaly.get("severity", "low")
            if severity in severity_counts:
                severity_counts[severity] += 1

        return {
            "anomalies": anomalies,
            "summary": {
                "total_anomalies": len(anomalies),
                "severity_counts": severity_counts
            }
        }

    def fallback_to_heuristic(self, entries: List[dict], history: dict) -> dict:
        """回退到启发式算法"""
        self.logger.info("使用启发式算法进行分析")

        anomalies = heuristic_anomalies(entries, history)

        # 计算汇总信息
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for anomaly in anomalies:
            severity = anomaly.get("severity", "low")
            if severity in severity_counts:
                severity_counts[severity] += 1

        return {
            "anomalies": anomalies,
            "summary": {
                "total_anomalies": len(anomalies),
                "severity_counts": severity_counts
            }
        }

    def analyze_with_progress(self, batches: List[AnalysisBatch],
                              analyzer_func, callback=None) -> List[dict]:
        """带进度回调的批量分析"""
        results = []
        total = len(batches)

        for i, batch in enumerate(batches):
            # 检查缓存
            cached = self.get_cached_result(batch.batch_id)
            if cached:
                self.logger.info(f"使用缓存结果: 批次 {batch.batch_id}")
                results.append(cached)
            else:
                # 执行分析
                try:
                    result = analyzer_func(batch)
                    self.save_cached_result(batch.batch_id, result)
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"批次 {batch.batch_id} 分析失败: {e}")
                    # 返回空结果
                    results.append(
                        {"anomalies": [], "summary": {"total_anomalies": 0}})

            # 进度回调
            if callback:
                callback(i + 1, total)

            # 添加小延迟避免过快请求
            if i < total - 1:
                time.sleep(0.5)

        return results
