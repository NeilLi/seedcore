from fastapi import APIRouter
from typing import Dict

from ...energy.api import _ledger


router = APIRouter()


@router.post('/energy/reset')
def energy_reset() -> Dict[str, str]:
    """Reset the energy ledger (consistent under /energy/*).

    Alias maintained at /reset_energy for backward compatibility.
    """
    _ledger.reset()
    return {"message": "Energy ledger has been reset."}


@router.get('/reset_energy', include_in_schema=False)
def reset_energy_legacy_alias() -> Dict[str, str]:
    return energy_reset()