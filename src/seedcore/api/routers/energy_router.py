from fastapi import APIRouter
from typing import Dict

from ...energy.api import _ledger
from ...energy.energy_persistence import EnergyLedgerStore


router = APIRouter()


@router.post('/energy/reset')
def energy_reset() -> Dict[str, str]:
    """Reset the energy ledger (consistent under /energy/*).

    Alias maintained at /reset_energy for backward compatibility.
    """
    _ledger.reset()
    return {"message": "Energy ledger has been reset."}


@router.get('/energy/balance/{scope}/{scope_id}')
def get_energy_balance(scope: str, scope_id: str):
    # Use env-configured store to read balances
    store = EnergyLedgerStore({"enabled": True})
    b = store.get_balance(scope, scope_id)
    return {"scope": scope, "scope_id": scope_id, "balance": float(b)}


@router.post('/energy/rebuild')
def rebuild_energy_balances():
    store = EnergyLedgerStore({"enabled": True})
    store.rebuild_balances()
    return {"ok": True}


@router.get('/energy/healthz')
def energy_healthz():
    store = EnergyLedgerStore({"enabled": True})
    ok = store.set_balance("_health", "_probe", 0.0)
    return {"persistence_ok": bool(ok)}


@router.get('/reset_energy', include_in_schema=False)
def reset_energy_legacy_alias() -> Dict[str, str]:
    return energy_reset()