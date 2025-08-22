"""
Ray utility functions for SeedCore.
Provides centralized, robust Ray initialization and connection management.
"""

import os
import ray
import logging
from typing import Optional, Any, Dict

_log = logging.getLogger(__name__)

def _client_connected() -> bool:
    try:
        # This is the canonical check in Ray Client mode.
        from ray.util.client import ray as client_ray
        return client_ray.is_connected()
    except Exception:
        return False

def is_ray_available() -> bool:
    """True iff we can make a control-plane RPC to the cluster."""
    try:
        if _client_connected() or ray.is_initialized():
            # Will raise if not actually connected.
            ray.cluster_resources()
            return True
        return False
    except Exception:
        return False

def ensure_ray_initialized(
    ray_address: Optional[str] = None,
    ray_namespace: Optional[str] = "seedcore-dev",
    force_reinit: bool = False,
    **init_kwargs: Any
) -> bool:
    """Idempotent connect that respects existing client connections."""
    if _client_connected() or ray.is_initialized():
        return True
    
    addr = ray_address or os.getenv("RAY_ADDRESS")
    ns = ray_namespace or os.getenv("SEEDCORE_NS")
    
    if not addr:
        _log.warning("RAY_ADDRESS not set; skipping Ray connect()")
        return False
    
    # Try with/without namespace, then last-resort allow_multiple.
    for attempt in (
        dict(address=addr, namespace=ns),
        dict(address=addr, namespace=None),
        dict(address=addr, namespace=ns, allow_multiple=True),
    ):
        try:
            ray.init(ignore_reinit_error=True, logging_level=logging.INFO, **attempt)
            # Sanity: verify connectivity
            ray.cluster_resources()
            _log.info("✅ Connected to Ray (attempt=%s)", attempt)
            return True
        except Exception as e:
            _log.warning("Ray connect attempt failed (%s): %s", attempt, e)
    
    _log.error("❌ All Ray connect attempts failed")
    return False

def shutdown_ray() -> None:
    """Safely shutdown Ray connection."""
    try:
        if ray.is_initialized():
            ray.shutdown()
            _log.info("Ray shutdown successful")
    except Exception as e:
        _log.error(f"Error during Ray shutdown: {e}")

def get_ray_cluster_info() -> dict:
    """Get information about the current Ray cluster."""
    try:
        if not is_ray_available():
            return {"status": "not_available"}
        
        # Get cluster resources
        resources = ray.cluster_resources()
        available = ray.available_resources()
        
        return {
            "status": "available",
            "cluster_resources": dict(resources),
            "available_resources": dict(available),
            "nodes": len(ray.nodes()),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def test_ray_connection() -> bool:
    """Test Ray connection with a simple task."""
    try:
        if not is_ray_available():
            return False
        
        # Test with a simple remote function
        @ray.remote
        def test_function():
            return "Ray connection test successful"
        
        result = ray.get(test_function.remote())
        _log.info(f"Ray connection test: {result}")
        return True
        
    except Exception as e:
        _log.error(f"Ray connection test failed: {e}")
        return False 