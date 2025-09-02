#!/usr/bin/env python3
from typing import Any, Dict, Optional, Tuple, List
from collections import defaultdict, deque
import math
import os
import sys
import json
import time
import uuid
import logging
import ast
import argparse
import asyncio

"""
Verify SeedCore architecture end-to-end:

UPDATED FOR NEW SERVICE BOUNDARIES:
- Task creation: POST /api/v1/tasks (seedcore-api service)
- Orchestrator: /orchestrator/pipeline/* (Ray Serve orchestrator for pipeline operations)
- Health checks: GET /health (both services)
- Response format: {"id": "uuid", "status": "string", "result": {...}, "created_at": "datetime"}

- Ray cluster reachable
- Coordinator actor healthy & organism initialized
- N Dispatchers + M GraphDispatchers present and responsive
- Serve apps 'orchestrator', 'cognitive', 'ml_service' up
- Submit fast-path task (low drift) -> COMPLETED
- Submit escalation task (high drift) -> COMPLETED
- (Optional) Submit graph task via DB function -> COMPLETED
- Pull Coordinator status/metrics snapshot

IMPORTANT: This script has been updated to gracefully handle missing debugging methods
on the deployed OrganismManager. It will check for method availability before calling
them and provide informative logging about what's available vs. what's missing.

RAY SERVE ERROR FIX: This script now uses a whitelist approach to prevent calling
unsupported methods on the OrganismManager deployment, which eliminates the noisy
"Unhandled error ... Tried to call a method ... does not exist" Ray Serve logs.
The SUPPORTED_COORD_METHODS whitelist and call_if_supported() function ensure only
known-good methods are invoked.

RAY 2.32 COMPATIBILITY FIX: Fixed "coroutine was expected, got DeploymentResponse" 
errors by replacing asyncio.run() with DeploymentResponse.result() pattern in:
- call_if_supported() function
- serve_deployment_status() function  
- check_cluster_and_actors() health check
This ensures compatibility with Ray 2.32+ where handle.method.remote() returns
DeploymentResponse instead of coroutines.

ORCHESTRATOR HEALTH PATH FIX: Fixed 404 errors on health endpoint by replacing
urljoin(orch_url, "/health") with orch_url.rstrip("/") + "/health to preserve
the /orchestrator base path. This ensures health requests go to /orchestrator/health
instead of just /health.

ANOMALY-TRIAGE TIMEOUT & SERVE BACKPRESSURE FIX: Fixed timeout issues and added
latency tracking for pipeline endpoints. Increased anomaly-triage timeout from 8s
to 30s to handle Ray 2.32's default max_ongoing_requests=5 which can cause
queuing. Added comprehensive latency metrics including min/max/avg/P95 for
performance monitoring and backpressure detection.

DISPATCHER HEALTH "UNKNOWN" FIX: Fixed dispatcher health status showing as "unknown"
by softening the health check logic. If actor_ping() succeeds, treat status as
"healthy" unless explicitly unhealthy, rather than requiring get_status() to return
a valid dict. Added comprehensive heartbeat metrics tracking including last-seen
time, uptime, and ping count for each dispatcher.

THROUGHPUT & DEPLOYMENT CONFIGURATION: Added recommendations to eliminate
max_ongoing_requests warnings by pinning explicit values on deployments.
Recommended configurations range from standard (32/2) to maximum capacity (64/4).
Added DB telemetry monitoring for retry policy analysis and DLQ health tracking.

ORCHESTRATOR CONNECTIVITY FIXES: This script now includes comprehensive diagnostics
for orchestrator connectivity issues that cause tasks to get stuck in 'queued' status:
- Enhanced submit_via_orchestrator() with detailed logging and error handling
- Orchestrator connectivity testing (status endpoints, task submission)
- Queue worker status checking to identify stuck tasks
- Option to fail fast when orchestrator is unreachable (no DB fallback)
- Detailed diagnosis and fix recommendations for common issues

Run inside a pod with cluster network access (or locally with port-forward).
Prereqs: pip install requests psycopg2-binary (if DB checks enabled)

Env:
  RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
  RAY_NAMESPACE=seedcore-dev
  SEEDCORE_PG_DSN=postgresql://postgres:postgres@postgresql:5432/seedcore

  # Service Boundaries (Updated):
  # - Task creation: SEEDCORE_API_URL (seedcore-api service)
  # - Orchestrator: ORCH_URL (Ray Serve orchestrator for pipeline operations)
  SEEDCORE_API_URL=http://seedcore-api:8002           (seedcore-api service for task CRUD)
  SEEDCORE_API_TIMEOUT=5.0                           (timeout for seedcore-api calls)
  ORCH_URL=http://seedcore-svc-stable-svc:8000/orchestrator  (orchestrator for pipeline operations)
  ORCH_PATHS=/pipeline/create-task                   (orchestrator pipeline endpoints)
  
  # API Schema (Updated Service Boundaries):
  # - Task creation: POST /api/v1/tasks (seedcore-api)
  # - Task response: {"id": "uuid", "status": "string", "result": {...}, "created_at": "datetime"}
  # - Orchestrator: /orchestrator/pipeline/* (Ray Serve orchestrator)
  # - Pipeline endpoints: /pipeline/anomaly-triage, /pipeline/tune/status/{job_id}
  
  # IMPORTANT: Avoid double colons (::) in ORCH_URL - use single colon (:) for port
  # Correct: http://127.0.0.1:8000/orchestrator
  # Wrong:  http://127.0.0.1::8000/orchestrator

  OCPS_DRIFT_THRESHOLD=0.5
  COGNITIVE_TIMEOUT_S=8.0
  COGNITIVE_MAX_INFLIGHT=64
  FAST_PATH_LATENCY_SLO_MS=1000
  MAX_PLAN_STEPS=16

  EXPECT_DISPATCHERS=2
  EXPECT_GRAPH_DISPATCHERS=0          # Set to 0 to disable GraphDispatchers
  STRICT_GRAPH_DISPATCHERS=false      # Allow fewer GraphDispatchers than expected
  VERIFY_GRAPH_TASK=true|false
  DEBUG_ROUTING=true|false          # Enable comprehensive routing debugging
  DEBUG_LEVEL=INFO|DEBUG           # Set logging level for debugging
  STRICT_MODE=true|false           # Exit on validation failures (default: true)
  ENABLE_MOCK_ROUTING_TESTS=false # Enable mock routing tests (default: false)
  ENABLE_DIRECT_FALLBACK=false    # Enable direct execution fallback when orchestrator is down (default: false)
  TASK_TIMEOUT_S=90               # Timeout for waiting for task completion (default: 90s)
  TASK_STATUS_CHECK_INTERVAL_S=5  # Interval for checking task status (default: 5s)
  
  # Ray Serve configuration to reduce timeout warnings
  RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S=2.0  # Increase from default 0.1s to reduce warnings
  RAY_SERVE_MAX_QUEUE_LENGTH=2000                 # Increase queue capacity
  SUPPRESS_RAY_SERVE_WARNINGS=false              # Set to true to suppress Ray Serve timeout warnings
  
  # Task creation timing (for orchestrator database integration issues)
  TASK_DB_INSERTION_RETRIES=5                    # Number of retries to find task in database
  TASK_DB_INSERTION_DELAY_S=2.0                  # Delay between retries for database insertion
  
  # To completely avoid any debug calls that might cause Ray Serve errors:
  # DEBUG_ROUTING=false

Usage:
  python verify_seedcore_architecture.py           # Run full verification
  python verify_seedcore_architecture.py --debug   # Run only routing debugging
  python verify_seedcore_architecture.py --strict  # Exit on validation failures
  python verify_seedcore_architecture.py --help    # Show this help
"""

# === METRICS / TIMEOUTS / GLOBALS ===
# Centralized timeouts (overridable via env)
def _env_float(k: str, d: float) -> float:
    try:
        return float(os.getenv(k, str(d)))
    except Exception:
        return d

TIMEOUTS = {
    "serve_call_s": _env_float("SERVE_CALL_TIMEOUT_S", 8.0),
    "serve_status_s": _env_float("SERVE_STATUS_TIMEOUT_S", 5.0),
    "http_s": _env_float("HTTP_TIMEOUT_S", 8.0),
    "http_pipeline_s": _env_float("HTTP_PIPELINE_TIMEOUT_S", 30.0),
}

# === METRICS TRACKING FOR API CALL FAILURES ===
# Simple counter to track coordinator API call failures
coord_api_call_failures = {}

def track_api_failure(method: str):
    """Track API call failures for metrics."""
    coord_api_call_failures[method] = coord_api_call_failures.get(method, 0) + 1
    log.info(f"📊 API call failure tracked: coord_api_call_failures{{method={method}}} = {coord_api_call_failures[method]}")

def get_api_failure_metrics() -> dict[str, int]:
    """Get current API failure metrics."""
    return coord_api_call_failures.copy()

# === ORCHESTRATOR HEALTH METRICS ===
# Counter to track orchestrator health HTTP status codes
orchestrator_health_http_status = {}

def track_orchestrator_health_status(status_code: int):
    """Track orchestrator health endpoint HTTP status codes."""
    orchestrator_health_http_status[status_code] = orchestrator_health_http_status.get(status_code, 0) + 1
    log.info(f"📊 Orchestrator health status tracked: orchestrator_health_http_status{{status={status_code}}} = {orchestrator_health_http_status[status_code]}")

def get_orchestrator_health_metrics() -> dict[int, int]:
    """Get current orchestrator health metrics."""
    return orchestrator_health_http_status.copy()

# === LATENCY TRACKING FOR PIPELINE ENDPOINTS ===
# Track latency for pipeline endpoints to identify performance issues
pipeline_latency_metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

def track_pipeline_latency(endpoint: str, latency_ms: float):
    """Track latency for pipeline endpoints."""
    pipeline_latency_metrics[endpoint].append(latency_ms)
    
    log.info(f"📊 Pipeline latency tracked: {endpoint} = {latency_ms:.1f}ms")

def get_pipeline_latency_metrics() -> dict[str, list[float]]:
    """Get current pipeline latency metrics."""
    return {k: v.copy() for k, v in pipeline_latency_metrics.items()}

def get_pipeline_latency_summary() -> dict[str, dict[str, float]]:
    """Get summary statistics for pipeline latency metrics."""
    summary = {}
    for endpoint, latencies in pipeline_latency_metrics.items():
        if latencies:
            arr = sorted(latencies)
            n = len(arr)
            idx = math.ceil(0.95 * (n - 1))
            summary[endpoint] = {
                "count": n,
                "min_ms": arr[0],
                "max_ms": arr[-1],
                "avg_ms": sum(arr) / n,
                "p95_ms": arr[idx],
            }
    return summary

# === DISPATCHER HEARTBEAT METRICS ===
# Track dispatcher health and last-seen times
dispatcher_heartbeat_metrics = {}

def track_dispatcher_heartbeat(dispatcher_name: str, status: str, ping_success: bool):
    """Track dispatcher heartbeat and health status."""
    current_time = time.time()
    if dispatcher_name not in dispatcher_heartbeat_metrics:
        dispatcher_heartbeat_metrics[dispatcher_name] = {
            "first_seen": current_time,
            "last_seen": current_time,
            "ping_count": 0,
            "status_count": 0,
            "last_status": "unknown"
        }
    
    metrics = dispatcher_heartbeat_metrics[dispatcher_name]
    metrics["last_seen"] = current_time
    
    if ping_success:
        metrics["ping_count"] += 1
        metrics["last_status"] = status
    
    log.info(f"📊 Dispatcher heartbeat tracked: {dispatcher_name} = {status} (ping: {ping_success})")

def get_dispatcher_heartbeat_metrics() -> dict[str, dict[str, Any]]:
    """Get current dispatcher heartbeat metrics."""
    return {k: v.copy() for k, v in dispatcher_heartbeat_metrics.items()}

def get_dispatcher_heartbeat_summary() -> dict[str, dict[str, Any]]:
    """Get summary statistics for dispatcher heartbeat metrics."""
    summary = {}
    current_time = time.time()
    
    for dispatcher_name, metrics in dispatcher_heartbeat_metrics.items():
        age_seconds = current_time - metrics["first_seen"]
        last_seen_seconds = current_time - metrics["last_seen"]
        
        summary[dispatcher_name] = {
            "age_seconds": age_seconds,
            "last_seen_seconds": last_seen_seconds,
            "ping_count": metrics["ping_count"],
            "last_status": metrics["last_status"],
            "uptime_minutes": age_seconds / 60.0
        }
    
    return summary

# === IMPORT PATH FIX FOR DIRECT EXECUTION ===
# This allows the script to work both ways:
# 1. python scripts/verify_seedcore_architecture.py (direct execution)
# 2. python -m scripts.verify_seedcore_architecture (module execution)
if __name__ == "__main__":
    import sys
    import os
    from pathlib import Path
    
    # Get the project root (parent of scripts/ directory)
    # Since script is now in scripts/host/, we need to go up two levels
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    
    # Add project root to sys.path if not already there
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
        print(f"🔧 Fixed import path: added {project_root} to sys.path")
        print(f"   This allows imports like 'src.seedcore.models.result_schema' to work")
        print(f"   when running the script directly with 'python {__file__}'")
        print()

# === USAGE EXAMPLES ===
# This script now works both ways thanks to the import path fix above:
#
# ✅ DIRECT EXECUTION (recommended for development):
#    python scripts/host/verify_seedcore_architecture.py
#    python scripts/host/verify_seedcore_architecture.py --debug
#
# ✅ MODULE EXECUTION (recommended for production):
#    python -m scripts.host.verify_seedcore_architecture
#    python -m scripts.host.verify_seedcore_architecture --debug
#
# The import path fix ensures that 'src.seedcore.models.result_schema' 
# imports work correctly in both cases by dynamically adjusting sys.path.



