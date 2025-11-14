# seedcore/ml/distillation/system_episode.py
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]
from typing import List, Dict, Any
import numpy as np


class SystemMetric(BaseModel):
    ts: float
    avg_capability: float
    avg_latency_ms: float
    energy_total: float
    # ... add whatever you already have


class MemoryMetric(BaseModel):
    ts: float
    hit_rate: float
    avg_context_tokens: float
    drift_score: float


class AgentSnapshot(BaseModel):
    ts: float
    agent_id: str
    role: str
    energy_spent: float
    success: bool
    # ... etc.


class SystemEpisode(BaseModel):
    episode_id: str
    start_ts: float
    end_ts: float
    system_metrics: List[SystemMetric]
    memory_metrics: List[MemoryMetric]
    agent_snapshots: List[AgentSnapshot]
    global_outcome: Dict[str, Any]  # e.g. task_success, latency, delta_E, etc.


def episode_to_features(ep: SystemEpisode) -> Dict[str, float]:
    # Compute simple stats; you can refine later
    caps = [m.avg_capability for m in ep.system_metrics]
    lats = [m.avg_latency_ms for m in ep.system_metrics]
    energy = [m.energy_total for m in ep.system_metrics]

    # Example features
    return {
        "cap_mean": float(np.mean(caps)),
        "cap_slope": float((caps[-1] - caps[0]) / max(len(caps) - 1, 1)),
        "lat_mean": float(np.mean(lats)),
        "lat_p95": float(np.percentile(lats, 95)),
        "energy_delta": float(energy[-1] - energy[0]),
        # ... memory, agent stats, etc.
    }
