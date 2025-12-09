"""
故障诊断API接口
"""

from __future__ import annotations

from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

from ..domain.models import FaultDiagnosisResponse, FaultDiagnosisSummary, FaultDiagnosisIssue
from .handler import FaultDiagnosisHandler


def create_diagnosis_router(archive_root: str = None) -> APIRouter:
    """创建故障诊断路由"""
    router = APIRouter(prefix="/api/v1/diagnosis", tags=["故障诊断"])

    handler = FaultDiagnosisHandler(archive_root)

    @router.post("/create", response_model=dict)
    async def create_diagnosis(
        device_id: Optional[str] = Form(None),
        description: Optional[str] = Form(None)
    ):
        """
        创建故障诊断任务

        - **device_id**: 设备ID（可选）
        - **description**: 故障描述（可选）
        """
        try:
            diagnosis_id = handler.create_diagnosis(
                device_id=device_id,
                description=description,
                metadata={}
            )
            return {
                "success": True,
                "diagnosis_id": diagnosis_id,
                "message": "诊断任务创建成功，请上传文件"
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": str(e)}
            )

    @router.post("/{diagnosis_id}/upload")
    async def upload_files(
        diagnosis_id: str,
        files: List[UploadFile] = File(...)
    ):
        """
        上传故障文件

        - **diagnosis_id**: 诊断ID
        - **files**: 要上传的文件列表
        """
        try:
            file_infos = handler.save_files(diagnosis_id, files)
            return {
                "success": True,
                "diagnosis_id": diagnosis_id,
                "files": file_infos,
                "message": f"成功上传 {len(file_infos)} 个文件"
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": str(e)}
            )

    @router.post("/{diagnosis_id}/analyze")
    async def analyze_diagnosis(diagnosis_id: str):
        """
        开始分析故障

        - **diagnosis_id**: 诊断ID
        """
        try:
            result = handler.analyze_diagnosis(diagnosis_id)
            return {
                "success": True,
                "diagnosis_id": diagnosis_id,
                "result": result
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": str(e)}
            )

    @router.get("/{diagnosis_id}", response_model=dict)
    async def get_diagnosis(diagnosis_id: str):
        """
        获取诊断结果

        - **diagnosis_id**: 诊断ID
        """
        result = handler.get_diagnosis(diagnosis_id)
        if not result:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "诊断任务不存在"}
            )
        return {
            "success": True,
            "diagnosis": result
        }

    @router.get("/", response_model=dict)
    async def list_diagnoses(
        device_id: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200)
    ):
        """
        列出诊断任务

        - **device_id**: 设备ID（可选，用于过滤）
        - **limit**: 返回数量限制
        """
        try:
            diagnoses = handler.list_diagnoses(device_id=device_id, limit=limit)
            return {
                "success": True,
                "diagnoses": diagnoses,
                "total": len(diagnoses)
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": str(e)}
            )

    @router.post("/submit")
    async def submit_diagnosis(
        device_id: Optional[str] = Form(None),
        description: Optional[str] = Form(None),
        files: List[UploadFile] = File(...)
    ):
        """
        一站式提交：创建诊断任务、上传文件并开始分析

        - **device_id**: 设备ID（可选）
        - **description**: 故障描述（可选）
        - **files**: 要上传的文件列表
        """
        try:
            # 1. 创建诊断任务
            diagnosis_id = handler.create_diagnosis(
                device_id=device_id,
                description=description,
                metadata={}
            )

            # 2. 上传文件
            file_infos = handler.save_files(diagnosis_id, files)

            # 3. 开始分析
            result = handler.analyze_diagnosis(diagnosis_id)

            return {
                "success": True,
                "diagnosis_id": diagnosis_id,
                "files_uploaded": len(file_infos),
                "result": result,
                "message": "诊断完成"
            }
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": str(e)}
            )

    return router
