#!/usr/bin/env python3
"""
Autonomous Hotel OS — SeedCore-Aligned Agentic Simulator
--------------------------------------------------------
Runs from host (outside Kubernetes). Submits realistic hotel events to SeedCore API,
reusing the same environment variables and endpoint shapes as verify_seedcore_architecture.py.

Env (aligned with SeedCore scripts):
  SEEDCORE_API_URL            (default: http://seedcore-api:8002)
  SEEDCORE_API_TIMEOUT        (default: 5.0)
  OCPS_TAU_FAST               (default: 0.4)
  OCPS_TAU_PLAN               (default: 0.8)
  SEEDCORE_USE_SDK            (true|false) for NIM driver selection
  NIM_LLM_BASE_URL            (default: http://127.0.0.1:8000/v1)
  NIM_LLM_API_KEY             (default: none)
  NIM_LLM_MODEL               (default: meta/llama-3.1-8b-base)

Endpoint (aligned):
  POST {SEEDCORE_API_URL}/api/v1/tasks
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import random
import signal
import sys
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Ensure project src and root are on sys.path when running from host
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# --- Optional NIM integration -------------------------------------------------
try:
    from seedcore.ml.driver import get_driver as get_nim_driver
    _NIM_OK = True
except Exception:
    _NIM_OK = False

# --- Try to import verify_seedcore_architecture helpers (optional) -----------
_VSA = None
try:
    import importlib.util, pathlib
    vsa_path = pathlib.Path(__file__).with_name("verify_seedcore_architecture.py")
    if vsa_path.exists():
        spec = importlib.util.spec_from_file_location("verify_seedcore_architecture", str(vsa_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
        _VSA = mod
except Exception:
    _VSA = None


# --- Logging ------------------------------------------------------------------
def configure_logging(json_logs: bool, level: str = "INFO"):
    lvl = getattr(logging, level.upper(), logging.INFO)
    if json_logs:
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                payload = {
                    "ts": int(time.time() * 1000),
                    "lvl": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                return json.dumps(payload)
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(JsonFormatter())
        logging.basicConfig(level=lvl, handlers=[h])
    else:
        logging.basicConfig(
            level=lvl,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
        )

log = logging.getLogger("hotel-simulator")


# --- HTTP session (reuse VSA if present) -------------------------------------
def make_session(timeout: float, retries: int = 3, backoff: float = 0.5) -> requests.Session:
    # If VSA exposes a session factory, prefer it to remain aligned
    if _VSA and hasattr(_VSA, "make_session"):
        try:
            return _VSA.make_session(timeout=timeout, retries=retries, backoff=backoff)  # type: ignore
        except Exception:
            pass
    # Fallback: local resilient session
    s = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "TRACE"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    orig = s.request
    def with_default_timeout(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout
        return orig(method, url, **kwargs)
    s.request = with_default_timeout  # type: ignore
    return s


# --- Health checks (use VSA if present) --------------------------------------
def seedcore_health(session: requests.Session, api_base: str) -> bool:
    if _VSA and hasattr(_VSA, "check_api_health"):
        try:
            ok = _VSA.check_api_health(session, api_base)  # type: ignore
            log.info(f"SeedCore health (VSA): {ok}")
            return bool(ok)
        except Exception:
            pass
    # Fallback: simple GET probes
    for path in ("/health", "/healthz", "/api/v1/health"):
        url = api_base.rstrip("/") + path
        try:
            r = session.get(url)
            if r.status_code < 500:
                log.info(f"Health: {url} -> {r.status_code}")
                return True
        except Exception:
            continue
    log.warning("Health checks did not pass; proceeding.")
    return False


# --- Routing class ------------------------------------------------------------
def classify_route(S: float, tau_fast: float, tau_plan: float) -> str:
    if S < tau_fast:
        return "FAST"
    elif S < tau_plan:
        return "PLANNER"
    return "HGNN"


# --- NIM deep plan (optional) -------------------------------------------------
def nim_preview_plan(
    proto_hint: Dict[str, Any],
    nim_base_url: str,
    nim_model: str,
    use_sdk: bool,
    api_key: str,
    timeout: int = 30,
) -> Optional[str]:
    if not _NIM_OK:
        return None
    try:
        driver = get_nim_driver(
            use_sdk=use_sdk,
            base_url=nim_base_url,
            api_key=api_key,
            model=nim_model,
            timeout=timeout,
            auto_fallback=True,
        )
        messages = [
            {"role": "system", "content": "You are the OCPS deep planner for an autonomous hotel. Respond with a short, executable playbook (bulleted steps)."},
            {"role": "user", "content": json.dumps(proto_hint)},
        ]
        return driver.chat(messages, max_tokens=300, temperature=0.4)
    except Exception as e:
        log.warning(f"NIM preview failed: {e}")
        return None


# --- Submission ---------------------------------------------------------------
def submit_hotel_event(
    session: requests.Session,
    api_endpoint: str,
    event_type: str,
    description: str,
    surprise_score: float,
    tags: List[str],
    params: Dict[str, Any],
    *,
    attach_nim: bool,
    nim_cfg: Optional[Dict[str, Any]],
    dry_run: bool,
    tau_fast: float,
    tau_plan: float,
) -> Optional[str]:
    route = classify_route(surprise_score, tau_fast, tau_plan)
    cid = str(uuid.uuid4())
    headers = {"X-Request-ID": cid, "Content-Type": "application/json"}

    # HGNN-only deep preview
    if attach_nim and route == "HGNN" and nim_cfg:
        hint = {"tags": tags, "params": params, "route": route, "surprise": surprise_score}
        plan = nim_preview_plan(
            hint,
            nim_cfg["base_url"],
            nim_cfg["model"],
            bool(nim_cfg.get("use_sdk", True)),
            nim_cfg.get("api_key", "none"),
            nim_cfg.get("timeout", 30),
        )
        if plan:
            params = dict(params)
            params["nim_preview_plan"] = plan

    payload = {
        "type": event_type,
        "description": description,
        "params": {**params, "tags": tags, "route": route},
        "drift_score": surprise_score,
        "run_immediately": True,
        "correlation_id": cid,
    }

    if dry_run:
        log.info(f"DRY-RUN [{route}] S={surprise_score:.2f}: {description}")
        log.debug(json.dumps(payload, indent=2))
        return None

    log.info(f"SUBMIT [{route}] S={surprise_score:.2f}: {description}")
    try:
        r = session.post(api_endpoint, headers=headers, json=payload)
        if 200 <= r.status_code < 300:
            tid = (r.json() or {}).get("id")
            log.info(f"Accepted. Task ID: {tid}  (cid={cid})")
            return tid
        log.error(f"API error {r.status_code}: {r.text[:400]}")
    except requests.exceptions.RequestException as e:
        log.error(f"Request failed: {e}")
    return None


# --- Scenarios (tags/params mirror your Hotel OS spec) -----------------------
def scenario_vip_prearrival(session, endpoint, tau_fast, tau_plan, ocps_tau, **kwargs):
    shuttle_eta = 14
    return submit_hotel_event(
        session=session,
        api_endpoint=endpoint,
        event_type="guest_event",
        description=f"VIP Guest (Maria) pre-arrival. Shuttle ETA: {shuttle_eta}m.",
        surprise_score=round(ocps_tau - 0.2, 3),
        tags=["vip", "privacy", "pre_arrival"],
        params={"guest_id": "G-MARIA", "shuttle_eta_min": shuttle_eta},
        tau_fast=tau_fast, tau_plan=tau_plan, **kwargs
    )

def scenario_robot_delivery(session, endpoint, tau_fast, tau_plan, **kwargs):
    return submit_hotel_event(
        session=session,
        api_endpoint=endpoint,
        event_type="iot_event",
        description="Service robot Srv-12 delivering towels to room 1201",
        surprise_score=round(random.uniform(0.05, 0.15), 3),
        tags=["robot_mission", "amenity", "in_stay"],
        params={"robot_id": "Srv-12", "room": 1201, "item_sku": "TOWEL_SET"},
        tau_fast=tau_fast, tau_plan=tau_plan, **kwargs
    )

def scenario_hvac_fault(session, endpoint, tau_fast, tau_plan, **kwargs):
    room = random.randint(1000, 4500)
    temp = round(random.uniform(28.0, 32.0), 1)
    return submit_hotel_event(
        session=session,
        api_endpoint=endpoint,
        event_type="facility_event",
        description=f"HVAC fault detected in room {room}. Temp rising: {temp}°C",
        surprise_score=round(tau_fast + 0.1, 3),
        tags=["hvac_fault", "in_stay", "anomaly"],
        params={"room": room, "current_temp_c": temp, "target_temp_c": 21.0},
        tau_fast=tau_fast, tau_plan=tau_plan, **kwargs
    )

def scenario_luggage_chain_breach(session, endpoint, tau_fast, tau_plan, **kwargs):
    return submit_hotel_event(
        session=session,
        api_endpoint=endpoint,
        event_type="security_event",
        description="Luggage custody chain broken for AGV-04. Bag misdelivered.",
        surprise_score=round(tau_fast + 0.2, 3),
        tags=["luggage_custody", "privacy", "guest_recovery"],
        params={"agv_id": "AGV-04", "chain_of_custody": "broken", "last_scan": "Dock-3"},
        tau_fast=tau_fast, tau_plan=tau_plan, **kwargs
    )

def scenario_complex_hgnn(session, endpoint, tau_fast, tau_plan, **kwargs):
    return submit_hotel_event(
        session=session,
        api_endpoint=endpoint,
        event_type="security_event",
        description="COMPLEX: VIP in room 1510 reports severe peanut allergy AND HVAC is offline.",
        surprise_score=0.84,
        tags=["allergen", "hvac_fault", "vip", "privacy", "guest_recovery"],
        params={"room": "1510", "guest_id": "G-VIP-1510", "report_source": "in_room_tablet"},
        tau_fast=tau_fast, tau_plan=tau_plan, **kwargs
    )


# --- CLI & Main --------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SeedCore-aligned Agentic Hotel Simulator")
    p.add_argument("--json-logs", action="store_true")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))

    # SeedCore-aligned envs
    p.add_argument("--api-url", default=os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002"))
    p.add_argument("--api-timeout", type=float, default=float(os.getenv("SEEDCORE_API_TIMEOUT", "5.0")))
    p.add_argument("--tau-fast", type=float, default=float(os.getenv("OCPS_TAU_FAST", "0.4")))
    p.add_argument("--tau-plan", type=float, default=float(os.getenv("OCPS_TAU_PLAN", "0.8")))
    p.add_argument("--ocps-drift-threshold", type=float, default=float(os.getenv("OCPS_DRIFT_THRESHOLD", "0.5")))

    # Run shape
    p.add_argument("--cycles", type=int, default=0, help="0=infinite")
    p.add_argument("--rate", type=float, default=1.0, help="avg events/sec within a wave")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")

    # NIM preview
    default_use_sdk = os.getenv("SEEDCORE_USE_SDK", "true").lower() in ("1", "true", "yes")
    p.add_argument("--attach-nim-plan", action="store_true", help="Attach NIM deep-plan preview for HGNN events")
    p.add_argument("--nim-base-url", default=os.getenv("NIM_LLM_BASE_URL", "http://127.0.0.1:8000/v1"))
    p.add_argument("--nim-model", default=os.getenv("NIM_LLM_MODEL", "meta/llama-3.1-8b-base"))
    p.add_argument("--nim-use-sdk", default=default_use_sdk, action=argparse.BooleanOptionalAction)
    p.add_argument("--nim-api-key", default=os.getenv("NIM_LLM_API_KEY", "none"))
    p.add_argument("--nim-timeout", type=int, default=int(os.getenv("SEEDCORE_NIM_TIMEOUT", "30")))
    return p.parse_args()

_SHUTDOWN = threading.Event()
def _sig_handler(signum, frame):
    _SHUTDOWN.set()
signal.signal(signal.SIGINT, _sig_handler)
signal.signal(signal.SIGTERM, _sig_handler)

def main():
    args = parse_args()
    configure_logging(args.json_logs, args.log_level)

    api_endpoint = f"{args.api_url.rstrip('/')}/api/v1/tasks"
    session = make_session(timeout=args.api_timeout)

    seedcore_health(session, args.api_url)

    nim_cfg = {
        "base_url": args.nim_base_url,
        "model": args.nim_model,
        "use_sdk": args.nim_use_sdk,
        "api_key": args.nim_api_key,
        "timeout": args.nim_timeout,
    } if args.attach_nim_plan else None

    log.info("=== Autonomous Hotel OS Simulator (SeedCore) ===")
    log.info(f"API: {api_endpoint}")
    log.info(f"Thresholds: tau_fast={args.tau_fast} tau_plan={args.tau_plan}")
    log.info(f"NIM preview: {'ENABLED' if args.attach_nim_plan else 'disabled'} (driver={'ok' if _NIM_OK else 'missing'})")
    log.info(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE'}  Concurrency={args.concurrency}  Rate≈{args.rate} ev/s")

    metrics = {"submitted": 0, "accepted": 0, "errors": 0, "fast": 0, "planner": 0, "hgnn": 0}

    def _submit(job):
        try:
            tid = job()
            metrics["submitted"] += 1
            if tid or args.dry_run:
                metrics["accepted"] += 1
            else:
                metrics["errors"] += 1
        except Exception as e:
            log.error(f"Submit failed: {e}")
            metrics["errors"] += 1

    def run_wave():
        work: List[Tuple[str, callable]] = [
            ("vip", lambda: scenario_vip_prearrival(session, api_endpoint, args.tau_fast, args.tau_plan, args.ocps_drift_threshold,
                                                    attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
            ("robot1", lambda: scenario_robot_delivery(session, api_endpoint, args.tau_fast, args.tau_plan,
                                                       attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
            ("hvac", lambda: scenario_hvac_fault(session, api_endpoint, args.tau_fast, args.tau_plan,
                                                 attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
            ("robot2", lambda: scenario_robot_delivery(session, api_endpoint, args.tau_fast, args.tau_plan,
                                                       attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
            ("custody", lambda: scenario_luggage_chain_breach(session, api_endpoint, args.tau_fast, args.tau_plan,
                                                              attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
            ("complex", lambda: scenario_complex_hgnn(session, api_endpoint, args.tau_fast, args.tau_plan,
                                                      attach_nim=args.attach_nim_plan, nim_cfg=nim_cfg, dry_run=args.dry_run)),
        ]
        interval = 1.0 / max(args.rate, 0.0001)
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = []
            for _, job in work:
                futures.append(pool.submit(_submit, job))
                time.sleep(random.uniform(0.5 * interval, 1.5 * interval))
            for f in as_completed(futures):
                _ = f.result()

    def count_routes():
        metrics["fast"] += 3   # vip + robot1 + robot2
        metrics["planner"] += 2  # hvac + custody
        metrics["hgnn"] += 1   # complex

    cycles = args.cycles
    wave = 0
    try:
        while not _SHUTDOWN.is_set() and (cycles == 0 or wave < cycles):
            wave += 1
            log.info(f"--- Wave {wave} ---")
            run_wave()
            count_routes()
            if _SHUTDOWN.is_set():
                break
            log.info("Waiting 30s before next wave...")
            for _ in range(30):
                if _SHUTDOWN.is_set():
                    break
                time.sleep(1)
    finally:
        log.info("\n=== Summary ===")
        log.info(json.dumps(metrics, indent=2))

if __name__ == "__main__":
    main()
