from fastapi import APIRouter
from ..clients.prometheus_client import create_metrics_response

router = APIRouter()

@router.get("/metrics")
async def get_metrics():
    """Get Prometheus metrics."""
    return create_metrics_response()
