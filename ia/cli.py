from __future__ import annotations

import argparse
import os
from typing import Optional

from .config import load_env_config
from .analyzer.k2_client import K2Client
from .orchestrator.pipeline import run_pipeline, reanalyze_recent_runs, reanalyze_missing
from .reporting.aggregate import collect_runs  # 保留以备后续CLI扩展


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="UB 智能分析（抓取→解析→分析→报告）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_crawl = sub.add_parser(
        "crawl", help="抓取→解析→分析→生成 report.html")
    p_crawl.add_argument("--source-url", required=False,
                         help="HTTP 根地址（可省略，默认读 config.json 或使用内置默认）")
    p_crawl.add_argument(
        "--archive-root", default="./archive", help="归档根目录（默认 ./archive）")
    p_crawl.add_argument("--days", type=int, default=None,
                         help="扫描最近多少天（可省略，默认读 config.json 或为3天）")
    p_crawl.add_argument(
        "--no-fallback", action="store_true", help="严格使用K2，失败不回退启发式")

    p_re = sub.add_parser("reanalyze", help="对最近 N 个已有 run 进行复分析（不重新抓取）")
    p_missing = sub.add_parser(
        "reanalyze-missing", help="仅复分析未完成K2分析的 run（跳过已分析的）")
    p_re.add_argument(
        "--archive-root", default="./archive", help="归档根目录（默认 ./archive）")
    p_re.add_argument("--limit", type=int, default=5,
                      help="复分析的 run 数量（最近 N 个）")
    p_re.add_argument("--force", action="store_true", help="强制覆盖已有 K2 结果")
    p_re.add_argument("--no-fallback", action="store_true",
                      help="严格使用K2，失败不回退启发式")
    p_missing.add_argument(
        "--archive-root", default="./archive", help="归档根目录（默认 ./archive）")
    p_missing.add_argument("--max-runs", type=int,
                           default=None, help="最多处理多少个 run（缺省为全部）")
    p_missing.add_argument(
        "--days", type=int, default=None, help="仅处理最近N天（例如3）")
    p_missing.add_argument(
        "--no-fallback", action="store_true", help="严格使用K2，失败不回退启发式")

    args = parser.parse_args(argv)

    if args.cmd == "crawl":
        cfg = load_env_config(args.source_url, args.archive_root, args.days)
        k2 = K2Client(cfg.model) if cfg.model.enabled else None
        os.makedirs(cfg.archive_root, exist_ok=True)
        try:
            done = run_pipeline(cfg.source_url, cfg.archive_root, cfg.days, k2)
        except Exception as e:
            if args.no_fallback:
                raise
            print(f"K2 调用失败，回退到启发式分析：{e}")
            done = run_pipeline(
                cfg.source_url, cfg.archive_root, cfg.days, None)
        print(f"已处理 {len(done)} 个新 run。归档目录: {cfg.archive_root}")
        print("提示：聚合视图已由前端渲染提供，无需生成 dashboard.html")
    elif args.cmd == "reanalyze":
        # 读取环境变量中的模型配置
        cfg = load_env_config(
            source_url=None, archive_root=args.archive_root, days=None)
        k2 = K2Client(cfg.model) if cfg.model.enabled else None
        os.makedirs(args.archive_root, exist_ok=True)
        try:
            done = reanalyze_recent_runs(
                args.archive_root, args.limit, k2, force=args.force)
        except Exception as e:
            if args.no_fallback:
                raise
            print(f"K2 调用失败，回退到启发式分析：{e}")
            done = reanalyze_recent_runs(
                args.archive_root, args.limit, None, force=args.force)
        print(f"已复分析 {len(done)} 个 run。归档目录: {args.archive_root}")
        print("提示：聚合视图已由前端渲染提供，无需生成 dashboard.html")
    elif args.cmd == "reanalyze-missing":
        cfg = load_env_config(
            source_url=None, archive_root=args.archive_root, days=None)
        k2 = K2Client(cfg.model) if cfg.model.enabled else None
        if args.no_fallback and (not k2 or not k2.enabled()):
            raise RuntimeError("严格K2模式需要提供K2配置(OPENAI_*)")
        try:
            done = reanalyze_missing(args.archive_root, k2 if k2 and k2.enabled() else (
                None if not args.no_fallback else k2), max_runs=args.max_runs, days=args.days)
        except Exception as e:
            if args.no_fallback:
                raise
            print(f"K2 调用失败，回退到启发式分析：{e}")
            done = reanalyze_missing(
                args.archive_root, None, max_runs=args.max_runs, days=args.days)
        print(f"已复分析缺失的 {len(done)} 个 run。归档目录: {args.archive_root}")
        print("提示：聚合视图已由前端渲染提供，无需生成 dashboard.html")


if __name__ == "__main__":
    main()
