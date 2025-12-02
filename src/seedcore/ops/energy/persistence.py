"""
Energy Persistence Layer.
Handles the durable storage of Energy Transactions (EnergyTx) and Balances.

Designed for high-throughput, append-only writes.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging
import time

# Reuse the existing CheckpointStore pattern (MySQL-backed by default)
from seedcore.agents.checkpoint import CheckpointStoreFactory, CheckpointStore

logger = logging.getLogger(__name__)

@dataclass
class EnergyTx:
    """Immutable record of an energy event."""
    tx_id: str
    ts: float
    scope: str          # "agent" | "organ" | "cluster"
    scope_id: str       # agent_id or organ_id or "-"
    dE: float           # Change in energy (Hamiltonian delta)
    cost: float         # Resource cost (if applicable)
    breakdown: Dict[str, float]   # pair/hyper/entropy/reg/mem/total
    meta: Dict[str, Any]          # p_fast, drift, etc.
    step_id: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "tx_id": self.tx_id,
            "ts": self.ts,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "step_id": self.step_id,
            "dE": self.dE,
            "cost": self.cost,
            "breakdown": self.breakdown,
            "meta": self.meta,
        }

class EnergyLedgerStore:
    """
    Persistence adapter for the Energy Service.
    
    Responsibilities:
    1. Append transactions (EnergyTx) to durable storage.
    2. Update current balances (Optimistic locking or eventual consistency).
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {"enabled": True} # Default enable
        
        # Initialize Backend
        # We leverage the existing CheckpointStore infrastructure
        self.store: CheckpointStore = CheckpointStoreFactory.from_config(self.cfg)
        
        # Keys configuration
        self.balance_key = self.cfg.get("key_balances", "energy/balances")
        self.tx_prefix = self.cfg.get("key_tx_prefix", "energy/tx")

    # ------------------------------------------------------------------
    # WRITE PATH (Hot)
    # ------------------------------------------------------------------

    def append_tx(self, tx: EnergyTx) -> bool:
        """
        Persist a single transaction.
        Strategy: Write as a discrete object/row.
        """
        try:
            # Key: energy/tx/{timestamp}_{tx_id} to allow time-ordered listing
            key = f"{self.tx_prefix}/{int(tx.ts)}_{tx.tx_id}"
            payload = tx.to_json()
            
            return self.store.save(key, payload)
        except Exception as e:
            logger.warning(f"[EnergyStore] Failed to append TX {tx.tx_id}: {e}")
            return False

    def apply_tx_to_balance(self, tx: EnergyTx) -> float:
        """
        Update the cumulative energy balance for the scope.
        Returns the new balance.
        """
        # Note: This is a read-modify-write. In a real DB, use atomic increments.
        # For CheckpointStore (KV semantics), this is best-effort consistency.
        
        scope_key = f"{self.balance_key}/{tx.scope}/{tx.scope_id}"
        
        try:
            # 1. Load Current
            data = self.store.load(scope_key) or {}
            current_bal = float(data.get("balance", 0.0))
            
            # 2. Update (Convention: Balance -= dE)
            # Improving energy (negative dE) increases the "Credit" balance.
            # Worsening energy (positive dE) decreases it.
            impact = -(tx.dE) - tx.cost
            new_bal = current_bal + impact
            
            # 3. Save
            self.store.save(scope_key, {
                "balance": new_bal, 
                "last_updated": time.time(),
                "last_tx": tx.tx_id
            })
            
            return new_bal
            
        except Exception as e:
            logger.warning(f"[EnergyStore] Failed to update balance: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # READ PATH (Cold/Admin)
    # ------------------------------------------------------------------

    def get_balance(self, scope: str, scope_id: str) -> float:
        """Retrieve current balance for a scope."""
        key = f"{self.balance_key}/{scope}/{scope_id}"
        try:
            data = self.store.load(key)
            return float(data.get("balance", 0.0)) if data else 0.0
        except Exception:
            return 0.0