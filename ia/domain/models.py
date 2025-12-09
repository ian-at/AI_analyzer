from __future__ import annotations

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class EngineInfo(BaseModel):
    name: str
    version: str


class RunSummary(BaseModel):
    total_anomalies: int = 0
    severity_counts: Dict[str, int] = Field(
        default_factory=lambda: {"high": 0, "medium": 0, "low": 0})
    analysis_engine: Optional[EngineInfo] = None


class RunItem(BaseModel):
    run_dir: str
    rel: str
    date: str
    patch_id: Optional[str] = None
    patch_set: Optional[str] = None
    total_anomalies: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    engine: Optional[Dict[str, Any]] = None


class RunsResponse(BaseModel):
    runs: List[RunItem]
    page: int
    page_size: int
    total: int


class SeriesPoint(BaseModel):
    date: str
    value: float
    run_dir: str


class SeriesResponse(BaseModel):
    metric: str
    series: List[SeriesPoint]


class TopDriftItem(BaseModel):
    metric: str = Field(description="suite::case::metric")
    last_value: float
    mean_prev: float
    pct_change: float


class TopDriftsResponse(BaseModel):
    items: List[TopDriftItem]


class Anomaly(BaseModel):
    suite: Optional[str] = None
    case: Optional[str] = None
    metric: Optional[str] = None
    current_value: Optional[float] = None
    unit: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[float] = None
    primary_reason: Optional[str] = None
    deltas: Dict[str, Any] = Field(default_factory=dict)
    root_causes: List[Dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: Dict[str, Any] = Field(default_factory=dict)
    suggested_next_checks: List[str] = Field(default_factory=list)


class AnomalySummary(BaseModel):
    total_anomalies: int
    severity_counts: Dict[str, int]
    abnormal_runs: int
    total_runs: int


class AnomalyTimelineItem(BaseModel):
    date: str
    total: int
    high: int
    medium: int
    low: int


class AnomalyTimelineResponse(BaseModel):
    items: List[AnomalyTimelineItem]


class RunDetailResponse(BaseModel):
    run_dir: str
    rel: str
    meta: Dict[str, Any]
    summary: Union[RunSummary, Dict[str, Any]]
    anomalies: Union[List[Anomaly], List[Dict[str, Any]]]
    ub: List[Dict[str, Any]]


class DefectAnnotation(BaseModel):
    label: Optional[str] = Field(
        default=None, description="标签，例如 true_defect/non_defect/unknown")
    investigated: Optional[bool] = Field(default=None, description="是否已排查")
    note: Optional[str] = Field(default=None, description="备注")
    severity_override: Optional[str] = Field(
        default=None, description="可选：覆盖严重度")


class JobStatus(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# 故障诊断相关模型
class FileUploadInfo(BaseModel):
    """文件上传信息"""
    filename: str
    size: int
    content_type: Optional[str] = None
    file_path: str


class FaultDiagnosisRequest(BaseModel):
    """故障诊断请求"""
    device_id: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None  # 'fault' 或 'routine'，用于区分故障分析与日常日志分析
    files: List[FileUploadInfo] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FaultDiagnosisIssue(BaseModel):
    """故障问题"""
    issue_type: str  # 问题类型，如：硬件故障、软件错误、配置问题等
    severity: str  # 严重程度：critical, high, medium, low
    confidence: float  # 置信度 0-1
    title: str  # 问题标题
    description: str  # 问题描述
    root_causes: List[Dict[str, Any]] = Field(default_factory=list)  # 根因分析
    evidence: Dict[str, Any] = Field(default_factory=dict)  # 支撑证据
    suggested_solutions: List[str] = Field(default_factory=list)  # 建议解决方案
    related_files: List[str] = Field(default_factory=list)  # 相关文件


class FaultDiagnosisSummary(BaseModel):
    """故障诊断汇总"""
    total_issues: int
    severity_counts: Dict[str, int] = Field(
        default_factory=lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0})
    analysis_engine: Optional[EngineInfo] = None
    analysis_time: Optional[str] = None


class FaultDiagnosisResponse(BaseModel):
    """故障诊断响应"""
    diagnosis_id: str
    device_id: Optional[str] = None
    status: str  # pending, analyzing, completed, failed
    summary: FaultDiagnosisSummary
    issues: List[FaultDiagnosisIssue] = Field(default_factory=list)
    raw_files: List[FileUploadInfo] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
