from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def parse_unixbench_pre_text(html_text: str) -> list[dict[str, Any]]:
    """解析 UnixBench 的 <pre> 文本，提取每项测试数值与 Index 表。

    产出统一记录：
    - suite: "UnixBench"
    - case: ""（留空）
    - metric: 测试名称或 "<名称> INDEX" 或 "System Benchmarks Index Score"
    - value: 数值
    - unit: 原始单位（lps/MWIPS/KBps/lpm/index/score 等）
    - status: ""
    - raw: 原始行内容或解析细节
    """
    soup = BeautifulSoup(html_text, "html.parser")
    pre = soup.find("pre")
    if not pre:
        return []

    text = pre.get_text("\n")
    lines = [ln.rstrip() for ln in text.splitlines()]

    records: list[dict[str, Any]] = []

    # 第一类：直接数值行，例如：
    # Dhrystone 2 using register variables      160329308.0 lps   (10.0 s, 7 samples)
    # 约束单位在常见集合内，并要求后续存在括号，以避免误匹配头部说明行
    direct_pat = re.compile(
        r"^(?P<name>.+?)\s+(?P<value>[-+]?\d+(?:\.\d+)?)\s+(?P<unit>(?:lps|MWIPS|KBps|lpm))\s*\(",
        re.IGNORECASE,
    )

    # 第二类：Index 表格行（在 'System Benchmarks Index Values' 段落之后）
    idx_header_pat = re.compile(
        r"^System Benchmarks Index Values", re.IGNORECASE)
    idx_line_pat = re.compile(
        r"^(?P<name>.*?)\s+(?P<baseline>\d+(?:\.\d+)?)\s+(?P<result>\d+(?:\.\d+)?)\s+(?P<index>\d+(?:\.\d+)?)\s*$"
    )
    idx_score_pat = re.compile(
        r"^System Benchmarks Index Score\s+(?P<score>\d+(?:\.\d+)?)\s*$", re.IGNORECASE)

    in_idx_section = False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if idx_header_pat.match(s):
            in_idx_section = True
            continue
        if in_idx_section:
            mline = idx_line_pat.match(s)
            if mline:
                name = _norm_name(mline.group("name"))
                try:
                    index_val = float(mline.group("index"))
                except Exception:
                    continue
                records.append({
                    "suite": "UnixBench",
                    "case": "",
                    "metric": f"{name} INDEX",
                    "value": index_val,
                    "unit": "index",
                    "status": "",
                    "raw": {"baseline": mline.group("baseline"), "result": mline.group("result"), "line": s},
                })
                continue
            mscore = idx_score_pat.match(s)
            if mscore:
                try:
                    score = float(mscore.group("score"))
                except Exception:
                    continue
                records.append({
                    "suite": "UnixBench",
                    "case": "",
                    "metric": "System Benchmarks Index Score",
                    "value": score,
                    "unit": "score",
                    "status": "",
                    "raw": {"line": s},
                })
                # 不 break，允许后续潜在行
                continue

        # 尝试匹配直接数值行
        md = direct_pat.match(s)
        if md:
            name = _norm_name(md.group("name"))
            try:
                val = float(md.group("value"))
            except Exception:
                continue
            unit = md.group("unit")
            records.append({
                "suite": "UnixBench",
                "case": "",
                "metric": name,
                "value": val,
                "unit": unit,
                "status": "",
                "raw": {"line": s},
            })

    return records
