from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


HEADER_SYNONYMS = {
    "suite": {"suite", "test suite", "suite_name"},
    "case": {"case", "test case", "name", "test_name"},
    "metric": {"metric", "kpi", "item", "metric_name"},
    "value": {"value", "result", "score", "val"},
    "unit": {"unit", "units"},
    "status": {"status", "pass", "fail", "result_status"},
}


def normalize_header(text: str) -> str:
    t = (text or "").strip().lower()
    for k, syns in HEADER_SYNONYMS.items():
        if t in syns:
            return k
    return t


def try_parse_number(text: str) -> tuple[float | None, str | None]:
    t = (text or "").strip()
    # 匹配数字与可选单位，例如 "12.3 ms" 或 "1,234 ops/s"
    m = re.match(r"^([-+]?\d+(?:[\.,]\d+)?)\s*([a-zA-Z%\/_-]+)?$", t)
    if not m:
        return None, None
    num_s = m.group(1).replace(",", "")
    try:
        num = float(num_s)
    except ValueError:
        return None, None
    unit = m.group(2)
    return num, unit


def parse_ub_html(html_text: str) -> list[dict[str, Any]]:
    """尽力解析：扫描表格，映射列头到标准字段，提取包含数值的行。"""
    # 使用内置 html.parser，避免对系统依赖的要求
    soup = BeautifulSoup(html_text, "html.parser")
    records: list[dict[str, Any]] = []

    tables = soup.find_all("table")
    for table in tables:
        # 识别表头
        header_cells = None
        thead = table.find("thead")
        if thead and thead.find("tr"):
            header_cells = [th.get_text(strip=True) for th in thead.find(
                "tr").find_all(["th", "td"])]
        else:
            # 尝试第一行为表头
            first_tr = table.find("tr")
            if first_tr:
                header_cells = [td.get_text(strip=True)
                                for td in first_tr.find_all(["th", "td"])]
        if not header_cells:
            continue

        header_keys = [normalize_header(h) for h in header_cells]
        # 收集数据行
        trs = table.find_all("tr")
        if trs and header_cells and trs[0].get_text(strip=True) == "".join(header_cells):
            trs = trs[1:]

        for tr in trs:
            cells = [td.get_text(strip=True)
                     for td in tr.find_all(["td", "th"])]
            if not cells or len(cells) < len(header_keys):
                continue
            row = {header_keys[i]: cells[i] for i in range(len(header_keys))}

            value_raw = row.get("value") or row.get("result") or ""
            num, unit = try_parse_number(value_raw)
            if num is None:
                continue
            rec = {
                "suite": row.get("suite") or "",
                "case": row.get("case") or row.get("name") or "",
                "metric": row.get("metric") or "value",
                "value": num,
                "unit": row.get("unit") or unit,
                "status": row.get("status") or "",
                "raw": row,
            }
            records.append(rec)

    return records
