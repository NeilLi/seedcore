"""
Energy Ledger (V2).
Tracks system stability metrics (Hamiltonian Energy) over time.
Acts as the short-term memory for the Energy Service control loop.
"""

from dataclasses import dataclass, field
from collections import deque
from typing import Dict, Any, Optional, List
import time
import uuid
import asyncio
import logging

# New: persistence (append-only ledger + balances)
from .persistence import EnergyLedgerStore, EnergyTx

logger = logging.getLogger(__name__)


@dataclass
class EnergyTerms:
    """Snapshot for telemetry."""

    pair: float = 0.0
    hyper: float = 0.0
    entropy: float = 0.0
    reg: float = 0.0
    mem: float = 0.0
    drift: float = 0.0
    anomaly: float = 0.0
    scaling: float = 0.0
    total: float = 0.0


@dataclass
class EnergyLedger:
    # Current Snapshot (O(1) Read)
    pair: float = 0.0
    hyper: float = 0.0
    entropy: float = 0.0
    reg: float = 0.0
    mem: float = 0.0
    drift_term: float = 0.0
    anomaly_term: float = 0.0
    scaling_score: float = 0.0

    # Last calculated Delta E (for Flywheel logic)
    last_delta: float = 0.0

    # Rolling History (for trend analysis / plotting)
    # Using deque allows O(1) appends and automatic truncation
    history_len: int = 1000
    pair_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    hyper_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    entropy_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    reg_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    mem_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    drift_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    anomaly_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    scaling_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    total_history: deque = field(default_factory=lambda: deque(maxlen=1000))

    # Persistence
    _ledger_store: Optional[EnergyLedgerStore] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        # Sync maxlen if overridden in init
        if self.pair_history.maxlen != self.history_len:
            self.pair_history = deque(maxlen=self.history_len)
            self.total_history = deque(maxlen=self.history_len)
            # ... repeat for others if strictly needed

    def _store(self) -> EnergyLedgerStore:
        if self._ledger_store is None:
            cfg = {"enabled": True}  # Default enable
            self._ledger_store = EnergyLedgerStore(cfg)
        return self._ledger_store

    def log_step(
        self, breakdown: Dict[str, float], extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record a full energy calculation step.
        Updates internal state, history, and persists transaction.
        """
        # 1. Update Internal State (Atomic-ish assignment)
        self.pair = float(breakdown.get("pair", 0.0))
        self.hyper = float(breakdown.get("hyper", 0.0))
        self.entropy = float(breakdown.get("entropy", 0.0))
        self.reg = float(breakdown.get("reg", 0.0))
        self.mem = float(breakdown.get("mem", 0.0))
        self.drift_term = float(breakdown.get("drift_term", 0.0))
        self.anomaly_term = float(breakdown.get("anomaly_term", 0.0))

        total_val = float(breakdown.get("total", 0.0))
        self.scaling_score = float(extra.get("scaling_score", 0.0))
        self.last_delta = float(
            extra.get("delta_E", 0.0)
        )  # Use explicit delta from Flywheel logic

        # 2. Update History Deques
        self.pair_history.append(self.pair)
        self.hyper_history.append(self.hyper)
        self.entropy_history.append(self.entropy)
        self.reg_history.append(self.reg)
        self.mem_history.append(self.mem)
        self.drift_history.append(self.drift_term)
        self.anomaly_history.append(self.anomaly_term)
        self.scaling_history.append(self.scaling_score)
        self.total_history.append(total_val)

        # 3. Persist Transaction (Async-friendly check)
        rec = {
            "ts": extra.get("ts", time.time()),
            "dE": self.last_delta,
            "terms": breakdown,
            "meta": extra,
        }

        try:
            tx = EnergyTx(
                tx_id=str(uuid.uuid4()),
                ts=rec["ts"],
                scope=str(extra.get("scope", "cluster")),
                scope_id=str(extra.get("scope_id", "-")),
                dE=total_val,  # Note: storing total as primary value
                cost=float(extra.get("cost", 0.0)),
                breakdown=breakdown,
                meta=extra,
            )

            # Write to store (assuming synchronous wrapper or low latency)
            ok = self._store().append_tx(tx)
            rec["ok"] = ok

        except Exception as e:
            logger.warning(f"Ledger persistence failed: {e}")
            rec["ok"] = False

        return rec

    @property
    def total(self) -> float:
        """Dynamic total based on current terms."""
        return (
            self.pair
            + self.hyper
            + self.entropy
            + self.reg
            + self.mem
            + self.drift_term
            + self.anomaly_term
        )

    # --- Methods for EnergySampler Integration ---

    async def get_last_total_energy(self) -> Optional[float]:
        """
        Retrieve the last recorded total energy.
        Used by Flywheel logic to calculate delta_E.
        """
        if not self.total_history:
            return None
        return self.total_history[-1]

    def get_recent_energy(self, window: int = 100) -> Dict[str, List[float]]:
        """Get recent history for plotting/analysis."""
        w = min(window, len(self.total_history))
        return {
            "total": list(self.total_history)[-w:],
            "entropy": list(self.entropy_history)[-w:],
            "mem": list(self.mem_history)[-w:],
            "drift": list(self.drift_history)[-w:],
        }

    # --- Legacy / Helper Updates ---

    def reset(self):
        """Hard reset of state."""
        self.pair = self.hyper = self.entropy = self.reg = self.mem = 0.0
        self.drift_term = self.anomaly_term = 0.0
        self.scaling_score = 0.0
        self.last_delta = 0.0

        self.pair_history.clear()
        self.hyper_history.clear()
        self.entropy_history.clear()
        self.reg_history.clear()
        self.mem_history.clear()
        self.drift_history.clear()
        self.anomaly_history.clear()
        self.scaling_history.clear()
        self.total_history.clear()