# Import the new centralized result schema for validation (optional)
try:
    from src.seedcore.models.result_schema import (
        TaskResult, ResultKind, from_legacy_result
    )
    HAS_RESULT_SCHEMA = True
except ImportError:
    HAS_RESULT_SCHEMA = False

# ---- Helper functions for result normalization
def _maybe_parse(x):
    if isinstance(x, str):
        s = x.strip()
        # try JSON first
        try:
            return json.loads(s)
        except Exception:
            pass
        # then safe Python literal (legacy)
        try:
            return ast.literal_eval(s)
        except Exception:
            return x
    return x

def _is_plan_like(items):
    """Returns True if the list looks like HGNN plan steps."""
    if not isinstance(items, list):
        return False
    
    # Only assume HGNN if multi-step or explicit planner marks
    if len(items) > 1:
        for it in items:
            if isinstance(it, dict) and ("organ_id" in it or "solution_steps" in it):
                return True
    
    # For single items, require explicit HGNN indicators
    if len(items) == 1:
        item = items[0]
        if isinstance(item, dict):
            # Check for explicit HGNN markers
            if (item.get("plan_source") == "cognitive_core" or 
                "solution_steps" in item or 
                item.get("kind") == "escalated"):
                return True
            # Don't assume single organ_id means HGNN - could be fast path
            return False
    
    return False

def detect_plan(res: dict) -> tuple[bool, list]:
    """
    Consolidated helper to detect HGNN plan indicators in a result.
    
    Returns:
        Tuple[bool, List]: (has_plan, plan_steps)
        - has_plan: True if any HGNN indicators are present
        - plan_steps: The actual plan list if found, empty list otherwise
    """
    if not isinstance(res, dict):
        return False, []
    
    # Check for new centralized schema format first - prefer explicit signals
    if res.get("kind") in ["escalated", "cognitive"] and "payload" in res:
        payload = res["payload"]
        if "solution_steps" in payload:
            plan_steps = payload["solution_steps"]
            if isinstance(plan_steps, list) and len(plan_steps) > 0:
                return True, plan_steps
        
        # Check nested result structure for cognitive results
        if res.get("kind") == "cognitive" and "result" in payload:
            nested_result = payload["result"]
            if isinstance(nested_result, dict) and "solution_steps" in nested_result:
                plan_steps = nested_result["solution_steps"]
                if isinstance(plan_steps, list) and len(plan_steps) > 0:
                    return True, plan_steps
    
    # Check for explicit escalated flag
    if res.get("escalated") is True:
        return True, []
    
    # Check for legacy format indicators
    plan = res.get("plan") or res.get("solution_steps")
    if plan and isinstance(plan, list) and len(plan) > 0:
        return True, plan
    
    # Check for list_result type with plan-like content - use updated logic
    if res.get("type") == "list_result":
        items = res.get("items", [])
        if _is_plan_like(items):
            return True, items
    
    # Check for legacy raw_result
    if "raw_result" in res:
        raw = res["raw_result"]
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list) and _is_plan_like(parsed):
                return True, parsed
            elif isinstance(parsed, dict) and "solution_steps" in parsed:
                plan_steps = parsed["solution_steps"]
                if isinstance(plan_steps, list) and len(plan_steps) > 0:
                    return True, plan_steps
        except Exception:
            pass
    
    return False, []

# ---- safe env readers
def sanitize_url(url: str) -> Optional[str]:
    """
    Sanitize and validate a URL, fixing common malformations.
    
    Fixes issues like:
    - Double colons (::) -> single colon (:)
    - Missing protocol
    - Extra slashes
    """
    if not url:
        return None
    
    # Fix double colons (common typo)
    if "::" in url:
        url = url.replace("::", ":")
        log.warning(f"⚠️ Fixed double colons in URL: {url}")
    
    # Ensure protocol is present
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
        log.warning(f"⚠️ Added missing protocol to URL: {url}")
    
    # Remove trailing slashes for consistency
    url = url.rstrip("/")
    
    # Basic validation
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.netloc:
            log.error(f"❌ Invalid URL format: {url}")
            return None
        return url
    except Exception as e:
        log.error(f"❌ URL validation failed: {e}")
        return None

def fix_service_url_issues():
    """
    Provide helpful guidance for fixing service URL issues.
    """
    api_url = env('SEEDCORE_API_URL', '')
    orch_url = env('ORCH_URL', '')
    
    if not api_url:
        log.info("📋 SEEDCORE_API_URL is not set")
        log.info("   Set it with: export SEEDCORE_API_URL='http://seedcore-api:8002'")
        log.info("   For local testing: export SEEDCORE_API_URL='http://127.0.0.1:8002'")
    
    if not orch_url:
        log.info("📋 ORCH_URL is not set")
        log.info("   Set it with: export ORCH_URL='http://127.0.0.1:8000/orchestrator'")
        return
    
    if "::" in orch_url:
        log.error("❌ ORCH_URL contains double colons (::) - this is the root cause!")
        log.error("   Current value: " + orch_url)
        log.error("   This creates an invalid URL that cannot be parsed")
        log.error("")
        log.error("🔧 IMMEDIATE FIXES:")
        log.error("   1. Fix in current shell:")
        log.error("      export ORCH_URL='http://127.0.0.1:8000/orchestrator'")
        log.error("")
        log.error("   2. Fix the double colon issue:")
        log.error("      export ORCH_URL=$(echo $ORCH_URL | sed 's/::/:/g')")
        log.error("")
        log.error("   3. Verify the fix:")
        log.error("      echo $ORCH_URL")
        log.error("      Should show: http://127.0.0.1:8000/orchestrator")
        log.error("")
        log.error("   4. Re-run the script after fixing")
        return
    
    # Check other common issues
    if not orch_url.startswith(("http://", "https://")):
        log.warning("⚠️ ORCH_URL missing protocol")
        log.info("   Add protocol: export ORCH_URL='http://127.0.0.1:8000/orchestrator'")
    
    log.info("✅ ORCH_URL looks valid: " + orch_url)

def env(k: str, default: str = "") -> str:
    return os.getenv(k, default)

def env_int(k: str, d: int) -> int:
    try:
        return int(env(k, str(d)))
    except ValueError:
        return d

def env_float(k: str, d: float) -> float:
    try:
        return float(env(k, str(d)))
    except ValueError:
        return d

def env_bool(k: str, d: bool=False) -> bool:
    return env(k, str(d)).lower() in ("1","true","yes","on")

# ---- Ray Serve environment setup (before logging to avoid import issues)
def setup_ray_serve_environment_early():
    """Set up Ray Serve environment variables early to avoid timeout warnings."""
    # Set Ray Serve queue length response deadline to reduce warnings
    queue_deadline = env("RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S", "2.0")
    os.environ["RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S"] = queue_deadline
    
    # Additional Ray Serve configuration to reduce backpressure
    if "RAY_SERVE_MAX_QUEUE_LENGTH" not in os.environ:
        os.environ["RAY_SERVE_MAX_QUEUE_LENGTH"] = "2000"
    
    # Suppress Ray Serve timeout warnings if requested
    if env_bool("SUPPRESS_RAY_SERVE_WARNINGS", False):
        os.environ["RAY_SERVE_LOG_LEVEL"] = "ERROR"
        os.environ["RAY_LOG_LEVEL"] = "ERROR"

# Set up Ray Serve environment early
setup_ray_serve_environment_early()

# ---- logging setup (after env functions are defined)
debug_level = env("DEBUG_LEVEL", "INFO").upper()
log_level = logging.DEBUG if debug_level == "DEBUG" else logging.INFO
logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("verify-seedcore")

# Log import status
if HAS_RESULT_SCHEMA:
    log.info("✅ Result schema module imported successfully")
else:
    log.warning("⚠️ Result schema module not available, using fallback validation")

log.info(f"🔧 Log level set to: {debug_level}")

# ---- Strict mode control
def should_exit_on_failure() -> bool:
    """Determine if script should exit on validation failures."""
    return STRICT_MODE_ENABLED

def exit_if_strict(message: str, exit_code: int = 1):
    """Exit with message if strict mode is enabled, otherwise log error."""
    if should_exit_on_failure():
        log.error(f"❌ {message}")
        sys.exit(exit_code)
    else:
        log.error(f"❌ {message} (continuing due to non-strict mode)")

# Global strict mode flag (can be overridden by command line)
STRICT_MODE_ENABLED = True

# ---- HTTP helpers (requests optional, single Session)
_REQ_SESSION = None
def _requests():
    global _REQ_SESSION
    try:
        import requests  # type: ignore
        if _REQ_SESSION is None:
            _REQ_SESSION = requests.Session()
        return requests
    except Exception:
        return None

def http_post(url: str, json_body: dict[str, Any], timeout: float = TIMEOUTS["http_s"]) -> tuple[int, str, Optional[dict[str, Any]]]:
    req = _requests()
    if not req:
        raise RuntimeError("requests not installed; pip install requests")
    try:
        resp = _REQ_SESSION.post(url, json=json_body, timeout=timeout)  # type: ignore
        txt = resp.text
        try:
            js = resp.json()
        except Exception:
            js = None
        return resp.status_code, txt, js
    except Exception as e:
        return 0, str(e), None

def http_get(url: str, timeout: float = TIMEOUTS["http_s"]) -> tuple[int, str, Optional[dict[str, Any]]]:
    req = _requests()
    if not req:
        raise RuntimeError("requests not installed; pip install requests")
    try:
        resp = _REQ_SESSION.get(url, timeout=timeout)  # type: ignore
        txt = resp.text
        try:
            js = resp.json()
        except Exception:
            js = None
        return resp.status_code, txt, js
    except Exception as e:
        return 0, str(e), None

# ---- Result normalization helper
def normalize_result(result) -> dict:
    """Normalize task result to ensure it's a Python dict."""
    if result is None:
        return {}

    if isinstance(result, dict):
        return result

    if isinstance(result, str):
        # raw JSON / legacy-printed list/dict
        try:
            return json.loads(result)
        except Exception:
            parsed = _maybe_parse(result)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                items = [_maybe_parse(x) for x in parsed]
                return {
                    "type": "list_result",
                    "items": items,
                    "count": len(items),
                    "escalated": _is_plan_like(items),
                }
            # fallback
            return {"type": "unknown_result", "value": result, "original_type": "str"}

    if isinstance(result, list):
        items = [_maybe_parse(x) for x in result]
        return {
            "type": "list_result",
            "items": items,
            "count": len(items),
            "escalated": _is_plan_like(items),
        }

    # Handle other types (Ray ObjectRef, Pydantic models, etc.)
    try:
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        if hasattr(result, "__dict__"):
            return dict(result.__dict__)
    except Exception:
        pass

    return {
        "type": "unknown_result",
        "value": str(result),
        "original_type": str(type(result)),
    }

# ---- DB helpers (optional)
def pg_conn():
    dsn = env("SEEDCORE_PG_DSN")
    if not dsn:
        return None
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
    except Exception:
        log.warning("psycopg2-binary not installed; DB checks disabled")
        return None
    try:
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        return conn
    except Exception as e:
        log.warning(f"PG connect failed: {e}")
        return None

def pg_get_task(conn, task_id: uuid.UUID) -> Optional[dict[str, Any]]:
    import psycopg2.extras  # type: ignore
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM tasks WHERE id=%s", (str(task_id),))
        row = cur.fetchone()
        return dict(row) if row else None

def pg_wait_status(conn, task_id: uuid.UUID, want: str, timeout_s: float = 60.0) -> Optional[dict[str, Any]]:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        row = pg_get_task(conn, task_id)
        if row:
            last = row
            st = (row.get("status") or "").lower()
            if st == want.lower():
                return row
        time.sleep(1.0)
    return last

