#!/usr/bin/env python3
"""
Lightweight verifier for the anomaly-triage pipeline.

Sequence:
  Client -> Orchestrator:        POST /pipeline/anomaly-triage (+corr)
  Orchestrator -> ml_service:    POST /ml/detect/anomaly (+corr)
  Orchestrator -> cognitive:     POST /cognitive/reason-about-failure (+corr)
  Orchestrator -> cognitive:     POST /cognitive/make-decision (+corr)
  [optional] Orchestrator -> ml: POST /ml/xgboost/tune/submit (+corr)
  [best-effort] Orchestrator -> cognitive: POST /cognitive/synthesize-memory (+corr)
  Orchestrator -> Client:        anomalies + reason + decision (+ job?)

Resource-conscious defaults:
- Short series (n=32)
- Small noise (0.01)
- Modest spike (scale=4.0)
- Low HTTP concurrency limits
- Shorter timeouts with headroom
"""

from __future__ import annotations
import argparse, asyncio, json, os, sys, time, uuid, statistics
from typing import Any, Dict, List, Optional, Tuple
import httpx

# ---------- Env helpers ----------
def env_float(k: str, default: float) -> float:
    try:
        return float(os.getenv(k, str(default)))
    except Exception:
        return default

def env_str(k: str, default: str) -> str:
    return os.getenv(k, default)

DEFAULT_ORCH_URL = env_str("ORCH_URL", "http://127.0.0.1:8000/orchestrator")

# Presets tuned for resource usage
PRESETS = {
    "ultra": {
        "series_len": 24,
        "noise": 0.008,
        "spike_at": 0.7,
        "spike_scale": 3.5,
        "http_timeout_s": 60.0,
        "max_conns": 6,
        "max_keepalive": 3,
        "tune_timeout_s": 60.0,
        "tune_poll_s": 4.0,
    },
    "light": {
        "series_len": 32,
        "noise": 0.01,
        "spike_at": 0.7,
        "spike_scale": 4.0,
        "http_timeout_s": 60.0,
        "max_conns": 8,
        "max_keepalive": 4,
        "tune_timeout_s": 90.0,
        "tune_poll_s": 3.0,
    },
    "full": {
        "series_len": 256,
        "noise": 0.02,
        "spike_at": 0.7,
        "spike_scale": 6.0,
        "http_timeout_s": 60.0,
        "max_conns": 100,
        "max_keepalive": 50,
        "tune_timeout_s": 120.0,
        "tune_poll_s": 3.0,
    },
}

# ---------- Data helpers ----------
def make_series(kind: str, n: int, noise: float, spike_at: float, spike_scale: float) -> List[float]:
    import random
    n = max(10, int(n))
    if kind == "ramp":
        base = [i / n for i in range(n)]
        return [b + random.uniform(-noise, noise) for b in base]
    if kind == "flatnoise":
        return [random.uniform(-noise, noise) for _ in range(n)]
    # default: spike
    xs = [random.uniform(-noise, noise) for _ in range(n)]
    idx = max(0, min(n - 1, int(spike_at * n)))
    xs[idx] += spike_scale
    return xs

