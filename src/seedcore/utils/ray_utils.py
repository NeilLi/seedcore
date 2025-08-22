"""
Ray utility functions for SeedCore.
Provides centralized, robust Ray initialization and connection management.
"""

import os
import ray
import logging
from typing import Optional, Any, Dict

# Use a module-level flag for a fast path to avoid repeated checks.
_RAY_INITIALIZED = False

def ensure_ray_initialized(
    ray_address: Optional[str] = None,
    ray_namespace: Optional[str] = "seedcore-dev",
    force_reinit: bool = False,
    **init_kwargs: Any
) -> bool:
    """
    Connects to Ray if not already connected. Idempotent and environment-aware.

    This is the single source of truth for all Ray connections.

    Args:
        ray_address: Optional Ray cluster address to connect to
        ray_namespace: Optional Ray namespace to use
        force_reinit: If True, force reinitialize Ray even if already connected
        **init_kwargs: Additional Ray initialization arguments (e.g., runtime_env)

    Behavior:
    1. If already connected and force_reinit=False, does nothing.
    2. If force_reinit=True, shuts down existing connection and reconnects.
    3. If RAY_ADDRESS env var is set, connects as a client to that address.
    4. If RAY_ADDRESS is not set, connects with address="auto" to join the
       existing cluster (for code running inside Ray pods) or start a local one.
    """
    global _RAY_INITIALIZED
    
    # Handle force reinit
    if force_reinit and ray.is_initialized():
        logging.info("Force reinit requested, shutting down existing Ray connection")
        ray.shutdown()
        _RAY_INITIALIZED = False
    
    if _RAY_INITIALIZED:
        return True

    if ray.is_initialized():
        _RAY_INITIALIZED = True
        return True

    # Use the provided address, fall back to environment variable, then to "auto"
    address_to_use = ray_address or os.getenv("RAY_ADDRESS") or "auto"
    
    logging.info(f"Ray not initialized. Attempting to connect with address='{address_to_use}'...")

    try:
        # For Ray Client, strip runtime_env (not applied) to avoid warnings.
        init_kwargs = dict(init_kwargs or {})
        if address_to_use.startswith("ray://"):
            init_kwargs.pop("runtime_env", None)
            ray.init(
                address=address_to_use,
                namespace=ray_namespace,
                ignore_reinit_error=True,
                logging_level=logging.WARNING,
                allow_multiple=True,
                **init_kwargs,
            )
        else:
            # Local/auto mode can accept runtime_env, working_dir, etc.
            ray.init(
                address=address_to_use,
                namespace=ray_namespace,
                ignore_reinit_error=True,
                logging_level=logging.WARNING,
                **init_kwargs,
            )
        _RAY_INITIALIZED = True
        logging.info("Successfully connected to Ray.")
        return True
    except Exception as e:
        # Check if the error is about already being connected
        if "already connected" in str(e).lower() or "allow_multiple" in str(e).lower():
            logging.info("Ray is already connected to the cluster, marking as initialized")
            _RAY_INITIALIZED = True
            return True
        logging.error(f"Failed to connect to Ray at address '{address_to_use}': {e}", exc_info=True)
        return False


def shutdown_ray() -> None:
    """Safely shutdown Ray connection."""
    try:
        if ray.is_initialized():
            ray.shutdown()
            logging.info("Ray shutdown successful")
    except Exception as e:
        logging.error(f"Error during Ray shutdown: {e}")


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
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def test_ray_connection() -> bool:
    """Test Ray connection with a simple task."""
    try:
        if not ensure_ray_initialized():
            return False
        
        # Test with a simple remote function
        @ray.remote
        def test_function():
            return "Ray connection test successful"
        
        result = ray.get(test_function.remote())
        logging.info(f"Ray connection test: {result}")
        return True
        
    except Exception as e:
        logging.error(f"Ray connection test failed: {e}")
        return False 