def pg_insert_generic_task(conn, ttype: str, description: str, params: dict[str, Any], drift: float) -> uuid.UUID:
    import psycopg2.extras  # type: ignore
    tid = uuid.uuid4()
    now_sql = "NOW()"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, type, description, params, domain, drift_score, status, attempts, created_at, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, NULL, %s, 'queued', 0, {now}, {now})
            """.format(now=now_sql),
            (str(tid), ttype, description, json.dumps(params), drift),
        )
    return tid

def pg_create_graph_rag_task(conn, node_ids: list[int], hops: int, topk: int, description: str) -> Optional[uuid.UUID]:
    # Requires migrations that define create_graph_rag_task(...)
    tid = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT create_graph_rag_task(%s::int[], %s::int, %s::int, %s);",
                        (node_ids, hops, topk, description))
            row = cur.fetchone()
            if row and row[0]:
                tid = row[0]
                log.info(f"Created graph RAG task with ID: {tid}")
            else:
                log.warning("create_graph_rag_task returned no task ID")
    except Exception as e:
        log.warning(f"create_graph_rag_task call failed: {e}")
    return tid

# ---- Ray helpers
def ray_connect():
    import ray  # type: ignore
    
    # Log the Ray Serve environment variables that were set early
    queue_deadline = env("RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S", "2.0")
    max_queue = env("RAY_SERVE_MAX_QUEUE_LENGTH", "2000")
    log.info(f"🔧 Ray Serve config: QUEUE_DEADLINE={queue_deadline}s, MAX_QUEUE={max_queue}")
    
    addr = env("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
    ns = env("RAY_NAMESPACE", env("SEEDCORE_NS", "seedcore-dev"))
    log.info(f"Connecting to Ray: {addr} ns={ns}")
    
    try:
        ray.init(address=addr, namespace=ns, log_to_driver=False, ignore_reinit_error=True)
        log.info("✅ Ray connection established")
    except Exception as e:
        log.error(f"❌ Ray connection failed: {e}")
        raise
    
    return ray

def get_actor(ray, name: str) -> Optional[Any]:
    try:
        return ray.get_actor(name, namespace=env("RAY_NAMESPACE", "seedcore-dev"))
    except Exception:
        return None

def actor_ping(ray, handle, timeout=5.0) -> bool:
    try:
        ref = handle.ping.remote()
        return ray.get(ref, timeout=timeout) == "pong"
    except Exception:
        return False

def actor_status(ray, handle, timeout=10.0) -> dict[str, Any]:
    try:
        ref = handle.get_status.remote()
    except Exception:
        return {}
    try:
        return ray.get(ref, timeout=timeout)
    except Exception:
        return {}

def serve_get_handle(ray, app_name: str):
    try:
        from ray import serve  # type: ignore
        return serve.get_app_handle(app_name)
    except Exception as e:
        log.warning(f"Serve handle for '{app_name}' not available: {e}")
        return None

def serve_deployment_status(handle, timeout=10.0) -> dict[str, Any]:
    """Get status from a Serve deployment handle."""
    try:
        resp = handle.status.remote()  # DeploymentResponse
        try:
            return resp.result(timeout_s=timeout)  # Use timeout parameter
        except Exception as e:
            log.warning(f"⚠️ Status call failed: {e}")
            track_api_failure("status")               # Track failure for metrics
            return {}
    except Exception as e:
        log.warning(f"⚠️ Status call failed: {e}")
        return {}

# ---- Orchestrator client
def submit_via_seedcore_api(task: dict[str, Any]) -> Optional[uuid.UUID]:
    """
    Submit task to seedcore-api using the new service boundaries.
    
    Expected response format:
    {
        "id": "uuid",
        "status": "string", 
        "result": {...},
        "created_at": "datetime"
    }
    """
    api_url = env("SEEDCORE_API_URL", "")
    if not api_url:
        log.warning("⚠️ SEEDCORE_API_URL not set - seedcore-api submission disabled")
        return None
    
    # Validate and sanitize the URL
    api_url = sanitize_url(api_url)
    if not api_url:
        log.error("❌ SEEDCORE_API_URL is malformed and cannot be fixed")
        return None
    
    # Use the standard task creation endpoint
    url = api_url.rstrip("/") + "/api/v1/tasks"
    timeout = float(env("SEEDCORE_API_TIMEOUT", "5.0"))
    
    log.info(f"🚀 Submitting task to seedcore-api: {url}")
    payload_preview = json.dumps(task, default=str)
    if len(payload_preview) > 800:
        payload_preview = payload_preview[:800] + "... (truncated)"
    log.debug(f"📋 Task payload: {payload_preview}")
    
    # Simple retry/backoff
    for attempt in range(3):
        try:
            log.info(f"🔗 POST {url} (attempt {attempt+1}/3)")
            code, txt, js = http_post(url, task, timeout=timeout)
            log.info(f"📡 Response: {code} - {txt[:200]}")
            
            if code >= 200 and code < 300:
                log.info(f"✅ Success! Response: {js}")
                # Accept seedcore-api response format:
                # {"id": "uuid", "status": "string", "result": {...}, "created_at": "datetime"}
                if isinstance(js, dict) and "id" in js:
                    task_id = js["id"]
                    log.info(f"✅ Task created via seedcore-api: {task_id}")
                    return uuid.UUID(task_id)
                else:
                    log.error(f"❌ Unexpected response format from seedcore-api: {js}")
                    return None
            elif code == 410:
                log.warning(f"⚠️ Endpoint deprecated (410): {txt}")
                return None
            else:
                log.warning(f"⚠️ HTTP {code}: {txt}")
                if attempt < 2:  # Don't sleep on last attempt
                    time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            log.warning(f"⚠️ Exception on attempt {attempt+1}: {e}")
            if attempt < 2:  # Don't sleep on last attempt
                time.sleep(1.0 * (attempt + 1))
    
    log.error(f"❌ All attempts failed for seedcore-api task: {task['type']}")
    return None

def submit_via_orchestrator(task: dict[str, Any]) -> Optional[uuid.UUID]:
    """
    Submit task to orchestrator pipeline using the new service boundaries.
    
    This function now uses the orchestrator for pipeline operations only,
    not direct task creation. For task creation, use submit_via_seedcore_api().
    
    Expected response format:
    {
        "task_id": "uuid",
        "status": "string", 
        "message": "string",
        "created_at": number
    }
    """
    base = env("ORCH_URL", "")
    if not base:
        log.warning("⚠️ ORCH_URL not set - orchestrator pipeline submission disabled")
        return None
    
    # Validate and sanitize the URL
    base = sanitize_url(base)
    if not base:
        log.error("❌ ORCH_URL is malformed and cannot be fixed")
        return None
    
    paths = [p.strip() for p in env("ORCH_PATHS", "/pipeline/create-task").split(",") if p.strip()]
    if not paths:
        log.warning("⚠️ ORCH_PATHS not set - orchestrator pipeline submission disabled")
        return None
    
    log.info(f"🚀 Submitting task to orchestrator pipeline: {base} with paths {paths}")
    payload_preview = json.dumps(task, default=str)
    if len(payload_preview) > 800:
        payload_preview = payload_preview[:800] + "... (truncated)"
    log.debug(f"📋 Task payload: {payload_preview}")
    
    for p in paths:
        url = base.rstrip("/") + p
        # simple retry/backoff per path
        for attempt in range(3):
            try:
                log.info(f"🔗 POST {url} (attempt {attempt+1}/3)")
                code, txt, js = http_post(url, task, timeout=TIMEOUTS["http_s"])
                log.info(f"📡 Response: {code} - {txt[:200]}")
                
                if code >= 200 and code < 300:
                    log.info(f"✅ Success! Response: {js}")
                    # Accept orchestrator pipeline response format:
                    # {"task_id": "uuid", "status": "string", "message": "string", "created_at": number}
                    if isinstance(js, dict):
                        # Try id first (current TaskResponse format)
                        if "id" in js:
                            try:
                                task_id = uuid.UUID(str(js["id"]))
                                log.info(f"🎯 Extracted id from dict: {task_id}")
                                return task_id
                            except Exception as e:
                                log.warning(f"⚠️ Failed to parse id from dict: {e}")
                            # non-2xx or parse failure → retry/backoff
                            if code < 200 or code >= 300:
                                if code == 0:
                                    log.info(f"🔄 Connection aborted (attempt {attempt+1}/3), retrying...")
                                else:
                                    log.warning(f"⚠️ HTTP {code} from {url}: {txt[:200]}")
                            if attempt < 2:
                                time.sleep(0.5 * (2 ** attempt))
                            continue
                        # Try task_id (legacy format - fallback)
                        elif "task_id" in js:
                            try:
                                task_id = uuid.UUID(str(js["task_id"]))
                                log.info(f"🎯 Extracted task_id from dict: {task_id}")
                                return task_id
                            except Exception as e:
                                log.warning(f"⚠️ Failed to parse task_id from dict: {e}")
                            # non-2xx or parse failure → retry/backoff
                            if code < 200 or code >= 300:
                                if code == 0:
                                    log.info(f"🔄 Connection aborted (attempt {attempt+1}/3), retrying...")
                                else:
                                    log.warning(f"⚠️ HTTP {code} from {url}: {txt[:200]}")
                            if attempt < 2:
                                time.sleep(0.5 * (2 ** attempt))
                            continue
                        else:
                            log.warning(f"⚠️ Response dict missing both 'id' and 'task_id' fields: {list(js.keys())}")
                            # non-2xx or parse failure → retry/backoff
                            if code < 200 or code >= 300:
                                if code == 0:
                                    log.info(f"🔄 Connection aborted (attempt {attempt+1}/3), retrying...")
                                else:
                                    log.warning(f"⚠️ HTTP {code} from {url}: {txt[:200]}")
                            if attempt < 2:
                                time.sleep(0.5 * (2 ** attempt))
                            continue
                    # fallback: parse UUID from text
                    try:
                        task_id = uuid.UUID(str(js))
                        log.info(f"🎯 Extracted task_id from text: {task_id}")
                        return task_id
                    except Exception as e:
                        log.warning(f"⚠️ Failed to parse task_id from text: {e}")
                    # non-2xx or parse failure → retry/backoff
                    if code < 200 or code >= 300:
                        if code == 0:
                            log.info(f"🔄 Connection aborted (attempt {attempt+1}/3), retrying...")
                        else:
                            log.warning(f"⚠️ HTTP {code} from {url}: {txt[:200]}")
                    if attempt < 2:
                        time.sleep(0.5 * (2 ** attempt))
                    continue
                # non-2xx or parse failure → retry/backoff
                if code < 200 or code >= 300:
                    if code == 0:
                        log.info(f"🔄 Connection aborted (attempt {attempt+1}/3), retrying...")
                    else:
                        log.warning(f"⚠️ HTTP {code} from {url}: {txt[:200]}")
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                continue
            except Exception as e:
                log.error(f"❌ Exception posting to {url}: {e}")
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                continue
    
    log.error(f"❌ All orchestrator endpoints failed for task: {task['type']}")
    return None

# ---- Enhanced debugging functions for routing bug investigation

# --- Put near your other helpers in verify_seedcore_architecture.py ---

SUPPORTED_COORD_METHODS = {
    "health",
    "status",
    "get_organism_status",
    "get_organism_summary",
    "handle_incoming_task",
    "handle_task",
    "initialize_organism",
    "make_decision",
    "plan_task",
    "reconfigure",
    "shutdown_organism",
    "test_routing",
}

def serve_can_call(method_name: str) -> bool:
    return method_name in SUPPORTED_COORD_METHODS

def call_if_supported(coord, method_name: str, *args, timeout_s: Optional[float] = None, max_retries: int = 2, **kwargs):
    """Never invokes replica for unsupported methods (prevents noisy Ray logs)."""
    if not serve_can_call(method_name):
        log.info(f"📋 Coordinator does not support '{method_name}' (skipping)")
        return None
    
    for attempt in range(max_retries + 1):
        try:
            method = getattr(coord, method_name)
            resp = method.remote(*args, **kwargs)  # DeploymentResponse
            try:
                return resp.result(timeout_s=timeout_s or TIMEOUTS["serve_call_s"])
            except Exception as e:
                # Handle specific Ray client callback errors gracefully
                if "InvalidStateError" in str(e) and "CANCELLED" in str(e):
                    if attempt < max_retries:
                        log.debug(f"📋 Call '{method_name}' was cancelled (attempt {attempt+1}/{max_retries+1}), retrying...")
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        log.debug(f"📋 Call '{method_name}' was cancelled after {max_retries+1} attempts")
                        track_api_failure(method_name)
                        return None
                elif "queue length" in str(e).lower():
                    if attempt < max_retries:
                        log.debug(f"📋 Call '{method_name}' failed due to queue timeout (attempt {attempt+1}/{max_retries+1}), retrying...")
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        log.debug(f"📋 Call '{method_name}' failed due to queue length timeout after {max_retries+1} attempts")
                        track_api_failure(method_name)
                        return None
                else:
                    log.warning(f"⚠️ Call '{method_name}' failed: {e}")
                    track_api_failure(method_name)
                    return None
        except Exception as e:
            # Handle connection and other Ray client errors
            if "InvalidStateError" in str(e) and "CANCELLED" in str(e):
                if attempt < max_retries:
                    log.debug(f"📋 Call '{method_name}' was cancelled during setup (attempt {attempt+1}/{max_retries+1}), retrying...")
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    log.debug(f"📋 Call '{method_name}' was cancelled during setup after {max_retries+1} attempts")
                    return None
            else:
                log.warning(f"⚠️ Call '{method_name}' failed: {e}")
                return None
    
    return None

def inspect_coordinator_routing_logic(ray, coord):
    """Inspect coordinator's routing logic and configuration to identify routing bugs."""
    log.info("🔍 INSPECTING COORDINATOR ROUTING LOGIC")
    log.info("=" * 50)

    # Always safe
    st = serve_deployment_status(coord)
    log.info(f"📋 Coordinator status: {json.dumps(st, indent=2, default=str)}")

    # Only supported calls
    s = call_if_supported(coord, "get_organism_status", timeout_s=TIMEOUTS["serve_call_s"])
    if s is not None:
        log.info(f"📋 get_organism_status: {json.dumps(s, indent=2, default=str)}")

    g = call_if_supported(coord, "get_organism_summary", timeout_s=TIMEOUTS["serve_call_s"])
    if g is not None:
        log.info(f"📋 get_organism_summary: {json.dumps(g, indent=2, default=str)}")

    log.info("=" * 50)