def extract_nested(d: Dict[str, Any], *path: str, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

def summarize_latencies(samples_ms: List[float]) -> Dict[str, float]:
    if not samples_ms:
        return {}
    s = sorted(samples_ms)
    p95 = s[int(0.95 * (len(s) - 1))]
    return {
        "count": float(len(s)),
        "min_ms": float(s[0]),
        "max_ms": float(s[-1]),
        "avg_ms": float(sum(s) / len(s)),
        "median_ms": float(statistics.median(s)),
        "p95_ms": float(p95),
    }

# ---------- HTTP steps ----------
async def anomaly_triage(
    client: httpx.AsyncClient,
    orch_url: str,
    agent_id: str,
    series: List[float],
    context: Dict[str, Any],
    corr_id: str,
) -> Tuple[Dict[str, Any], Dict[str, float]]:
    url = orch_url.rstrip("/") + "/pipeline/anomaly-triage"
    headers = {"X-Correlation-ID": corr_id, "X-Service": "scenario-verifier"}
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            url,
            json={"agent_id": agent_id, "series": series, "context": context},
            headers=headers,
        )
        dt_ms = (time.perf_counter() - t0) * 1000.0
        resp.raise_for_status()
        # Try JSON; if it fails, include the raw text for debugging
        try:
            return resp.json(), {"anomaly_triage_ms": dt_ms}
        except Exception:
            raise RuntimeError(f"Non-JSON response ({resp.status_code}): {resp.text[:500]}")
    except httpx.HTTPStatusError as e:
        body = e.response.text if e.response is not None else ""
        raise RuntimeError(f"HTTP {e.response.status_code} from orchestrator: {e}\nBody: {body[:800]}") from e
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise RuntimeError(f"Connection error to orchestrator: {type(e).__name__}: {e!r}") from e
    except httpx.ReadTimeout as e:
        raise RuntimeError(f"Read timeout from orchestrator: {type(e).__name__}: {e!r}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"HTTP error to orchestrator: {type(e).__name__}: {e!r}") from e

async def poll_tune_status(
    client: httpx.AsyncClient,
    orch_url: str,
    job_id: str,
    corr_id: str,
    timeout_s: float,
    poll_s: float,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, float]]:
    url = orch_url.rstrip("/") + f"/pipeline/tune/status/{job_id}"
    headers = {"X-Correlation-ID": corr_id, "X-Service": "scenario-verifier"}
    t_start = time.perf_counter()
    polls, last_latency = 0, 0.0
    while (time.perf_counter() - t_start) < timeout_s:
        polls += 1
        t0 = time.perf_counter()
        r = await client.get(url, headers=headers)
        last_latency = (time.perf_counter() - t0) * 1000.0
        if r.status_code == 200:
            payload = r.json()
            status = (payload.get("status") or payload.get("state") or "").lower()
            if status in {"succeeded", "completed", "failed", "error", "terminated"}:
                return payload, {"tune_polls": float(polls), "last_tune_poll_ms": last_latency}
        await asyncio.sleep(poll_s)
    return None, {"tune_polls": float(polls), "last_tune_poll_ms": last_latency}

