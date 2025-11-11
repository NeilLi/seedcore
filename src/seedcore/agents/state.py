# src/seedcore/agents/state.py
"""
AgentState: capability/memory/quality metrics with EWMA smoothing.

This module provides:
- AgentState: dataclass for core KPIs (capability, mem_util, rolling quality, etc.)
- RollingStat: fixed-window mean/variance without heavy deps
- Ewma: exponential smoothing for capability & arbitrary signals

Intended use:
    state = AgentState()
    state.update_mem_util(0.35)
    state.update_capability(observed=0.82)  # EWMA-smoothed
    state.record_task_outcome(success=True, quality=0.9, salience=0.7, duration_s=1.2)

    # Export to heartbeat:
    perf = state.to_performance_metrics()
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from collections import deque
from typing import Deque, Dict, Optional, Tuple, Any
import math
import time


# ----------------------------- helpers -----------------------------------------


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


class RollingStat:
    """
    Fixed-size rolling stats (mean, variance) over a numeric stream.
    Uses a deque for O(1) push/pop, and maintains running sum/sumsq.
    """

    def __init__(self, maxlen: int = 200) -> None:
        self.maxlen = int(maxlen)
        self.buf: Deque[float] = deque(maxlen=self.maxlen)
        self._sum = 0.0
        self._sumsq = 0.0

    def add(self, x: float) -> None:
        x = float(x)
        if len(self.buf) == self.maxlen:
            old = self.buf[0]
            self._sum -= old
            self._sumsq -= old * old
        self.buf.append(x)
        self._sum += x
        self._sumsq += x * x

    def mean(self) -> Optional[float]:
        n = len(self.buf)
        if n == 0:
            return None
        return self._sum / n

    def variance(self) -> Optional[float]:
        n = len(self.buf)
        if n < 2:
            return None
        mu = self._sum / n
        return max(0.0, (self._sumsq / n) - mu * mu)

    def clear(self) -> None:
        self.buf.clear()
        self._sum = 0.0
        self._sumsq = 0.0

    def to_list(self) -> list[float]:
        return list(self.buf)

    def __len__(self) -> int:
        return len(self.buf)


class Ewma:
    """
    Exponential Weighted Moving Average.
    y_t = (1 - alpha) * y_{t-1} + alpha * x_t
    """

    def __init__(self, alpha: float = 0.1, init: Optional[float] = None) -> None:
        self.alpha = float(alpha)
        self.value: Optional[float] = None if init is None else float(init)

    def update(self, x: float) -> float:
        x = float(x)
        if self.value is None:
            self.value = x
        else:
            a = self.alpha
            self.value = (1.0 - a) * self.value + a * x
        return self.value

    def get(self, default: float = 0.0) -> float:
        return float(self.value) if self.value is not None else float(default)


# ----------------------------- AgentState --------------------------------------


@dataclass
class AgentState:
    """
    Core, JSON-safe agent state and KPIs.

    Fields
    ------
    c: capability score (EWMA-smoothed scalar in [0,1])
    mem_util: memory utilization (0..1) used as a backpressure signal
    p: role probability vector (E/S/O legacy support), optional
    h: embedding placeholder (JSON-safe list), optional

    Rolling KPIs
    ------------
    quality: rolling quality scores
    latency: rolling task durations (seconds)
    salience: rolling salience values (0..1)
    success_rate: maintained via success deque (1/0)

    Memory interaction counters (for research/telemetry)
    ----------------------------------------------------
    memory_writes
    memory_hits_on_writes
    salient_events_logged
    total_compression_gain

    Methods
    -------
    - update_capability(observed): EWMA update & clamp to [0,1]
    - update_mem_util(x)
    - record_task_outcome(...)
    - to_performance_metrics(): dict used by heartbeat
    - to_dict()/from_dict(): JSON-safe snapshot/restore
    """

    # Primary KPIs
    c: float = 0.5
    mem_util: float = 0.0

    # Optional legacy/compat fields
    p: Dict[str, float] = field(default_factory=lambda: {"E": 0.9, "S": 0.1, "O": 0.0})
    h: list[float] = field(default_factory=lambda: [0.0] * 128)

    # Rolling metrics (use small windows for responsiveness)
    quality_window: int = 200
    latency_window: int = 200
    salience_window: int = 200
    success_window: int = 200

    # EWMA tunables
    ewma_alpha_capability: float = 0.1

    # Internal runtime accumulators (excluded from dataclass repr)
    _quality: RollingStat = field(default_factory=lambda: RollingStat(maxlen=200), repr=False)
    _latency: RollingStat = field(default_factory=lambda: RollingStat(maxlen=200), repr=False)
    _salience: RollingStat = field(default_factory=lambda: RollingStat(maxlen=200), repr=False)
    _success: Deque[int] = field(default_factory=lambda: deque(maxlen=200), repr=False)
    _ewma_c: Ewma = field(default_factory=lambda: Ewma(alpha=0.1, init=0.5), repr=False)

    # Counters
    tasks_processed: int = 0
    memory_writes: int = 0
    memory_hits_on_writes: int = 0
    salient_events_logged: int = 0
    total_compression_gain: float = 0.0

    # Timestamps
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

    # ------------------------ updates ------------------------------------------

    def update_capability(self, observed: float) -> float:
        """EWMA update for capability; returns current value."""
        observed = clamp01(float(observed))
        self._ewma_c.alpha = float(self.ewma_alpha_capability)
        self.c = clamp01(self._ewma_c.update(observed))
        self.last_updated = time.time()
        return self.c

    def update_mem_util(self, x: float) -> float:
        """Update memory utilization backpressure signal."""
        self.mem_util = clamp01(float(x))
        self.last_updated = time.time()
        return self.mem_util

    def record_quality(self, q: float) -> None:
        self._quality.add(clamp01(float(q)))
        self.last_updated = time.time()

    def record_latency(self, duration_s: float) -> None:
        self._latency.add(max(0.0, float(duration_s)))
        self.last_updated = time.time()

    def record_salience(self, s: float) -> None:
        self._salience.add(clamp01(float(s)))
        self.last_updated = time.time()

    def record_success(self, success: bool) -> None:
        self._success.append(1 if success else 0)
        self.last_updated = time.time()

    def record_task_outcome(
        self,
        *,
        success: bool,
        quality: Optional[float] = None,
        salience: Optional[float] = None,
        duration_s: Optional[float] = None,
        capability_observed: Optional[float] = None,
    ) -> None:
        """
        One-stop update after a task completes.
        """
        self.tasks_processed += 1
        self.record_success(success)
        if quality is not None:
            self.record_quality(quality)
        if salience is not None:
            self.record_salience(salience)
        if duration_s is not None:
            self.record_latency(duration_s)
        if capability_observed is not None:
            self.update_capability(capability_observed)

    # ------------------------ rollups ------------------------------------------

    def rolling_quality_avg(self) -> Optional[float]:
        return self._quality.mean()

    def rolling_latency_avg(self) -> Optional[float]:
        return self._latency.mean()

    def rolling_salience_avg(self) -> Optional[float]:
        return self._salience.mean()

    def rolling_success_rate(self) -> Optional[float]:
        n = len(self._success)
        if n == 0:
            return None
        return sum(self._success) / n

    # ------------------------ decay & maintenance ------------------------------

    def decay(self, rate: float = 0.0) -> None:
        """
        Optional decay hook to slowly relax capability toward mid (0.5)
        when the agent is idle for long periods.
        """
        r = max(0.0, min(1.0, float(rate)))
        if r <= 0.0:
            return
        # Pull c toward 0.5
        self.c = clamp01(self.c * (1.0 - r) + 0.5 * r)
        # mem_util trends down a bit if decaying
        self.mem_util = clamp01(self.mem_util * (1.0 - 0.5 * r))
        self.last_updated = time.time()

    def reset_rolling(self) -> None:
        self._quality.clear()
        self._latency.clear()
        self._salience.clear()
        self._success.clear()
        self.last_updated = time.time()

    # ------------------------ exports ------------------------------------------

    def to_performance_metrics(self) -> Dict[str, Any]:
        """
        Compact metrics dict suitable for heartbeat payloads.
        """
        return {
            "capability_score_c": float(self.c),
            "mem_util": float(self.mem_util),
            "quality_avg": self.rolling_quality_avg(),
            "latency_avg_s": self.rolling_latency_avg(),
            "salience_avg": self.rolling_salience_avg(),
            "success_rate": self.rolling_success_rate(),
            "tasks_processed": int(self.tasks_processed),
            "memory_writes": int(self.memory_writes),
            "memory_hits_on_writes": int(self.memory_hits_on_writes),
            "salient_events_logged": int(self.salient_events_logged),
            "total_compression_gain": float(self.total_compression_gain),
            "last_updated": float(self.last_updated),
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        JSON-safe snapshot of state (includes rolling buffers as lists).
        """
        payload = asdict(self)
        # Replace non-serializable rolling structures with lists
        payload.update({
            "_quality": self._quality.to_list(),
            "_latency": self._latency.to_list(),
            "_salience": self._salience.to_list(),
            "_success": list(self._success),
            "_ewma_c": {"alpha": self._ewma_c.alpha, "value": self._ewma_c.value},
        })
        return payload

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentState":
        """
        Restore from snapshot produced by to_dict().
        """
        # Extract rolling buffers and ewma first
        quality_buf = d.pop("_quality", [])
        latency_buf = d.pop("_latency", [])
        salience_buf = d.pop("_salience", [])
        success_buf = d.pop("_success", [])
        ewma_c = d.pop("_ewma_c", {"alpha": 0.1, "value": 0.5})

        # Build base dataclass
        obj = cls(**d)  # type: ignore[arg-type]

        # Restore window sizes (if changed in snapshot)
        obj._quality = RollingStat(maxlen=obj.quality_window)
        obj._latency = RollingStat(maxlen=obj.latency_window)
        obj._salience = RollingStat(maxlen=obj.salience_window)
        obj._success = deque(maxlen=obj.success_window)
        obj._ewma_c = Ewma(alpha=float(ewma_c.get("alpha", 0.1)), init=None)

        # Refill rolling buffers
        for x in quality_buf:
            obj._quality.add(float(x))
        for x in latency_buf:
            obj._latency.add(float(x))
        for x in salience_buf:
            obj._salience.add(float(x))
        for s in success_buf:
            obj._success.append(1 if int(s) else 0)

        # Restore ewma value
        if ewma_c.get("value") is not None:
            obj._ewma_c.value = float(ewma_c["value"])
            obj.c = clamp01(obj._ewma_c.get(default=obj.c))

        return obj