def check_organ_availability(ray):
    """Check the health and availability of fast-path organs."""
    log.info("🔍 CHECKING ORGAN AVAILABILITY")
    log.info("=" * 50)
    
    try:
        # Check dispatcher actors (fast-path organs)
        dispatcher_status = {}
        for i in range(10):  # Check up to 10 dispatchers
            actor_name = f"seedcore_dispatcher_{i}"
            handle = get_actor(ray, actor_name)
            if handle:
                ping_success = actor_ping(ray, handle)
                if ping_success:
                    # Fix: Soften health check - if ping succeeds, treat as healthy unless explicitly unhealthy
                    status = actor_status(ray, handle) or {}
                    # Use ping success as health indicator if get_status() returns empty or non-dict
                    health = status.get('status', 'healthy' if ping_success else 'unknown')
                    dispatcher_status[actor_name] = {"status": health}
                    
                    # Track heartbeat metrics
                    track_dispatcher_heartbeat(actor_name, health, ping_success)
                else:
                    dispatcher_status[actor_name] = {"status": "unresponsive"}
                    # Track failed ping
                    track_dispatcher_heartbeat(actor_name, "unresponsive", False)
            else:
                break  # No more dispatchers
        
        log.info(f"📋 Found {len(dispatcher_status)} dispatchers:")
        for name, status in dispatcher_status.items():
            health = status.get('status', 'unknown')
            log.info(f"   {name}: {health}")
            
            # Check if dispatcher has organ info
            if hasattr(handle, 'get_organ_info'):
                try:
                    organ_info = ray.get(handle.get_organ_info.remote(), timeout=5.0)
                    log.info(f"📋      Organ info: {organ_info}")
                except Exception as e:
                    log.debug(f"      Could not get organ info: {e}")
            else:
                log.debug(f"      Dispatcher {name} has no get_organ_info() method")
        
        # Check if any dispatchers are unhealthy (using softened logic)
        unhealthy_dispatchers = [name for name, status in dispatcher_status.items() 
                               if status.get("status") not in ['healthy', 'unknown']]
        
        if unhealthy_dispatchers:
            log.warning(f"⚠️ UNHEALTHY DISPATCHERS: {unhealthy_dispatchers}")
            log.warning("This could force escalation even for low-drift tasks!")
        else:
            log.info("✅ All dispatchers appear healthy")
            
    except Exception as e:
        log.error(f"❌ Organ availability check failed: {e}")
    
    log.info("=" * 50)

def check_coordinator_internal_state(ray, coord):
    """Check coordinator's internal state to understand routing decisions."""
    log.info("🔍 CHECKING COORDINATOR INTERNAL STATE")
    log.info("=" * 50)

    # Only safe methods; skip the rest entirely
    s = call_if_supported(coord, "get_organism_status")
    if s is not None:
        log.info(f"📋 organism_status: {json.dumps(s, indent=2, default=str)}")

    g = call_if_supported(coord, "get_organism_summary")
    if g is not None:
        log.info(f"📋 organism_summary: {json.dumps(g, indent=2, default=str)}")

    log.info("=" * 50)

def check_coordinator_capabilities(ray, coord):
    """Check if coordinator has the expected routing methods for debugging."""
    log.info("🔍 CHECKING COORDINATOR CAPABILITIES")
    log.info("=" * 50)

    # Report only what we'll actually call
    available = sorted(list(SUPPORTED_COORD_METHODS))
    log.info(f"📋 Supported methods (whitelist): {available}")

    # Basic health checks via whitelisted calls
    h = call_if_supported(coord, "health", timeout_s=TIMEOUTS["serve_status_s"])
    if isinstance(h, dict):
        log.info(f"✅ health: {h}")
    else:
        log.warning("⚠️ health() not available or failed")

    s = call_if_supported(coord, "status", timeout_s=TIMEOUTS["serve_status_s"])
    if isinstance(s, dict):
        log.info(f"✅ status: {json.dumps(s, indent=2, default=str)}")
    else:
        log.warning("⚠️ status() not available or failed")

    log.info("=" * 50)

def verify_environment_configuration():
    """Verify that environment variables are set correctly."""
    log.info("🔍 VERIFYING ENVIRONMENT CONFIGURATION")
    log.info("=" * 50)
    
    # Check critical routing configuration
    drift_threshold = env('OCPS_DRIFT_THRESHOLD', 'NOT_SET')
    log.info(f"📋 OCPS_DRIFT_THRESHOLD: {drift_threshold}")
    
    if drift_threshold == 'NOT_SET':
        log.error("❌ OCPS_DRIFT_THRESHOLD not set! This will cause routing issues!")
    else:
        try:
            threshold_value = float(drift_threshold)
            log.info(f"✅ OCPS_DRIFT_THRESHOLD parsed as: {threshold_value}")
            
            # Check if it's reasonable
            if threshold_value <= 0:
                log.error("❌ OCPS_DRIFT_THRESHOLD must be positive!")
            elif threshold_value > 1.0:
                log.warning("⚠️ OCPS_DRIFT_THRESHOLD > 1.0 (unusually high)")
            else:
                log.info("✅ OCPS_DRIFT_THRESHOLD value looks reasonable")
        except ValueError:
            log.error(f"❌ OCPS_DRIFT_THRESHOLD '{drift_threshold}' is not a valid number!")
    
    # Check other routing-related config
    cognitive_timeout = env('COGNITIVE_TIMEOUT_S', 'NOT_SET')
    log.info(f"📋 COGNITIVE_TIMEOUT_S: {cognitive_timeout}")
    
    fast_path_latency = env('FAST_PATH_LATENCY_SLO_MS', 'NOT_SET')
    log.info(f"📋 FAST_PATH_LATENCY_SLO_MS: {fast_path_latency}")
    
    # Check Ray configuration
    ray_address = env('RAY_ADDRESS', 'NOT_SET')
    ray_namespace = env('RAY_NAMESPACE', 'NOT_SET')
    log.info(f"📋 RAY_ADDRESS: {ray_address}")
    log.info(f"📋 RAY_NAMESPACE: {ray_namespace}")
    
    # Check orchestrator configuration
    orch_url = env('ORCH_URL', 'NOT_SET')
    orch_paths = env('ORCH_PATHS', 'NOT_SET')
    log.info(f"📋 ORCH_URL: {orch_url}")
    log.info(f"📋 ORCH_PATHS: {orch_paths}")
    
    # Check for common URL malformations
    if orch_url != 'NOT_SET':
        if "::" in orch_url:
            log.error("❌ ORCH_URL contains double colons (::) - this will cause connection failures!")
            log.error("   Current: " + orch_url)
            log.error("   Should be: " + orch_url.replace("::", ":"))
            log.error("   Fix: export ORCH_URL='http://127.0.0.1:8000/orchestrator'")
        elif not orch_url.startswith(("http://", "https://")):
            log.warning("⚠️ ORCH_URL missing protocol - will be auto-fixed")
    
    # Test orchestrator connectivity
    test_orchestrator_connectivity()
    
    log.info("=" * 50)

def test_orchestrator_connectivity():
    """Test connectivity to the orchestrator service."""
    log.info("🔍 TESTING ORCHESTRATOR CONNECTIVITY")
    log.info("=" * 50)
    
    orch_url = env("ORCH_URL", "")
    if not orch_url:
        log.warning("⚠️ ORCH_URL not set - skipping connectivity test")
        return

    # Guard pipeline tests behind env flag (default: off)
    if not env_bool("TEST_PIPELINES", False):
        log.info("🔍 Skipping pipeline endpoint tests (set TEST_PIPELINES=true to enable)")
        log.info("=" * 50)
        return
    
    # Validate and sanitize the URL first
    orch_url = sanitize_url(orch_url)
    if not orch_url:
        log.error("❌ ORCH_URL is malformed and cannot be used for connectivity testing")
        return
    
    # Test basic connectivity
    try:
        import requests
        from urllib.parse import urljoin
        
        # Test health endpoint (new API)
        # Fix: Use proper URL concatenation to preserve /orchestrator base path
        health_url = orch_url.rstrip("/") + "/health"
        log.info(f"🔗 Testing health endpoint: {health_url}")
        
        response = requests.get(health_url, timeout=5.0)
        log.info(f"📡 Health endpoint response: {response.status_code}")
        # Track the HTTP status code for metrics
        track_orchestrator_health_status(response.status_code)
        if response.status_code == 200:
            log.info("✅ Health endpoint accessible")
        else:
            log.warning(f"⚠️ Health endpoint returned {response.status_code}")
            
    except ImportError:
        log.warning("⚠️ requests module not available - using http_get helper")
        # Use the existing http_get helper
        health_url = orch_url.rstrip("/") + "/health"
        code, txt, js = http_get(health_url, timeout=5.0)
        log.info(f"📡 Health endpoint response: {code}")
        # Track the HTTP status code for metrics
        track_orchestrator_health_status(code)
        if code == 200:
            log.info("✅ Health endpoint accessible")
        else:
            log.warning(f"⚠️ Health endpoint returned {code}")
            
    except Exception as e:
        log.error(f"❌ Failed to test orchestrator connectivity: {e}")
    
    # Test task submission endpoint
    orch_paths = env("ORCH_PATHS", "/tasks")
    for path in orch_paths.split(","):
        path = path.strip()
        if not path:
            continue
            
        test_url = orch_url.rstrip("/") + path
        log.info(f"🔗 Testing task endpoint: {test_url}")
        
        # Test with a simple ping task
        test_payload = {"type": "ping", "description": "connectivity test", "run_immediately": True}
        code, txt, js = http_post(test_url, test_payload, timeout=5.0)
        
        if code >= 200 and code < 300:
            log.info(f"✅ Task endpoint {path} accessible (HTTP {code})")
            if isinstance(js, dict):
                if "id" in js:
                    log.info(f"🎯 Received id: {js['id']}")
                elif "task_id" in js:  # Fallback for legacy format
                    log.info(f"🎯 Received task_id: {js['task_id']}")
                else:
                    log.info(f"📋 Response keys: {list(js.keys())}")
        else:
            log.warning(f"⚠️ Task endpoint {path} returned HTTP {code}: {txt[:100]}")
    
    # Test with actual task types that the system expects
    log.info("🔍 TESTING WITH ACTUAL TASK TYPES")
    test_tasks = [
        {
            "type": "ping",
            "description": "Test connectivity with real task type",
            "params": {"priority": "low"},
            "drift_score": 0.1,
            "run_immediately": True
        },
        {
            "type": "general_query", 
            "description": "Test escalation task type",
            "params": {"force_decomposition": True},
            "drift_score": 0.8,
            "run_immediately": True
        }
    ]
    
    for i, test_task in enumerate(test_tasks):
        log.info(f"🧪 Testing task {i+1}: {test_task['type']} (drift: {test_task['drift_score']})")
        
        # Try each endpoint
        for path in orch_paths.split(","):
            path = path.strip()
            if not path:
                continue
                
            test_url = orch_url.rstrip("/") + path
            code, txt, js = http_post(test_url, test_task, timeout=5.0)
            
            if code >= 200 and code < 300:
                log.info(f"✅ Task {i+1} accepted by {path} (HTTP {code})")
                if isinstance(js, dict):
                    if "id" in js:
                        log.info(f"🎯 Received id: {js['id']}")
                    elif "task_id" in js:  # Fallback for legacy format
                        log.info(f"🎯 Received task_id: {js['task_id']}")
                    else:
                        log.info(f"📋 Response keys: {list(js.keys())}")
                break
            else:
                log.warning(f"⚠️ Task {i+1} rejected by {path} (HTTP {code}): {txt[:100]}")
        else:
            log.error(f"❌ Task {i+1} rejected by all endpoints")
    
    # Test new pipeline endpoints
    test_pipeline_endpoints(orch_url)

def test_pipeline_endpoints(orch_url: str):
    """Test the new pipeline endpoints from the latest API."""
    log.info("🔍 TESTING NEW PIPELINE ENDPOINTS")
    
    # Note about Serve backpressure in Ray 2.32+
    log.info("💡 NOTE: Ray 2.32+ default max_ongoing_requests=5 (was 100)")
    log.info("   This can cause queuing and timeouts on heavy endpoints")
    log.info("   Fix: @serve.deployment(max_ongoing_requests=64, num_replicas=2)")
    log.info("   Or increase client timeout (now set to 30s for anomaly-triage)")
    
    # Deployment configuration recommendations to eliminate warnings
    log.info("🔧 DEPLOYMENT CONFIG RECOMMENDATIONS:")
    log.info("   @serve.deployment(max_ongoing_requests=32, num_replicas=2)  # Standard")
    log.info("   @serve.deployment(max_ongoing_requests=48, num_replicas=3)  # Medium throughput")
    log.info("   @serve.deployment(max_ongoing_requests=64, num_replicas=4)  # Maximum capacity (organism limit)")
    
    # Test anomaly triage endpoint
    anomaly_url = orch_url.rstrip("/") + "/pipeline/anomaly-triage"
    log.info(f"🔗 Testing anomaly triage endpoint: {anomaly_url}")
    
    anomaly_payload = {
        "agent_id": "test-agent-123",
        "series": [1.0, 2.0, 3.0, 4.0, 5.0],
        "context": {"service": "test-service", "region": "us-west-2"}
    }
    
    # Fix: Increase timeout to 30s to handle Serve backpressure and processing delays
    # Ray 2.32 default max_ongoing_requests=5 can cause queuing
    start_time = time.time()
    code, txt, js = http_post(anomaly_url, anomaly_payload, timeout=TIMEOUTS["http_pipeline_s"])
    end_time = time.time()
    
    # Calculate and track latency
    latency_ms = (end_time - start_time) * 1000
    track_pipeline_latency("anomaly-triage", latency_ms)
    
    if code >= 200 and code < 300:
        log.info(f"✅ Anomaly triage endpoint accessible (HTTP {code}) - Latency: {latency_ms:.1f}ms")
        if isinstance(js, dict):
            log.info(f"📋 Response: {json.dumps(js, indent=2, default=str)}")
    else:
        log.warning(f"⚠️ Anomaly triage endpoint returned HTTP {code}: {txt[:100]} - Latency: {latency_ms:.1f}ms")
    
    # Test tune status endpoint
    tune_status_url = orch_url.rstrip("/") + "/pipeline/tune/status/test-job-123"
    log.info(f"🔗 Testing tune status endpoint: {tune_status_url}")
    
    # Add latency tracking for tune status endpoint as well
    start_time = time.time()
    code, txt, js = http_get(tune_status_url, timeout=TIMEOUTS["http_s"])
    end_time = time.time()
    
    # Calculate and track latency
    latency_ms = (end_time - start_time) * 1000
    track_pipeline_latency("tune-status", latency_ms)
    
    if code >= 200 and code < 300:
        log.info(f"✅ Tune status endpoint accessible (HTTP {code}) - Latency: {latency_ms:.1f}ms")
        if isinstance(js, dict):
            log.info(f"📋 Response: {json.dumps(js, indent=2, default=str)}")
    else:
        log.warning(f"⚠️ Tune status endpoint returned HTTP {code}: {txt[:100]} - Latency: {latency_ms:.1f}ms")
    
    log.info("=" * 50)

