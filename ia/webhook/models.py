"""
Webhook请求和响应模型定义
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class SimplifiedWebhookResponse(BaseModel):
    """简化的Webhook响应模型"""
    success: bool = Field(..., description="是否成功找到数据并开始处理")
    job_id: Optional[str] = Field(None, description="任务ID")
    patch: str = Field(..., description="补丁标识，格式: patch_id/patch_set")
    message: str = Field(..., description="处理消息")
    engine: Optional[str] = Field(None, description="分析引擎")
    ai_model_configured: Optional[str] = Field(None, description="配置的AI模型")
    force_refetch: bool = Field(False, description="是否强制重新获取")
    force_reanalyze: bool = Field(True, description="是否强制重新分析")
    max_search_days: int = Field(7, description="最大搜索天数")
    status_url: Optional[str] = Field(None, description="状态查询URL")
    estimated_time: Optional[str] = Field(None, description="预计完成时间")
    process_flow: Optional[List[str]] = Field(None, description="处理流程")
    error: Optional[str] = Field(None, description="错误信息")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "job_id": "bc491f7b0374",
                "patch": "2299/4",
                "message": "已开始获取和分析 patch 2299/4，请使用 job_id 查询进度",
                "engine": "heuristic",
                "ai_model_configured": "heuristic",
                "force_refetch": False,
                "force_reanalyze": True,
                "max_search_days": 7,
                "status_url": "/api/v1/jobs/bc491f7b0374",
                "estimated_time": "600秒内完成",
                "process_flow": [
                    "1. 检查本地是否有数据",
                    "2. 如需要，从远程获取UB数据",
                    "3. 解析HTML生成ub.jsonl",
                    "4. 执行AI异常分析（使用models_config.json配置的模型）",
                    "5. 生成分析报告"
                ]
            }
        }
