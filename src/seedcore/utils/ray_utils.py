"""
Ray utility functions for SeedCore.
Provides flexible Ray initialization and connection management.
"""

import os
import socket
import ray
import logging
from typing import Optional, Tuple
from ..config.ray_config import get_ray_config, configure_ray_remote, configure_ray_local

logger = logging.getLogger(__name__)


def _can_connect_tcp(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    """Return True if a TCP connection can be established to host:port within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except Exception:
        return False


def _parse_ray_url(ray_url: str) -> Tuple[str, int]:
    """Parse a ray://host:port URL into (host, port). Defaults port to 10001 if missing."""
    try:
        without_scheme = ray_url.replace("ray://", "", 1)
        if ":" in without_scheme:
            host_str, port_str = without_scheme.rsplit(":", 1)
            return host_str, int(port_str)
        return without_scheme, 10001
    except Exception:
        return ray_url, 10001


def resolve_ray_address() -> Optional[str]:
    """Resolve a sensible default RAY_ADDRESS for both Kubernetes and Docker Compose.
    
    Priority order:
    1) Respect explicit RAY_ADDRESS if set
    2) Derive from RAY_HOST + RAY_PORT if available
    3) Fall back to localhost for development
    """
    # Check for explicit RAY_ADDRESS first
    explicit = os.getenv("RAY_ADDRESS")
    if explicit:
        logger.debug(f"Using explicit RAY_ADDRESS: {explicit}")
        return explicit
    
    # Check if we're in a head/worker pod (should not set RAY_ADDRESS)
    # This is indicated by RAY_HOST being unset or pointing to localhost
    ray_host = os.getenv("RAY_HOST")
    if not ray_host or ray_host in ["localhost", "127.0.0.1"]:
        logger.debug("In head/worker pod - RAY_HOST indicates local operation")
        return "auto"
    
    # Derive address from RAY_HOST + RAY_PORT
    ray_port = os.getenv("RAY_PORT", "10001")
    derived_address = f"ray://{ray_host}:{ray_port}"
    logger.debug(f"Derived RAY_ADDRESS from RAY_HOST/RAY_PORT: {derived_address}")
    return derived_address


def init_ray_with_smart_defaults() -> bool:
    """Initialize Ray with smart defaults based on the new configuration pattern.
    
    This function automatically handles the different pod roles:
    - Head/worker pods: use "auto" or unset
    - Client pods: use derived or explicit RAY_ADDRESS
    """
    try:
        # Check if Ray is already initialized
        if ray.is_initialized():
            logger.info("Ray is already initialized")
            return True
        
        ray_address = resolve_ray_address()
        namespace = os.getenv("RAY_NAMESPACE")
        
        if ray_address and ray_address != "auto":
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
        
        logger.info("Ray initialization successful")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Ray: {e}")
        return False


def init_ray(namespace: Optional[str] = None, ray_address: Optional[str] = None) -> bool:
    """Initialize Ray with the specified namespace and address.
    
    Args:
        namespace: Ray namespace to use (defaults to environment variable)
        ray_address: Ray cluster address (optional, will derive from RAY_HOST/RAY_PORT if not provided)
    
    Returns:
        True if Ray was initialized successfully, False otherwise
    """
    try:
        if ray.is_initialized():
            logger.info("✅ Ray is already initialized")
            return True
        
        # Get namespace from environment, default to "seedcore-dev" for consistency
        if namespace is None:
            namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Get Ray address from environment or derive from RAY_HOST/RAY_PORT
        if ray_address is None:
            ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
            ray_port = os.getenv("RAY_PORT", "10001")
            ray_address = f"ray://{ray_host}:{ray_port}"
        
        if ray_address and ray_address != "ray://seedcore-svc-head-svc:10001":
            logger.info(f"Initializing Ray with address: {ray_address}")
            ray.init(
                address=ray_address,
                ignore_reinit_error=True,
                namespace=namespace
            )
        else:
            logger.info(f"Initializing Ray locally with namespace: {namespace}")
            ray.init(ignore_reinit_error=True, namespace=namespace)
        
        logger.info("✅ Ray initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Ray: {e}")
        return False


def shutdown_ray() -> None:
    """Safely shutdown Ray connection."""
    try:
        if ray.is_initialized():
            ray.shutdown()
            logger.info("Ray shutdown successful")
    except Exception as e:
        logger.error(f"Error during Ray shutdown: {e}")


def is_ray_available() -> bool:
    """Check if Ray is available and initialized."""
    try:
        return ray.is_initialized()
    except Exception:
        return False


def get_ray_cluster_info() -> dict:
    """Get information about the current Ray cluster."""
    try:
        if not ray.is_initialized():
            return {"status": "not_initialized"}
        
        # Get cluster resources
        resources = ray.cluster_resources()
        available = ray.available_resources()
        
        return {
            "status": "initialized",
            "cluster_resources": dict(resources),
            "available_resources": dict(available),
            "nodes": len(ray.nodes()),
            "config": str(get_ray_config())
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def test_ray_connection() -> bool:
    """Test Ray connection with a simple task."""
    try:
        if not ray.is_initialized():
            logger.warning("Ray not initialized, attempting to initialize...")
            if not init_ray():
                return False
        
        # Test with a simple remote function
        @ray.remote
        def test_function():
            return "Ray connection test successful"
        
        result = ray.get(test_function.remote())
        logger.info(f"Ray connection test: {result}")
        return True
        
    except Exception as e:
        logger.error(f"Ray connection test failed: {e}")
        return False 


def ensure_ray_initialized(ray_address: Optional[str] = None, ray_namespace: Optional[str] = None) -> bool:
    """Ensure Ray is initialized with the specified namespace and address.
    
    Args:
        ray_address: Ray cluster address (optional, will derive from RAY_HOST/RAY_PORT if not provided)
        ray_namespace: Ray namespace to use (defaults to environment variable)
    
    Returns:
        True if Ray was initialized successfully, False otherwise
    """
    try:
        if ray.is_initialized():
            logger.info("✅ Ray is already initialized")
            return True
        
        # Get namespace from environment, default to "seedcore-dev" for consistency
        if ray_namespace is None:
            ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Get Ray address from environment or derive from RAY_HOST/RAY_PORT
        if ray_address is None:
            ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
            ray_port = os.getenv("RAY_PORT", "10001")
            ray_address = f"ray://{ray_host}:{ray_port}"
        
        if ray_address and ray_address != "ray://seedcore-svc-head-svc:10001":
            logger.info(f"Initializing Ray with address: {ray_address}")
            ray.init(address=ray_address, ignore_reinit_error=True, namespace=ray_namespace)
        else:
            logger.info(f"Initializing Ray locally with namespace: {ray_namespace}")
            ray.init(ignore_reinit_error=True, namespace=ray_namespace)
        
        logger.info("✅ Ray initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Ray: {e}")
        return False 