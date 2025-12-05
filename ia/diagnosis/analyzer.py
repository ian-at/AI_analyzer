"""
故障诊断分析器 - 使用AI模型分析故障日志和文件
"""

from __future__ import annotations

import json
import os
import time
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import ModelConfig, load_env_config
from ..domain.models import FaultDiagnosisIssue, FaultDiagnosisSummary, FileUploadInfo
from .file_manager import FileManager


logger = logging.getLogger(__name__)


@dataclass
class ModelEndpoint:
    """模型端点配置"""
    name: str
    api_base: str
    api_key: str
    model: str
    enabled: bool = True
    priority: int = 1
    timeout: int = 120
    max_retries: int = 3
    last_used: float = 0
    error_count: int = 0
    success_count: int = 0


# 故障诊断专用的AI提示词
DIAGNOSIS_SYSTEM_PROMPT = (
    "你是一名专业的计算机故障诊断专家。你将收到故障设备的日志文件和相关信息。\n"
    "任务：分析故障原因，识别问题，并提供解决方案。\n"
    "准则：\n"
    "- 仔细分析所有提供的日志文件和错误信息\n"
    "- 识别关键错误、警告和异常模式\n"
    "- 区分硬件故障、软件错误、配置问题、网络问题等不同类型\n"
    "- 评估问题的严重程度：critical（系统无法运行）、high（核心功能受影响）、medium（部分功能受影响）、low（轻微影响）\n"
    "- 提供根因分析，包括可能的原因和证据\n"
    "- 给出具体可执行的解决方案和修复步骤\n"
    "- 如果信息不足，明确说明需要哪些额外信息\n"
    "- 所有输出使用中文\n"
    "- 严格按JSON格式输出，符合给定schema"
)

DIAGNOSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "object",
            "properties": {
                "total_issues": {"type": "integer"},
                "severity_counts": {
                    "type": "object",
                    "properties": {
                        "critical": {"type": "integer"},
                        "high": {"type": "integer"},
                        "medium": {"type": "integer"},
                        "low": {"type": "integer"}
                    }
                }
            },
            "required": ["total_issues", "severity_counts"]
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string", "enum": ["硬件故障", "软件错误", "配置问题", "网络问题", "系统资源", "其他"]},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "root_causes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "cause": {"type": "string"},
                                "likelihood": {"type": "number", "minimum": 0, "maximum": 1},
                                "evidence": {"type": "string"}
                            },
                            "required": ["cause", "likelihood"]
                        }
                    },
                    "evidence": {
                        "type": "object",
                        "properties": {
                            "error_messages": {"type": "array", "items": {"type": "string"}},
                            "log_excerpts": {"type": "array", "items": {"type": "string"}},
                            "patterns": {"type": "array", "items": {"type": "string"}}
                        }
                    },
                    "suggested_solutions": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "related_files": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["issue_type", "severity", "confidence", "title", "description", "root_causes", "suggested_solutions"]
            }
        }
    },
    "required": ["summary", "issues"]
}