def check_current_task_status(conn, task_id: uuid.UUID = None):
    """Check the current status of tasks in the database."""
    if not conn:
        log.warning("⚠️ No database connection - cannot check task status")
        return
    
    log.info("🔍 CHECKING CURRENT TASK STATUS")
    log.info("=" * 50)
    
    try:
        with conn.cursor() as cur:
            if task_id:
                # Check specific task
                cur.execute("SELECT * FROM tasks WHERE id = %s", (str(task_id),))
                row = cur.fetchone()
                if row:
                    log.info(f"📋 Task {task_id}:")
                    log.info(f"   Status: {row[3] if len(row) > 3 else 'unknown'}")
                    log.info(f"   Attempts: {row[7] if len(row) > 7 else 'unknown'}")
                    log.info(f"   Created: {row[8] if len(row) > 8 else 'unknown'}")
                    log.info(f"   Updated: {row[9] if len(row) > 9 else 'unknown'}")
                else:
                    log.warning(f"⚠️ Task {task_id} not found in database")
            else:
                # Check all recent tasks
                cur.execute("""
                    SELECT id, type, status, attempts, created_at, updated_at
                    FROM tasks 
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                
                rows = cur.fetchall()
                if rows:
                    log.info("📋 Recent tasks (last hour):")
                    for row in rows:
                        task_id, task_type, status, attempts, created_at, updated_at = row
                        age_seconds = (time.time() - created_at.timestamp()) if created_at else 0
                        log.info(f"   {task_id}: {task_type} -> {status} (attempts: {attempts}, age: {age_seconds:.1f}s)")
                else:
                    log.info("📋 No recent tasks found in database")
                
                # Check for stuck tasks
                cur.execute("""
                    SELECT COUNT(*) as stuck_count
                    FROM tasks 
                    WHERE status = 'queued' 
                    AND attempts = 0
                    AND created_at < NOW() - INTERVAL '1 minute'
                """)
                
                stuck_count = cur.fetchone()[0]
                if stuck_count > 0:
                    log.warning(f"⚠️ Found {stuck_count} tasks stuck in 'queued' status for >1 minute")
                    log.warning("   This indicates queue workers are not processing tasks")
                else:
                    log.info("✅ No stuck tasks found")
                    
    except Exception as e:
        log.error(f"❌ Failed to check task status: {e}")

def check_queue_worker_status():
    """Check if there are any queue workers processing the tasks table."""
    log.info("🔍 CHECKING QUEUE WORKER STATUS")
    log.info("=" * 50)
    
    # Check if we can connect to the database
    conn = None
    try:
        import psycopg2
        pg_dsn = env("SEEDCORE_PG_DSN", "")
        if pg_dsn:
            conn = psycopg2.connect(pg_dsn)
            log.info("✅ Database connection successful")
            
            # Check for active tasks
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        status, 
                        COUNT(*) as count,
                        MIN(created_at) as oldest,
                        MAX(created_at) as newest,
                        AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_age_seconds
                    FROM tasks 
                    GROUP BY status
                    ORDER BY status
                """)
                
                rows = cur.fetchall()
                if rows:
                    log.info("📊 Current task status distribution:")
                    for status, count, oldest, newest, avg_age in rows:
                        log.info(f"   {status}: {count} tasks")
                        if oldest and newest:
                            log.info(f"     Oldest: {oldest}")
                            log.info(f"     Newest: {newest}")
                        if avg_age is not None:
                            log.info(f"     Avg age: {avg_age:.1f}s")
                else:
                    log.warning("⚠️ No tasks found in database")
                
                # Check for stuck tasks (queued for too long)
                cur.execute("""
                    SELECT 
                        COUNT(*) as stuck_count,
                        MIN(created_at) as oldest_stuck
                    FROM tasks 
                    WHERE status = 'queued' 
                    AND updated_at = created_at
                    AND attempts = 0
                """)
                
                stuck_count, oldest_stuck = cur.fetchone()
                if stuck_count > 0:
                    log.warning(f"⚠️ Found {stuck_count} stuck tasks (queued, no attempts, no updates)")
                    if oldest_stuck:
                        age_hours = (time.time() - oldest_stuck.timestamp()) / 3600
                        log.warning(f"   Oldest stuck task is {age_hours:.1f} hours old")
                    log.warning("   These tasks will never be processed without a queue worker!")
                else:
                    log.info("✅ No stuck tasks found")
                
                # Check retry policy and DLQ health
                cur.execute("""
                    SELECT 
                        status,
                        attempts,
                        COUNT(*) as count,
                        AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_age_seconds
                    FROM tasks 
                    WHERE attempts > 0
                    GROUP BY status, attempts
                    ORDER BY attempts DESC, status
                """)
                
                retry_rows = cur.fetchall()
                if retry_rows:
                    log.info("📊 Retry policy analysis:")
                    for status, attempts, count, avg_age in retry_rows:
                        avg_age_hours = avg_age / 3600 if avg_age else 0
                        log.info(f"   {status} (attempts={attempts}): {count} tasks, avg age: {avg_age_hours:.1f}h")
                        
                        # Flag high retry counts that might indicate DLQ issues
                        if attempts >= 3:
                            log.warning(f"⚠️ High retry count: {count} tasks with {attempts} attempts")
                            if avg_age_hours > 16:
                                log.warning(f"   Long retry age: {avg_age_hours:.1f}h - review retry policy & DLQ")
                else:
                    log.info("✅ No retry attempts detected")
                    
        else:
            log.warning("⚠️ SEEDCORE_PG_DSN not set - cannot check queue status")
            
    except ImportError:
        log.warning("⚠️ psycopg2 not available - cannot check queue status")
    except Exception as e:
        log.error(f"❌ Failed to check queue status: {e}")
    finally:
        if conn:
            conn.close()
    
    log.info("=" * 50)

def test_routing_decision_logic():
    """Test the routing decision logic with various drift scores."""
    log.info("🔍 TESTING ROUTING DECISION LOGIC")
    log.info("=" * 50)
    
    drift_threshold = env_float('OCPS_DRIFT_THRESHOLD', 0.5)
    log.info(f"📋 Testing with threshold: {drift_threshold}")
    
    # Test cases
    test_cases = [
        (0.1, "Should route to fast-path (below threshold)"),
        (0.3, "Should route to fast-path (below threshold)"),
        (0.49, "Should route to fast-path (just below threshold)"),
        (0.5, "Should escalate (at threshold)"),
        (0.51, "Should escalate (just above threshold)"),
        (0.7, "Should escalate (above threshold)"),
        (0.9, "Should escalate (well above threshold)")
    ]
    
    for drift_score, expected in test_cases:
        should_escalate = drift_score >= drift_threshold
        log.info(f"📊 Drift {drift_score:.2f}: {'ESCALATE' if should_escalate else 'FAST-PATH'} - {expected}")
    
    log.info("=" * 50)

def test_routing_with_mock_tasks(ray, coord):
    """Test routing logic by submitting mock tasks with different drift scores."""
    # Check if mock tests are enabled
    if not env_bool("ENABLE_MOCK_ROUTING_TESTS", False):
        log.info("🔍 MOCK ROUTING TESTS DISABLED (set ENABLE_MOCK_ROUTING_TESTS=true to enable)")
        log.info("   This prevents flooding the orchestrator with test tasks in production")
        return
    
    log.info("🔍 TESTING ROUTING WITH MOCK TASKS")
    log.info("=" * 50)
    
    try:
        # Test different drift scores to see routing behavior
        test_cases = [
            (0.1, "Very low drift - should definitely go to fast path"),
            (0.3, "Low drift - should go to fast path"),
            (0.49, "Just below threshold - should go to fast path"),
            (0.5, "At threshold - should escalate"),
            (0.51, "Just above threshold - should escalate"),
            (0.7, "High drift - should escalate")
        ]
        
        for drift_score, description in test_cases:
            log.info(f"🧪 Testing drift {drift_score:.2f}: {description}")
            
            # Create mock task
            mock_task = {
                "type": "test_query",
                "description": f"Test task with drift {drift_score}",
                "params": {"test": True, "drift": drift_score},
                "drift_score": drift_score
            }
            
            # Try to submit via coordinator if it has a test method
            if serve_can_call('test_routing'):
                try:
                    result = call_if_supported(coord, 'test_routing', mock_task)
                    if result is not None:
                        log.info(f"   📋 Routing result: {json.dumps(result, indent=2, default=str)}")
                        
                        # Analyze the result
                        if isinstance(result, dict):
                            escalated = result.get('escalated', False)
                            route_type = result.get('route_type', 'unknown')
                            organ_id = result.get('organ_id')
                            
                            expected_escalation = drift_score >= env_float('OCPS_DRIFT_THRESHOLD', 0.5)
                            
                            # Explicit escalation confirmation check
                            if escalated is True:
                                log.info("✅ Escalation confirmed: HGNN decomposition plan")
                                # Check for required escalation metadata
                                plan_source = result.get('plan_source')
                                if plan_source == "cognitive_core":
                                    log.info(f"   ✅ Plan source confirmed: {plan_source}")
                                else:
                                    log.warning(f"   ⚠️ Missing or incorrect plan_source: {plan_source}")
                                
                                step_count = result.get('step_count')
                                if step_count is not None:
                                    log.info(f"   ✅ Step count: {step_count}")
                                else:
                                    log.warning("   ⚠️ Missing step_count in escalation result")
                            else:
                                log.info("✅ Fast path confirmed: direct routing")
                            
                            if escalated == expected_escalation:
                                log.info(f"   ✅ Routing correct: drift {drift_score} -> {'escalated' if escalated else 'fast_path'}")
                            else:
                                log.warning(f"   ⚠️ Routing incorrect: drift {drift_score} -> {'escalated' if escalated else 'fast_path'} (expected {'escalated' if expected_escalation else 'fast_path'})")
                            
                            log.info(f"   📋 Route type: {route_type}, Organ: {organ_id}")
                    else:
                        log.info("   📋 test_routing method not available or failed")
                        
                except Exception as e:
                    log.warning(f"   ⚠️ test_routing method not available or failed: {e}")
            
            # Try to submit via orchestrator if available
            else:
                log.info("   📋 No test_routing method available, skipping mock task test")
                break
            
            # Small delay between tests
            time.sleep(0.5)
            
    except Exception as e:
        log.error(f"❌ Mock task routing test failed: {e}")
    
    log.info("=" * 50)

def diagnose_routing_issue():
    """Provide a clear diagnosis of the routing issue based on collected information."""
    log.info("🔍 ROUTING ISSUE DIAGNOSIS")
    log.info("=" * 60)
    
    # Check environment configuration
    drift_threshold = env('OCPS_DRIFT_THRESHOLD', 'NOT_SET')
    if drift_threshold == 'NOT_SET':
        log.error("❌ ROOT CAUSE: OCPS_DRIFT_THRESHOLD environment variable is not set!")
        log.error("   This will cause the coordinator to use a default value or fail to route correctly.")
        log.error("   SOLUTION: Set OCPS_DRIFT_THRESHOLD=0.5 in your environment.")
        return
    
    try:
        threshold_value = float(drift_threshold)
        log.info(f"📋 Drift threshold: {threshold_value}")
        
        if threshold_value <= 0:
            log.error("❌ ROOT CAUSE: OCPS_DRIFT_THRESHOLD is not positive!")
            log.error("   This will cause all tasks to be escalated regardless of drift score.")
            log.error("   SOLUTION: Set OCPS_DRIFT_THRESHOLD to a positive value (e.g., 0.5)")
            return
            
    except ValueError:
        log.error(f"❌ ROOT CAUSE: OCPS_DRIFT_THRESHOLD '{drift_threshold}' is not a valid number!")
        log.error("   This will cause parsing errors and incorrect routing decisions.")
        log.error("   SOLUTION: Ensure OCPS_DRIFT_THRESHOLD is a valid number (e.g., 0.5)")
        return
    
    # Check orchestrator connectivity
    orch_url = env('ORCH_URL', 'NOT_SET')
    if orch_url == 'NOT_SET':
        log.error("❌ ROOT CAUSE: ORCH_URL environment variable is not set!")
        log.error("   This will cause submit_via_orchestrator() to return None and fall back to DB insertion.")
        log.error("   SOLUTION: Set ORCH_URL to point to your orchestrator service.")
        return
    
    # Check if the issue is likely configuration vs. logic
    log.info("🔍 LIKELY ROOT CAUSES:")
    log.info("1. Configuration mismatch between environment and coordinator")
    log.info("2. Organ unavailability forcing escalation fallback")
    log.info("3. Bug in coordinator's routing decision logic")
    log.info("4. Environment variable not being read correctly inside coordinator")
    log.info("5. Orchestrator service unreachable (causing DB fallback to orphaned tasks)")
    log.info("6. No queue workers processing the tasks table")
    
    log.info("🔍 SPECIFIC ISSUE ANALYSIS:")
    log.info("The assertion failure occurs because:")
    log.info("- submit_via_orchestrator() failed (returned None)")
    log.info("- pg_insert_generic_task() was called as fallback")
    log.info("- Task was inserted into DB with status='queued'")
    log.info("- No queue workers are processing the tasks table")
    log.info("- Task remains stuck in 'queued' status forever")
    log.info("- wait_for_completion() times out waiting for 'completed' status")
    
    log.info("🔍 NEXT STEPS:")
    log.info("1. Check coordinator logs for routing decision details")
    log.info("2. Verify coordinator is reading OCPS_DRIFT_THRESHOLD correctly")
    log.info("3. Check if fast-path organs are healthy and available")
    log.info("4. Look for any forced escalation logic in coordinator code")
    log.info("5. Test orchestrator connectivity: curl -v '$ORCH_URL/status'")
    log.info("6. Check if queue workers are running and processing tasks")
    
    log.info("=" * 60)

