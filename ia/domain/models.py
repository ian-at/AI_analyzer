from __future__ import annotations

from typing import Optional, List, Dict, Any
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
    summary: RunSummary | Dict[str, Any]
    anomalies: List[Anomaly] | List[Dict[str, Any]]
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
