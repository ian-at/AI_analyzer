#!/usr/bin/env python3
"""
读取 `logs_payload.json` 并调用 API 的一站式提交接口 `/api/v1/diagnosis/submit`。

用法:
  python3 scripts/submit_logs_payload.py [--url http://localhost:8000]

脚本行为：
  - 读取仓库根的 `logs_payload.json` 文件
  - 将 `files.contents` 中的每个条目写入临时文件
  - 使用 `requests` 以 multipart/form-data 调用 `/api/v1/diagnosis/submit`
  - 打印响应 JSON
"""

import json
import os
import sys
import tempfile
import argparse
from pathlib import Path

import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("IA_SERVER_URL", "http://localhost:8000"), help="API server base URL")
    args = p.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    payload_path = repo_root / "logs_payload.json"
    if not payload_path.exists():
        print(f"找不到 {payload_path}. 请确保在仓库根创建了 logs_payload.json")
        sys.exit(1)

    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    device_id = payload.get("device_id") or ""
    description = payload.get("description") or ""
    files_map = payload.get("files", {}).get("contents", {})

    # 写入临时文件并准备 multipart 上传表单
    tmp_files = []
    try:
        for name, content in files_map.items():
            tf = tempfile.NamedTemporaryFile(delete=False)
            tf.write(content.encode("utf-8"))
            tf.flush()
            tf.close()
            tmp_files.append((name, tf.name))

        files = []
        for orig_name, path in tmp_files:
            # 把字段名改为 'files' 以匹配 FastAPI 接收列表
            files.append(("files", (orig_name, open(path, "rb"), "text/plain")))

        submit_url = args.url.rstrip("/") + "/api/v1/diagnosis/submit"
        data = {
            "device_id": device_id,
            "description": description,
        }

        print(f"POSTing to {submit_url} with {len(files)} file(s)...")
        resp = requests.post(submit_url, data=data, files=files, timeout=120)
        try:
            print("Response status:", resp.status_code)
            print(resp.json())
        except Exception:
            print("非 JSON 响应: ")
            print(resp.text)

    finally:
        # 关闭 file handles and remove temp files
        for _, path in tmp_files:
            try:
                os.unlink(path)
            except Exception:
                pass


if __name__ == "__main__":
    main()
