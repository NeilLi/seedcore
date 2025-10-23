"""Core storage functionality for job state persistence."""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def persist_job_state(storage: Any, job_id: str, state: Dict[str, Any], ttl_s: int = 86400) -> bool:
    """
    Persist job state using safe storage.
    
    Args:
        storage: Safe storage instance
        job_id: Job identifier
        state: Job state dictionary
        ttl_s: Time to live in seconds
        
    Returns:
        True if successful, False otherwise
    """
    success = storage.set(f"job:{job_id}", state, ttl=ttl_s)
    if not success:
        logger.warning(f"Failed to persist job state for {job_id}")
    return success


def get_job_state(storage: Any, job_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve job state using safe storage.
    
    Args:
        storage: Safe storage instance
        job_id: Job identifier
        
    Returns:
        Job state dictionary or None if not found
    """
    return storage.get(f"job:{job_id}")
