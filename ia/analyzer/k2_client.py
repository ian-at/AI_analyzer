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
        "anomalies": {"type": "array"},
    },
    "required": ["anomalies"],
}


PROMPT_SYSTEM = (
    "你是一名内核 UB 测试分析专家。你将收到当前 run 的各指标条目，以及每个指标的简短历史与统计特征。\n"
    "任务：识别“真正异常”的指标，并给出最可能的根因（需结合统计特征进行证据化解释）。\n"
    "准则：\n"
    "- 波动性：UB 数据存在天然波动，请优先依据稳健统计特征（robust_z、与历史中位数/均值的百分比变化、history_n）。\n"
    "- 阈值建议：abs(robust_z)≥3 或 |Δ vs median|≥30% 或 |Δ vs mean|≥30% 时可以判为异常；边界情况应谨慎，证据不足时判为非异常。\n"
    "- 方向性：明确说明异常是“性能下降”还是“性能提升”，并用当前值与历史对比定量描述。\n"
    "- 根因与证据：每个异常必须给出 primary_reason 与至少一个 root_cause（含 likelihood 0~1），并在 supporting_evidence 中引用具体特征（如历史样本数、robust_z、Δ% 等）。\n"
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
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

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
                "严格返回有效 JSON；不要包含 markdown；每个异常需包含 severity 与 confidence；"
                "结合 features（如 robust_z、pct_change_vs_median、pct_change_vs_mean、mean、median、history_n、current_value）给出根因与证据引用；"
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
        except Exception as e:
            # 如模型未返回合规 JSON，则返回空结果并附带原始输出与错误信息
            result = {"summary": {"total_anomalies": 0},
                      "anomalies": [], "_raw": content, "_error": str(e)}
        return result
