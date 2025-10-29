"""
Ray utility functions for SeedCore.
Provides centralized, robust Ray initialization and connection management.
Gateway discovery is derived from RAY_ADDRESS (with optional SERVE_GATEWAY override).

Supports running in:
- Ray head pods
- Ray worker pods
- seedcore-api pods (or any other in-cluster workload)
"""

from __future__ import annotations

import logging
import os
import re
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse, urlunparse

_log = logging.getLogger(__name__)

# -------------------------------
# Environment & defaults
# -------------------------------

DEFAULT_SERVE_PORT  = 8000
DEFAULT_API_NS_ENV  = "SEEDCORE_NS"      # optional global namespace hint

ENV_SERVE_GATEWAY   = "SERVE_GATEWAY"    # explicit override
ENV_RAY_ADDRESS     = "RAY_ADDRESS"      # canonical source set by Ray
ENV_SERVE_BASE      = "SERVE_BASE_PATH"  # default "/ml"
ENV_COG_BASE        = "COG_BASE_PATH"    # default "/cognitive"
ENV_SERVE_SERVICE   = "SERVE_SERVICE"    # "stable" (default) or "serve"
ENV_POD_NAMESPACE   = "POD_NAMESPACE"    # set via Downward API when possible

# Matches both with & without 5-char run-id (e.g., -cklbk- or -lz98r-)
HEAD_RE = re.compile(
    r""" ^
        (?P<base> [a-z0-9-]+? )                     # base prefix (lazy)
        (?: - (?P<runid>[a-z0-9]{5}) )?             # optional run-id
        -head-svc                                   # head service suffix
        (?P<fqdn>\.[A-Za-z0-9_.-]+)?                # optional .ns.svc.cluster.local
        $ """,
    re.X,
)

# -------------------------------
# Small utilities
# -------------------------------

def _normalize_http(url_or_host: str, default_port: int = DEFAULT_SERVE_PORT) -> str:
    """
    Normalize to a clean HTTP(S) base without trailing slash.
    Accepts bare hosts, `ray://` endpoints, or full URLs.
    """
    if not url_or_host:
        return f"http://127.0.0.1:{default_port}"

    s = url_or_host.strip()
    # Accept ray://host:port[/...]
    if s.startswith("ray://"):
        s = s[len("ray://"):]
    # If no explicit scheme, treat as host[:port]
    if "://" not in s:
        host = s.split("/", 1)[0]
        if ":" not in host:
            host = f"{host}:{default_port}"
        return f"http://{host}"

    u = urlparse(s, scheme="http")
    netloc = u.netloc or u.path  # tolerate malformed "http://host:port" vs bare
    if ":" not in netloc:
        netloc = f"{netloc}:{default_port}"
    return urlunparse((u.scheme, netloc, "", "", "", ""))

def _host_from_ray_address(ra: str) -> str:
    """Extract host from RAY_ADDRESS (supports 'host:port', 'ray://host:port', URLs)."""
    ra = (ra or "").strip()
    if not ra:
        return "127.0.0.1"
    if ra.startswith("ray://"):
        ra = ra[len("ray://"):]
    u = urlparse(ra if "://" in ra else f"tcp://{ra}")
    return (u.hostname or "").strip() or "127.0.0.1"

def _in_k8s_namespace() -> Optional[str]:
    """Best-effort namespace detection (env first, then serviceaccount file)."""
    ns = os.getenv(ENV_POD_NAMESPACE) or os.getenv(DEFAULT_API_NS_ENV)
    if ns:
        return ns.strip()
    try:
        with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
            return f.read().strip()
    except Exception:
        return None

def _compose_service_fqdn(name: str, namespace: Optional[str]) -> str:
    """If `name` already looks FQDN-ish, return it. Otherwise add namespace FQDN if known."""
    if "." in name:
        return name
    return f"{name}.{namespace}.svc.cluster.local" if namespace else name

