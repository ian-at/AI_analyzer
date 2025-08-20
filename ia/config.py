from __future__ import annotations

import os
from dataclasses import dataclass
import json


@dataclass
class ModelConfig:
    api_key: str | None
    api_base: str | None
    model: str | None
    verify_ssl: bool | None = None

    @property
    def enabled(self) -> bool:
        # 支持本地模型：API_KEY为"EMPTY"时仍可启用（适用于本地Qwen等模型）
        has_key = self.api_key and self.api_key.strip() and self.api_key.upper() != "EMPTY"
        has_model = bool(self.model and self.model.strip())
        has_base = bool(self.api_base and self.api_base.strip())

        # 有API_KEY和模型名称，或者有本地API_BASE和模型名称（API_KEY为EMPTY）
        return (has_key and has_model) or (not has_key and has_model and has_base)


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
    # 支持读取 ./config.json 或 <archive_root>/config.json（项目根优先）
    cfg_paths = [
        os.path.join(os.getcwd(), "config.json"),
        os.path.join(archive_root or "./archive", "config.json"),
    ]
    file_cfg = {}
    for p in cfg_paths:
        try:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
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

    model_cfg = ModelConfig(
        api_key=api_key,
        api_base=api_base,
        model=model,
        verify_ssl=verify_ssl,
    )
    return AppConfig(
        source_url=source_url,
        archive_root=archive_root,
        days=days,
        model=model_cfg,
    )
