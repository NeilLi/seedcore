from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import uuid


# ---------- API models ----------
# Task model is now imported from centralized models

class AnomalyTriageRequest(BaseModel):
    agent_id: str
    series: List[float] = []
    context: Dict[str, Any] = {}
    # Note: drift_score is now computed dynamically via ML service

class AnomalyTriageResponse(BaseModel):
    agent_id: str
    anomalies: Dict[str, Any]
    reason: Dict[str, Any]
    decision: Dict[str, Any]
    correlation_id: str
    p_fast: float
    escalated: bool
    tuning_job: Optional[Dict[str, Any]] = None

class TuneCallbackRequest(BaseModel):
    job_id: str
    E_before: Optional[float] = None
    E_after: Optional[float] = None
    gpu_seconds: Optional[float] = None
    status: str = "completed"  # completed, failed
    error: Optional[str] = None


