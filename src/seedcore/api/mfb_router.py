from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session

from ..memory.flashbulb_memory import FlashbulbMemoryManager
from ..database import get_db_session

router = APIRouter(
    prefix="/mfb",
    tags=["Flashbulb Memory (Mfb)"]
)

mfb_manager = FlashbulbMemoryManager()

class LogIncidentRequest(BaseModel):
    event_data: Dict[str, Any] = Field(..., description="The full JSON data of the event.")
    salience_score: float = Field(..., gt=0, description="The score that triggered this incident.")

class LogIncidentResponse(BaseModel):
    incident_id: UUID

class GetIncidentResponse(BaseModel):
    incident_id: UUID
    event_data: Dict[str, Any]

@router.post("/log_incident", response_model=LogIncidentResponse)
def log_incident(
    request: LogIncidentRequest,
    db: Session = Depends(get_db_session)
):
    try:
        incident_id = mfb_manager.log_incident(db, request.event_data, request.salience_score)
        return LogIncidentResponse(incident_id=incident_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log incident: {e}")

@router.get("/incident/{incident_id}", response_model=GetIncidentResponse)
def get_incident(
    incident_id: UUID,
    db: Session = Depends(get_db_session)
):
    event_data = mfb_manager.get_incident(db, str(incident_id))
    if not event_data:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return GetIncidentResponse(incident_id=incident_id, event_data=event_data) 