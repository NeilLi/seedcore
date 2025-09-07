from fastapi import APIRouter, Request
import time
import logging
from ...telemetry.services.stats import StatsCollector
from ...telemetry.services.metrics import ENERGY_SLOPE

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/health")
async def health(request: Request):
    mw_staleness = request.app.state.stats.mw_stats().get("avg_staleness_s", 0)
    energy_slope = ENERGY_SLOPE._value.get()
    # Track how long energy_slope has been positive
    if not hasattr(request.app.state, "_slope_positive_since"):
        request.app.state._slope_positive_since = None
    now = time.time()
    if energy_slope > 0:
        if request.app.state._slope_positive_since is None:
            request.app.state._slope_positive_since = now
    else:
        request.app.state._slope_positive_since = None
    slope_positive_duration = (now - request.app.state._slope_positive_since) if request.app.state._slope_positive_since else 0
    warnings = []
    if mw_staleness > 3:
        warnings.append(f"Mw staleness high: {mw_staleness:.2f}s")
    if slope_positive_duration > 300:
        warnings.append(f"energy_delta_last positive for {slope_positive_duration:.0f}s")
    return {
        "ok": not warnings,
        "warnings": warnings,
        "mw_staleness": mw_staleness,
        "energy_delta_last": energy_slope,
        "slope_positive_duration": slope_positive_duration
    }
