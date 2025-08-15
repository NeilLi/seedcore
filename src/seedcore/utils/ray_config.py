import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def resolve_ray_address() -> Optional[str]:
    """Resolve a sensible default RAY_ADDRESS for both Kubernetes and Docker Compose.
    
    This function implements the new pattern where:
    1) Respect explicit RAY_ADDRESS if set
    2) For head/worker pods: return None or "auto" 
    3) For client pods: derive from RAY_HOST/RAY_PORT if available
    4) Fallback to localhost for development
    """
    # Check for explicit RAY_ADDRESS first
    explicit = os.getenv("RAY_ADDRESS")
    if explicit:
        logger.debug(f"Using explicit RAY_ADDRESS: {explicit}")
        return explicit
    
    # Check if we're in a head/worker pod (should not set RAY_ADDRESS)
    # This is indicated by RAY_ADDRESS being unset or "auto"
    ray_address = os.getenv("RAY_ADDRESS")
    if not ray_address or ray_address == "auto":
        logger.debug("In head/worker pod - RAY_ADDRESS should be unset or 'auto'")
        return ray_address or "auto"
    
    # For client pods, derive from RAY_HOST/RAY_PORT
    host = os.getenv("RAY_HOST")
    port = os.getenv("RAY_PORT")
    
    if host and port:
        derived_address = f"ray://{host}:{port}"
        logger.debug(f"Derived RAY_ADDRESS from RAY_HOST/RAY_PORT: {derived_address}")
        return derived_address
    
    # Fallback for development
    logger.warning("RAY_ADDRESS not set and RAY_HOST/RAY_PORT not available, using localhost")
    return "ray://localhost:10001"

def get_ray_namespace() -> Optional[str]:
    """Get the Ray namespace from environment variables."""
    return os.getenv("RAY_NAMESPACE")

def init_ray_with_smart_defaults():
    """Initialize Ray with smart defaults based on the new configuration pattern.
    
    This function automatically handles the different pod roles:
    - Head/worker pods: use "auto" or unset
    - Client pods: use derived or explicit RAY_ADDRESS
    """
    import ray
    
    ray_address = resolve_ray_address()
    namespace = get_ray_namespace()
    
    if ray_address:
        logger.info(f"Initializing Ray with address: {ray_address}, namespace: {namespace}")
        ray.init(
            address=ray_address,
            namespace=namespace,
            ignore_reinit_error=True
        )
    else:
        logger.info("Initializing Ray locally (head/worker mode)")
        ray.init(
            address="auto",
            namespace=namespace,
            ignore_reinit_error=True
        )

def get_ray_serve_address() -> Optional[str]:
    """Get the Ray Serve address from environment variables."""
    # Try RAY_SERVE_ADDRESS first, then fall back to RAY_SERVE_URL
    return os.getenv("RAY_SERVE_ADDRESS") or os.getenv("RAY_SERVE_URL")

def get_ray_dashboard_address() -> Optional[str]:
    """Get the Ray Dashboard address from environment variables."""
    # Try RAY_DASHBOARD_ADDRESS first, then fall back to RAY_DASHBOARD_URL
    return os.getenv("RAY_DASHBOARD_ADDRESS") or os.getenv("RAY_DASHBOARD_URL")
