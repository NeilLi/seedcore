#!/usr/bin/env python3
"""
Comprehensive Smoke Test for SeedCore CognitiveService (Ray Head)

What this validates:
  1) Env + provider wiring (LLM_PROVIDER, LLM_PROVIDERS, NIM/MLS endpoints)
  2) Ray connectivity from head pod
  3) In-cluster DNS resolution for Serve/Cognitive FQDNs (derived via ray_utils)
  4) CognitiveService /info and /health
  5) Functional calls:
      - plan (FAST, DEEP)
      - plan_with_escalation (FAST -> DEEP)
      - solve_problem
      - synthesize_memory
      - assess_capabilities
      - reason_about_failure
  6) Provider/model overrides passthrough (optional)

Exit code:
  - 0 on full success, 1 if any check fails.

Usage (typical on Ray head pod):
  export LLM_PROVIDER=openai
  export LLM_PROVIDERS=openai,anthropic,nim
  # Optional NIM defaults for local/on-prem
  export NIM_LLM_BASE_URL=http://seedcore-nim-svc.seedcore-dev.svc.cluster.local:8080/v1
  export NIM_LLM_API_KE=none
  python /app/tools/smoke_cognitive.py
"""

import os
import sys
import json
import time
import socket
import traceback
from typing import Dict, Any, List, Optional

import anyio

# ---------- Defaults (safe for local and cluster) ----------
os.environ.setdefault("LLM_PROVIDER", "nim")              # deep default
os.environ.setdefault("LLM_PROVIDERS", "nim")             # fast pool default
os.environ.setdefault("NIM_LLM_API_KE", "none")
# If you want to default NIM to localhost in dev:
os.environ.setdefault("NIM_LLM_BASE_URL", "http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1")

# ---------- Helpers ----------
def _active_providers() -> List[str]:
    try:
        from seedcore.utils.llm_registry import get_active_providers
        provs = get_active_providers() or []
        return [p.lower() for p in provs]
    except Exception:
        return [p.strip().lower() for p in os.getenv("LLM_PROVIDERS", "").split(",") if p.strip()]

def _dns_ok(host: str, timeout: float = 0.5) -> bool:
    if not host or host.startswith("http"):
        return True
    orig = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False
    finally:
        socket.setdefaulttimeout(orig)