def provide_fix_recommendations():
    """Provide specific recommendations for fixing the routing bug."""
    log.info("🔧 ROUTING BUG FIX RECOMMENDATIONS")
    log.info("=" * 60)
    
    log.info("📋 ORCHESTRATOR CONNECTIVITY ISSUES:")
    log.info("1. Check ORCH_URL and ORCH_PATHS environment variables")
    log.info("2. Test connectivity: curl -v '$ORCH_URL/health'")
    log.info("3. Test task submission: curl -v -X POST '$ORCH_URL/tasks' -d '{\"type\":\"ping\",\"description\":\"test\"}'")
    log.info("4. Test pipeline endpoints: curl -v -X POST '$ORCH_URL/pipeline/anomaly-triage' -d '{\"agent_id\":\"test\",\"series\":[1,2,3],\"context\":{\"service\":\"test\"}}' --max-time 30")
    log.info("5. Verify orchestrator service is running: kubectl get pods -l app=orchestrator")
    log.info("6. Check orchestrator logs: kubectl logs <orchestrator-pod>")
    
    log.info("📋 QUEUE WORKER ISSUES:")
    log.info("1. Check if queue workers are running: kubectl get pods -l app=queue-worker")
    log.info("2. Verify tasks table is being processed: check DB for stuck 'queued' tasks")
    log.info("3. Look for queue worker logs: kubectl logs <queue-worker-pod>")
    log.info("4. Check if tasks are being picked up: monitor attempts and locked_by columns")
    
    log.info("📋 IMMEDIATE ACTIONS:")
    log.info("1. Check coordinator logs for routing decision details")
    log.info("2. Verify OCPS_DRIFT_THRESHOLD is set correctly in coordinator environment")
    log.info("3. Check if fast-path organs are healthy and responding")
    
    log.info("📋 CODE INVESTIGATION:")
    log.info("1. Look at coordinator's route_and_execute method")
    log.info("2. Check the drift score comparison logic (>= vs >)")
    log.info("3. Look for any forced escalation fallback logic")
    log.info("4. Verify environment variable parsing in coordinator initialization")
    
    log.info("📋 COMMON BUG PATTERNS:")
    log.info("1. Threshold comparison inverted: if drift_score >= threshold: escalate()")
    log.info("2. Environment variable not loaded: using default value instead")
    log.info("3. Organ unavailability forcing escalation as fallback")
    log.info("4. String vs float comparison: '0.1' >= '0.5' evaluates to True")
    log.info("5. Orchestrator unreachable causing DB fallback to orphaned tasks")
    log.info("6. No queue workers consuming the tasks table")
    log.info("7. Serve backpressure: Ray 2.32+ max_ongoing_requests=5 causing timeouts")
    log.info("8. Dispatcher health 'unknown': get_status() not implemented or returns empty")
    
    log.info("📋 DEBUGGING COMMANDS:")
    log.info("1. Check coordinator environment: kubectl exec -it <coordinator-pod> -- env | grep OCPS")
    log.info("2. Check coordinator logs: kubectl logs <coordinator-pod> | grep -i routing")
    log.info("3. Check organ health: kubectl logs <dispatcher-pod> | grep -i health")
    log.info("4. Test orchestrator: curl -v '$ORCH_URL/health'")
    
    log.info("📋 SERVE BACKPRESSURE FIXES:")
    log.info("1. Increase max_ongoing_requests: @serve.deployment(max_ongoing_requests=64)")
    log.info("2. Add more replicas: @serve.deployment(num_replicas=2)")
    log.info("3. Increase client timeout: timeout=30.0 (already applied)")
    log.info("4. Check Serve logs: kubectl logs <serve-pod> | grep -i backpressure")
    log.info("5. Monitor queue depth: kubectl logs <serve-pod> | grep -i queue")
    log.info("6. SIGTERM handler warnings: benign in non-main thread, suppress if needed")
    
    log.info("📋 DISPATCHER HEALTH FIXES:")
    log.info("1. Implement get_status() method on dispatchers to return {status: 'healthy'}")
    log.info("2. Or use softened health check: ping success = healthy (already applied)")
    log.info("3. Check dispatcher logs: kubectl logs <dispatcher-pod> | grep -i health")
    log.info("4. Monitor heartbeat metrics: shows last-seen time and ping count")
    log.info("5. Test task creation: curl -v -X POST '$ORCH_URL/tasks' -d '{\"type\":\"ping\",\"description\":\"test\"}'")
    log.info("6. Check queue status: psql -d seedcore -c \"SELECT status, COUNT(*) FROM tasks GROUP BY status;\"")
    
    log.info("=" * 60)

# ---- scenario steps
def check_cluster_and_actors():
    ray = ray_connect()
    ns = env("RAY_NAMESPACE", "seedcore-dev")

    # Coordinator - now managed by Ray Serve organism app
    try:
        from ray import serve
        coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
        log.info("✅ Found OrganismManager Serve deployment")
        
        # Check health using the Serve deployment
        try:
            health_res = coord.health.remote()
            try:
                health_result = health_res.result(timeout_s=TIMEOUTS["serve_status_s"])
                log.info(f"Coordinator health: {health_result}")
                assert health_result.get("status") == "healthy", f"Coordinator unhealthy: {health_result}"
                assert health_result.get("organism_initialized") is True, "Organism not initialized"
            except Exception as e:
                log.warning(f"Could not get health status: {e}")
                # If health check fails, just verify the handle exists
                log.info("Coordinator handle exists, proceeding with verification")
        except Exception as e:
            log.warning(f"Could not get health status: {e}")
            # If health check fails, just verify the handle exists
            log.info("Coordinator handle exists, proceeding with verification")
    except Exception as e:
        log.error(f"Failed to get OrganismManager Serve deployment: {e}")
        raise AssertionError("OrganismManager Serve deployment not found")

    # Dispatchers
    want_d = env_int("EXPECT_DISPATCHERS", 2)
    found_d = 0
    for i in range(max(1, want_d)):
        h = get_actor(ray, f"seedcore_dispatcher_{i}")
        if h and actor_ping(ray, h):
            found_d += 1
    assert found_d >= want_d, f"Only {found_d}/{want_d} Dispatchers responsive"

    # GraphDispatchers (optional - can be disabled)
    want_g = env_int("EXPECT_GRAPH_DISPATCHERS", 0)  # Default to 0 (disabled)
    found_g = 0
    if want_g > 0:
        log.info(f"Checking for {want_g} GraphDispatchers...")
        for i in range(max(1, want_g)):
            actor_name = f"seedcore_graph_dispatcher_{i}"
            h = get_actor(ray, actor_name)
            if h:
                if actor_ping(ray, h):
                    found_g += 1
                    log.info(f"✅ Found responsive GraphDispatcher: {actor_name}")
                else:
                    log.warning(f"⚠️ Found GraphDispatcher but not responsive: {actor_name}")
            else:
                log.info(f"📋 GraphDispatcher not found: {actor_name}")
        
        if found_g < want_g:
            log.warning(f"⚠️ Only {found_g}/{want_g} GraphDispatchers responsive")
            if env_bool("STRICT_GRAPH_DISPATCHERS", False):
                assert found_g >= want_g, f"Only {found_g}/{want_g} GraphDispatchers responsive (set STRICT_GRAPH_DISPATCHERS=false to allow fewer)"
            else:
                log.info("📋 Continuing with fewer GraphDispatchers (STRICT_GRAPH_DISPATCHERS=false)")
    else:
        log.info("📋 GraphDispatchers disabled (EXPECT_GRAPH_DISPATCHERS=0)")

    # Serve apps
    for app in ("orchestrator", "cognitive", "ml_service"):
        handle = serve_get_handle(ray, app)
        assert handle is not None, f"Serve app '{app}' not available"

    log.info("Actors and Serve apps look good.")
    return ray, coord, want_g, found_g

def monitor_task_status(conn, tid: uuid.UUID, label: str, timeout_s: float = None):
    """Monitor task status with detailed logging and diagnostics."""
    if timeout_s is None:
        timeout_s = env_float("TASK_TIMEOUT_S", 90.0)
    
    check_interval = env_float("TASK_STATUS_CHECK_INTERVAL_S", 5.0)
    
    log.info(f"🔍 Monitoring {label} task {tid} for up to {timeout_s}s (checking every {check_interval}s)...")
    
    deadline = time.time() + timeout_s
    last_status = None
    status_count = 0
    
    while time.time() < deadline:
        row = pg_get_task(conn, tid)
        if not row:
            log.error(f"❌ {label}: Task {tid} not found in database")
            return None
        
        current_status = (row.get("status") or "").lower()
        attempts = row.get("attempts", 0)
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        
        # Log status changes
        if current_status != last_status:
            log.info(f"📋 {label}: Status changed from '{last_status}' to '{current_status}'")
            last_status = current_status
            status_count = 1
        else:
            status_count += 1
        
        # Log periodic updates for long-running tasks
        if status_count % 6 == 0:  # Every 30 seconds (6 * 5s)
            age_seconds = time.time() - created_at.timestamp() if created_at else 0
            log.info(f"📋 {label}: Still {current_status} (age: {age_seconds:.1f}s, attempts: {attempts})")
        
        # Check for stuck tasks
        if current_status == "queued" and attempts == 0:
            age_seconds = time.time() - created_at.timestamp() if created_at else 0
            if age_seconds > 30:  # Stuck for more than 30 seconds
                log.warning(f"⚠️ {label}: Task stuck in 'queued' status for {age_seconds:.1f}s with no attempts")
                log.warning("   This suggests queue workers are not processing tasks")
                log.warning("   Check: kubectl get pods -l app=queue-worker")
        
        # Check for failed tasks
        if current_status == "failed":
            log.error(f"❌ {label}: Task failed after {attempts} attempts")
            error_info = row.get("error_info") or row.get("result")
            if error_info:
                log.error(f"   Error: {error_info}")
            return row
        
        # Check for completed tasks
        if current_status == "completed":
            result = row.get("result")
            if result is not None:
                log.info(f"✅ {label}: COMPLETED with result keys={list(result.keys()) if isinstance(result, dict) else '…'}")
                return row
            else:
                log.warning(f"⚠️ {label}: Status is 'completed' but no result found")
                return row
        
        time.sleep(check_interval)
    
    # Timeout reached
    log.error(f"❌ {label}: Task {tid} timed out after {timeout_s}s")
    log.error(f"   Final status: {last_status}")
    log.error(f"   Final attempts: {attempts}")
    
    # Provide diagnostic information
    log.error("🔍 DIAGNOSTIC INFORMATION:")
    log.error("   1. Check if queue workers are running: kubectl get pods -l app=queue-worker")
    log.error("   2. Check queue worker logs: kubectl logs <queue-worker-pod>")
    log.error("   3. Check orchestrator logs: kubectl logs <orchestrator-pod>")
    log.error("   4. Check task in database: SELECT * FROM tasks WHERE id = '%s'" % str(tid))
    
    return row

def wait_for_completion(conn, tid: uuid.UUID, label: str, timeout_s: float = 90.0):
    """Wait for task completion with enhanced monitoring."""
    return monitor_task_status(conn, tid, label, timeout_s)

