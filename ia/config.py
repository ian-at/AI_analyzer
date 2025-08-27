from __future__ import annotations

import os
from dataclasses import dataclass
import json
from typing import Optional, Dict, Any


@dataclass
class ModelConfig:
    api_key: str | None
    api_base: str | None
    model: str | None
    verify_ssl: bool | None = None
    # 新增多模型配置支持
    models_config_file: str | None = None
    batch_optimization_enabled: bool = True
    max_batch_size: int = 10
    cache_enabled: bool = True

    @property
    def enabled(self) -> bool:
        # 支持本地模型：API_KEY为"EMPTY"时仍可启用（适用于本地Qwen等模型）
        has_key = self.api_key and self.api_key.strip() and self.api_key.upper() != "EMPTY"
        has_model = bool(self.model and self.model.strip())
        has_base = bool(self.api_base and self.api_base.strip())
        has_models_config = bool(
            self.models_config_file and os.path.exists(self.models_config_file))

        # 有API_KEY和模型名称，或者有本地API_BASE和模型名称（API_KEY为EMPTY），或者有多模型配置文件
        return (has_key and has_model) or (not has_key and has_model and has_base) or has_models_config


@dataclass
class AppConfig:
    source_url: str
    archive_root: str
    days: int
    model: ModelConfig


def load_env_config(
    source_url: str | None,
    archive_root: str | None,
    days: int | None = None,
) -> AppConfig:
    # 先尝试从配置文件加载（无需每次手动导入），若不存在再回退到环境变量
    # 支持读取多个配置文件位置
    # 只使用相对路径
    cfg_paths = [
        "models_config.json",
        "./models_config.json",
        "config.json",
        "./config.json",
        os.path.join(archive_root or "./archive", "models_config.json"),
        os.path.join(archive_root or "./archive", "config.json"),
    ]
    file_cfg = {}
    models_cfg_file = None

    # 已在上面合并加载配置

    # 查找模型配置文件（优先models_config.json）
    for p in ["models_config.json", "./models_config.json", "config.json", "./config.json"]:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    temp_cfg = json.load(f)
                    # 如果是models_config或包含models字段，则作为模型配置
                    if "models" in temp_cfg or "models_config" in p:
                        models_cfg_file = p
                    # 如果还没有主配置，也使用这个文件
                    if not file_cfg:
                        file_cfg = temp_cfg
                    if models_cfg_file:
                        break
        except Exception:
            pass

    # 模型配置读取
    api_key = (file_cfg.get("OPENAI_API_KEY") if file_cfg else None)
    api_base = (file_cfg.get("OPENAI_API_BASE") if file_cfg else None)
    model = (file_cfg.get("OPENAI_MODEL") if file_cfg else None)
    verify_ssl_cfg = file_cfg.get("OPENAI_VERIFY_SSL") if file_cfg else None
    # 环境变量覆盖文件配置，便于临时切换
    api_key = os.environ.get("OPENAI_API_KEY", api_key)
    api_base = os.environ.get("OPENAI_API_BASE", api_base)
    model = os.environ.get("OPENAI_MODEL", model)
    verify_env = os.environ.get("OPENAI_VERIFY_SSL")
    if verify_env is not None:
        verify_ssl = not (verify_env.strip().lower() in ("0", "false", "no"))
    elif isinstance(verify_ssl_cfg, bool):
        verify_ssl = verify_ssl_cfg
    elif isinstance(verify_ssl_cfg, str):
        verify_ssl = not (verify_ssl_cfg.strip().lower()
                          in ("0", "false", "no"))
    else:
        verify_ssl = True

    # App 配置读取（CLI 参数为空时回退）
    source_url = source_url or os.environ.get("SOURCE_URL") or (file_cfg.get(
        "SOURCE_URL") if file_cfg else None) or "http://10.42.39.161/results/"
    archive_root = archive_root or os.environ.get("ARCHIVE_ROOT") or (
        file_cfg.get("ARCHIVE_ROOT") if file_cfg else None) or "./archive"
    if days is None:
        days_val = os.environ.get("DAYS") or (
            file_cfg.get("DAYS") if file_cfg else None)
        try:
            days = int(days_val) if days_val is not None else 3
        except Exception:
            days = 3

    # 读取批量优化和缓存配置
    batch_opt_enabled = file_cfg.get("batch_optimization", {}).get(
        "enabled", True) if file_cfg else True
    max_batch_size = file_cfg.get("batch_optimization", {}).get(
        "max_batch_size", 10) if file_cfg else 10
    cache_enabled = file_cfg.get("batch_optimization", {}).get(
        "cache_enabled", True) if file_cfg else True

    # 环境变量覆盖
    batch_opt_enabled = os.environ.get("BATCH_OPTIMIZATION_ENABLED", str(
        batch_opt_enabled)).lower() in ("true", "1", "yes")
    max_batch_size = int(os.environ.get("MAX_BATCH_SIZE", str(max_batch_size)))
    cache_enabled = os.environ.get("CACHE_ENABLED", str(
        cache_enabled)).lower() in ("true", "1", "yes")

    model_cfg = ModelConfig(
        api_key=api_key,
        api_base=api_base,
        model=model,
        verify_ssl=verify_ssl,
        models_config_file=models_cfg_file,
        batch_optimization_enabled=batch_opt_enabled,
        max_batch_size=max_batch_size,
        cache_enabled=cache_enabled,
    )
    return AppConfig(
        source_url=source_url,
        archive_root=archive_root,
        days=days,
        model=model_cfg,
    )


def load_analysis_config() -> Dict[str, Any]:
    """加载分析配置

    Returns:
        分析配置字典，包含异常检测阈值等参数
    """
    # 尝试从多个位置加载配置文件
    config_paths = [
        "analysis_config.json",
        "./analysis_config.json",
        os.path.join(".", "analysis_config.json"),
    ]

    for config_path in config_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"警告：无法加载分析配置文件 {config_path}: {e}")

    # 返回默认配置
    return {
        "anomaly_detection": {
            "min_samples_for_anomaly": 10,
            "min_samples_for_history": 10,
            "robust_z_thresholds": {
                "high": 8.0,
                "medium": 6.0,
                "low": 4.0
            },
            "pct_change_thresholds": {
                "high": 50,
                "medium": 35,
                "low": 25
            }
        },
        "ai_analysis": {
            "enable_batch_optimization": True,
            "max_batch_size": 10,
            "enable_cache": True
        }
    }
