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

    Precedence:
    1) Respect explicit RAY_ADDRESS if set
    2) If running in Kubernetes (service account mounted), prefer seedcore-dev-head-svc
    3) If Docker Compose hostname is available, prefer ray-head
    4) Fallback candidates: localhost
    """
    # 1) Respect explicit env if provided
    explicit = os.getenv("RAY_ADDRESS")
    if explicit:
        return explicit

    candidates = []

    # 2) Detect Kubernetes via service account mount
    if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token"):
        candidates.append("ray://seedcore-dev-head-svc:10001")
        # Also try fully qualified DNS to be safe
        candidates.append("ray://seedcore-dev-head-svc.seedcore-dev.svc.cluster.local:10001")

    # 3) Docker Compose common hostname
    candidates.append("ray://ray-head:10001")

    # 4) Localhost fallback
    candidates.append("ray://localhost:10001")

    for candidate in candidates:
        host, port = _parse_ray_url(candidate)
        if _can_connect_tcp(host, port):
            return candidate

    return None


def init_ray(
    host: Optional[str] = None,
    port: int = 10001,
    password: Optional[str] = None,
    force_reinit: bool = False
) -> bool:
    """
    Initialize Ray connection using configuration.
    
    Args:
        host: Remote host (if None, uses environment or local)
        port: Ray port (default: 10001)
        password: Ray password (if needed)
        force_reinit: Force reinitialization even if already connected
        
    Returns:
        bool: True if initialization successful, False otherwise
    """
    try:
        # Try environment-specific resolution first
        # Check if Ray is already initialized
        if ray.is_initialized() and not force_reinit:
            logger.info("Ray is already initialized")
            return True
        
        # Get Ray address from environment variable (Ray 2.20 compatibility)
        ray_address = os.getenv("RAY_ADDRESS") or resolve_ray_address()
        
        if ray_address:
            # Use the environment variable directly
            logger.info(f"Initializing Ray with RAY_ADDRESS: {ray_address}")
            ray.init(address=ray_address, ignore_reinit_error=True, namespace="seedcore")
        elif host:
            # Configure Ray if host is provided
            configure_ray_remote(host, port, password)
            logger.info(f"Configured Ray for remote connection: {host}:{port}")
            
            # Get current configuration
            config = get_ray_config()
            connection_args = config.get_connection_args()
            ray.init(**connection_args)
        else:
            # Get current configuration
            config = get_ray_config()
            
            # Get connection arguments
            connection_args = config.get_connection_args()
            
            # Initialize Ray
            if config.is_configured():
                logger.info(f"Initializing Ray with: {config}")
                ray.init(**connection_args)
            else:
                logger.info("Initializing Ray locally")
                ray.init(ignore_reinit_error=True, namespace="seedcore")
        
        logger.info("Ray initialization successful")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Ray: {e}")
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