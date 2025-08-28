from __future__ import annotations

import json
import os
import time
import logging
from typing import Any, Optional, List, Dict
from dataclasses import dataclass
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import ModelConfig
from .batch_optimizer import BatchOptimizer, AnalysisBatch
from .progress_tracker import get_tracker


JSON_SCHEMA_DESC = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "total_anomalies": {"type": "integer"},
                "severity_counts": {"type": "object"},
            },
            "required": ["total_anomalies"],
        },
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "suite": {"type": "string"},
                    "case": {"type": "string"},
                    "metric": {"type": "string"},
                    "current_value": {"type": "number"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "primary_reason": {"type": "string"},
                    "supporting_evidence": {
                        "type": "object",
                        "properties": {
                            "history_n": {"type": "integer"},
                            "mean": {"type": ["number", "null"]},
                            "median": {"type": ["number", "null"]},
                            "robust_z": {"type": ["number", "null"]},
                            "pct_change_vs_median": {"type": ["number", "null"]},
                            "pct_change_vs_mean": {"type": ["number", "null"]}
                        },
                        "required": ["history_n"]
                    },
                    "root_causes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cause": {"type": "string"},
                                "likelihood": {"type": ["number", "null"]}
                            },
                            "required": ["cause"]
                        }
                    },
                    "suggested_next_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "具体可执行的后续检查建议"
                    }
                },
                "required": ["suite", "case", "metric", "current_value", "severity", "confidence", "primary_reason", "supporting_evidence", "root_causes", "suggested_next_checks"]
            }
        },
    },
    "required": ["summary", "anomalies"],
}


PROMPT_SYSTEM = (
    "你是一名内核 UB 测试分析专家。你将收到当前 run 的各指标条目，以及每个指标的简短历史与统计特征。\n"
    "任务：识别『真正异常』的指标，并给出最可能的根因和具体的后续检查建议。\n"
    "准则：\n"
    "- 波动性：UB 数据存在天然波动，请优先依据稳健统计特征（robust_z、与历史中位数/均值的百分比变化、history_n）。\n"
    "- 阈值建议：使用AND逻辑进行严格判断，必须同时满足统计偏离和性能变化两个条件。分级阈值：高严重度(abs(robust_z)≥8.0 且 |Δ vs median|≥50%)、中等严重度(abs(robust_z)≥6.0 且 |Δ vs median|≥35%)、低严重度(abs(robust_z)≥4.0 且 |Δ vs median|≥25%)；历史样本数必须≥10才进行异常判断；边界情况应谨慎，证据不足时判为非异常。\n"
    "- 方向性：明确说明异常是『性能下降』还是『性能提升』，并用当前值与历史对比定量描述。\n"
    "- 根因与证据：每个异常必须给出 primary_reason 与至少一个 root_cause（含 likelihood 0~1），并在 supporting_evidence 中引用具体特征（如历史样本数、robust_z、pct_change_vs_median 等）。\n"
    "- 后续建议：每个异常必须在 suggested_next_checks 中提供3-5个具体可执行的检查建议，例如：『检查 /proc/cpuinfo 确认CPU频率设置』、『查看 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor』、『运行 htop 检查系统负载』、『检查内核日志中的热限频告警』、『验证cgroup限制配置』等。\n"
    "- 置信度：每个异常项必须包含 confidence 字段（0~1之间的数值），不可为null或省略，基于统计证据强度评估。\n"
    "- 环境：目标平台为 ARM64，Linux 内核 pKVM 场景（EL1/EL2）。常见影响因素包括：CPU 频率/能效策略（cpufreq governor: performance/powersave/schedutil）、热限频、big.LITTLE 调度失衡、中断亲和与 IRQ 绑核、cgroup/cpuset/rt 限制、隔离核/IRQ 亲和（isolcpus/nohz_full）、虚拟化开销（EL2 trap/PMU 虚拟化/阶段页表）、页大小/THP、缓存/内存带宽与 NUMA（若存在）、编译器优化与链接方式、二进制是否被重新编译、内核/固件配置变更等。\n"
    "- 术语边界：请避免输出 x86 专有概念（如 SMT/Turbo Boost 等），优先给出 ARM64/pKVM 相关表述。\n"
    "- 语言：除专有名词外，所有自然语言字段请使用中文表达（含 primary_reason、root_causes.cause、suggested_next_checks 等）。\n"
    "- 输出：confidence 返回 0~1 的小数；严格按 JSON 输出，符合给定 schema，不要输出 Markdown 或解释文字。"
)


