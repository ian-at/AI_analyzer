#!/usr/bin/env bash
set -euo pipefail

# 一键运行：抓取最近3天并生成聚合报告
# 依赖 ./config.json 或 ./archive/config.json 中的 OPENAI_* 与 SOURCE_URL/ARCHIVE_ROOT/DAYS

cd "$(dirname "$0")/.."

python3 -m ia.cli crawl || true

echo "完成：已抓取并分析最近DAYS=3（或配置指定天数）的UB数据，生成各run的report.html。聚合视图由前端 /dashboard 动态渲染，无需 dashboard.html"


