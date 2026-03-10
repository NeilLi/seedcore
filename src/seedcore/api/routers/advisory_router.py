from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException  # pyright: ignore[reportMissingImports]

from ...serve.coordinator_client import CoordinatorServiceClient


router = APIRouter(tags=["advisory"])


_COORDINATOR_TIMEOUT_S = float(os.getenv("ADVISORY_COORD_TIMEOUT_S", "15"))
_COORDINATOR = CoordinatorServiceClient(timeout=_COORDINATOR_TIMEOUT_S)


@router.post("/advisory")
async def generate_advisory(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    SeedCore API ingress for stateless reasoning advisories.
    Proxies to the Coordinator advisory contract endpoint.
    """
    try:
        return await _COORDINATOR.advisory(payload)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Coordinator advisory endpoint unavailable: {e}",
        )

