#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from verify_rct_hot_path_shadow import (
    CANONICAL_CASES,
    FIXTURE_ROOT,
    _build_request,
    _get_json,
    _persist_authoritative_approval,
    _resolve_active_snapshot,
)


DEFAULT_ARTIFACT_DIR = Path(".local-runtime/hot_path_benchmarks")


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _prepare_case_payloads(base_url: str) -> tuple[str | None, list[tuple[str, dict[str, Any]]]]:
    active_snapshot = _resolve_active_snapshot(base_url)
    prepared: list[tuple[str, dict[str, Any]]] = []
    for case_name in CANONICAL_CASES:
        case_dir = FIXTURE_ROOT / case_name
        persisted_approval = _persist_authoritative_approval(base_url, case_dir)
        payload = _build_request(case_dir, persisted_approval=persisted_approval)
        if active_snapshot:
            payload["policy_snapshot_ref"] = active_snapshot
            payload["action_intent"]["action"]["security_contract"]["version"] = active_snapshot
        prepared.append((case_name, payload))
    return active_snapshot, prepared


def _percentile(samples: list[float], percentile: int) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)


def run_benchmark(
    *,
    base_url: str,
    total_requests: int,
    warmup_requests: int,
    concurrency: int,
    artifact_root: Path,
    request_delay_ms: float = 0.0,
    jitter_ms_max: float = 0.0,
    simulated_client_failure_rate: float = 0.0,
    client_max_retries: int = 3,
    simulated_retry_backoff_ms: float = 5.0,
) -> dict[str, Any]:
    evaluate_url = f"{base_url.rstrip('/')}/pdp/hot-path/evaluate?debug=true"
    status_url = f"{base_url.rstrip('/')}/pdp/hot-path/status"
    active_snapshot, prepared_cases = _prepare_case_payloads(base_url)
    if not prepared_cases:
        raise RuntimeError("No canonical RCT cases were prepared for hot-path benchmarking.")

    status_before = _get_json(status_url)
    before_total = int(status_before.get("total") or 0)
    before_mismatched = int(status_before.get("mismatched") or 0)
    before_parity_ok = int(status_before.get("parity_ok") or 0)

    rate = max(0.0, min(1.0, float(simulated_client_failure_rate)))
    max_transport_attempts = max(1, int(client_max_retries) + 1)
    backoff_s = max(0.0, float(simulated_retry_backoff_ms)) / 1000.0

    def invoke(index: int, *, warmup: bool) -> dict[str, Any]:
        delay_ms = max(0.0, float(request_delay_ms))
        if jitter_ms_max > 0:
            delay_ms += random.uniform(0.0, float(jitter_ms_max))
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

        case_name, template = prepared_cases[index % len(prepared_cases)]
        payload = copy.deepcopy(template)
        payload["request_id"] = f"bench:{case_name}:{'warmup' if warmup else 'run'}:{index}"

        transport_injections = 0
        for attempt in range(max_transport_attempts):
            flaky = rate > 0 and random.random() < rate
            if flaky:
                transport_injections += 1
                if attempt >= max_transport_attempts - 1:
                    return {
                        "case": case_name,
                        "request_id": payload["request_id"],
                        "external_latency_ms": 0.0,
                        "reported_latency_ms": None,
                        "disposition": None,
                        "reason_code": None,
                        "status": "error",
                        "error": "simulated_connectivity_exhausted",
                        "simulated_transport_failures": transport_injections,
                    }
                if backoff_s > 0:
                    time.sleep(backoff_s)
                continue
            break

        started = time.perf_counter()
        try:
            response = _post_json(evaluate_url, payload)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            out: dict[str, Any] = {
                "case": case_name,
                "request_id": payload["request_id"],
                "external_latency_ms": elapsed_ms,
                "reported_latency_ms": response.get("latency_ms"),
                "disposition": response.get("decision", {}).get("disposition"),
                "reason_code": response.get("decision", {}).get("reason_code"),
                "status": "ok",
            }
            if transport_injections:
                out["simulated_transport_failures"] = transport_injections
            return out
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            err: dict[str, Any] = {
                "case": case_name,
                "request_id": payload["request_id"],
                "external_latency_ms": elapsed_ms,
                "reported_latency_ms": None,
                "disposition": None,
                "reason_code": None,
                "status": "error",
                "error": str(exc),
            }
            if transport_injections:
                err["simulated_transport_failures"] = transport_injections
            return err

    for warmup_index in range(max(0, warmup_requests)):
        invoke(warmup_index, warmup=True)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [
            pool.submit(invoke, request_index, warmup=False)
            for request_index in range(max(0, total_requests))
        ]
        results = [future.result() for future in futures]

    status_after = _get_json(status_url)
    artifact_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_root / f"rct_hot_path_benchmark_{timestamp}.json"

    external_latencies = [float(item["external_latency_ms"]) for item in results if item.get("status") == "ok"]
    reason_counts = Counter(str(item.get("reason_code") or "") for item in results)
    disposition_counts = Counter(str(item.get("disposition") or "") for item in results)
    disposition_by_case: dict[str, dict[str, int]] = {}
    by_case: dict[str, Counter] = defaultdict(Counter)
    for item in results:
        case = str(item.get("case") or "unknown")
        if item.get("status") != "ok":
            by_case[case]["request_error"] += 1
            continue
        disp = str(item.get("disposition") or "none")
        by_case[case][disp] += 1
    disposition_by_case = {case: dict(counts) for case, counts in by_case.items()}
    error_count = sum(1 for item in results if item.get("status") != "ok")
    exhausted = sum(
        1 for item in results if item.get("error") == "simulated_connectivity_exhausted"
    )
    transport_injections_total = sum(
        int(item.get("simulated_transport_failures") or 0) for item in results
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "mode": status_after.get("mode"),
        "active_snapshot": active_snapshot or status_after.get("active_snapshot_version"),
        "graph_age_seconds": status_after.get("graph_age_seconds"),
        "authz_graph_ready": status_after.get("authz_graph_ready"),
        "graph_freshness_ok": status_after.get("graph_freshness_ok"),
        "enforce_ready": status_after.get("enforce_ready"),
        "warmup_requests": max(0, warmup_requests),
        "total_requests": max(0, total_requests),
        "concurrency": max(1, concurrency),
        "request_delay_ms": max(0.0, float(request_delay_ms)),
        "jitter_ms_max": max(0.0, float(jitter_ms_max)),
        "simulated_client_failure_rate": rate,
        "client_max_retries": int(client_max_retries),
        "simulated_retry_backoff_ms": max(0.0, float(simulated_retry_backoff_ms)),
        "simulated_transport_failure_injections": transport_injections_total,
        "simulated_connectivity_exhausted_count": exhausted,
        "success_count": len(results) - error_count,
        "error_count": error_count,
        "mismatch_count": max(0, int(status_after.get("mismatched") or 0) - before_mismatched),
        "parity_ok_delta": max(0, int(status_after.get("parity_ok") or 0) - before_parity_ok),
        "total_delta": max(0, int(status_after.get("total") or 0) - before_total),
        "latency_ms": {
            "p50": _percentile(external_latencies, 50),
            "p95": _percentile(external_latencies, 95),
            "p99": _percentile(external_latencies, 99),
            "avg": round(statistics.fmean(external_latencies), 2) if external_latencies else None,
        },
        "disposition_counts": dict(disposition_counts),
        "disposition_by_case": disposition_by_case,
        "quarantine_count": int(disposition_counts.get("quarantine", 0)),
        "top_reason_codes": [
            {"reason_code": reason_code, "count": count}
            for reason_code, count in reason_counts.most_common(5)
        ],
        "artifact_path": str(artifact_path),
        "results": results,
    }
    artifact_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the Restricted Custody Transfer hot-path endpoint.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8002/api/v1",
        help="Runtime API base URL.",
    )
    parser.add_argument("--requests", type=int, default=40, help="Total benchmark requests.")
    parser.add_argument("--warmup", type=int, default=4, help="Warmup requests before measuring.")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent in-flight benchmark requests.")
    parser.add_argument(
        "--artifact-dir",
        default=str(DEFAULT_ARTIFACT_DIR),
        help="Directory where benchmark artifacts will be written.",
    )
    parser.add_argument(
        "--request-delay-ms",
        type=float,
        default=0.0,
        help="Fixed per-request delay before POST (simulates edge / coordination latency).",
    )
    parser.add_argument(
        "--jitter-ms-max",
        type=float,
        default=0.0,
        help="Additional uniform [0, max] ms jitter per request (simulates noisy links).",
    )
    parser.add_argument(
        "--simulated-client-failure-rate",
        type=float,
        default=0.0,
        help="Probability [0,1] of a synthetic pre-request transport failure per attempt (intermittent connectivity drill).",
    )
    parser.add_argument(
        "--client-max-retries",
        type=int,
        default=3,
        help="Retries after synthetic transport failures before giving up on a request.",
    )
    parser.add_argument(
        "--simulated-retry-backoff-ms",
        type=float,
        default=5.0,
        help="Sleep between synthetic transport failures (milliseconds).",
    )
    args = parser.parse_args()

    summary = run_benchmark(
        base_url=args.base_url,
        total_requests=args.requests,
        warmup_requests=args.warmup,
        concurrency=args.concurrency,
        artifact_root=Path(args.artifact_dir),
        request_delay_ms=args.request_delay_ms,
        jitter_ms_max=args.jitter_ms_max,
        simulated_client_failure_rate=args.simulated_client_failure_rate,
        client_max_retries=args.client_max_retries,
        simulated_retry_backoff_ms=args.simulated_retry_backoff_ms,
    )

    latency = summary.get("latency_ms") or {}
    print("Restricted Custody Transfer Hot-Path Benchmark")
    print(f"mode: {summary.get('mode')}")
    print(f"active_snapshot: {summary.get('active_snapshot')}")
    print(f"graph_age_seconds: {summary.get('graph_age_seconds')}")
    print(
        "requests: "
        f"warmup={summary.get('warmup_requests')} "
        f"total={summary.get('total_requests')} "
        f"concurrency={summary.get('concurrency')}"
    )
    print(
        "latency_ms: "
        f"p50={latency.get('p50')} "
        f"p95={latency.get('p95')} "
        f"p99={latency.get('p99')} "
        f"avg={latency.get('avg')}"
    )
    print(
        "outcomes: "
        f"success={summary.get('success_count')} "
        f"errors={summary.get('error_count')} "
        f"mismatches={summary.get('mismatch_count')} "
        f"quarantine={summary.get('quarantine_count')} "
        f"synth_transport_injections={summary.get('simulated_transport_failure_injections')} "
        f"synth_exhausted={summary.get('simulated_connectivity_exhausted_count')}"
    )
    dbc = summary.get("disposition_by_case") or {}
    if dbc:
        print(f"disposition_by_case: {json.dumps(dbc, sort_keys=True)}")
    print(f"artifact: {summary.get('artifact_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
