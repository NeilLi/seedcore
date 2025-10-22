from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple, List
import threading, time, math
import numpy as np

PatternKey = Tuple[str, ...]  # sorted organ names


def _key(organs: Iterable[str]) -> PatternKey:
    return tuple(sorted(set(map(str, organs))))


@dataclass
class _Stats:
    count: float = 0.0
    success: float = 0.0
    score: float = 0.0
    t_last: float = 0.0


class HGNNPatternShim:
    """
    Tiny escalation→E_patterns shim.
    - Bounded scores in [0,1] keep hyperedge weights contractive.
    - Exponential decay approximates online template learning cheaply.
    """

    def __init__(self, half_life_s: float = 900.0, topk: int = 64, eps: float = 1e-6):
        self.half_life = max(1.0, half_life_s)
        self.decay = math.log(2.0) / self.half_life
        self.topk = topk
        self.eps = eps
        self._stats: Dict[PatternKey, _Stats] = {}
        self._lock = threading.Lock()

    def log_escalation(self, organs: List[str], success: bool, latency_ms: float = 0.0):
        """Record an escalation event.

        Inputs are sanitized to be robust to None/invalid values:
        - organs: empty or None becomes an empty pattern key
        - success: None treated as False
        - latency_ms: None/non-numeric coerced to 0.0, negatives clipped to 0.0
        """
        now = time.time()
        organs = organs or []
        k = _key(organs)
        # Coerce inputs safely
        success_flag = bool(success)
        try:
            lat = float(latency_ms) if latency_ms is not None else 0.0
        except (TypeError, ValueError):
            lat = 0.0
        if lat < 0.0:
            lat = 0.0
        with self._lock:
            st = self._stats.get(k) or _Stats()
            # decay to "now"
            dt = max(0.0, now - (st.t_last or now))
            decay_w = math.exp(-self.decay * dt)
            st.count *= decay_w
            st.success *= decay_w
            st.score *= decay_w
            # update
            st.count += 1.0
            st.success += 1.0 if success_flag else 0.0
            # success-rate + mild latency bonus (bounded)
            sr = st.success / max(self.eps, st.count)
            lat_bonus = 1.0 / (1.0 + lat / 2000.0)  # ∈ (0,1], downweights very slow plans
            st.score += 0.5 * sr + 0.5 * lat_bonus
            st.t_last = now
            self._stats[k] = st

    def get_E_patterns(self):
        """Return (E_vector, index_map) with E in [0,1]^K, top-K by score."""
        with self._lock:
            items = sorted(self._stats.items(), key=lambda kv: kv[1].score, reverse=True)[: self.topk]
        if not items:
            return np.zeros((0,), dtype=np.float32), []
        scores = np.array([s.score for _, s in items], dtype=np.float32)
        # normalize into [0,1] with safe max
        denom = max(scores.max(), 1e-6)
        E = (scores / denom).clip(0.0, 1.0).astype(np.float32)
        index_map = [orgs for orgs, _ in items]
        return E, index_map


# module-level singleton
SHIM = HGNNPatternShim()