def _strip_runid_head_to_target(host: str, prefer: str = "stable") -> str:
    """
    Convert:
      seedcore-svc-cklbk-head-svc(.fqdn) -> seedcore-svc-stable-svc(.fqdn)
      seedcore-svc-head-svc(.fqdn)       -> seedcore-svc-serve/stable-svc(.fqdn)
    Preserves namespace/FQDN suffix. If not a head-svc, returns original host.
    """
    m = HEAD_RE.match(host)
    if not m:
        return host
    base = m.group("base")
    fqdn = m.group("fqdn") or ""
    suffix = "-stable-svc" if prefer == "stable" else "-serve-svc"
    return f"{base}{suffix}{fqdn}"

def _resolve_ok(host: str, timeout_s: float = 0.4) -> bool:
    """Fast DNS existence check using system resolver (CoreDNS in cluster)."""
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_s)
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(old)

# -------------------------------
# Gateway & paths
# -------------------------------

def _derive_serve_gateway() -> str:
    """
    Derive Ray Serve HTTP gateway robustly:
      1) SERVE_GATEWAY -> normalize & use verbatim.
      2) RAY_ADDRESS:
         - localhost/127.0.0.1 -> http://127.0.0.1:8000
         - *-head-svc(.fqdn)    -> strip run-id & map to {base}-{stable|serve}-svc
           (default prefers 'stable', configurable via SERVE_SERVICE)
           Verify DNS; if not resolvable, try the alternate flavor; finally try direct host.
      3) In cluster, default to seedcore-svc-{stable|serve}-svc in same namespace.
      4) Last resort, seedcore-svc-{stable|serve}-svc without namespace.
    """
    prefer = (os.getenv(ENV_SERVE_SERVICE) or "stable").strip().lower()
    if prefer not in ("stable", "serve"):
        prefer = "stable"

    # 1) Hard override
    sg = os.getenv(ENV_SERVE_GATEWAY)
    if sg:
        gw = _normalize_http(sg, DEFAULT_SERVE_PORT)
        _log.info("SERVE_GATEWAY override in use: %s", gw)
        return gw

    ns = _in_k8s_namespace()

    # 2) Derive from Ray address
    ra = os.getenv(ENV_RAY_ADDRESS)
    if ra:
        host = _host_from_ray_address(ra)
        if host in ("127.0.0.1", "localhost"):
            gw = f"http://127.0.0.1:{DEFAULT_SERVE_PORT}"
            _log.info("Derived SERVE gateway (localhost): %s", gw)
            return gw

        # Map head -> stable/serve
        candidate = _compose_service_fqdn(_strip_runid_head_to_target(host, prefer), ns)
        if _resolve_ok(candidate):
            gw = f"http://{candidate}:{DEFAULT_SERVE_PORT}"
            _log.info("Derived SERVE gateway (from RAY_ADDRESS %s): %s", prefer, gw)
            return gw

        # Try alternate flavor (stable <-> serve)
        alt = "serve" if prefer == "stable" else "stable"
        alt_candidate = _compose_service_fqdn(_strip_runid_head_to_target(host, alt), ns)
        if _resolve_ok(alt_candidate):
            gw = f"http://{alt_candidate}:{DEFAULT_SERVE_PORT}"
            _log.info("Derived SERVE gateway (alternate %s): %s", alt, gw)
            return gw

        # Try the direct host as-is (could already be a stable/serve svc or external)
        direct = _compose_service_fqdn(host, ns)
        if _resolve_ok(direct):
            gw = f"http://{direct}:{DEFAULT_SERVE_PORT}"
            _log.warning("Derived SERVE gateway (direct host fallback): %s", gw)
            return gw

        _log.warning("Unable to resolve gateway candidates derived from RAY_ADDRESS=%s; falling back.", ra)

    # 3) Cluster-aware default
    default_name = "seedcore-svc-stable-svc" if prefer == "stable" else "seedcore-svc-serve-svc"
    default_fqdn = _compose_service_fqdn(default_name, ns)
    gw = f"http://{default_fqdn}:{DEFAULT_SERVE_PORT}"
    _log.info("Derived SERVE gateway (cluster-aware fallback): %s", gw)
    return gw

