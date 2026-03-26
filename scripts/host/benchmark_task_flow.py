#!/usr/bin/env python3
"""Benchmark the live SeedCore task flow from create -> dispatch -> completion."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_BASE = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
API_V1 = f"{API_BASE}/api/v1"


@dataclass
class TaskSample:
    task_id: str
    status: str
    decision_kind: str | None
    route_reason: str | None
    queue_wait_ms: float | None
    exec_latency_ms: float | None
    wall_ms: float
    started_at: str | None
    finished_at: str | None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _task_payload(index: int) -> dict[str, Any]:
    nonce = f"{time.time_ns()}-{index}"
    description = f"benchmark fast query {index} [{nonce}]"
    return {
        "type": "query",
        "description": description,
        "params": {
            "task_description": description,
            "query": {"problem_statement": description},
            "interaction": {"mode": "one_shot"},
            "cognitive": {
                "cog_type": "problem_solving",
                "decision_kind": "fast",
            },
        },
        "run_immediately": True,
    }


def _wait_for_task(session: requests.Session, task_id: str, *, timeout_s: float, poll_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        response = session.get(f"{API_V1}/tasks/{task_id}", timeout=10)
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        status = str(payload.get("status") or "").lower()
        if status in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(poll_s)
    raise TimeoutError(f"Task {task_id} did not reach terminal state; last={last_payload}")


def _sample_stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min_ms": round(min(ordered), 3),
        "p50_ms": round(ordered[len(ordered) // 2], 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))], 3),
        "avg_ms": round(statistics.fmean(ordered), 3),
    }


def main() -> int:
    iterations = int(os.getenv("SEEDCORE_TASK_BENCH_ITERS", "8"))
    timeout_s = float(os.getenv("SEEDCORE_TASK_BENCH_TIMEOUT_S", "30"))
    poll_s = float(os.getenv("SEEDCORE_TASK_BENCH_POLL_S", "0.5"))

    session = requests.Session()
    health = session.get(f"{API_BASE}/health", timeout=5)
    health.raise_for_status()

    samples: list[TaskSample] = []
    failures: list[dict[str, Any]] = []

    for index in range(iterations):
        create_started = time.perf_counter()
        response = session.post(f"{API_V1}/tasks", json=_task_payload(index), timeout=10)
        response.raise_for_status()
        created = response.json()
        task_id = str(created["id"])
        terminal = _wait_for_task(session, task_id, timeout_s=timeout_s, poll_s=poll_s)
        wall_ms = (time.perf_counter() - create_started) * 1000.0

        exec_meta = (((terminal.get("result") or {}).get("meta") or {}).get("exec") or {})
        routing = ((terminal.get("result") or {}).get("routing") or {})
        created_at = _parse_iso(terminal.get("created_at"))
        started_at = _parse_iso(exec_meta.get("started_at"))
        finished_at = _parse_iso(exec_meta.get("finished_at"))
        queue_wait_ms = None
        if created_at is not None and started_at is not None:
            queue_wait_ms = max(0.0, (started_at - created_at).total_seconds() * 1000.0)

        sample = TaskSample(
            task_id=task_id,
            status=str(terminal.get("status") or "").lower(),
            decision_kind=(terminal.get("result") or {}).get("decision_kind"),
            route_reason=routing.get("reason"),
            queue_wait_ms=queue_wait_ms,
            exec_latency_ms=exec_meta.get("latency_ms"),
            wall_ms=wall_ms,
            started_at=exec_meta.get("started_at"),
            finished_at=exec_meta.get("finished_at"),
        )
        samples.append(sample)

        if sample.status != "completed":
            failures.append({"task_id": task_id, "status": sample.status, "error": terminal.get("error")})

    for sample in samples:
        print(
            "[TASK] "
            + json.dumps(
                {
                    "task_id": sample.task_id,
                    "status": sample.status,
                    "decision_kind": sample.decision_kind,
                    "route_reason": sample.route_reason,
                    "queue_wait_ms": round(sample.queue_wait_ms or 0.0, 3),
                    "exec_latency_ms": round(float(sample.exec_latency_ms or 0.0), 3),
                    "wall_ms": round(sample.wall_ms, 3),
                },
                sort_keys=True,
            )
        )

    if failures:
        print(f"Task flow benchmark failed: {failures}", file=sys.stderr)
        return 1

    queue_values = [sample.queue_wait_ms for sample in samples if sample.queue_wait_ms is not None]
    exec_values = [float(sample.exec_latency_ms) for sample in samples if sample.exec_latency_ms is not None]
    wall_values = [sample.wall_ms for sample in samples]

    summary = {
        "iterations": len(samples),
        "statuses": sorted({sample.status for sample in samples}),
        "route_reasons": sorted({sample.route_reason for sample in samples if sample.route_reason}),
        "decision_kinds": sorted({sample.decision_kind for sample in samples if sample.decision_kind}),
        "queue_wait_ms": _sample_stats(queue_values) if queue_values else {},
        "exec_latency_ms": _sample_stats(exec_values) if exec_values else {},
        "wall_ms": _sample_stats(wall_values),
    }
    print("[SUMMARY] " + json.dumps(summary, sort_keys=True))

    if queue_values and exec_values:
        queue_avg = statistics.fmean(queue_values)
        exec_avg = statistics.fmean(exec_values)
        if exec_avg > queue_avg * 2:
            if summary["route_reasons"] == ["coordinator-direct-general-query"]:
                barrier = "coordinator_route"
                note = (
                    "Most latency is inside the coordinator/direct-query path after dispatch; "
                    "queueing is a smaller fraction."
                )
            else:
                barrier = "execution_path"
                note = "Most latency is inside execution after dispatch; queueing is a smaller fraction."
        elif queue_avg > exec_avg:
            barrier = "dispatch_queue"
            note = "Queue wait is dominating; dispatcher capacity or claim cadence is the first barrier."
        else:
            barrier = "mixed"
            note = "Queueing and execution are both material."
    else:
        barrier = "unknown"
        note = "Insufficient timing fields to classify the barrier."

    print("[ANALYSIS] " + json.dumps({"primary_barrier": barrier, "note": note}, sort_keys=True))
    print("\nTask flow benchmark passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