class FaultDiagnosisAnalyzer:
    """故障诊断分析器"""

    def __init__(self, model_config: Optional[ModelConfig] = None, file_manager: Optional[FileManager] = None):
        """
        初始化分析器

        Args:
            model_config: 模型配置（如果为None，将尝试从配置加载）
            file_manager: 文件管理器
        """
        self.file_manager = file_manager or FileManager()
        self.models: List[ModelEndpoint] = []
        self.session = self._create_session()
        
        # 加载模型配置
        if model_config is None:
            config = load_env_config(None, None, None)
            model_config = config.model
        
        self._load_models_config(model_config)

    def _create_session(self) -> requests.Session:
        """创建带重试机制的HTTP会话"""
        session = requests.Session()
        try:
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["POST", "GET"]
            )
        except TypeError:
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                method_whitelist=["POST", "GET"]
            )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _load_models_config(self, model_config: ModelConfig):
        """加载模型配置"""
        config_paths = [
            "models_config.json",
            "./models_config.json",
            os.path.join(os.path.dirname(__file__), "../../models_config.json"),
            "/data/intelligent-analysis/models_config.json",
        ]

        config_data = None
        for path in config_paths:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                try:
                    with open(abs_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                    logger.info(f"成功从 {abs_path} 加载模型配置")
                    break
                except Exception as e:
                    logger.warning(f"加载配置文件 {abs_path} 失败: {e}")

        if config_data and "models" in config_data:
            # 从配置文件加载多个模型
            for model_cfg in config_data["models"]:
                endpoint = ModelEndpoint(
                    name=model_cfg.get("name", ""),
                    api_base=model_cfg.get("api_base", ""),
                    api_key=model_cfg.get("api_key", ""),
                    model=model_cfg.get("model", ""),
                    enabled=model_cfg.get("enabled", True),
                    priority=model_cfg.get("priority", 1),
                    timeout=model_cfg.get("timeout", 120),
                    max_retries=model_cfg.get("max_retries", 3)
                )
                if endpoint.enabled:
                    self.models.append(endpoint)
        elif model_config.enabled:
            # 使用环境变量或默认配置
            endpoint = ModelEndpoint(
                name="default",
                api_base=model_config.api_base or "https://api.openai.com/v1",
                api_key=model_config.api_key or "",
                model=model_config.model or "",
                enabled=True
            )
            self.models.append(endpoint)

        # 按优先级排序
        self.models.sort(key=lambda x: x.priority)

        if self.models:
            logger.info(f"已加载 {len(self.models)} 个模型端点")
            for m in self.models:
                logger.info(f"  - {m.name}: {m.model} (优先级={m.priority})")

    def enabled(self) -> bool:
        """检查是否有可用的AI模型"""
        return len(self.models) > 0

    def _select_model(self) -> Optional[ModelEndpoint]:
        """选择最佳可用模型"""
        available = [m for m in self.models if m.enabled and m.error_count < 5]
        if not available:
            # 重置错误计数
            for m in self.models:
                m.error_count = 0
            available = [m for m in self.models if m.enabled]

        if not available:
            return None

        # 选择优先级最高且成功率最好的
        available.sort(key=lambda x: (x.priority, -x.success_count, x.error_count))

        # 简单的速率限制：避免过快调用同一个模型
        now = time.time()
        for m in available:
            if now - m.last_used > 0.5:  # 至少间隔0.5秒
                return m

        return available[0]

    def analyze(self, diagnosis_id: str, device_id: Optional[str] = None,
                description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        分析故障

        Args:
            diagnosis_id: 诊断ID
            device_id: 设备ID
            description: 故障描述
            metadata: 元数据

        Returns:
            分析结果
        """
        logger.info(f"开始分析故障诊断: {diagnosis_id}")

        # 读取文件
        file_infos = self.file_manager.list_files(diagnosis_id)
        if not file_infos:
            logger.warning(f"未找到文件: {diagnosis_id}")
            return self._create_empty_result()

        # 读取文件内容
        file_contents = {}
        for file_info in file_infos:
            filename = file_info.get("stored_filename")
            original_filename = file_info.get("filename")
            if filename:
                content = self.file_manager.read_file_content(diagnosis_id, filename)
                if content:
                    file_contents[original_filename] = content

        # 准备AI分析数据
        analysis_data = {
            "diagnosis_id": diagnosis_id,
            "device_id": device_id,
            "description": description or "未提供故障描述",
            "metadata": metadata or {},
            "files": {
                "count": len(file_infos),
                "names": [f.get("filename") for f in file_infos],
                "contents": file_contents
            }
        }

        # 使用AI分析
        if self.enabled():
            try:
                result = self._analyze_with_ai(analysis_data)
                logger.info(f"AI分析完成: {diagnosis_id}")
                return result
            except Exception as e:
                logger.error(f"AI分析失败: {e}", exc_info=True)
                # 降级到基础分析
                return self._analyze_basic(analysis_data)
        else:
            # 使用基础分析
            return self._analyze_basic(analysis_data)

    def _analyze_with_ai(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用AI模型分析"""
        # 选择模型
        model = self._select_model()
        if not model:
            raise RuntimeError("没有可用的AI模型")

        # 构建请求
        url = model.api_base.rstrip("/") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if model.api_key and model.api_key.strip() and model.api_key.upper() != "EMPTY":
            headers["Authorization"] = f"Bearer {model.api_key}"

        # 准备提示词
        user_content = json.dumps(analysis_data, ensure_ascii=False, indent=2)

        data = {
            "model": model.model,
            "messages": [
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {"role": "user", "content": f"请分析以下故障信息：\n\n{user_content}\n\n请按照JSON schema输出分析结果。"}
            ],
            "temperature": 0.2,
        }

        # 发送请求
        model.last_used = time.time()
        resp = self.session.post(url, headers=headers, json=data, timeout=model.timeout)
        resp.raise_for_status()

        # 更新模型统计
        model.success_count += 1
        model.error_count = max(0, model.error_count - 1)

        js = resp.json()
        content = js["choices"][0]["message"]["content"]

        # 解析JSON
        result = self._parse_ai_response(content)

        # 添加引擎信息
        if "summary" not in result:
            result["summary"] = {}
        result["summary"]["analysis_engine"] = {
            "name": model.name,
            "version": "1.0"
        }
        result["summary"]["analysis_time"] = datetime.utcnow().isoformat() + "Z"

        return result

    def _parse_ai_response(self, content: str) -> Dict[str, Any]:
        """解析AI响应"""
        # 移除代码块标记
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("` ")
            if text.lower().startswith("json"):
                text = text[4:]

        # 提取JSON
        first_brace = text.find("{")
        if first_brace > 0:
            text = text[first_brace:]
        last_brace = text.rfind("}")
        if last_brace != -1:
            text = text[:last_brace + 1]

        try:
            return json.loads(text)
        except Exception as e:
            logger.error(f"解析AI响应失败: {e}")
            logger.debug(f"响应内容: {content[:500]}")
            return self._create_empty_result()

    def _analyze_basic(self, analysis_data: Dict[str, Any]) -> Dict[str, Any]:
        """基础分析（不使用AI）"""
        issues = []
        file_contents = analysis_data.get("files", {}).get("contents", {})

        # 简单的关键词匹配
        critical_keywords = ["fatal", "critical", "panic", "kernel", "crash", "致命", "崩溃"]
        high_keywords = ["error", "failed", "exception", "错误", "失败"]
        medium_keywords = ["warning", "warn", "警告"]

        for filename, content in file_contents.items():
            content_lower = content.lower()
            severity = "low"
            if any(kw in content_lower for kw in critical_keywords):
                severity = "critical"
            elif any(kw in content_lower for kw in high_keywords):
                severity = "high"
            elif any(kw in content_lower for kw in medium_keywords):
                severity = "medium"

            if severity != "low":
                issues.append({
                    "issue_type": "软件错误",
                    "severity": severity,
                    "confidence": 0.5,
                    "title": f"在 {filename} 中发现{severity}级别问题",
                    "description": f"文件 {filename} 中包含可能的问题指示",
                    "root_causes": [{
                        "cause": "需要进一步分析日志文件",
                        "likelihood": 0.5
                    }],
                    "evidence": {
                        "related_file": filename
                    },
                    "suggested_solutions": [
                        "检查相关日志文件的详细内容",
                        "查看系统错误日志",
                        "联系技术支持"
                    ],
                    "related_files": [filename]
                })

        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for issue in issues:
            severity = issue.get("severity", "low")
            if severity in severity_counts:
                severity_counts[severity] += 1

        return {
            "summary": {
                "total_issues": len(issues),
                "severity_counts": severity_counts,
                "analysis_engine": {
                    "name": "basic_analyzer",
                    "version": "1.0"
                },
                "analysis_time": datetime.utcnow().isoformat() + "Z"
            },
            "issues": issues
        }

    def _create_empty_result(self) -> Dict[str, Any]:
        """创建空结果"""
        return {
            "summary": {
                "total_issues": 0,
                "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "analysis_engine": {
                    "name": "none",
                    "version": "1.0"
                },
                "analysis_time": datetime.utcnow().isoformat() + "Z"
            },
            "issues": []
        }