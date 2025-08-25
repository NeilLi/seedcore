import os
import logging
import ray
import asyncio

# Module-level flag to ensure the connection logic runs only once per process.
_is_connected = False

# Global bootstrap lock for runtime initialization
_bootstrap_lock = asyncio.Lock()

def connect():
    """
    Connects to Ray using environment variables. Idempotent and safe to call multiple times.
    This is the single source of truth for initializing the Ray connection.
    """
    global _is_connected
    
    # If already connected, just return
    if _is_connected and ray.is_initialized():
        _is_connected = True
        return

    # This logic handles all environments:
    # 1. Inside a Ray pod (head/worker): RAY_ADDRESS is not set, Ray connects to its local instance.
    # 2. As a client (seedcore-api): RAY_ADDRESS is set to "ray://<...>" and it connects to the cluster.
    ray_address = os.getenv("RAY_ADDRESS", "auto")
    namespace = os.getenv("RAY_NAMESPACE", "seedcore-dev")

    logging.info(f"Attempting to connect to Ray at address '{ray_address}' in namespace '{namespace}'...")
    
    try:
        # If Ray is already initialized, try to connect with allow_multiple=True
        if ray.is_initialized():
            logging.info("Ray is already initialized. Attempting to connect with allow_multiple=True...")
            try:
                # Connect to existing cluster without forcing namespace
                ray.init(
                    address=ray_address,
                    ignore_reinit_error=True,
                    allow_multiple=True,
                    logging_level=logging.INFO,
                )
                _is_connected = True
                logging.info("✅ Successfully connected to Ray with allow_multiple=True.")
                return
            except Exception as e:
                logging.warning(f"Failed to connect with allow_multiple=True: {e}")
                # If that fails, just return since Ray is already initialized
                _is_connected = True
                logging.info("✅ Using existing Ray connection.")
                return
        
        # Normal connection attempt - try without namespace first
        try:
            ray.init(
                address=ray_address,
                ignore_reinit_error=True,
                logging_level=logging.INFO,
            )
            _is_connected = True
            logging.info("✅ Successfully connected to Ray (no namespace specified).")
        except Exception as e:
            # If that fails, try with the specified namespace
            logging.info(f"Connection without namespace failed, trying with namespace '{namespace}'...")
            ray.init(
                address=ray_address,
                namespace=namespace,
                ignore_reinit_error=True,
                logging_level=logging.INFO,
            )
            _is_connected = True
            logging.info(f"✅ Successfully connected to Ray with namespace '{namespace}'.")
            
    except Exception as e:
        # If the error is about multiple connections, try with allow_multiple=True
        if "already connected" in str(e) and "allow_multiple=True" in str(e):
            logging.info("Detected multiple connection attempt. Retrying with allow_multiple=True...")
            try:
                ray.init(
                    address=ray_address,
                    ignore_reinit_error=True,
                    allow_multiple=True,
                    logging_level=logging.INFO,
                )
                _is_connected = True
                logging.info("✅ Successfully connected to Ray with allow_multiple=True.")
                return
            except Exception as e2:
                logging.critical(f"❌ CRITICAL: Failed to connect to Ray even with allow_multiple=True. Application may not function. Error: {e2}")
                raise
        else:
            logging.critical(f"❌ CRITICAL: Failed to connect to Ray. Application may not function. Error: {e}")
            raise

def is_connected():
    """Check if Ray is connected."""
    try:
        # Check if Ray is initialized
        if not ray.is_initialized():
            return False
        
        # Try to get runtime context to verify connection is working
        runtime_context = ray.get_runtime_context()
        if runtime_context is None:
            return False
        
        # Additional verification: try to list some basic cluster info
        try:
            # Try to get cluster resources (this will fail if not properly connected)
            cluster_resources = ray.cluster_resources()
            if not cluster_resources:
                return False
        except Exception:
            return False
        
        # If we get here, Ray is properly connected
        return True
    except Exception:
        return False

def wait_for_ray_ready(max_wait_seconds: int = 5) -> bool:
    """Wait for Ray to be fully ready after connection."""
    import time
    
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        if is_connected():
            return True
        time.sleep(0.1)  # Small delay between checks
    
    return False

def get_connection_info():
    """Get information about the current Ray connection."""
    if not is_connected():
        return {"status": "not_connected"}
    
    try:
        runtime_context = ray.get_runtime_context()
        cluster_resources = ray.cluster_resources()
        
        return {
            "status": "connected",
            "namespace": getattr(runtime_context, 'namespace', 'default'),
            "address": getattr(runtime_context, 'gcs_address', 'unknown'),
            "node_id": getattr(runtime_context, 'node_id', 'unknown'),
            "cluster_resources": cluster_resources,
            "ray_version": ray.__version__,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def ensure_runtime_ready() -> bool:
    """
    Idempotently (re)establish Ray connection and initialize OrganismManager.
    Safe to call from /readyz and a background task.
    """
    async with _bootstrap_lock:
        try:
            # 1) Connect to Ray if needed
            if not is_connected():
                connect()  # idempotent
                if not wait_for_ray_ready(max_wait_seconds=10):
                    return False

            # 2) Initialize OrganismManager once Ray is up
            # Note: This function doesn't have access to app.state, so it only handles Ray connection
            # The OrganismManager initialization will be handled by the calling code
            return True
        except Exception:
            logging.exception("Runtime bootstrap failed")
            return False
