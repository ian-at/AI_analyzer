"""
文件管理模块 - 处理故障诊断中的文件上传和存储
"""

from __future__ import annotations

import os
import uuid
import hashlib
import shutil
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from ..utils.io import ensure_dir, write_json, read_json


logger = logging.getLogger(__name__)


class FileManager:
    """文件管理器 - 处理故障诊断文件的上传、存储和管理"""

    def __init__(self, base_dir: str = "./archive/diagnosis"):
        """
        初始化文件管理器

        Args:
            base_dir: 文件存储基础目录
        """
        self.base_dir = base_dir
        ensure_dir(base_dir)

    def save_uploaded_files(self, files: List[Any], diagnosis_id: str) -> List[Dict[str, Any]]:
        """
        保存上传的文件

        Args:
            files: FastAPI UploadFile 对象列表
            diagnosis_id: 诊断ID

        Returns:
            文件信息列表
        """
        diagnosis_dir = os.path.join(self.base_dir, diagnosis_id)
        files_dir = os.path.join(diagnosis_dir, "files")
        ensure_dir(files_dir)

        file_infos = []
        for file in files:
            try:
                # 生成唯一文件名（避免冲突）
                original_filename = file.filename
                file_ext = os.path.splitext(original_filename)[1]
                unique_filename = f"{uuid.uuid4().hex[:8]}_{original_filename}"
                file_path = os.path.join(files_dir, unique_filename)

                # 保存文件
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)

                # 计算文件哈希
                file_hash = self._compute_file_hash(file_path)

                # 获取文件大小
                file_size = os.path.getsize(file_path)

                file_info = {
                    "filename": original_filename,
                    "stored_filename": unique_filename,
                    "file_path": file_path,
                    "relative_path": f"files/{unique_filename}",
                    "size": file_size,
                    "content_type": file.content_type,
                    "hash": file_hash,
                    "uploaded_at": datetime.utcnow().isoformat() + "Z"
                }

                file_infos.append(file_info)
                logger.info(f"保存文件: {original_filename} -> {file_path}")

            except Exception as e:
                logger.error(f"保存文件失败 {file.filename}: {e}")
                raise

        # 保存文件元数据
        metadata_path = os.path.join(diagnosis_dir, "files_metadata.json")
        write_json(metadata_path, {"files": file_infos})

        return file_infos

    def _compute_file_hash(self, file_path: str) -> str:
        """计算文件MD5哈希"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def get_file_path(self, diagnosis_id: str, filename: str) -> Optional[str]:
        """
        获取文件路径

        Args:
            diagnosis_id: 诊断ID
            filename: 文件名（存储的文件名）

        Returns:
            文件路径，如果不存在返回None
        """
        file_path = os.path.join(self.base_dir, diagnosis_id, "files", filename)
        if os.path.exists(file_path):
            return file_path
        return None

    def read_file_content(self, diagnosis_id: str, filename: str, max_size: int = 10 * 1024 * 1024) -> Optional[str]:
        """
        读取文件内容（文本文件）

        Args:
            diagnosis_id: 诊断ID
            filename: 文件名
            max_size: 最大文件大小（默认10MB）

        Returns:
            文件内容，如果文件不存在或过大返回None
        """
        file_path = self.get_file_path(diagnosis_id, filename)
        if not file_path:
            return None

        if os.path.getsize(file_path) > max_size:
            logger.warning(f"文件过大，跳过读取: {filename}")
            return None

        try:
            # 尝试UTF-8编码
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.error(f"读取文件失败 {filename}: {e}")
            return None

    def list_files(self, diagnosis_id: str) -> List[Dict[str, Any]]:
        """
        列出诊断相关的所有文件

        Args:
            diagnosis_id: 诊断ID

        Returns:
            文件信息列表
        """
        metadata_path = os.path.join(self.base_dir, diagnosis_id, "files_metadata.json")
        if not os.path.exists(metadata_path):
            return []

        try:
            metadata = read_json(metadata_path)
            return metadata.get("files", [])
        except Exception as e:
            logger.error(f"读取文件元数据失败: {e}")
            return []

    def get_diagnosis_dir(self, diagnosis_id: str) -> str:
        """获取诊断目录路径"""
        return os.path.join(self.base_dir, diagnosis_id)
