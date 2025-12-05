"""
故障诊断处理器 - 处理故障诊断请求
"""

from __future__ import annotations

import os
import uuid
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from ..config import load_env_config
from ..domain.models import FaultDiagnosisResponse, FaultDiagnosisSummary, FaultDiagnosisIssue, FileUploadInfo
from .file_manager import FileManager
from .analyzer import FaultDiagnosisAnalyzer
from ..utils.io import write_json, read_json, ensure_dir


logger = logging.getLogger(__name__)


class FaultDiagnosisHandler:
    """故障诊断处理器"""

    def __init__(self, archive_root: str = None):
        """
        初始化处理器

        Args:
            archive_root: 归档根目录
        """
        self.archive_root = archive_root or os.environ.get("IA_ARCHIVE_DIAGNOSIS", "./archive/diagnosis")
        ensure_dir(self.archive_root)

        # 加载配置
        config = load_env_config(None, None, None)

        # 初始化组件
        self.file_manager = FileManager(self.archive_root)
        self.analyzer = FaultDiagnosisAnalyzer(config.model, self.file_manager)

    def create_diagnosis(self, device_id: Optional[str] = None,
                         description: Optional[str] = None,
                         metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        创建诊断任务

        Args:
            device_id: 设备ID
            description: 故障描述
            metadata: 元数据

        Returns:
            诊断ID
        """
        diagnosis_id = uuid.uuid4().hex[:16]
        diagnosis_dir = self.file_manager.get_diagnosis_dir(diagnosis_id)

        # 创建诊断元数据
        diagnosis_meta = {
            "diagnosis_id": diagnosis_id,
            "device_id": device_id,
            "description": description,
            "metadata": metadata or {},
            "status": "pending",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "files": []
        }

        meta_path = os.path.join(diagnosis_dir, "diagnosis_meta.json")
        write_json(meta_path, diagnosis_meta)

        logger.info(f"创建诊断任务: {diagnosis_id}")
        return diagnosis_id

    def save_files(self, diagnosis_id: str, files: List[Any]) -> List[Dict[str, Any]]:
        """
        保存上传的文件

        Args:
            diagnosis_id: 诊断ID
            files: 文件列表

        Returns:
            文件信息列表
        """
        file_infos = self.file_manager.save_uploaded_files(files, diagnosis_id)

        # 更新诊断元数据
        diagnosis_dir = self.file_manager.get_diagnosis_dir(diagnosis_id)
        meta_path = os.path.join(diagnosis_dir, "diagnosis_meta.json")
        if os.path.exists(meta_path):
            meta = read_json(meta_path)
            meta["files"] = file_infos
            meta["status"] = "files_uploaded"
            write_json(meta_path, meta)

        return file_infos

    def analyze_diagnosis(self, diagnosis_id: str, async_mode: bool = False) -> Dict[str, Any]:
        """
        分析诊断

        Args:
            diagnosis_id: 诊断ID
            async_mode: 是否异步模式

        Returns:
            分析结果或任务ID
        """
        diagnosis_dir = self.file_manager.get_diagnosis_dir(diagnosis_id)
        meta_path = os.path.join(diagnosis_dir, "diagnosis_meta.json")

        if not os.path.exists(meta_path):
            raise ValueError(f"诊断任务不存在: {diagnosis_id}")

        meta = read_json(meta_path)

        # 更新状态
        meta["status"] = "analyzing"
        meta["analysis_started_at"] = datetime.utcnow().isoformat() + "Z"
        write_json(meta_path, meta)

        try:
            # 执行分析
            result = self.analyzer.analyze(
                diagnosis_id,
                device_id=meta.get("device_id"),
                description=meta.get("description"),
                metadata=meta.get("metadata")
            )

            # 保存分析结果
            result_path = os.path.join(diagnosis_dir, "analysis_result.json")
            write_json(result_path, result)

            # 更新元数据
            meta["status"] = "completed"
            meta["completed_at"] = datetime.utcnow().isoformat() + "Z"
            meta["analysis_result"] = result
            write_json(meta_path, meta)

            logger.info(f"诊断分析完成: {diagnosis_id}")
            return result

        except Exception as e:
            logger.error(f"诊断分析失败: {diagnosis_id}, {e}", exc_info=True)
            meta["status"] = "failed"
            meta["error"] = str(e)
            write_json(meta_path, meta)
            raise

    def get_diagnosis(self, diagnosis_id: str) -> Optional[Dict[str, Any]]:
        """
        获取诊断结果

        Args:
            diagnosis_id: 诊断ID

        Returns:
            诊断结果，如果不存在返回None
        """
        diagnosis_dir = self.file_manager.get_diagnosis_dir(diagnosis_id)
        meta_path = os.path.join(diagnosis_dir, "diagnosis_meta.json")

        if not os.path.exists(meta_path):
            return None

        meta = read_json(meta_path)

        # 读取分析结果
        result_path = os.path.join(diagnosis_dir, "analysis_result.json")
        analysis_result = None
        if os.path.exists(result_path):
            analysis_result = read_json(result_path)

        # 构建响应
        response = {
            "diagnosis_id": diagnosis_id,
            "device_id": meta.get("device_id"),
            "status": meta.get("status", "pending"),
            "created_at": meta.get("created_at"),
            "completed_at": meta.get("completed_at"),
            "error": meta.get("error"),
            "files": meta.get("files", []),
            "analysis_result": analysis_result or meta.get("analysis_result")
        }

        return response

    def list_diagnoses(self, device_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        列出诊断任务

        Args:
            device_id: 设备ID（可选过滤）
            limit: 返回数量限制

        Returns:
            诊断任务列表
        """
        diagnoses = []
        base_dir = self.archive_root

        if not os.path.exists(base_dir):
            return []

        # 遍历所有诊断目录
        for item in os.listdir(base_dir):
            diagnosis_dir = os.path.join(base_dir, item)
            if not os.path.isdir(diagnosis_dir):
                continue

            meta_path = os.path.join(diagnosis_dir, "diagnosis_meta.json")
            if not os.path.exists(meta_path):
                continue

            try:
                meta = read_json(meta_path)
                if device_id and meta.get("device_id") != device_id:
                    continue

                diagnoses.append({
                    "diagnosis_id": item,
                    "device_id": meta.get("device_id"),
                    "status": meta.get("status", "pending"),
                    "created_at": meta.get("created_at"),
                    "completed_at": meta.get("completed_at"),
                    "file_count": len(meta.get("files", []))
                })
            except Exception as e:
                logger.warning(f"读取诊断元数据失败 {item}: {e}")

        # 按创建时间排序（最新的在前）
        diagnoses.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return diagnoses[:limit]
