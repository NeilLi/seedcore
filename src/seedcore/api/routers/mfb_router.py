from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging

from ...memory.flashbulb_memory import FlashbulbMemoryManager
from ...database import get_mysql_session

# Set up logging
logger = logging.getLogger(__name__)

# Create router
mfb_router = APIRouter(prefix="/mfb", tags=["flashbulb-memory"])

# Initialize the FlashbulbMemoryManager
flashbulb_manager = FlashbulbMemoryManager()

@mfb_router.post("/incidents")
async def log_incident(
    event_data: Dict[str, Any],
    salience_score: float = Query(..., ge=0.0, le=1.0, description="Salience score between 0 and 1"),
    db: Session = Depends(get_mysql_session)
):
    """
    Log a flashbulb incident with high salience.
    
    Args:
        event_data: The event data to be stored
        salience_score: Salience score between 0 and 1
        db: Database session
        
    Returns:
        Dict containing the incident_id
    """
    try:
        incident_id = flashbulb_manager.log_incident(db, event_data, salience_score)
        
        return {
            "status": "success",
            "incident_id": incident_id,
            "message": f"Incident logged successfully with ID: {incident_id}"
        }
        
    except Exception as e:
        logger.error(f"Error logging incident: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to log incident: {str(e)}")

@mfb_router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    db: Session = Depends(get_mysql_session)
):
    """
    Retrieve a specific flashbulb incident by ID.
    
    Args:
        incident_id: The unique identifier of the incident
        db: Database session
        
    Returns:
        Dict containing the incident data
    """
    try:
        incident_data = flashbulb_manager.get_incident(db, incident_id)
        
        if incident_data is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        
        return {
            "status": "success",
            "incident_id": incident_id,
            "data": incident_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving incident {incident_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve incident: {str(e)}")

@mfb_router.get("/incidents")
async def get_incidents(
    start_time: Optional[str] = Query(None, description="Start time in ISO format"),
    end_time: Optional[str] = Query(None, description="End time in ISO format"),
    salience_threshold: Optional[float] = Query(0.8, ge=0.0, le=1.0, description="Minimum salience score"),
    db: Session = Depends(get_mysql_session)
):
    """
    Retrieve flashbulb incidents with optional filtering.
    
    Args:
        start_time: Optional start time filter
        end_time: Optional end time filter
        salience_threshold: Minimum salience score (default: 0.8)
        db: Database session
        
    Returns:
        List of incidents matching the criteria
    """
    try:
        if start_time and end_time:
            # Get incidents by time range
            incidents = flashbulb_manager.get_incidents_by_time_range(db, start_time, end_time)
        else:
            # Get high salience incidents
            incidents = flashbulb_manager.get_high_salience_incidents(db, salience_threshold)
        
        return {
            "status": "success",
            "count": len(incidents),
            "incidents": incidents
        }
        
    except Exception as e:
        logger.error(f"Error retrieving incidents: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve incidents: {str(e)}")

@mfb_router.get("/stats")
async def get_stats(db: Session = Depends(get_mysql_session)):
    """
    Get statistics about flashbulb incidents.
    
    Args:
        db: Database session
        
    Returns:
        Dict containing statistics
    """
    try:
        total_count = flashbulb_manager.get_incident_count(db)
        
        # Get recent incidents (last 24 hours)
        end_time = datetime.utcnow().isoformat()
        start_time = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        recent_incidents = flashbulb_manager.get_incidents_by_time_range(db, start_time, end_time)
        
        # Calculate average salience of recent incidents
        if recent_incidents:
            avg_salience = sum(incident["salience_score"] for incident in recent_incidents) / len(recent_incidents)
        else:
            avg_salience = 0.0
        
        return {
            "status": "success",
            "total_incidents": total_count,
            "recent_incidents_24h": len(recent_incidents),
            "average_salience_24h": round(avg_salience, 3)
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

@mfb_router.delete("/incidents/{incident_id}")
async def delete_incident(
    incident_id: str,
    db: Session = Depends(get_mysql_session)
):
    """
    Delete a flashbulb incident (for cleanup purposes).
    
    Args:
        incident_id: The unique identifier of the incident to delete
        db: Database session
        
    Returns:
        Dict confirming deletion
    """
    try:
        # First check if the incident exists
        incident_data = flashbulb_manager.get_incident(db, incident_id)
        if incident_data is None:
            raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
        
        # Delete the incident
        db.execute(
            "DELETE FROM flashbulb_incidents WHERE incident_id = :incident_id",
            {"incident_id": incident_id}
        )
        db.commit()
        
        logger.info(f"Deleted incident {incident_id}")
        
        return {
            "status": "success",
            "message": f"Incident {incident_id} deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting incident {incident_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete incident: {str(e)}") 