def coerce_json_from_text(text: str) -> dict:
    # Remove code fences if present
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("` ")
        # try to find the json block
        if t.lower().startswith("json"):
            t = t[4:]
    # Remove leading non-json prefix
    first_brace = t.find("{")
    if first_brace > 0:
        t = t[first_brace:]
    # Remove trailing junk after last closing brace
    last_brace = t.rfind("}")
    if last_brace != -1:
        t = t[: last_brace + 1]
    return json.loads(t)


@dataclass
class ModelEndpoint:
    """模型端点配置"""
    name: str
    api_base: str
    api_key: str
    model: str
    enabled: bool = True
    priority: int = 1
    timeout: int = 120
    max_retries: int = 3
    last_used: float = 0
    error_count: int = 0
    success_count: int = 0


class K2Client:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.logger = logging.getLogger(__name__)
        self.batch_optimizer = BatchOptimizer()
        self.models = []
        self.config = {}  # 初始化配置字典
        self.session = self._create_session()
        self._load_models_config()

    def _create_session(self) -> requests.Session:
        """创建带重试机制的会话"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["POST", "GET"]  # 兼容旧版本urllib3
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _load_models_config(self):
        """加载模型配置"""
        # 查找配置文件
        config_paths = [
            "models_config.json",
            "./models_config.json",
            os.path.join(os.path.dirname(__file__),
                         "../../models_config.json"),
            "/data/intelligent-analysis/models_config.json",  # 添加绝对路径
        ]

        config_data = None
        for path in config_paths:
            abs_path = os.path.abspath(path)
            self.logger.debug(
                f"检查配置文件: {abs_path} (存在={os.path.exists(abs_path)})")
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                        self.logger.info(f"成功从 {abs_path} 加载模型配置")
                        break
                except Exception as e:
                    self.logger.warning(f"加载配置文件 {abs_path} 失败: {e}")

        if config_data and "models" in config_data:
            # 从配置文件加载多个模型
            for model_cfg in config_data["models"]:
                endpoint = ModelEndpoint(
                    name=model_cfg.get("name", ""),
                    api_base=model_cfg.get("api_base", ""),
                    api_key=model_cfg.get("api_key", ""),
                    model=model_cfg.get("model", ""),
                    enabled=model_cfg.get("enabled", True),
                    priority=model_cfg.get("priority", 1),
                    timeout=model_cfg.get("timeout", 120),
                    max_retries=model_cfg.get("max_retries", 3)
                )
                if endpoint.enabled:
                    self.models.append(endpoint)

            # 保存配置供后续使用
            self.config = config_data

            # 保存批量优化配置
            if "batch_optimization" in config_data:
                batch_cfg = config_data["batch_optimization"]
                self.batch_optimizer.max_batch_size = batch_cfg.get(
                    "max_batch_size", 10)
                self.batch_optimizer.min_batch_size = batch_cfg.get(
                    "min_batch_size", 3)

        # 如果没有配置文件，使用环境变量或默认配置
        if not self.models and self.cfg.api_key and self.cfg.model:
            endpoint = ModelEndpoint(
                name="default",
                api_base=self.cfg.api_base or "https://api.openai.com/v1",
                api_key=self.cfg.api_key,
                model=self.cfg.model,
                enabled=True
            )
            self.models.append(endpoint)

        # 按优先级排序
        self.models.sort(key=lambda x: x.priority)

        if self.models:
            self.logger.info(f"已加载 {len(self.models)} 个模型端点")
            for m in self.models:
                self.logger.info(f"  - {m.name}: {m.model} (优先级={m.priority})")

    def enabled(self) -> bool:
        return len(self.models) > 0

    def get_model_name(self) -> str:
        """获取当前使用的AI模型名称"""
        if not self.enabled():
            return "no_model"

        # 选择最佳可用模型
        available = [m for m in self.models if m.enabled and m.error_count < 5]
        if available:
            # 按优先级排序，返回第一个模型的名称
            available.sort(key=lambda x: x.priority)
            return available[0].model

        # 如果没有可用模型，返回第一个模型的名称
        return self.models[0].model if self.models else "unknown_model"

    def _select_model(self) -> Optional[ModelEndpoint]:
        """选择最佳可用模型"""
        available = [m for m in self.models if m.enabled and m.error_count < 5]
        if not available:
            # 重置错误计数
            for m in self.models:
                m.error_count = 0
            available = [m for m in self.models if m.enabled]

        if not available:
            return None

        # 选择优先级最高且成功率最好的
        available.sort(key=lambda x: (
            x.priority, -x.success_count, x.error_count))

        # 简单的速率限制：避免过快调用同一个模型
        now = time.time()
        for m in available:
            if now - m.last_used > 0.5:  # 至少间隔0.5秒
                return m

        return available[0]

    def analyze(self, run_id: str, group_id: str, entries: list[dict[str, Any]], history: dict, job_id: str = None) -> dict:
        """分析异常，支持批量优化和多模型"""
        if not self.enabled():
            raise RuntimeError("AI 客户端未启用（缺少配置）")

        # 创建进度跟踪
        if job_id:
            tracker = get_tracker()
            tracker.create_job(job_id, total_batches=1)
            tracker.update_progress(job_id, status="running")

            # 检查是否需要批量处理
        # 根据配置的批次大小决定是否使用批量优化
        batch_config = self.config.get("batch_optimization", {})
        max_batch_size = batch_config.get("max_batch_size", 10)
        min_batch_size = batch_config.get("min_batch_size", 3)

        # 当条目数超过最大批次大小时，使用批量优化
        if len(entries) > max_batch_size:
            self.logger.info(
                f"检测到 {len(entries)} 个条目，超过最大批次大小 {max_batch_size}，使用批量优化")
            return self._analyze_batch_optimized(run_id, group_id, entries, history, job_id)

        # 标准分析流程
        result = self._analyze_with_fallback(
            run_id, group_id, entries, history, job_id)

        # 更新进度为完成
        if job_id:
            tracker = get_tracker()
            tracker.update_progress(
                job_id, status="completed", current_batch=1, total_batches=1)

        return result

    def _analyze_with_fallback(self, run_id: str, group_id: str,
                               entries: list[dict[str, Any]],
                               history: dict, job_id: str = None) -> dict:
        """带故障转移的分析"""
        last_error = None
        used_model = None

        for attempt in range(3):
            model = self._select_model()
            if not model:
                self.logger.error("没有可用的模型")
                break

            try:
                self.logger.info(f"使用模型 {model.name} 进行分析")
                if job_id:
                    tracker = get_tracker()
                    tracker.update_progress(job_id, current_model=model.model)

                result = self._analyze_with_model(
                    model, run_id, group_id, entries, history)
                used_model = model.model  # 记录成功使用的模型

                # 在结果中添加实际使用的模型信息
                if "summary" not in result:
                    result["summary"] = {}
                result["summary"]["analysis_model"] = model.model
                result["summary"]["model_name"] = model.name

                return result
            except Exception as e:
                last_error = e
                model.error_count += 1
                self.logger.warning(
                    f"模型 {model.name} 分析失败 (尝试 {attempt + 1}/3): {e}")
                time.sleep(2 ** attempt)  # 指数退避

        # 所有模型都失败，使用启发式算法
        self.logger.warning(f"所有AI模型失败，回退到启发式算法: {last_error}")
        if job_id:
            tracker = get_tracker()
            tracker.update_progress(
                job_id, status="failed", error_message=str(last_error))

        result = self.batch_optimizer.fallback_to_heuristic(entries, history)

        # 标记为启发式算法
        if "summary" not in result:
            result["summary"] = {}
        result["summary"]["analysis_model"] = "heuristic"
        result["summary"]["model_name"] = "heuristic"

        return result

    def _analyze_with_model(self, model: ModelEndpoint, run_id: str, group_id: str,
                            entries: list[dict[str, Any]],
                            history: dict[str, list[float]]) -> dict:
        """使用指定模型进行分析"""
        model.last_used = time.time()

        url = model.api_base.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }

        # 仅在有有效API_KEY时才添加Authorization头（支持本地模型）
        if model.api_key and model.api_key.strip() and model.api_key.upper() != "EMPTY":
            headers["Authorization"] = f"Bearer {model.api_key}"

        # 转换history的键为字符串（JSON不支持tuple作为键）
        history_str_keys = {}
        for k, v in history.items():
            if isinstance(k, tuple):
                history_str_keys["::".join(str(x) for x in k)] = v
            else:
                history_str_keys[k] = v

        user_payload = {
            "run_id": run_id,
            "group_id": group_id,
            "entries": entries,
            "history": history_str_keys,
            "context": {
                "arch": "arm64",
                "os": "linux",
                "hypervisor": "pKVM",
                "suite": "UnixBench"
            },
            "output_schema": JSON_SCHEMA_DESC,
            "instructions": (
                "严格返回有效 JSON；不要包含 markdown；每个异常项必须包含 severity 和 confidence 字段，confidence 必须是0~1之间的数值，不可为null；"
                "必须包含完整的 supporting_evidence 字段，包含 history_n、mean、median、robust_z 等统计信息；"
                "必须包含 root_causes 数组，每个根因包含 cause 和 likelihood 字段；"
                "必须包含 suggested_next_checks 数组，每个异常至少提供3-5个具体可执行的检查命令或步骤；"
            ),
        }

        data = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": json.dumps(
                    user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }

        resp = self.session.post(
            url,
            headers=headers,
            json=data,
            timeout=model.timeout,
            verify=True
        )
        resp.raise_for_status()

        model.success_count += 1
        model.error_count = max(0, model.error_count - 1)

        js = resp.json()
        content = js["choices"][0]["message"]["content"]

        try:
            result = coerce_json_from_text(content)
            # 补充支撑证据
            if "anomalies" in result:
                from .anomaly import compute_entry_features
                features = compute_entry_features(entries, history)
                for anomaly in result["anomalies"]:
                    key = f"{anomaly.get('suite', '')}::{anomaly.get('case', '')}::{anomaly.get('metric', '')}"
                    feature_data = features.get(key, {})

                    # 确保supporting_evidence字段完整
                    if not anomaly.get("supporting_evidence"):
                        anomaly["supporting_evidence"] = {}

                    evidence = anomaly["supporting_evidence"]
                    for field in ["history_n", "mean", "median", "robust_z", "pct_change_vs_median", "pct_change_vs_mean"]:
                        if field not in evidence:
                            evidence[field] = feature_data.get(field)

                    # 确保必要字段存在
                    if not anomaly.get("root_causes"):
                        anomaly["root_causes"] = []
                    if not anomaly.get("suggested_next_checks"):
                        anomaly["suggested_next_checks"] = []

        except Exception as e:
            result = {"summary": {"total_anomalies": 0},
                      "anomalies": [], "_raw": content, "_error": str(e)}

        return result

    def _analyze_batch_optimized(self, run_id: str, group_id: str,
                                 entries: list[dict[str, Any]],
                                 history: dict, job_id: str = None) -> dict:
        """使用批量优化进行分析"""
        self.logger.info(f"使用批量优化分析 {len(entries)} 个条目")

        # 优化批次
        batches = self.batch_optimizer.optimize_batches(entries, history)
        total_batches = len(batches)
        self.logger.info(f"分成 {total_batches} 个批次进行分析")

        # 更新总批次数
        if job_id:
            tracker = get_tracker()
            tracker.update_progress(
                job_id, total_batches=total_batches, current_batch=0)

        batch_results = []
        current_batch_num = 0

        def analyze_batch(batch: AnalysisBatch) -> dict:
            nonlocal current_batch_num
            current_batch_num += 1

            # 更新进度
            if job_id:
                tracker = get_tracker()
                progress_pct = (current_batch_num / total_batches) * 100
                tracker.update_progress(
                    job_id,
                    current_batch=current_batch_num,
                    total_batches=total_batches
                )
                self.logger.info(
                    f"批次 {current_batch_num}/{total_batches} 开始分析 ({progress_pct:.1f}%)")

            batch_entries = batch.entries
            batch_history = {}
            for e in batch_entries:
                key = f"{e.get('suite', '')}::{e.get('case', '')}::{e.get('metric', '')}"
                k = (e.get('suite', ''), e.get('case', ''), e.get('metric', ''))
                if k in history:
                    batch_history[key] = history[k]

            try:
                result = self._analyze_with_fallback(
                    run_id, f"{group_id}_batch_{batch.batch_id}",
                    batch_entries, batch_history, job_id
                )
                self.logger.info(
                    f"批次 {current_batch_num}/{total_batches} 分析完成")
                return result
            except Exception as e:
                self.logger.error(f"批次 {batch.batch_id} 分析失败: {e}")
                return self.batch_optimizer.fallback_to_heuristic(batch_entries, history)

        # 顺序处理批次（为了更好的进度跟踪）
        for batch in batches:
            result = analyze_batch(batch)
            batch_results.append(result)

        # 标记为完成
        if job_id:
            tracker = get_tracker()
            tracker.update_progress(
                job_id, status="completed")

        # 合并结果
        merged = self.batch_optimizer.merge_batch_results(batch_results)

        # 确保包含模型信息
        if batch_results and "summary" in batch_results[0]:
            if "summary" not in merged:
                merged["summary"] = {}
            merged["summary"]["analysis_model"] = batch_results[0]["summary"].get(
                "analysis_model", "unknown")
            merged["summary"]["model_name"] = batch_results[0]["summary"].get(
                "model_name", "unknown")

        return merged
