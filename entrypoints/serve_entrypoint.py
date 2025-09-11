#!/usr/bin/env python3
"""
Ray Serve Entrypoint with XGBoost Service Deployment

This script creates a proper Ray Serve deployment wrapper around the XGBoost service.
It registers the service with Ray Serve so it can handle requests.
"""

import os
import sys
import time
import signal
import socket
import traceback

import ray
from ray import serve
from fastapi import FastAPI, Request

# Add the app directory to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.utils.ray_utils import ensure_ray_initialized

# -------------------------------
# Config
# -------------------------------
RAY_ADDR   = os.getenv("RAY_ADDRESS", "auto")
RAY_NS     = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
HTTP_HOST  = os.getenv("SERVE_HTTP_HOST", "0.0.0.0")
HTTP_PORT  = int(os.getenv("SERVE_HTTP_PORT", "8000"))
PY_PATH    = os.getenv("PYTHONPATH", "/app:/app/src")
WORKDIR    = os.getenv("WORKING_DIR", "/app")

MANAGED_BY_RAYSERVICE = os.getenv("MANAGED_BY_RAYSERVICE", "0").lower() in {"1","true","yes","on"}
SERVE_RST  = os.getenv("SERVE_RESET", "0").lower() in {"1","true","yes","on"}

# -------------------------------
# Helpers
# -------------------------------
def log(msg: str):
    print(f"[serve] {msg}", flush=True)

def err(msg: str):
    print(f"[serve][ERROR] {msg}", file=sys.stderr, flush=True)

def wait_tcp(host: str, port: int, timeout_s: int = 2, tries: int = 90) -> bool:
    for _ in range(tries):
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return True
        except OSError:
            time.sleep(2)
    return False

def parse_ray_addr(ray_addr: str):
    if not isinstance(ray_addr, str) or not ray_addr.startswith("ray://"):
        return None, None
    rest = ray_addr[len("ray://"):]
    host, _, port = rest.partition(":")
    try:
        return host, int(port)
    except Exception:
        return None, None

# -------------------------------
# XGBoost Service Deployment
# -------------------------------
def get_xgboost_service():
    """Get the XGBoost service instance."""
    try:
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        return get_xgboost_service()
    except ImportError:
        # Fallback to src path
        try:
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            return get_xgboost_service()
        except Exception as e:
            err(f"Failed to import XGBoost service: {e}")
            return None

# 1. Define your FastAPI app as usual
fastapi_app = FastAPI()

@fastapi_app.get("/")
def root():
    return {"status": "ok", "message": "XGBoost service ready"}

@fastapi_app.get("/health")
def health():
    return {"status": "healthy", "service": "xgboost-api"}

@fastapi_app.get("/xgb/models")
async def list_models():
    """List available models."""
    try:
        svc = get_xgboost_service()
        if svc is None:
            return {"error": "Service not available", "status": "error"}
        models = svc.list_models()
        return {"models": models, "status": "success"}
    except Exception as e:
        return {"error": str(e), "status": "error"}

@fastapi_app.get("/xgb/model_info")
async def get_model_info():
    """Get current model information."""
    try:
        svc = get_xgboost_service()
        if svc is None:
            return {"error": "Service not available", "status": "error"}
        info = svc.get_model_info()
        return {"model_info": info, "status": "success"}
    except Exception as e:
        return {"error": str(e), "status": "error"}

@fastapi_app.post("/xgb")
async def predict(request: Request):
    """Handle XGBoost prediction requests."""
    try:
        svc = get_xgboost_service()
        if svc is None:
            return {"error": "Service not available", "status": "error"}
        
        data = await request.json()
        result = svc.predict(data)
        return {"prediction": result, "status": "success"}
    except Exception as e:
        err(f"Error in XGBoost prediction: {e}")
        return {"error": str(e), "status": "error"}

# 2. Wrap it in a Ray Serve deployment
@serve.deployment
@serve.ingress(fastapi_app)
class FastAPIWrapper:
    # This class can be empty or can contain other logic
    # if you need to manage state.
    pass

# 3. Define the final application that Ray Serve can deploy
app = FastAPIWrapper.bind()

# -------------------------------
# Main
# -------------------------------
def main():
    # Preflight TCP only if using ray://
    host, port = parse_ray_addr(RAY_ADDR)
    if host and port:
        log(f"Preflight: waiting for Ray Client {host}:{port} ...")
        if not wait_tcp(host, port, tries=90):
            err(f"Ray Client {host}:{port} not reachable.")
            sys.exit(1)

    # Build runtime_env
    runtime_env = {
        "working_dir": WORKDIR,
        "env_vars": {"PYTHONPATH": PY_PATH},
    }

    # Connect to Ray
    try:
        log(f"Connecting to Ray at {RAY_ADDR} (namespace={RAY_NS})")
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS, runtime_env=runtime_env):
            err("Failed to connect to Ray")
            sys.exit(1)
        log("✅ Connected to Ray successfully")
    except Exception as e:
        err(f"Failed to connect to Ray: {e}")
        sys.exit(1)

    # Optional reset so HTTP options can apply cleanly
    if SERVE_RST:
        log("SERVE_RESET=1 → serve.shutdown() before (re)starting HTTP.")
        try:
            serve.shutdown()
        except Exception:
            pass
        time.sleep(1.0)

    # Start Serve HTTP unless a controller is managed elsewhere
    if MANAGED_BY_RAYSERVICE:
        log("MANAGED_BY_RAYSERVICE=1 → skipping serve.start(); controller managed by operator.")
    else:
        log(f"Starting Serve HTTP on {HTTP_HOST}:{HTTP_PORT}")
        serve.start(detached=True, http_options={"host": HTTP_HOST, "port": HTTP_PORT})

    # Deploy FastAPI app wrapped in Ray Serve
    try:
        serve.run(app, name="xgboost-api")
        log("✅ FastAPI app deployed successfully with Ray Serve")
    except Exception as e:
        err(f"Failed to deploy FastAPI app: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Graceful shutdown hooks
    def _graceful_shutdown(signum, frame):
        log(f"Received signal {signum}; shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    # Idle loop
    log("✅ XGBoost service is now running and ready to handle requests!")
    log("   - Root endpoint: /")
    log("   - Health check: /health")
    log("   - XGBoost API: /xgb")
    log("   - Models: /xgb/models")
    log("   - Model info: /xgb/model_info")
    log("   - Predictions: POST /xgb with JSON data")
    log("\nPress Ctrl+C or send SIGTERM to stop.")
    
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        log("Shutting down gracefully...")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        err("Fatal error in entrypoint:")
        traceback.print_exc()
        sys.exit(1)
