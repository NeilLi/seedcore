from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import json
import logging

# Reuse the existing CheckpointStore pattern (MySQL-backed by default)
from ...agents.checkpoint_store import CheckpointStoreFactory, CheckpointStore

log = logging.getLogger(__name__)


@dataclass
class EnergyTx:
    tx_id: str
    ts: float
    scope: str          # "agent" | "organ" | "cluster"
    scope_id: str       # agent_id or organ_id or "-"
    step_id: Optional[str]
    dE: float
    cost: float
    breakdown: Dict[str, float]   # pair/hyper/entropy/reg/mem/total
    meta: Dict[str, Any]          # p_fast, drift, etc.

    def to_json(self) -> Dict[str, Any]:
        b = {k: float(v) for k, v in self.breakdown.items()}
        return {
            "tx_id": self.tx_id,
            "ts": float(self.ts),
            "scope": self.scope,
            "scope_id": self.scope_id,
            "step_id": self.step_id,
            "dE": float(self.dE),
            "cost": float(self.cost),
            "breakdown": b,
            "meta": self.meta,
        }


class EnergyLedgerStore:
    """
    Append-only ledger + derived balances using a pluggable CheckpointStore backend.
    - Backed by the existing CheckpointStoreFactory (MySQL default)
    - For object stores (fs/s3), uses JSON lines at key 'energy/ledger.ndjson'
    - For SQL-like backends (mysql), stores each tx under key 'energy/tx/{tx_id}'
    - Balances are stored as a single JSON doc under key 'energy/balances.json'
    """

    def __init__(self, cfg: Optional[Dict[str, Any]]):
        # Allow environment-based overrides
        import os
        env_backend = os.getenv("ENERGY_LEDGER_BACKEND")
        env_enabled = os.getenv("ENERGY_LEDGER_ENABLED")
        env_root = os.getenv("ENERGY_LEDGER_ROOT")

        self.cfg = cfg or {"enabled": False}
        if env_backend:
            self.cfg["backend"] = env_backend
        if env_enabled is not None:
            # Any non-empty value toggles enabled; truthy strings enable
            self.cfg["enabled"] = str(env_enabled).lower() in ("1", "true", "yes", "on")
        if env_root and self.cfg.get("backend", "").lower() == "fs":
            self.cfg["root"] = env_root
        self.store: CheckpointStore = CheckpointStoreFactory.from_config(self.cfg)
        self.ledger_key = self.cfg.get("key_ledger", "energy/ledger.ndjson")
        self.balance_key = self.cfg.get("key_balances", "energy/balances.json")

    # ---- append txn ----
    def append_tx(self, tx: EnergyTx) -> bool:
        backend = (self.cfg.get("backend") or "mysql").lower()
        # SQL-like path: leverage store.save with unique key per tx
        if backend in ("sql", "mysql"):
            try:
                return self.store.save(self._tx_sql_key(tx.tx_id), tx.to_json())
            except Exception as e:
                log.warning(f"append_tx sql-like failed: {e}")
                return False

        # FS/S3 path: append one JSON line and rewrite
        try:
            cur = self.store.load(self.ledger_key) or {"ndjson": ""}
            ndjson = cur.get("ndjson", "")
            ndjson += json.dumps(tx.to_json(), separators=(",", ":")) + "\n"
            return self.store.save(self.ledger_key, {"ndjson": ndjson})
        except Exception as e:
            log.warning(f"append_tx fs/s3 failed: {e}")
            return False

    # ---- balances ----
    def get_balance(self, scope: str, scope_id: str) -> float:
        try:
            bal = self.store.load(self.balance_key) or {}
            return float(bal.get(scope, {}).get(scope_id, 0.0))
        except Exception as e:
            log.info(f"get_balance failed: {e}")
            return 0.0

    def set_balance(self, scope: str, scope_id: str, value: float) -> bool:
        try:
            bal = self.store.load(self.balance_key) or {}
            bal.setdefault(scope, {})[scope_id] = float(value)
            return self.store.save(self.balance_key, bal)
        except Exception as e:
            log.warning(f"set_balance failed: {e}")
            return False

    def apply_tx_to_balance(self, tx: EnergyTx) -> float:
        # Convention: balance_after = balance_before + (−dE − cost)
        before = self.get_balance(tx.scope, tx.scope_id)
        after = before + (-(tx.dE) - tx.cost)
        self.set_balance(tx.scope, tx.scope_id, after)
        return after

    # ---- rebuild (idempotent) ----
    def rebuild_balances(self) -> None:
        backend = (self.cfg.get("backend") or "mysql").lower()
        if backend in ("sql", "mysql"):
            # For SQL-like, assume external job/materialized view handles it
            return
        try:
            cur = self.store.load(self.ledger_key) or {}
            ndjson = cur.get("ndjson", "")
            bals: Dict[str, Dict[str, float]] = {}
            for line in ndjson.splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                scope = rec["scope"]
                scope_id = rec["scope_id"]
                dE = float(rec.get("dE", 0.0))
                cost = float(rec.get("cost", 0.0))
                bals.setdefault(scope, {}).setdefault(scope_id, 0.0)
                bals[scope][scope_id] += (-(dE) - cost)
            self.store.save(
                self.balance_key,
                {k: {i: float(v) for i, v in d.items()} for k, d in bals.items()},
            )
        except Exception as e:
            log.warning(f"rebuild_balances failed: {e}")

    # helper for SQL-store shim
    def _tx_sql_key(self, txid: str) -> str:
        return f"energy/tx/{txid}"