def _host_of_url(url: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.hostname or ""

def _elapsed(fn):
    async def wrap(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            out = await fn(*args, **kwargs)
            return out, (time.perf_counter() - t0)
        except Exception as e:
            return e, (time.perf_counter() - t0)
    return wrap

def _print_header(title: str):
    print("\n" + "=" * 16 + f" {title} " + "=" * 16)

def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

# ---------- Main smoke ----------
async def run_smoke() -> int:
    failures: List[str] = []

    _print_header("ENV & PROVIDERS")
    print("LLM_PROVIDER (deep default):", os.getenv("LLM_PROVIDER"))
    print("LLM_PROVIDERS (fast pool):  ", os.getenv("LLM_PROVIDERS"))
    print("Active providers resolved:  ", _active_providers())

    # 1) Ray connectivity / ensure ray initialized
    _print_header("RAY CONNECTIVITY")
    try:
        from seedcore.utils import ray_utils
        ok = ray_utils.ensure_ray_initialized()
        print("ray_utils.ensure_ray_initialized():", ok)
        if not ok:
            print("WARN: Ray not available or RAY_ADDRESS not set (continuing; service calls may still pass).")
    except Exception as e:
        print("WARN: ray_utils ensure failed:", e)

    # 2) Resolve ML/COG base URLs via ray_utils
    _print_header("ENDPOINT DISCOVERY")
    try:
        from seedcore.utils.ray_utils import ML, COG
        ml_base = str(ML).rstrip("/")
        cog_base = str(COG).rstrip("/")
    except Exception:
        ml_base = os.getenv("MLS_BASE_URL", "http://127.0.0.1:8000/ml").rstrip("/")
        cog_base = os.getenv("COG_BASE_URL", "http://127.0.0.1:8000/cognitive").rstrip("/")

    print("ML base:", ml_base)
    print("COG base:", cog_base)

    # 3) In-cluster DNS resolution sanity
    _print_header("DNS SANITY")
    ml_host = _host_of_url(ml_base)
    cog_host = _host_of_url(cog_base)
    print("ML host:", ml_host, "DNS:", "OK" if _dns_ok(ml_host) else "FAIL")
    print("COG host:", cog_host, "DNS:", "OK" if _dns_ok(cog_host) else "FAIL")
    if ml_host and not _dns_ok(ml_host):
        failures.append(f"DNS resolution failed for ML host {ml_host}")
    if cog_host and not _dns_ok(cog_host):
        failures.append(f"DNS resolution failed for COG host {cog_host}")

    # 4) Cognitive client /info /health
    _print_header("COGNITIVE SERVICE /info /health")
    from seedcore.serve.cognitive_client import CognitiveServiceClient
    client = CognitiveServiceClient(base_url=cog_base)

    try:
        info = await client.get_service_info()
        print("INFO:", _pretty(info))
    except Exception as e:
        print("ERROR: /info failed:", e)
        failures.append("GET /info failed")

    try:
        health = await client.health_check()
        print("HEALTH:", _pretty(health))
        if str(health.get("status", "")).lower() != "healthy":
            failures.append("Service health not healthy")
    except Exception as e:
        print("ERROR: /health failed:", e)
        failures.append("GET /health failed")

    # 5) Functional calls
    agent_id = "smoke-ray-head"
    task = "Draft a concise VIP arrival checklist with privacy & allergen safety."

    # plan (FAST)
    _print_header("PLAN (FAST)")
    plan_fast = _elapsed(client.plan)
    res, dt = await plan_fast(
        agent_id=agent_id,
        task_description=task,
        depth="fast",
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("plan FAST failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # plan (DEEP) — defaults to LLM_PROVIDER (openai)
    _print_header("PLAN (DEEP)")
    plan_deep = _elapsed(client.plan)
    res, dt = await plan_deep(
        agent_id=agent_id,
        task_description=task,
        depth="deep",
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("plan DEEP failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # plan_with_escalation (FAST -> DEEP)
    _print_header("PLAN WITH ESCALATION")
    plan_escalate = _elapsed(client.plan_with_escalation)
    res, dt = await plan_escalate(
        agent_id=agent_id,
        task_description="Give me a brief incident response playbook for a minor data leak, highlight first-hour actions.",
        preferred_order=_active_providers() or None,
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("plan_with_escalation failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # solve_problem
    _print_header("SOLVE PROBLEM")
    solve = _elapsed(client.solve_problem)
    res, dt = await solve(
        agent_id=agent_id,
        problem_statement="We need a 3-step action plan to onboard a high-sensitivity client with strict dietary/allergen concerns.",
        constraints={"length": "short"},
        available_tools={},
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("solve_problem failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # synthesize_memory
    _print_header("SYNTHESIZE MEMORY")
    synth = _elapsed(client.synthesize_memory)
    fragments = [
        {"type": "note", "text": "VIP prefers private check-in and sesame-free meals."},
        {"type": "event", "text": "Arrival at 19:30, concierge code phrase enabled."},
    ]
    res, dt = await synth(
        agent_id=agent_id,
        memory_fragments=fragments,
        synthesis_goal="Produce a compact memory card emphasizing privacy and allergen safety."
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("synthesize_memory failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # assess_capabilities
    _print_header("ASSESS CAPABILITIES")
    assess = _elapsed(client.assess_capabilities)
    res, dt = await assess(
        agent_id=agent_id,
        performance_data={"on_time": 0.92, "incidents_last_30d": 0},
        current_capabilities={"privacy_protocols": "v2"},
        target_capabilities={"privacy_protocols": "v3"},
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("assess_capabilities failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # reason_about_failure
    _print_header("REASON ABOUT FAILURE")
    failure = _elapsed(client.reason_about_failure)
    res, dt = await failure(
        agent_id=agent_id,
        incident_context={
            "symptoms": ["late room readiness", "missing allergen tags"],
            "timeline": ["t-2h prep incomplete", "t-0 arrival"],
        },
        knowledge_context={"SOP": "privacy v2, allergen labeling v1"},
    )
    if isinstance(res, Exception):
        print("ERROR:", res)
        failures.append("reason_about_failure failed")
    else:
        print(f"OK in {dt:.2f}s")
        print(_pretty(res))

    # ---------- Summary ----------
    _print_header("SUMMARY")
    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        return 1
    print("All smoke checks passed ✅")
    return 0

def main():
    try:
        code = anyio.run(run_smoke)
    except KeyboardInterrupt:
        print("Interrupted.")
        code = 130
    except Exception:
        print("Unhandled exception:\n", traceback.format_exc())
        code = 1
    sys.exit(code)

if __name__ == "__main__":
    main()