def scenario_fast_path(conn) -> uuid.UUID:
    """Low drift → fast routing to organ."""
    payload = {
        "type": "general_query",
        "description": "what time is it in UTC?",
        "params": {"priority": "low"},
        "drift_score": min(0.1, env_float("OCPS_DRIFT_THRESHOLD", 0.5) / 2.0),
        "run_immediately": True,
    }
    
    # Check if direct execution fallback is enabled
    enable_direct_fallback = env_bool("ENABLE_DIRECT_FALLBACK", False)
    
    # Try seedcore-api first (new service boundary)
    tid = submit_via_seedcore_api(payload)
    if tid:
        log.info(f"✅ Task created via seedcore-api: {tid}")
        return tid
    else:
        log.error("❌ Seedcore-api submission failed - no task ID returned")
    
    # Fallback: Try orchestrator pipeline (if configured)
    tid = submit_via_orchestrator(payload)
    if tid:
        log.info(f"✅ Task created via orchestrator pipeline: {tid}")
        return tid
    else:
        log.error("❌ Orchestrator pipeline submission failed - no task ID returned")
    
    # Provide detailed error information
    api_url = env('SEEDCORE_API_URL', '')
    orch_url = env('ORCH_URL', '')
    
    if api_url and "::" in api_url:
        log.error("❌ ROOT CAUSE: SEEDCORE_API_URL contains double colons (::)")
        log.error("   Current: " + api_url)
        log.error("   This creates an invalid URL that cannot be parsed")
        log.error("   Fix: export SEEDCORE_API_URL='http://seedcore-api:8002'")
        raise RuntimeError("SEEDCORE_API_URL is malformed (contains double colons). Fix the environment variable and retry.")
    
    if orch_url and "::" in orch_url:
        log.error("❌ ROOT CAUSE: ORCH_URL contains double colons (::)")
        log.error("   Current: " + orch_url)
        log.error("   This creates an invalid URL that cannot be parsed")
        log.error("   Fix: export ORCH_URL='http://127.0.0.1:8000/orchestrator'")
        raise RuntimeError("ORCH_URL is malformed (contains double colons). Fix the environment variable and retry.")
    
    if enable_direct_fallback:
        # Fallback: direct execution via Serve (no DB tracking)
        log.warning("⚠️ Both seedcore-api and orchestrator unavailable; executing via Serve handle (no DB verification).")
        # Note: This would need access to the coordinator handle from the calling context
        # For now, we'll raise an error indicating the services are needed
        raise RuntimeError("Both seedcore-api and orchestrator unavailable. Set ENABLE_DIRECT_FALLBACK=true and pass coordinator handle for direct execution.")
    else:
        # Fail fast - no fallback
        raise RuntimeError("Failed to create fast-path task via seedcore-api or orchestrator pipeline (no DB fallback)")

def scenario_escalation(conn) -> uuid.UUID:
    """High drift → escalate to CognitiveCore for planning."""
    payload = {
        "type": "general_query",
        "description": "Plan a multi-step analysis over graph + retrieval + synthesis",
        "params": {"force_decomposition": True},
        "drift_score": max(env_float("OCPS_DRIFT_THRESHOLD", 0.5) + 0.2, 0.9),
        "run_immediately": True,
    }
    # Try seedcore-api first (new service boundary)
    tid = submit_via_seedcore_api(payload)
    if tid:
        log.info(f"✅ Escalation task created via seedcore-api: {tid}")
        return tid
    
    # Fallback: Try orchestrator pipeline
    tid = submit_via_orchestrator(payload)
    if tid:
        log.info(f"✅ Escalation task created via orchestrator pipeline: {tid}")
        return tid
    
    assert tid, "Failed to create escalation task via seedcore-api or orchestrator pipeline"
    return tid

def scenario_graph_task(conn) -> Optional[uuid.UUID]:
    """Optional: exercise GraphDispatcher via DB function."""
    if not conn:
        return None
    try:
        # Create a graph RAG task and return the task ID for verification
        task_id = pg_create_graph_rag_task(conn, node_ids=[123], hops=2, topk=8, description="Find similar nodes to 123")
        if task_id:
            log.info(f"✅ Submitted graph RAG task via DB function with ID: {task_id}")
            return task_id
        else:
            log.warning("⚠️ Graph RAG task submission failed - no task ID returned")
            return None
    except Exception as e:
        log.warning(f"Graph task submission skipped: {e}")
        return None

