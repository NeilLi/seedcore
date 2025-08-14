#!/usr/bin/env python3
"""
Ray Serve Entrypoint (head-pod friendly)

Defaults assume:
- You're running this *on the Ray head pod* (RAY_ADDRESS="auto")
- Ray head & workers use your app image (deps & code are baked in)
- Serve HTTP should run here unless MANAGED_BY_RAYSERVICE=1

Env knobs (all optional):
  RAY_ADDRESS=auto | ray://seedcore-head-svc:10001
  RAY_NAMESPACE=seedcore-dev
  SERVE_HTTP_HOST=0.0.0.0
  SERVE_HTTP_PORT=8000
  MANAGED_BY_RAYSERVICE=0|1        # 1 -> don't call serve.start()
  SERVE_RESET=0|1                  # 1 -> serve.shutdown() before start
  ENABLE_HEALTH=0|1                # 1 -> expose /health via tiny app
  ROUTE_PREFIX=/                   # route prefix for your main app
  APP_IMPORT_PATH=seedcore.serve_entrypoint:build_app  # override importer
  PYTHONPATH=/app:/app/src
  WORKING_DIR=/app                 # used for runtime_env["working_dir"]
  RUNTIME_PIP=0|<requirements>     # usually 0 when image contains deps
"""

import os
import sys
import time
import signal
import socket
import traceback

import ray
from ray import serve

# Optional FastAPI for nicer /health
try:
    from fastapi import FastAPI
    from starlette.responses import PlainTextResponse
except Exception:
    FastAPI = None
    PlainTextResponse = None

# -------------------------------
# Config
# -------------------------------
RAY_ADDR   = os.getenv("RAY_ADDRESS", "auto")
RAY_NS     = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
HTTP_HOST  = os.getenv("SERVE_HTTP_HOST", "0.0.0.0")
HTTP_PORT  = int(os.getenv("SERVE_HTTP_PORT", "8000"))
PY_PATH    = os.getenv("PYTHONPATH", "/app:/app/src")
WORKDIR    = os.getenv("WORKING_DIR", "/app")
ROUTE_PREF = os.getenv("ROUTE_PREFIX", "/")

MANAGED_BY_RAYSERVICE = os.getenv("MANAGED_BY_RAYSERVICE", "0").lower() in {"1","true","yes","on"}
SERVE_RST  = os.getenv("SERVE_RESET", "0").lower() in {"1","true","yes","on"}
ENABLE_HEALTH = os.getenv("ENABLE_HEALTH", "1").lower() in {"1","true","yes","on"}

# If you're now using your own image for head/worker, pip-at-runtime is unnecessary:
RUNTIME_PIP = os.getenv("RUNTIME_PIP", "0")  # "0" disables runtime pip (recommended)

APP_IMPORT_PATH = os.getenv("APP_IMPORT_PATH", "seedcore.serve_entrypoint:build_app")

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

_stop = False
def _graceful_shutdown(signum, frame):
    global _stop
    log(f"Received signal {signum}; shutting down main loop...")
    _stop = True

# -------------------------------
# Minimal /health app (optional)
# -------------------------------
if ENABLE_HEALTH:
    if FastAPI is not None:
        health_app = FastAPI()

        @health_app.get("/health")
        def _health():
            return PlainTextResponse("ok")

        @serve.deployment
        @serve.ingress(health_app)
        class Health:  # noqa: N801
            pass
    else:
        @serve.deployment
        class Health:  # noqa: N801
            async def __call__(self, request):  # type: ignore[override]
                return "ok"

# -------------------------------
# Bootstrapping singletons (optional)
# -------------------------------
def try_bootstrap_singletons():
    try:
        try:
            from seedcore.bootstrap import bootstrap_actors  # type: ignore
        except ModuleNotFoundError:
            from src.seedcore.bootstrap import bootstrap_actors  # type: ignore

        mt, sc, mv = bootstrap_actors()
        log(f"Bootstrapped actors: miss_tracker={mt}, shared_cache={sc}, mv_store={mv}")
    except Exception:
        err("bootstrap_actors() failed (continuing):\n" + traceback.format_exc())

# -------------------------------
# Import your app builder
# -------------------------------
def import_build_app():
    # Allow override via APP_IMPORT_PATH="pkg.module:func"
    if ":" in APP_IMPORT_PATH:
        mod, _, func = APP_IMPORT_PATH.partition(":")
        mod = mod.strip()
        func = func.strip()
        module = __import__(mod, fromlist=[func])
        return getattr(module, func)
    # Fallback to legacy locations
    try:
        from seedcore.serve_entrypoint import build_app  # type: ignore
        return build_app
    except ModuleNotFoundError:
        from src.seedcore.serve_entrypoint import build_app  # type: ignore
        return build_app

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

    # Build runtime_env (keep minimal now that code+deps are in the image)
    runtime_env = {
        "working_dir": WORKDIR,
        "env_vars": {"PYTHONPATH": PY_PATH},
    }
    if RUNTIME_PIP and RUNTIME_PIP != "0":
        runtime_env["pip"] = RUNTIME_PIP
        log(f"runtime_env['pip'] enabled: {RUNTIME_PIP}")
    else:
        log("runtime_env['pip'] disabled (using baked deps).")

    # Connect to Ray
    log(f"Connecting to Ray at {RAY_ADDR} (namespace={RAY_NS})")
    ray.init(address=RAY_ADDR, namespace=RAY_NS, runtime_env=runtime_env)

    # Optional reset so HTTP options can apply cleanly
    if SERVE_RST:
        log("SERVE_RESET=1 → serve.shutdown() before (re)starting HTTP.")
        try:
            serve.shutdown()
        except Exception:
            pass
        time.sleep(1.0)

    # Start Serve HTTP unless a controller is managed elsewhere (e.g., RayService)
    if MANAGED_BY_RAYSERVICE:
        log("MANAGED_BY_RAYSERVICE=1 → skipping serve.start(); controller managed by operator.")
    else:
        log(f"Starting Serve HTTP on {HTTP_HOST}:{HTTP_PORT}")
        serve.start(detached=True, http_options={"host": HTTP_HOST, "port": HTTP_PORT})

    # Health app (optional, separate app so probes work even if main app fails)
    if ENABLE_HEALTH:
        try:
            serve.run(Health.bind(), name="health", route_prefix="/health")  # type: ignore[name-defined]
            log("Health endpoint deployed at /health")
        except Exception:
            err("Failed to deploy Health endpoint:\n" + traceback.format_exc())

    # Bootstrap singletons
    try_bootstrap_singletons()

    # Import and deploy your main application
    try:
        build_app = import_build_app()
        app = build_app()
        serve.run(app, route_prefix=ROUTE_PREF)
        log(f"Application deployed successfully at route_prefix={ROUTE_PREF!r}")
    except Exception:
        err("Failed to deploy application:\n" + traceback.format_exc())
        sys.exit(1)

    # Graceful shutdown hooks
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    # Idle loop
    log("Entrypoint is now idle; press Ctrl+C or send SIGTERM to stop.")
    while not _stop:
        time.sleep(2)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        err("Fatal error in entrypoint:\n" + traceback.format_exc())
        sys.exit(1)
