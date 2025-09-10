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
    list_remote_htmls,
    read_json,
    read_jsonl,
    write_json,
)


def stable_run_dir(archive_root: str, date_str: str, patch_id: str, patch_set: str) -> str:
    return os.path.join(
        archive_root,
        date_str,
        f"run_p{patch_id}_ps{patch_set}",
    )


def compute_md5(path: str) -> str:
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def iter_day_strings(base_url: str, days: int) -> Iterator[str]:
    for day_url in list_remote_date_dirs(base_url, max_age_days=days):
        # extract YYYY-MM-DD
        date_str = day_url.rstrip("/").split("/")[-1]
        yield date_str


def crawl_incremental(base_url: str, archive_root: str, days: int = 7) -> list[str]:
    """增量下载新的 HTML run，并返回新创建的 run 目录列表。"""
    new_runs: list[str] = []
    for date_str in iter_day_strings(base_url, days):
        day_url = base_url.rstrip("/") + f"/{date_str}/"
        htmls = list_remote_htmls(day_url)
        if not htmls:
            continue

        # daily index
        day_dir = os.path.join(archive_root, date_str)
        ensure_dir(day_dir)
        day_index_path = os.path.join(day_dir, "index.jsonl")

        for item in htmls:
            run_dir = stable_run_dir(
                archive_root, date_str, item.patch_id, item.patch_set)
            raw_dir = os.path.join(run_dir, "raw_html")
            ensure_dir(raw_dir)
            dest_html = os.path.join(raw_dir, item.name)

            # 先处理索引管理（无论文件是否存在）
            runs_index_path = os.path.join(archive_root, "runs_index.jsonl")
            existing_runs = read_jsonl(runs_index_path) if os.path.exists(
                runs_index_path) else []
            already_exists = any(
                r.get("patch_id") == item.patch_id and
                r.get("patch_set") == item.patch_set and
                r.get("date") == date_str
                for r in existing_runs
            )

            # 检查文件是否需要下载
            file_exists = os.path.exists(dest_html)
            need_download = not file_exists
            md5 = None

            if need_download:
                # 下载文件
                download_to(dest_html, item.url)
                md5 = compute_md5(dest_html)

                meta = {
                    "source_url": item.url,
                    "date": date_str,
                    "patch_id": item.patch_id,
                    "patch_set": item.patch_set,
                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                    "files": {"html": item.name, "html_md5": md5},
                }
                write_json(os.path.join(run_dir, "meta.json"), meta)
            else:
                # 文件已存在，尝试从meta.json获取md5
                try:
                    meta = read_json(os.path.join(run_dir, "meta.json"))
                    md5 = meta.get("files", {}).get("html_md5", "")
                except:
                    # 如果无法读取meta，重新计算md5
                    md5 = compute_md5(dest_html)

            # 统一处理索引（只有不存在时才添加）
            if not already_exists:
                append_jsonl(day_index_path, {
                    "run_dir": run_dir,
                    "patch_id": item.patch_id,
                    "patch_set": item.patch_set,
                    "name": item.name,
                    "md5": md5,
                })
                append_jsonl(runs_index_path, {
                    "run_dir": run_dir,
                    "date": date_str,
                    "patch_id": item.patch_id,
                    "patch_set": item.patch_set,
                })

            new_runs.append(run_dir)

    return new_runs
