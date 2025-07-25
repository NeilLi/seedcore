import uuid
import logging
import json
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

# Set up logging
logger = logging.getLogger(__name__)

class FlashbulbMemoryManager:
    """
    Manages flashbulb memory incidents using a MySQL backend.
    
    This class handles the storage and retrieval of high-salience events
    that are critical for long-term system memory and analysis.
    """
    
    def __init__(self):
        """Initialize the FlashbulbMemoryManager."""
        logger.info("✅ FlashbulbMemoryManager (MySQL) initialized.")
    
    def log_incident(self, db: Session, event_data: Dict[str, Any], salience_score: float) -> str:
        """
        Logs a high-salience event to the MySQL database.
        
        Args:
            db: SQLAlchemy database session
            event_data: Dictionary containing the event data to be stored
            salience_score: Float representing the salience/importance score
            
        Returns:
            str: The incident_id if successful
            
        Raises:
            Exception: If there's an error during the logging process
        """
        incident_id = str(uuid.uuid4())
        
        try:
            logger.info(f"Logging incident {incident_id} to MySQL with salience score: {salience_score}")
            
            # Insert the incident into the flashbulb_incidents table
            db.execute(
                text("""
                    INSERT INTO flashbulb_incidents (incident_id, salience_score, event_data)
                    VALUES (:incident_id, :salience_score, :event_data)
                """),
                {
                    "incident_id": incident_id,
                    "salience_score": salience_score,
                    "event_data": json.dumps(event_data)  # Serialize dict to JSON string
                }
            )
            db.commit()
            
            logger.info(f"✅ Successfully logged incident {incident_id}.")
            return incident_id
            
        except Exception as e:
            logger.error(f"❌ Error logging incident {incident_id}: {e}")
            db.rollback()
            raise
    
    def get_incident(self, db: Session, incident_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves an incident from the MySQL database.
        
        Args:
            db: SQLAlchemy database session
            incident_id: The unique identifier of the incident
            
        Returns:
            Optional[Dict[str, Any]]: The event data if found, None otherwise
        """
        try:
            logger.info(f"Retrieving incident {incident_id} from MySQL.")
            
            result = db.execute(
                text("SELECT event_data FROM flashbulb_incidents WHERE incident_id = :incident_id"),
                {"incident_id": incident_id}
            ).first()
            
            if result:
                # Parse the JSON string back to a dictionary
                event_data = json.loads(result[0])
                logger.info(f"✅ Successfully retrieved incident {incident_id}.")
                return event_data
            else:
                logger.warning(f"⚠️ Incident {incident_id} not found.")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error retrieving incident {incident_id}: {e}")
            raise
    
    def get_incidents_by_time_range(self, db: Session, start_time: str, end_time: str) -> list:
        """
        Retrieves incidents within a specified time range.
        
        Args:
            db: SQLAlchemy database session
            start_time: Start time in ISO format
            end_time: End time in ISO format
            
        Returns:
            list: List of incidents within the time range
        """
        try:
            logger.info(f"Retrieving incidents from {start_time} to {end_time}")
            
            result = db.execute(
                text("""
                    SELECT incident_id, salience_score, event_data, created_at 
                    FROM flashbulb_incidents 
                    WHERE created_at BETWEEN :start_time AND :end_time
                    ORDER BY created_at DESC
                """),
                {"start_time": start_time, "end_time": end_time}
            ).fetchall()
            
            incidents = []
            for row in result:
                incident = {
                    "incident_id": row[0],
                    "salience_score": row[1],
                    "event_data": json.loads(row[2]),
                    "created_at": row[3].isoformat() if row[3] else None
                }
                incidents.append(incident)
            
            logger.info(f"✅ Retrieved {len(incidents)} incidents from time range.")
            return incidents
            
        except Exception as e:
            logger.error(f"❌ Error retrieving incidents by time range: {e}")
            raise
    
    def get_high_salience_incidents(self, db: Session, threshold: float = 0.8) -> list:
        """
        Retrieves incidents with salience scores above a threshold.
        
        Args:
            db: SQLAlchemy database session
            threshold: Minimum salience score (default: 0.8)
            
        Returns:
            list: List of high-salience incidents
        """
        try:
            logger.info(f"Retrieving incidents with salience score >= {threshold}")
            
            result = db.execute(
                text("""
                    SELECT incident_id, salience_score, event_data, created_at 
                    FROM flashbulb_incidents 
                    WHERE salience_score >= :threshold
                    ORDER BY salience_score DESC, created_at DESC
                """),
                {"threshold": threshold}
            ).fetchall()
            
            incidents = []
            for row in result:
                incident = {
                    "incident_id": row[0],
                    "salience_score": row[1],
                    "event_data": json.loads(row[2]),
                    "created_at": row[3].isoformat() if row[3] else None
                }
                incidents.append(incident)
            
            logger.info(f"✅ Retrieved {len(incidents)} high-salience incidents.")
            return incidents
            
        except Exception as e:
            logger.error(f"❌ Error retrieving high-salience incidents: {e}")
            raise
    
    def get_incident_count(self, db: Session) -> int:
        """
        Gets the total count of incidents in the database.
        
        Args:
            db: SQLAlchemy database session
            
        Returns:
            int: Total number of incidents
        """
        try:
            result = db.execute(
                text("SELECT COUNT(*) FROM flashbulb_incidents")
            ).scalar()
            
            return result or 0
            
        except Exception as e:
            logger.error(f"❌ Error getting incident count: {e}")
            raise 