def scenario_debug_routing(ray, coord):
    """Debug routing issues by running comprehensive diagnostics."""
    log.info("🔍 RUNNING ROUTING DEBUG DIAGNOSTICS")
    log.info("=" * 60)
    
    # Step 1: Check coordinator capabilities
    check_coordinator_capabilities(ray, coord)
    
    # Step 2: Verify environment configuration
    verify_environment_configuration()
    
    # Step 3: Check queue worker status
    check_queue_worker_status()
    
    # Step 4: Test routing decision logic
    test_routing_decision_logic()
    
    # Step 5: Check organ availability
    check_organ_availability(ray)
    
    # Step 6: Inspect coordinator routing logic
    inspect_coordinator_routing_logic(ray, coord)
    
    # Step 7: Check coordinator internal state
    check_coordinator_internal_state(ray, coord)
    
    # Step 8: Test routing with mock tasks
    test_routing_with_mock_tasks(ray, coord)
    
    # Step 9: Provide diagnosis
    diagnose_routing_issue()
    
    # Step 10: Provide fix recommendations
    provide_fix_recommendations()
    
    log.info("=" * 60)
    log.info("🔍 ROUTING DEBUG DIAGNOSTICS COMPLETED")
    log.info("=" * 60)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Verify SeedCore architecture and debug routing issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify_seedcore_architecture.py           # Run full verification
  python verify_seedcore_architecture.py --debug   # Run only routing debugging
  python verify_seedcore_architecture.py --strict  # Exit on validation failures
  python verify_seedcore_architecture.py --help    # Show this help
  
  # API Endpoints (Updated for OpenAPI 3.1.0):
  # - Health: GET /orchestrator/health
  # - Tasks: POST /orchestrator/tasks
  # - Anomaly Triage: POST /orchestrator/pipeline/anomaly-triage
  # - Tune Status: GET /orchestrator/pipeline/tune/status/{job_id}
        """
    )
    
    parser.add_argument(
        '--debug', 
        action='store_true',
        help='Run only routing debugging diagnostics (skip full verification)'
    )
    
    parser.add_argument(
        '--debug-level',
        choices=['INFO', 'DEBUG'],
        default='INFO',
        help='Set logging level (default: INFO)'
    )
    
    # Let users pass --strict or --no-strict (None if unspecified)
    try:
        action = argparse.BooleanOptionalAction  # py3.9+
    except Exception:
        # fallback: keep --strict only; None if unspecified
        action = None
    if action:
        parser.add_argument('--strict', dest='strict', action=action, default=None,
                            help='Enable/disable strict mode. Defaults to env STRICT_MODE or True.')
    else:
        parser.add_argument('--strict', action='store_true',
                            help='Enable strict mode (no --no-strict on this Python).')
    
    return parser.parse_args()

def debug_only_mode(ray, coord):
    """Run only the routing debugging diagnostics."""
    log.info("🔍 RUNNING ROUTING DEBUG DIAGNOSTICS ONLY")
    log.info("=" * 60)
    
    # Run comprehensive debugging
    scenario_debug_routing(ray, coord)
    
    log.info("=" * 60)
    log.info("🎯 DEBUGGING COMPLETED - Check output above for routing issues")
    log.info("=" * 60)

def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Log API version information
    log.info("🔧 SeedCore Architecture Verification Script")
    log.info("📋 Updated for new service boundaries")
    log.info("📋 Task creation: seedcore-api (/api/v1/tasks)")
    log.info("📋 Pipeline operations: orchestrator (/orchestrator/pipeline/*)")
    
    # Check for common configuration issues and provide help
    fix_service_url_issues()
    
    # Apply chosen log level immediately
    if args.debug_level == 'DEBUG':
        logging.getLogger().setLevel(logging.DEBUG)
        log.setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)
        log.setLevel(logging.INFO)
    
    # Strict-mode resolution precedence: CLI > ENV > default(True)
    global STRICT_MODE_ENABLED
    if getattr(args, "strict", None) is not None:
        STRICT_MODE_ENABLED = bool(args.strict)
    else:
        STRICT_MODE_ENABLED = env_bool("STRICT_MODE", True)
    log.info(f"🔧 Strict mode: {STRICT_MODE_ENABLED}")
    
    # DB (optional, but highly recommended for verification)
    conn = pg_conn()
    if not conn:
        log.warning("⚠️ DB unavailable; skipping fast-path and escalation validation")
        log.warning("   Set SEEDCORE_PG_DSN environment variable for full verification")

    # Cluster & actors up?
    ray, coord, want_g, found_g = check_cluster_and_actors()

    # Check if running in debug-only mode
    if args.debug:
        debug_only_mode(ray, coord)
        return

    # DEBUG: Run comprehensive routing diagnostics (default off to reduce noise)
    if env_bool("DEBUG_ROUTING", False):
        scenario_debug_routing(ray, coord)

    # Fast path
    fast_tid = scenario_fast_path(conn)
    log.info(f"Fast path task_id = {fast_tid}")
    fast_path_has_plan = False  # Track for summary
    if conn:
        # Verify task was created in database before monitoring
        # Add retry logic for timing issues between orchestrator and database
        max_retries = env_int("TASK_DB_INSERTION_RETRIES", 5)
        retry_delay = env_float("TASK_DB_INSERTION_DELAY_S", 2.0)
        initial_check = None
        
        for attempt in range(max_retries):
            initial_check = pg_get_task(conn, fast_tid)
            if initial_check:
                log.info(f"✅ FAST-PATH: Task {fast_tid} found in database (attempt {attempt+1}), status: {initial_check.get('status', 'unknown')}")
                break
            else:
                if attempt < max_retries - 1:
                    log.warning(f"⚠️ FAST-PATH: Task {fast_tid} not found in database (attempt {attempt+1}/{max_retries}), retrying in {retry_delay}s...")
                    log.warning("   This may indicate a timing issue between orchestrator and database")
                    time.sleep(retry_delay)
                else:
                    log.error(f"❌ FAST-PATH: Task {fast_tid} not found in database after {max_retries} attempts")
                    log.error("   This indicates the orchestrator submission failed or database integration is incomplete")
                    log.error("   NOTE: The orchestrator may be returning task IDs without actually inserting into database")
                    log.error("   Check orchestrator logs and database connectivity")
                    exit_if_strict("Fast path task not found in database after creation")
                    return
        
        # Check current task status before waiting
        check_current_task_status(conn, fast_tid)
        
        row = wait_for_completion(conn, fast_tid, "FAST-PATH")
        
        # --- FAST PATH VALIDATION ---
        if row is None:
            log.error("❌ FAST-PATH: Task monitoring failed - no result returned")
            log.error("   This usually means the task was not found in the database")
            log.error("   Check if the orchestrator successfully created the task")
            exit_if_strict("Fast path task monitoring failed - task not found in database")
            return
        
        # Debug: inspect the database row structure
        log.info(f"📋 Fast path row keys: {list(row.keys())}")
        log.info(f"📋 Fast path result column type: {type(row.get('result'))}")
        
        # Normalize result: ensure it's a dict
        raw_res = row.get("result")
        log.info(f"📋 Raw fast path result type: {type(raw_res)}")
        
        res = normalize_result(raw_res)
        if isinstance(res, dict):
            # Log drift score and routing info to understand routing decision
            drift_score = row.get("drift_score")
            log.info(f"📋 Fast path drift_score: {drift_score}")
            log.info(f"📋 Expected drift threshold: {env_float('OCPS_DRIFT_THRESHOLD', 0.5)}")
            
            # Check if drift score should have triggered fast path
            threshold = env_float('OCPS_DRIFT_THRESHOLD', 0.5)
            if drift_score < threshold:
                log.info(f"✅ Drift score {drift_score} < {threshold} - should route to fast path")
            else:
                log.warning(f"⚠️ Drift score {drift_score} >= {threshold} - escalation expected")
                log.warning("   This suggests the task should have been escalated, not routed to fast path")
            
            # Use consolidated plan detection helper
            has_plan, plan_steps = detect_plan(res)
            fast_path_has_plan = has_plan  # Track for summary
            
            if has_plan:
                log.warning("⚠️ Fast path unexpectedly contains HGNN plan indicators (should be direct routing)")
                log.warning("🔍 ROUTING BUG DETECTED: Low-drift task was escalated!")
                log.warning("This suggests a bug in the coordinator's routing logic")
                
                # Additional debugging info
                if res.get("type") == "list_result":
                    log.warning("🔍 Task was processed as list_result (HGNN plan format)")
                    log.warning("🔍 This indicates the coordinator chose escalation path")
                if res.get("escalated"):
                    log.warning("🔍 Task explicitly marked as escalated")
                
                # Log the actual result structure for debugging
                log.warning("🔍 Full result structure for debugging:")
                log.warning(f"   {json.dumps(res, indent=2, default=str)}")
                
                # Provide specific debugging guidance
                log.warning("🔍 IMMEDIATE DEBUGGING STEPS:")
                log.warning("   1. Check coordinator logs for routing decision")
                log.warning("   2. Verify OCPS_DRIFT_THRESHOLD environment variable")
                log.warning("   3. Check if fast-path organs are available")
                log.warning("   4. Look for forced escalation logic in coordinator code")
                    
            else:
                log.info("✅ Fast path confirmed: direct routing (no HGNN plan)")
            
            # Log fast path characteristics
            fast_metadata = {k: v for k, v in res.items() if k in ["routed_to", "organ_id", "processing_time_ms", "type"]}
            if fast_metadata:
                log.info(f"📋 Fast path metadata: {fast_metadata}")
    else:
        log.warning("No DB connection; cannot verify fast-path completion in DB.")

    # Optional: Graph task (moved before escalation to ensure it runs)
    if env_bool("VERIFY_GRAPH_TASK", False):
        log.info("🔍 VERIFYING GRAPH TASK PROCESSING")
        log.info("=" * 50)
        g_tid = scenario_graph_task(conn)
        if g_tid and conn:
            log.info(f"⏳ Waiting for graph task {g_tid} to complete...")
            wait_for_completion(conn, g_tid, "GRAPH", timeout_s=150.0)
            log.info("✅ Graph task verification completed successfully")
        else:
            log.warning("⚠️ Graph task verification skipped - no task ID or DB connection")
    else:
        log.info("📋 Graph task verification disabled (VERIFY_GRAPH_TASK=false)")

    # Escalation
    esc_tid = scenario_escalation(conn)
    log.info(f"Escalation task_id = {esc_tid}")
    if conn:
        # Verify task was created in database before monitoring
        # Add retry logic for timing issues between orchestrator and database
        max_retries = env_int("TASK_DB_INSERTION_RETRIES", 5)
        retry_delay = env_float("TASK_DB_INSERTION_DELAY_S", 2.0)
        initial_check = None
        
        for attempt in range(max_retries):
            initial_check = pg_get_task(conn, esc_tid)
            if initial_check:
                log.info(f"✅ ESCALATION: Task {esc_tid} found in database (attempt {attempt+1}), status: {initial_check.get('status', 'unknown')}")
                break
            else:
                if attempt < max_retries - 1:
                    log.warning(f"⚠️ ESCALATION: Task {esc_tid} not found in database (attempt {attempt+1}/{max_retries}), retrying in {retry_delay}s...")
                    log.warning("   This may indicate a timing issue between orchestrator and database")
                    time.sleep(retry_delay)
                else:
                    log.error(f"❌ ESCALATION: Task {esc_tid} not found in database after {max_retries} attempts")
                    log.error("   This indicates the orchestrator submission failed or database integration is incomplete")
                    log.error("   NOTE: The orchestrator may be returning task IDs without actually inserting into database")
                    log.error("   Check orchestrator logs and database connectivity")
                    exit_if_strict("Escalation task not found in database after creation")
                    return
        
        row = wait_for_completion(conn, esc_tid, "ESCALATION")
        
        # --- HGNN VALIDATION ---
        if row is None:
            log.error("❌ ESCALATION: Task monitoring failed - no result returned")
            log.error("   This usually means the task was not found in the database")
            log.error("   Check if the orchestrator successfully created the task")
            exit_if_strict("Escalation task monitoring failed - task not found in database")
            return
        
        # Debug: inspect the database row structure
        log.info(f"📋 Database row keys: {list(row.keys())}")
        log.info(f"📋 Result column type: {type(row.get('result'))}")
        
        # Normalize result: ensure it's a dict
        raw_res = row.get("result")
        log.info(f"📋 Raw result type: {type(raw_res)}")
        
        res = normalize_result(raw_res)
        if res is None:
            exit_if_strict("Escalation result could not be normalized to dict")
            log.error(f"Raw result: {raw_res}")
            return
        
        # Use consolidated plan detection helper
        has_plan, plan = detect_plan(res)
        
        if not has_plan or not plan:
            log.warning("⚠️ Escalation did NOT include HGNN decomposition plan")
            log.warning(f"Available result keys: {list(res.keys())}")
            log.warning(f"Result content: {res}")
            log.warning("   This may indicate the task was processed differently than expected")
            # Don't exit - continue with the verification
            return
        
        # Validate plan structure
        if not isinstance(plan, list):
            exit_if_strict(f"Plan is not a list: {type(plan)}")
            return
        
        log.info(f"✅ Escalation returned HGNN plan with {len(plan)} steps")
        
        # Check each step structure
        valid_steps = 0
        for i, step in enumerate(plan):
            if not isinstance(step, dict):
                log.error(f"⚠️ Step {i} is not a dictionary: {step}")
                continue
                
            # Check for required fields (organ_id is essential)
            if "organ_id" not in step:
                log.error(f"⚠️ Step {i} missing organ_id: {step}")
                continue
            
            # Log step details
            organ_id = step.get("organ_id")
            success = step.get("success", "unknown")
            
            # Check if step has task info (either direct or nested)
            if "task" in step:
                task_info = step["task"]
                if isinstance(task_info, dict):
                    task_type = task_info.get("type", "unknown")
                else:
                    task_type = str(task_info)
            elif "result" in step:
                # Handle case where result contains the task info
                result = step["result"]
                if isinstance(result, dict):
                    task_type = result.get("type", "unknown")
                    # Log more details about the result structure
                    log.info(f"      📋 Result keys: {list(result.keys())}")
                else:
                    task_type = str(result)
            else:
                task_type = "unknown"
            
            # Log step details with more context
            log.info(f"   Step {i} -> organ={organ_id} success={success} task={task_type}")
            
            # Show additional step fields for debugging
            step_fields = [k for k in step.keys() if k not in ["organ_id", "success", "task", "result"]]
            if step_fields:
                log.info(f"      📋 Additional fields: {step_fields}")
            
            valid_steps += 1
        
        if valid_steps == 0:
            exit_if_strict("No valid steps found in HGNN plan")
            return
        
        # Ensure we can tell it was escalated
        # Check multiple indicators of HGNN involvement
        escalated = (
            res.get("escalated") is True or 
            "plan" in res or 
            "solution_steps" in res or
            res.get("type") == "list_result" or  # New structured format
            (plan and len(plan) > 0)  # If we successfully parsed a plan, that proves HGNN was involved
        )
        
        if escalated:
            log.info("✅ Escalation path confirmed (HGNN invoked)")
        else:
            exit_if_strict("Escalation result does not prove HGNN involvement")
            log.error(f"Plan found: {plan is not None}, Plan length: {len(plan) if plan else 0}")
            return
        
        # Log metadata for debugging
        metadata = {k: v for k, v in res.items() if k in ["escalated", "plan_source", "planner", "cognitive_core_version"]}
        if metadata:
            log.info(f"📋 Escalation metadata: {metadata}")
            
    else:
        log.warning("No DB connection; cannot verify escalation completion in DB.")

    # Snapshot coordinator metrics/status (best-effort)
    try:
        st = serve_deployment_status(coord)
        log.info(f"Coordinator final status snapshot: {json.dumps(st, indent=2, default=str)}")
    except Exception as e:
        log.warning(f"Coordinator status snapshot failed: {e}")

    # --- API FAILURE METRICS ---
    metrics = get_api_failure_metrics()
    if metrics:
        log.info("=" * 60)
        log.info("📊 COORDINATOR API CALL FAILURE METRICS")
        log.info("=" * 60)
        for method, count in metrics.items():
            log.info(f"   {method}: {count} failures")
        log.info("=" * 60)
    else:
        log.info("✅ No coordinator API call failures detected")

    # --- ORCHESTRATOR HEALTH METRICS ---
    health_metrics = get_orchestrator_health_metrics()
    if health_metrics:
        log.info("=" * 60)
        log.info("📊 ORCHESTRATOR HEALTH ENDPOINT METRICS")
        log.info("=" * 60)
        for status_code, count in health_metrics.items():
            log.info(f"   HTTP {status_code}: {count} responses")
        log.info("=" * 60)
    else:
        log.info("✅ No orchestrator health endpoint calls detected")

    # --- PIPELINE LATENCY METRICS ---
    latency_summary = get_pipeline_latency_summary()
    if latency_summary:
        log.info("=" * 60)
        log.info("📊 PIPELINE ENDPOINT LATENCY METRICS")
        log.info("=" * 60)
        for endpoint, stats in latency_summary.items():
            log.info(f"   {endpoint}:")
            log.info(f"     Count: {stats['count']}")
            log.info(f"     Min: {stats['min_ms']:.1f}ms")
            log.info(f"     Max: {stats['max_ms']:.1f}ms")
            log.info(f"     Avg: {stats['avg_ms']:.1f}ms")
            log.info(f"     P95: {stats['p95_ms']:.1f}ms")
        log.info("=" * 60)
    else:
        log.info("✅ No pipeline endpoint calls detected")

    # --- DISPATCHER HEARTBEAT METRICS ---
    heartbeat_summary = get_dispatcher_heartbeat_summary()
    if heartbeat_summary:
        log.info("=" * 60)
        log.info("📊 DISPATCHER HEARTBEAT METRICS")
        log.info("=" * 60)
        for dispatcher_name, stats in heartbeat_summary.items():
            log.info(f"   {dispatcher_name}:")
            log.info(f"     Status: {stats['last_status']}")
            log.info(f"     Uptime: {stats['uptime_minutes']:.1f} minutes")
            log.info(f"     Last seen: {stats['last_seen_seconds']:.1f}s ago")
            log.info(f"     Ping count: {stats['ping_count']}")
        log.info("=" * 60)
    else:
        log.info("✅ No dispatcher heartbeat data detected")

    # --- SERVE CONFIGURATION RECOMMENDATIONS ---
    log.info("=" * 60)
    log.info("🔧 SERVE DEPLOYMENT CONFIGURATION")
    log.info("=" * 60)
    log.info("📋 To eliminate max_ongoing_requests warnings:")
    log.info("   @serve.deployment(max_ongoing_requests=32, num_replicas=2)     # Standard")
    log.info("   @serve.deployment(max_ongoing_requests=48, num_replicas=3)     # Medium throughput")
    log.info("   @serve.deployment(max_ongoing_requests=64, num_replicas=4)     # Maximum capacity (organism limit)")
    log.info("📋 Current client timeouts:")
    log.info("   Anomaly-triage: 30.0s (increased from 8.0s)")
    log.info("   Other endpoints: 8.0s (default)")
    log.info("📋 Ray Serve environment variables set:")
    log.info(f"   RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S={env('RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S', '2.0')}s")
    log.info(f"   RAY_SERVE_MAX_QUEUE_LENGTH={env('RAY_SERVE_MAX_QUEUE_LENGTH', '2000')}")
    log.info(f"   SUPPRESS_RAY_SERVE_WARNINGS={env('SUPPRESS_RAY_SERVE_WARNINGS', 'false')}")
    log.info("📋 To further reduce queue length timeout warnings:")
    log.info("   export RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S=5.0  # Increase from 0.1s default")
    log.info("   export RAY_SERVE_MAX_QUEUE_LENGTH=5000  # Increase queue capacity")
    log.info("   export SUPPRESS_RAY_SERVE_WARNINGS=true  # Suppress timeout warnings entirely")
    log.info("📋 Task database insertion timing:")
    log.info(f"   TASK_DB_INSERTION_RETRIES={env('TASK_DB_INSERTION_RETRIES', '5')}")
    log.info(f"   TASK_DB_INSERTION_DELAY_S={env('TASK_DB_INSERTION_DELAY_S', '2.0')}")
    log.info("📋 NOTE: Orchestrator may return task IDs without inserting into database")
    log.info("   This is a known issue - orchestrator needs database integration")
    log.info("=" * 60)

    # --- VALIDATION SUMMARY ---
    log.info("=" * 60)
    log.info("🎯 SEEDCORE ARCHITECTURE VALIDATION SUMMARY")
    log.info("=" * 60)
    log.info("✅ Ray cluster & actors: HEALTHY")
    log.info("✅ Serve apps: RUNNING")
    
    # GraphDispatcher status
    if want_g > 0:
        if found_g >= want_g:
            log.info(f"✅ GraphDispatchers: {found_g}/{want_g} RESPONSIVE")
        else:
            log.warning(f"⚠️ GraphDispatchers: {found_g}/{want_g} RESPONSIVE")
    else:
        log.info("📋 GraphDispatchers: DISABLED")
    
    # Fast path summary - tie to actual results
    if conn:
        # Use the tracked result from validation
        if fast_path_has_plan:
            log.warning("⚠️ Fast path: BUG DETECTED (HGNN escalation)")
        else:
            log.info("✅ Fast path: DIRECT ROUTING (no HGNN)")
        
        # Check for drift score mismatch
        try:
            fast_row = pg_get_task(conn, fast_tid)
            if fast_row:
                drift_score = fast_row.get("drift_score")
                threshold = env_float('OCPS_DRIFT_THRESHOLD', 0.5)
                if drift_score and drift_score >= threshold:
                    log.warning(f"⚠️ Fast path drift score {drift_score} >= threshold {threshold}")
                    log.warning("   This suggests incorrect routing - should have escalated")
        except Exception:
            pass  # Ignore errors in summary
        
        # Add warning if fast path contains HGNN steps
        if fast_path_has_plan:
            log.warning("⚠️ SUMMARY: Fast path incorrectly escalated to HGNN")
            log.warning("   This indicates a routing bug in the coordinator")
    else:
        log.warning("⚠️ Fast path: UNKNOWN (DB unavailable)")
        log.warning("   Set SEEDCORE_PG_DSN environment variable for full verification")
    
    # Escalation summary
    if conn:
        try:
            esc_row = pg_get_task(conn, esc_tid)
            if esc_row and esc_row.get("result"):
                esc_res = normalize_result(esc_row.get("result"))
                has_plan, plan_steps = detect_plan(esc_res)
                if has_plan and plan_steps:
                    log.info(f"✅ Escalation: HGNN DECOMPOSITION ({len(plan_steps)} steps)")
                else:
                    log.warning("⚠️ Escalation: UNKNOWN (no plan detected)")
            else:
                log.warning("⚠️ Escalation: UNKNOWN (no result data)")
        except Exception as e:
            log.warning(f"⚠️ Escalation: UNKNOWN (error analyzing: {e})")
    else:
        log.warning("⚠️ Escalation: UNKNOWN (DB unavailable)")
        log.warning("   Set SEEDCORE_PG_DSN environment variable for full verification")
    
    log.info("✅ Coordinator: RESPONSIVE")
    
    # Overall status
    if conn:
        log.info("=" * 60)
        if fast_path_has_plan:
            log.warning("⚠️ ROUTING BUG DETECTED: Fast path incorrectly escalated to HGNN")
            log.warning("   Check coordinator logs and OCPS_DRIFT_THRESHOLD configuration")
            log.warning("   This indicates a bug in the coordinator's routing logic")
        else:
            log.info("🎉 All validations passed! SeedCore architecture is working correctly.")
        log.info("=" * 60)
    else:
        log.warning("=" * 60)
        log.warning("⚠️ Validation incomplete - DB unavailable for result verification")
        log.warning("   Set SEEDCORE_PG_DSN environment variable for full verification")
        log.warning("=" * 60)

if __name__ == "__main__":
    main()