# ---------- Main ----------
async def main() -> int:
    p = argparse.ArgumentParser(description="Lightweight verify anomaly-triage pipeline via orchestrator.")
    p.add_argument("--preset", choices=["ultra", "light", "full"], default=os.getenv("PRESET", "light"),
                   help="Resource profile (default: light).")
    p.add_argument("--orch-url", default=DEFAULT_ORCH_URL, help=f"Orchestrator base URL (default: {DEFAULT_ORCH_URL})")
    p.add_argument("--agent-id", default="agent-e2e", help="Agent ID to tag the request")
    p.add_argument("--series-kind", default="spike", choices=["spike", "ramp", "flatnoise"], help="Series generator type")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON results")
    p.add_argument("--poll-tune", action="store_true", help="If tune job is returned, poll its status")
    # Manual overrides (rarely needed; presets cover typical cases)
    p.add_argument("--series-len", type=int, help="Override series length")
    p.add_argument("--noise", type=float, help="Override noise amplitude")
    p.add_argument("--spike-at", type=float, help="Override spike position [0,1]")
    p.add_argument("--spike-scale", type=float, help="Override spike magnitude")
    p.add_argument("--timeout", type=float, help="Override HTTP timeout seconds")
    p.add_argument("--tune-timeout", type=float, help="Override tune status timeout seconds")
    p.add_argument("--tune-poll-s", type=float, help="Override tune status poll interval seconds")
    args = p.parse_args()

    cfg = PRESETS[args.preset].copy()
    # Apply manual overrides if provided
    if args.series_len is not None: cfg["series_len"] = args.series_len
    if args.noise is not None: cfg["noise"] = args.noise
    if args.spike_at is not None: cfg["spike_at"] = args.spike_at
    if args.spike_scale is not None: cfg["spike_scale"] = args.spike_scale
    if args.timeout is not None: cfg["http_timeout_s"] = args.timeout
    if args.tune_timeout is not None: cfg["tune_timeout_s"] = args.tune_timeout
    if args.tune_poll_s is not None: cfg["tune_poll_s"] = args.tune_poll_s

    # Build series & context
    series = make_series(args.series_kind, cfg["series_len"], cfg["noise"], cfg["spike_at"], cfg["spike_scale"])
    context: Dict[str, Any] = {
        "source": "scenario-verifier",
        "series_kind": args.series_kind,
        "preset": args.preset,
        "notes": "Lightweight E2E verification",
    }

    corr_id = f"e2e-{uuid.uuid4().hex[:8]}"

    limits = httpx.Limits(max_connections=cfg["max_conns"], max_keepalive_connections=cfg["max_keepalive"])
    timeout = httpx.Timeout(cfg["http_timeout_s"])
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # Step 1: call orchestrator anomaly-triage
        try:
            triage, lat = await anomaly_triage(client, args.orch_url, args.agent_id, series, context, corr_id)
        except Exception as e:
            # Always show type + repr to avoid empty messages
            print(f"❌ Orchestrator /pipeline/anomaly-triage failed: {type(e).__name__}: {e!r}", file=sys.stderr)
            return 1

        anomalies = triage.get("anomalies", {})
        reason = triage.get("reason", {})
        decision = triage.get("decision", {})
        tuning_job = triage.get("tuning_job")

        summary = {
            "correlation_id": corr_id,
            "latency_ms": lat,
            "anomaly_count": len(anomalies.get("anomalies", [])) if isinstance(anomalies, dict) else None,
            "decision_action": extract_nested(decision, "result", "action") or extract_nested(decision, "action"),
            "tuning_job_present": bool(tuning_job),
            "preset": args.preset,
            "series_len": cfg["series_len"],
        }

        print("\n=== ✅ Orchestrator anomaly-triage response ===")
        print(json.dumps(triage, indent=2) if args.pretty else json.dumps(triage, separators=(",", ":")))
        print("\n--- Summary ---")
        print(json.dumps(summary, indent=2))

        exit_code = 0

        # Step 2: Optionally poll tune status if the decision says so
        action = (extract_nested(decision, "result", "action") or extract_nested(decision, "action") or "").lower()
        if args.poll_tune and action in {"tune", "retrain", "retune"}:
            job_id = tuning_job.get("job_id") or tuning_job.get("id") if isinstance(tuning_job, dict) else None
            if not job_id:
                print("⚠️  Tuning requested but no job_id present. Skipping.", file=sys.stderr)
            else:
                print(f"\n=== ⏳ Polling tune status (job_id={job_id}) ===")
                status, tune_lat = await poll_tune_status(
                    client,
                    args.orch_url,
                    job_id,
                    corr_id,
                    timeout_s=cfg["tune_timeout_s"],
                    poll_s=cfg["tune_poll_s"],
                )
                print("\n--- Tune Status ---")
                if status:
                    print(json.dumps(status, indent=2) if args.pretty else json.dumps(status, separators=(",", ":")))
                else:
                    print(f"⚠️  Tune status polling timed out after {cfg['tune_timeout_s']}s")
                    exit_code = 2

                if tune_lat:
                    print("\n--- Tune Polling Metrics ---")
                    print(json.dumps(tune_lat, indent=2))

        if not isinstance(reason, dict) or not decision:
            print("❌ Missing reason or decision in orchestrator response.", file=sys.stderr)
            exit_code = max(exit_code, 1)

        print("\n🎉 Done.")
        return exit_code

if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)