def _derive_base_paths() -> Tuple[str, str]:
    ml  = (os.getenv(ENV_SERVE_BASE) or "/ml").strip() or "/ml"
    cog = (os.getenv(ENV_COG_BASE) or "/cognitive").strip() or "/cognitive"
    if not ml.startswith("/"):
        ml = "/" + ml
    if not cog.startswith("/"):
        cog = "/" + cog
    return ml.rstrip("/"), cog.rstrip("/")

# Compute once (fast, side-effect free). Keep helpers to rebuild on-demand if env changes.
_SERVE_GATEWAY: str
_ML_BASE: str
_COG_BASE: str

def _recompute_globals() -> None:
    global _SERVE_GATEWAY, _ML_BASE, _COG_BASE
    _SERVE_GATEWAY = _derive_serve_gateway().rstrip("/")
    _ML_BASE, _COG_BASE = _derive_base_paths()

# initialize at import
_recompute_globals()

# Public constants (read-only views)
SERVE_GATEWAY: str = _SERVE_GATEWAY
ML: str  = f"{SERVE_GATEWAY}{_ML_BASE}"
COG: str = f"{SERVE_GATEWAY}{_COG_BASE}"

def get_serve_urls(
    base_gateway: Optional[str] = None,
    ml_base: Optional[str] = None,
    cog_base: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build canonical Serve URLs. If base_gateway provided, normalize it; otherwise use cached SERVE_GATEWAY.
    """
    gw = _normalize_http(base_gateway or SERVE_GATEWAY).rstrip("/")
    mlp = (ml_base or _ML_BASE)
    if not mlp.startswith("/"):
        mlp = f"/{mlp}"
    cogp = (cog_base or _COG_BASE)
    if not cogp.startswith("/"):
        cogp = f"/{cogp}"

    return {
        "gateway": gw,
        "ml_root":      f"{gw}{mlp}/",
        "ml_health":    f"{gw}{mlp}/health",
        "ml_salience":  f"{gw}{mlp}/score/salience",
        "cog_root":     f"{gw}{cogp}/",
        "cog_health":   f"{gw}{cogp}/health",
    }

# -------------------------------
# Ray connection helpers (lazy)
# -------------------------------

def _client_connected() -> bool:
    """True iff a Ray Client session is active (ray.util.client)."""
    try:
        from ray.util.client import ray as client_ray  # type: ignore
        return client_ray.is_connected()
    except Exception:
        return False

def is_ray_available() -> bool:
    """True iff we can make a control-plane RPC to the cluster (client or native)."""
    # Client first
    if _client_connected():
        return True
    # Native
    try:
        import ray  # type: ignore
        if ray.is_initialized():
            # cluster_resources() throws when not connected
            ray.cluster_resources()
            return True
        return False
    except Exception:
        return False

def ensure_ray_initialized(
    ray_address: Optional[str] = None,
    ray_namespace: Optional[str] = "seedcore-dev",
    force_reinit: bool = False,
    **init_kwargs: Any,
) -> bool:
    """
    Idempotent connect that respects existing client connections.
    Tries (addr+ns) -> (addr+None) -> (addr+ns, allow_multiple=True).
    """
    try:
        import ray  # type: ignore
    except Exception as e:
        _log.warning("Ray not installed/available: %s", e)
        return False

    # Already connected?
    if _client_connected() or ray.is_initialized():
        if not force_reinit:
            return True

    addr = (ray_address or os.getenv(ENV_RAY_ADDRESS) or "").strip()
    ns = (ray_namespace or os.getenv(DEFAULT_API_NS_ENV) or "").strip() or None

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
            # Sanity check: ensure usable connection
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
        def ping():
            return "ok"

        result = ray.get(ping.remote())
        ok = result == "ok"
        _log.info("Ray connection test: %s", result)
        return ok
    except Exception as e:
        _log.error("Ray connection test failed: %s", e)
        return False

# -------------------------------
# Convenience for dynamic env updates
# -------------------------------

def refresh_gateway_and_paths() -> Dict[str, str]:
    """
    Recompute SERVE_GATEWAY/ML/COG from current environment.
    Useful if env vars are injected/changed after import.
    """
    _recompute_globals()
    return get_serve_urls()
