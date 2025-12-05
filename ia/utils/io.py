from __future__ import annotations

import gzip
import io
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

import requests
from bs4 import BeautifulSoup


DATE_DIR_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}/?$")  # 支持单数字月/日
# 适配 unixbench-1867-1.html 格式（1867 为 patch_id，1 为 patch_set）
HTML_NAME_RE = re.compile(
    r".*?-(?P<patch_id>\d+)-(?P<patch_set>\d+)\.html$", re.IGNORECASE)
# 适配 unit-2248-1.log 格式（2248 为 patch_id，1 为 patch_set）
UNIT_LOG_NAME_RE = re.compile(
    r"unit-(?P<patch_id>\d+)-(?P<patch_set>\d+)\.log$", re.IGNORECASE)
# 适配 interface-2248-1.log 格式（2248 为 patch_id，1 为 patch_set）
INTERFACE_LOG_NAME_RE = re.compile(
    r"^interface-(?P<patch_id>\d+)-(?P<patch_set>\d+)\.log$", re.IGNORECASE)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, data: str) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)


def write_json(path: str, obj: dict) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_jsonl(path: str, rows: Iterable[dict]) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: str, row: dict) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def fetch_url(url: str, timeout: int = 20) -> requests.Response:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp


def list_remote_date_dirs(base_url: str, max_age_days: int | None = None) -> list[str]:
    # 假设目录页为 Apache/nginx 的 autoindex 列表
    resp = fetch_url(base_url)
    # 使用内置 html.parser 以减少外部依赖
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if DATE_DIR_RE.match(href):
            # 归一化为绝对 URL
            if not base_url.endswith("/"):
                base = base_url + "/"
            else:
                base = base_url
            full = base + href.strip("/") + "/"
            links.append(full)

    if max_age_days is None:
        return sorted(links)

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    filtered: list[str] = []
    for link in links:
        # 支持单数字和双数字的月份/日期格式
        m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})/", link)
        if not m:
            continue
        try:
            # 标准化日期格式后解析
            date_str = m.group(1)
            parts = date_str.split('-')
            if len(parts) == 3:
                year, month, day = parts
                normalized_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                dt = datetime.strptime(normalized_date, "%Y-%m-%d")
            else:
                continue
        except ValueError:
            continue
        if dt >= cutoff:
            filtered.append(link)
    return sorted(filtered)


@dataclass
class RemoteHtml:
    url: str
    name: str
    patch_id: str
    patch_set: str


@dataclass
class RemoteLog:
    url: str
    name: str
    patch_id: str
    patch_set: str


def list_remote_htmls(day_url: str) -> list[RemoteHtml]:
    resp = fetch_url(day_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[RemoteHtml] = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href.lower().endswith(".html"):
            name = href.split("/")[-1]
            m = HTML_NAME_RE.search(name)
            if not m:
                continue
            patch_id = m.group("patch_id")
            patch_set = m.group("patch_set")
            if not day_url.endswith("/"):
                base = day_url + "/"
            else:
                base = day_url
            full_url = base + name
            results.append(RemoteHtml(full_url, name, patch_id, patch_set))
    return results


def list_remote_logs(day_url: str) -> list[RemoteLog]:
    """列出远程目录中的单元测试日志文件"""
    resp = fetch_url(day_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[RemoteLog] = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href.lower().endswith(".log"):
            name = href.split("/")[-1]
            m = UNIT_LOG_NAME_RE.search(name)
            if not m:
                continue
            patch_id = m.group("patch_id")
            patch_set = m.group("patch_set")
            if not day_url.endswith("/"):
                base = day_url + "/"
            else:
                base = day_url
            full_url = base + name
            results.append(RemoteLog(full_url, name, patch_id, patch_set))
    return results


def list_remote_interface_logs(day_url: str) -> list[RemoteLog]:
    """列出远程目录中的接口测试日志文件"""
    resp = fetch_url(day_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[RemoteLog] = []
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href.lower().endswith(".log"):
            name = href.split("/")[-1]
            m = INTERFACE_LOG_NAME_RE.search(name)
            if not m:
                continue
            patch_id = m.group("patch_id")
            patch_set = m.group("patch_set")
            if not day_url.endswith("/"):
                base = day_url + "/"
            else:
                base = day_url
            full_url = base + name
            results.append(RemoteLog(full_url, name, patch_id, patch_set))
    return results


def download_to(path: str, url: str, timeout: int = 60) -> None:
    ensure_dir(os.path.dirname(path))
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
