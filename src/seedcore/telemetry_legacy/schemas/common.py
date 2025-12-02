# Pydantic models shared by telemetry routes.
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime

class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None

class EnergyPayload(BaseModel):
    pair: float
    hyper: float
    entropy: float
    reg: float
    mem: float
    total: float

class AgentState(BaseModel):
    id: str
    type: str
    capability: float
    mem_util: float
    success_rate: float
    role_probs: Dict[str, float]

class SystemStatus(BaseModel):
    total_agents: int
    active_agents: int
    memory_utilization_kb: float
    ray_status: str

class TaskRequest(BaseModel):
    task_id: Optional[str] = None
    parameters: Dict[str, Any] = {}

class TaskResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
