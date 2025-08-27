"""
Webhook处理器 - 核心业务逻辑
"""

from __future__ import annotations

import os
import glob
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import requests

from ..config import load_env_config
from ..analyzer.k2_client import K2Client
from ..fetcher.crawler import crawl_incremental, stable_run_dir, compute_md5
from ..orchestrator.pipeline import parse_run, analyze_run
from ..utils.io import read_json, ensure_dir, list_remote_date_dirs, list_remote_htmls, download_to, write_json
from .models import SimplifiedWebhookResponse


logger = logging.getLogger(__name__)


class WebhookHandler:
    """Webhook处理器"""

    def __init__(self, archive_root: str = None, config=None):
        """
        初始化处理器

        Args:
            archive_root: 归档根目录
            config: 应用配置
        """
        self.archive_root = archive_root or os.environ.get(
            "IA_ARCHIVE", "./archive")
        self.config = config or load_env_config(None, self.archive_root)
        self.k2_client = K2Client(
            self.config.model) if self.config.model.enabled else None
        ensure_dir(self.archive_root)

    def search_patch_data(self, patch_id: str, patch_set: str, max_days: int = 7) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        搜索指定patch的数据，如果在远程找到会自动下载

        Args:
            patch_id: 补丁ID
            patch_set: 补丁集
            max_days: 最大搜索天数

        Returns:
            (是否找到, 日期字符串, 运行目录)
        """
        # 先检查本地是否已有数据
        pattern = os.path.join(self.archive_root, "*",
                               f"run_p{patch_id}_ps{patch_set}")
        existing = glob.glob(pattern)
        if existing:
            # 找到本地数据
            run_dir = existing[0]
            date_str = os.path.basename(os.path.dirname(run_dir))
            # 检查是否有meta.json文件（确保数据完整）
            if os.path.exists(os.path.join(run_dir, "meta.json")):
                logger.info(f"本地找到数据: {run_dir}")
                return True, date_str, run_dir

        # 搜索远程数据
        logger.info(f"开始搜索远程数据: patch {patch_id}/{patch_set}, 最近{max_days}天")
        source_url = self.config.source_url

        # 获取最近N天的日期目录
        try:
            date_dirs = list_remote_date_dirs(
                source_url, max_age_days=max_days)

            for date_url in date_dirs:
                date_str = date_url.rstrip("/").split("/")[-1]
                day_url = f"{source_url.rstrip('/')}/{date_str}/"

                # 列出该日期下的所有HTML文件
                htmls = list_remote_htmls(day_url)

                # 查找匹配的patch
                for item in htmls:
                    if item.patch_id == patch_id and item.patch_set == patch_set:
                        logger.info(
                            f"远程找到数据: {date_str}/p{patch_id}_ps{patch_set}.html")

                        # 构建本地目录
                        run_dir = stable_run_dir(
                            self.archive_root, date_str, patch_id, patch_set)

                        # 立即下载数据（复用crawler.py的逻辑）
                        try:
                            raw_dir = os.path.join(run_dir, "raw_html")
                            ensure_dir(raw_dir)
                            dest_html = os.path.join(raw_dir, item.name)

                            # 如果文件不存在，下载它
                            if not os.path.exists(dest_html):
                                logger.info(f"下载文件: {item.url} -> {dest_html}")
                                download_to(dest_html, item.url)

                                # 计算MD5
                                md5 = compute_md5(dest_html)

                                # 保存元数据
                                meta = {
                                    "source_url": item.url,
                                    "date": date_str,
                                    "patch_id": item.patch_id,
                                    "patch_set": item.patch_set,
                                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                                    "files": {"html": item.name, "html_md5": md5},
                                }
                                write_json(os.path.join(
                                    run_dir, "meta.json"), meta)
                                logger.info(f"数据下载完成: {run_dir}")

                            return True, date_str, run_dir

                        except Exception as e:
                            logger.error(f"下载数据失败: {e}")
                            # 继续搜索其他日期
                            continue

        except Exception as e:
            logger.error(f"搜索远程数据失败: {e}")

        return False, None, None

    def get_model_info(self) -> Tuple[str, str]:
        """
        获取模型配置信息

        Returns:
            (引擎名称, 模型名称)
        """
        # 从配置中获取实际的模型信息
        if self.config and hasattr(self.config, 'model'):
            model_config = self.config.model

            # 检查是否启用了AI模型
            if model_config.enabled:
                # 获取模型名称
                model_name = model_config.model if hasattr(
                    model_config, 'model') else "unknown"

                # 判断引擎类型
                if model_config.api_base and 'kimi' in str(model_config.api_base).lower():
                    engine = "kimi-k2"
                elif model_config.api_base and 'openai' in str(model_config.api_base).lower():
                    engine = "openai"
                elif model_config.api_base:
                    engine = "ai-model"
                else:
                    engine = "ai-model"

                return engine, model_name if model_name else "configured"

        # 如果没有配置AI模型，使用启发式算法
        return "heuristic", "heuristic"

    def process_webhook_simplified(self, patch_id: str, patch_set: str,
                                   force_refetch: bool = False,
                                   force_reanalyze: bool = True,
                                   max_search_days: int = 7,
                                   job_id: str = None) -> SimplifiedWebhookResponse:
        """
        处理简化的Webhook请求

        Args:
            patch_id: 补丁ID
            patch_set: 补丁集
            force_refetch: 是否强制重新获取
            force_reanalyze: 是否强制重新分析
            max_search_days: 最大搜索天数
            job_id: 任务ID

        Returns:
            SimplifiedWebhookResponse: 处理结果
        """
        engine, model = self.get_model_info()
        patch_str = f"{patch_id}/{patch_set}"

        try:
            # 搜索patch数据
            found, date_str, run_dir = self.search_patch_data(
                patch_id, patch_set, max_search_days)

            if not found:
                # 未找到数据
                return SimplifiedWebhookResponse(
                    success=False,
                    patch=patch_str,
                    message=f"未找到 patch {patch_str} 的UB数据（搜索了最近{max_search_days}天）",
                    engine=engine,
                    ai_model_configured=model,
                    force_refetch=force_refetch,
                    force_reanalyze=force_reanalyze,
                    max_search_days=max_search_days,
                    error=f"No data found for patch {patch_str}"
                )

            # 检查是否需要下载
            meta_path = os.path.join(run_dir, "meta.json")
            need_download = force_refetch or not os.path.exists(meta_path)

            if need_download:
                logger.info(f"下载数据: {date_str}/p{patch_id}_ps{patch_set}.html")
                self._download_patch_data(
                    self.config.source_url, date_str, patch_id, patch_set)

            # 检查是否需要解析
            ub_path = os.path.join(run_dir, "ub.jsonl")
            need_parse = not os.path.exists(ub_path) or os.path.getsize(
                ub_path) == 0 or force_refetch

            if need_parse:
                logger.info(f"解析HTML数据: {run_dir}")
                parse_run(run_dir)

            # 检查是否需要分析
            k2_path = os.path.join(run_dir, "anomalies.k2.jsonl")
            need_analyze = force_reanalyze or not os.path.exists(
                k2_path) or os.path.getsize(k2_path) == 0

            if need_analyze:
                logger.info(f"执行AI分析: {run_dir}")
                # 复用现有的analyze_run函数
                anomalies, summary = analyze_run(
                    run_dir,
                    self.k2_client,
                    self.archive_root,
                    reuse_existing=False,  # force_reanalyze=True时不复用
                    job_id=job_id
                )
            else:
                # 读取现有结果
                logger.info(f"使用缓存的分析结果: {run_dir}")
                from ..utils.io import read_jsonl
                anomalies = read_jsonl(k2_path)
                summary = read_json(os.path.join(run_dir, "summary.json"))

            # 构建成功响应
            return SimplifiedWebhookResponse(
                success=True,
                job_id=job_id,
                patch=patch_str,
                message=f"已开始获取和分析 patch {patch_str}，请使用 job_id 查询进度",
                engine=summary.get("analysis_engine", {}).get(
                    "name", engine) if isinstance(summary, dict) else engine,
                ai_model_configured=model,
                force_refetch=force_refetch,
                force_reanalyze=force_reanalyze,
                max_search_days=max_search_days,
                status_url=f"/api/v1/jobs/{job_id}" if job_id else None,
                estimated_time="600秒内完成",
                process_flow=[
                    "1. 检查本地是否有数据",
                    "2. 如需要，从远程获取UB数据",
                    "3. 解析HTML生成ub.jsonl",
                    f"4. 执行AI异常分析（使用config.json配置的模型: {model}）",
                    "5. 生成分析报告"
                ]
            )

        except Exception as e:
            logger.error(f"处理webhook请求失败: {e}", exc_info=True)
            return SimplifiedWebhookResponse(
                success=False,
                job_id=job_id,
                patch=patch_str,
                message=f"处理失败: {str(e)}",
                engine=engine,
                ai_model_configured=model,
                force_refetch=force_refetch,
                force_reanalyze=force_reanalyze,
                max_search_days=max_search_days,
                error=str(e)
            )

    def _download_patch_data(self, source_url: str, date_str: str, patch_id: str, patch_set: str):
        """
        下载指定patch的数据

        Args:
            source_url: 数据源URL
            date_str: 日期字符串
            patch_id: 补丁ID
            patch_set: 补丁集
        """
        from ..utils.io import download_to, write_json

        # 构建URL
        html_name = f"p{patch_id}_ps{patch_set}.html"
        url = f"{source_url.rstrip('/')}/{date_str}/{html_name}"

        # 构建本地路径
        run_dir = stable_run_dir(
            self.archive_root, date_str, patch_id, patch_set)
        raw_dir = os.path.join(run_dir, "raw_html")
        ensure_dir(raw_dir)
        dest_html = os.path.join(raw_dir, html_name)

        # 下载文件
        logger.info(f"下载文件: {url} -> {dest_html}")
        download_to(dest_html, url)

        # 保存元数据
        meta = {
            "source_url": url,
            "date": date_str,
            "patch_id": patch_id,
            "patch_set": patch_set,
            "downloaded_at": datetime.utcnow().isoformat() + "Z",
            "files": {"html": html_name}
        }
        write_json(os.path.join(run_dir, "meta.json"), meta)


def create_webhook_handler(archive_root: str = None) -> WebhookHandler:
    """
    创建Webhook处理器的工厂函数

    Args:
        archive_root: 归档根目录

    Returns:
        WebhookHandler实例
    """
    return WebhookHandler(archive_root)
