from __future__ import annotations

import json
import os
from typing import Any
import time

import requests

from ..config import ModelConfig


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
    "- 阈值建议：使用AND逻辑进行严格判断，必须同时满足统计偏离和性能变化两个条件。分级阈值：高严重度(abs(robust_z)≥8.0 且 |Δ vs median|≥50%)、中等严重度(abs(robust_z)≥6.0 且 |Δ vs median|≥35%)、低严重度(abs(robust_z)≥4.0 且 |Δ vs median|≥25%)；历史样本数必须≥20才进行异常判断；边界情况应谨慎，证据不足时判为非异常。\n"
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
    if t.startswith("```)"):
        # unlikely branch; keep generic
        t = t.strip("` ")
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


class K2Client:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def enabled(self) -> bool:
        return self.cfg.enabled

    def analyze(self, run_id: str, group_id: str, entries: list[dict[str, Any]], history: dict[str, list[float]]) -> dict:
        if not self.enabled():
            raise RuntimeError(
                "K2 客户端未启用（缺少 OPENAI_* 环境变量）")

        base = self.cfg.api_base or "https://api.openai.com/v1"
        url = base.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }

        # 仅在有有效API_KEY时才添加Authorization头（支持本地模型）
        if self.cfg.api_key and self.cfg.api_key.strip() and self.cfg.api_key.upper() != "EMPTY":
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        user_payload = {
            "run_id": run_id,
            "group_id": group_id,
            "entries": entries,
            "history": history,
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
                "suggested_next_checks 示例：『检查 /proc/cpuinfo 确认CPU频率』、『运行 cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor』、『使用 htop 检查系统负载』、『查看 dmesg | grep -i thermal 检查热限频』、『检查 /proc/cgroups 确认资源限制』等；"
                "结合 features（如 robust_z、pct_change_vs_median、mean、median、history_n、current_value）给出根因与证据引用；"
                "若证据不足，请不要硬判异常；所有自然语言字段必须使用中文；结合 ARM64 与 pKVM 场景优先给出相关根因，避免 x86 专属术语。"
            ),
        }

        data = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user", "content": json.dumps(
                    user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }

        # 简单退避重试（429/5xx）：最多 20 次，指数退避且尊重 Retry-After
        backoff = 5.0
        for attempt in range(20):
            resp = requests.post(
                url,
                headers=headers,
                json=data,
                timeout=120,
                verify=self.cfg.verify_ssl if self.cfg.verify_ssl is not None else True,
            )
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt == 19:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                delay = backoff
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                    except Exception:
                        import re as _re
                        m = _re.search(
                            r"([0-9]+(?:\.[0-9]+)?)", str(retry_after))
                        if m:
                            try:
                                delay = float(m.group(1))
                            except Exception:
                                delay = backoff
                time.sleep(delay)
                backoff = min(backoff * 2.0, 60.0)
                continue
            try:
                resp.raise_for_status()
            except requests.exceptions.SSLError:
                # 证书错误时直接抛出，让上层选择启发式回退
                raise
            break
        js = resp.json()
        content = js["choices"][0]["message"]["content"]
        try:
            result = coerce_json_from_text(content)
            # 为每个异常项补充支撑证据（如果AI没有完整返回）
            if "anomalies" in result:
                from .anomaly import compute_entry_features
                # 重新计算特征以确保supporting_evidence完整
                features = compute_entry_features(entries, history)
                for anomaly in result["anomalies"]:
                    key = f"{anomaly.get('suite', '')}::{anomaly.get('case', '')}::{anomaly.get('metric', '')}"
                    feature_data = features.get(key, {})

                    # 确保supporting_evidence字段存在且完整
                    if not anomaly.get("supporting_evidence"):
                        anomaly["supporting_evidence"] = {}

                    evidence = anomaly["supporting_evidence"]
                    # 补充缺失的统计信息
                    if "history_n" not in evidence:
                        evidence["history_n"] = feature_data.get(
                            "history_n", 0)
                    if "mean" not in evidence:
                        evidence["mean"] = feature_data.get("mean")
                    if "median" not in evidence:
                        evidence["median"] = feature_data.get("median")
                    if "robust_z" not in evidence:
                        evidence["robust_z"] = feature_data.get("robust_z")
                    if "pct_change_vs_median" not in evidence:
                        evidence["pct_change_vs_median"] = feature_data.get(
                            "pct_change_vs_median")
                    if "pct_change_vs_mean" not in evidence:
                        evidence["pct_change_vs_mean"] = feature_data.get(
                            "pct_change_vs_mean")

                        # 确保root_causes字段存在
                    if not anomaly.get("root_causes"):
                        anomaly["root_causes"] = []

                    # 确保suggested_next_checks字段存在且有实用内容
                    if not anomaly.get("suggested_next_checks"):
                        anomaly["suggested_next_checks"] = []

                    # 如果AI没有生成足够的建议，补充通用建议
                    if len(anomaly["suggested_next_checks"]) < 3:
                        base_checks = [
                            "检查 /proc/cpuinfo 确认CPU频率和核心配置",
                            "查看 /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 检查频率调节策略",
                            "运行 htop 或 top 检查系统负载和进程状态",
                            "查看 dmesg | grep -E '(thermal|throttle)' 检查热限频告警",
                            "检查 /proc/interrupts 查看中断分布和负载",
                            "验证 /proc/cgroups 和 /sys/fs/cgroup 下的资源限制配置"
                        ]

                        # 根据性能变化方向提供更具体的建议
                        if feature_data.get("robust_z", 0) < -2:  # 性能下降
                            specific_checks = [
                                "检查系统是否进入节能模式：cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor",
                                "查看是否有异常高的系统调用：strace -c -p <pid>",
                                "检查内存使用情况：free -h && cat /proc/meminfo",
                                "确认虚拟化开销：查看 /proc/stat 中的steal时间"
                            ]
                        else:  # 性能提升或其他
                            specific_checks = [
                                "确认测试环境一致性：检查内核版本和编译选项",
                                "验证缓存命中率和内存带宽：perf stat -e cache-misses",
                                "检查是否有调度优化：cat /proc/sys/kernel/sched_*"
                            ]

                        # 补充建议到最少4个
                        needed = 4 - len(anomaly["suggested_next_checks"])
                        available_checks = base_checks + specific_checks
                        anomaly["suggested_next_checks"].extend(
                            available_checks[:needed])

        except Exception as e:
            # 如模型未返回合规 JSON，则返回空结果并附带原始输出与错误信息
            result = {"summary": {"total_anomalies": 0},
                      "anomalies": [], "_raw": content, "_error": str(e)}
        return result
