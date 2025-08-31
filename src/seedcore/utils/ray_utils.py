"""
Ray utility functions for SeedCore.
Provides centralized, robust Ray initialization and connection management.
Gateway discovery is derived from RAY_ADDRESS (with optional SERVE_GATEWAY override).
"""

from __future__ import annotations

import os
import logging
from typing import Optional, Any, Dict, Tuple
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

DEFAULT_SERVE_PORT = 8000
ENV_SERVE_GATEWAY = "SERVE_GATEWAY"      # explicit override only
ENV_RAY_ADDRESS   = "RAY_ADDRESS"        # canonical source set by Ray
ENV_SERVE_BASE    = "SERVE_BASE_PATH"    # default "/ml"
ENV_COG_BASE      = "COG_BASE_PATH"      # default "/cognitive"


def _normalize_http(addr: str, default_port: int = DEFAULT_SERVE_PORT) -> str:
    """
    Normalize a host/URL-like string to "http://host:port" (no trailing slash).
    Accepts:
      - "localhost", "localhost:8000"
      - "http://x:8000", "https://x:443" (scheme preserved)
      - "ray://x:10001" or "x:6379" -> "http://x:8000"
    """
    if not addr:
        return f"http://127.0.0.1:{default_port}"

    addr = addr.strip()

    # Strip ray:// and any path
    if addr.startswith("ray://"):
        addr = addr[len("ray://"):]
    addr = addr.split("/", 1)[0]

    # If scheme missing, assume http
    if not addr.startswith(("http://", "https://")):
        host = addr if ":" in addr else f"{addr}:{default_port}"
        return f"http://{host}"

    # Has scheme already
    parsed = urlparse(addr)
    netloc = parsed.netloc or parsed.path
    if ":" not in netloc:
        netloc = f"{netloc}:{default_port}"
    return f"{parsed.scheme}://{netloc}"


def _host_from_ray_address(ra: str) -> str:
    """Extract host from RAY_ADDRESS which may be 'host:port', 'ray://host:port', or include a path."""
    ra = (ra or "").strip()
    if ra.startswith("ray://"):
        ra = ra[len("ray://"):]
    ra = ra.split("/", 1)[0]
    return ra.split(":", 1)[0] if ra else "127.0.0.1"


def _derive_serve_gateway() -> str:
    """
    Derive Ray Serve HTTP gateway with a simple, opinionated strategy:
      1) If SERVE_GATEWAY is set, use it verbatim (normalized).
      2) Else derive from RAY_ADDRESS:
         - localhost/127.0.0.1 -> http://127.0.0.1:8000
         - seedcore-svc-*-head-svc(.ns.svc.cluster.local) -> ...-serve-svc:8000
      3) Else default to 'http://seedcore-svc-stable-svc:8000'
    """
    sg = os.getenv(ENV_SERVE_GATEWAY)
    if sg:
        gw = _normalize_http(sg, DEFAULT_SERVE_PORT)
        _log.info("SERVE_GATEWAY override in use: %s", gw)
        return gw

    ra = os.getenv(ENV_RAY_ADDRESS)
    if ra:
        host = _host_from_ray_address(ra)
        if host in ("127.0.0.1", "localhost"):
            gw = f"http://127.0.0.1:{DEFAULT_SERVE_PORT}"
            _log.info("Derived SERVE gateway (localhost): %s", gw)
            return gw
        # map *-head-svc to *-serve-svc (works for FQDNs too)
        serve_host = host.replace("-head-svc", "-stable-svc")
        gw = f"http://{serve_host}:{DEFAULT_SERVE_PORT}"
        _log.info("Derived SERVE gateway (cluster svc): %s", gw)
        return gw

    gw = f"http://seedcore-svc-stable-svc:{DEFAULT_SERVE_PORT}"
    _log.info("Derived SERVE gateway (fallback): %s", gw)
    return gw


def _derive_base_paths() -> Tuple[str, str]:
    ml = (os.getenv(ENV_SERVE_BASE) or "/ml").rstrip("/") or "/ml"
    cog = (os.getenv(ENV_COG_BASE) or "/cognitive").rstrip("/") or "/cognitive"
    return ml, cog


# Public constants (computed without importing ray)
SERVE_GATEWAY: str = _derive_serve_gateway()
_ML_BASE, _COG_BASE = _derive_base_paths()
ML: str  = f"{SERVE_GATEWAY}{_ML_BASE}"
COG: str = f"{SERVE_GATEWAY}{_COG_BASE}"


def get_serve_urls(base_gateway: Optional[str] = None,
                   ml_base: Optional[str] = None,
                   cog_base: Optional[str] = None) -> Dict[str, str]:
    """
    Build canonical Serve URLs. Only normalize when an explicit base_gateway is provided,
    to avoid double-normalization of the precomputed SERVE_GATEWAY.
    """
    if base_gateway:
        gw = _normalize_http(base_gateway).rstrip("/")
    else:
        gw = SERVE_GATEWAY.rstrip("/")

    mlp = (ml_base or _ML_BASE)
    if not mlp.startswith("/"):
        mlp = f"/{mlp}"

    cogp = (cog_base or _COG_BASE)
    if not cogp.startswith("/"):
        cogp = f"/{cogp}"

    return {
        "gateway": gw,
        "ml_root": f"{gw}{mlp}/",
        "ml_health": f"{gw}{mlp}/health",
        "ml_salience": f"{gw}{mlp}/score/salience",
        "cog_root": f"{gw}{cogp}/",
        "cog_health": f"{gw}{cogp}/health",
    }


# -------------------------------
# Ray connection helpers (lazy)
# -------------------------------

def _client_connected() -> bool:
    try:
        # This is the canonical check in Ray Client mode.
        from ray.util.client import ray as client_ray  # type: ignore
        return client_ray.is_connected()
    except Exception:
        return False


def is_ray_available() -> bool:
    """True iff we can make a control-plane RPC to the cluster."""
    try:
        if _client_connected():
            return True
        import ray  # type: ignore  # lazy import
        if ray.is_initialized():
            ray.cluster_resources()  # raises if not connected
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
    try:
        import ray  # type: ignore  # lazy import
    except Exception as e:
        _log.warning("Ray not installed/available: %s", e)
        return False

    if _client_connected() or ray.is_initialized():
        if not force_reinit:
            return True

    addr = ray_address or os.getenv(ENV_RAY_ADDRESS)
    ns = ray_namespace or os.getenv("SEEDCORE_NS")

    if not addr:
        _log.warning("RAY_ADDRESS not set; skipping ray.init()")
        return False

    attempts = (
        dict(address=addr, namespace=ns),
        dict(address=addr, namespace=None),
        dict(address=addr, namespace=ns, allow_multiple=True),
    )

    for attempt in attempts:
        try:
            ray.init(ignore_reinit_error=True, logging_level=logging.INFO, **attempt, **init_kwargs)
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
        import ray  # type: ignore
        if ray.is_initialized():
            ray.shutdown()
            _log.info("Ray shutdown successful")
    except Exception as e:
        _log.error("Error during Ray shutdown: %s", e)


def get_ray_cluster_info() -> dict:
    """Get information about the current Ray cluster."""
    try:
        if not is_ray_available():
            return {"status": "not_available"}
        import ray  # type: ignore
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
        import ray  # type: ignore
        @ray.remote
        def test_function():
            return "Ray connection test successful"
        result = ray.get(test_function.remote())
        _log.info("Ray connection test: %s", result)
        return True
    except Exception as e:
        _log.error("Ray connection test failed: %s", e)
        return False
