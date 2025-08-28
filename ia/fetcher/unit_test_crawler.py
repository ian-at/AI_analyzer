from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Iterator

from ..utils.io import (
    append_jsonl,
    download_to,
    ensure_dir,
    list_remote_date_dirs,
    list_remote_logs,
    read_jsonl,
    write_json,
)


def stable_unit_run_dir(archive_root: str, date_str: str, patch_id: str, patch_set: str) -> str:
    """生成单元测试运行目录路径"""
    return os.path.join(
        archive_root,
        date_str,
        f"unit_p{patch_id}_ps{patch_set}",
    )


def compute_md5(path: str) -> str:
    """计算文件MD5哈希值"""
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def normalize_date_format(date_str: str) -> str:
    """将日期格式从 YYYY-M-DD 标准化为 YYYY-MM-DD"""
    parts = date_str.split('-')
    if len(parts) == 3:
        year, month, day = parts
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return date_str


def iter_unit_day_strings(base_url: str, days: int) -> Iterator[tuple[str, str]]:
    """迭代单元测试的日期目录，返回(原始日期字符串, 标准化日期字符串)"""
    for day_url in list_remote_date_dirs(base_url, max_age_days=days):
        # extract YYYY-M-DD or YYYY-MM-DD
        raw_date_str = day_url.rstrip("/").split("/")[-1]
        normalized_date_str = normalize_date_format(raw_date_str)
        yield raw_date_str, normalized_date_str


def crawl_unit_test_incremental(base_url: str, archive_root: str, days: int = 7) -> list[str]:
    """增量下载新的单元测试日志文件，并返回新创建的运行目录列表。"""
    new_runs: list[str] = []

    for raw_date_str, normalized_date_str in iter_unit_day_strings(base_url, days):
        day_url = base_url.rstrip("/") + f"/{raw_date_str}/"
        logs = list_remote_logs(day_url)
        if not logs:
            continue

        # daily index - 使用标准化的日期格式
        day_dir = os.path.join(archive_root, normalized_date_str)
        ensure_dir(day_dir)
        day_index_path = os.path.join(day_dir, "index.jsonl")

        for item in logs:
            run_dir = stable_unit_run_dir(
                archive_root, normalized_date_str, item.patch_id, item.patch_set)
            raw_dir = os.path.join(run_dir, "raw_logs")
            ensure_dir(raw_dir)
            dest_log = os.path.join(raw_dir, item.name)

            # Skip if already exists
            if os.path.exists(dest_log):
                continue

            # Download
            download_to(dest_log, item.url)
            md5 = compute_md5(dest_log)

            meta = {
                "source_url": item.url,
                "date": normalized_date_str,
                "patch_id": item.patch_id,
                "patch_set": item.patch_set,
                "downloaded_at": datetime.utcnow().isoformat() + "Z",
                "files": {"log": item.name, "log_md5": md5},
                "test_type": "unit_test",
            }
            write_json(os.path.join(run_dir, "meta.json"), meta)

            # indexes - 写入前检查是否已存在，避免重复
            # 检查runs_index.jsonl中是否已有该记录
            runs_index_path = os.path.join(archive_root, "runs_index.jsonl")
            existing_runs = read_jsonl(runs_index_path) if os.path.exists(
                runs_index_path) else []
            already_exists = any(
                r.get("patch_id") == item.patch_id and
                r.get("patch_set") == item.patch_set and
                r.get("date") == normalized_date_str
                for r in existing_runs
            )

            if not already_exists:
                # 只有不存在时才写入索引
                append_jsonl(day_index_path, {
                    "run_dir": run_dir,
                    "patch_id": item.patch_id,
                    "patch_set": item.patch_set,
                    "name": item.name,
                    "md5": md5,
                })
                append_jsonl(runs_index_path, {
                    "run_dir": run_dir,
                    "date": normalized_date_str,
                    "patch_id": item.patch_id,
                    "patch_set": item.patch_set,
                })
            new_runs.append(run_dir)

    return new_runs
