from fastapi import APIRouter
from pydantic import BaseModel
from ...hgnn.pattern_shim import SHIM


router = APIRouter(prefix="/ocps", tags=["ocps"])


class EscalationEvent(BaseModel):
    organs: list[str]
    success: bool
    latency_ms: float | None = 0.0


@router.post("/escalation_event")
def escalation_event(evt: EscalationEvent):
    SHIM.log_escalation(evt.organs, evt.success, evt.latency_ms or 0.0)
    return {"ok": True}


