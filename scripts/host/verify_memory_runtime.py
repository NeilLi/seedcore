#!/usr/bin/env python3
"""Verify live memory-related runtime surfaces for host-local SeedCore."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _url(base_env: str, default: str, path: str) -> str:
    base = os.getenv(base_env, default).rstrip("/")
    return f"{base}{path}"


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _memory_payload_ok(payload: dict[str, Any]) -> bool:
    return all(key in payload for key in ("mw", "mlt", "mfb"))


def _memory_metrics_ok(payload: dict[str, Any]) -> bool:
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    memory = metrics.get("memory", {}) if isinstance(metrics, dict) else {}
    return all(key in memory for key in ("mw", "mlt", "mfb"))


def main() -> int:
    results: list[CheckResult] = []

    checks = [
        (
            "serve.organism_health",
            _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/organism/health"),
            lambda payload: payload.get("status") == "healthy"
            and bool(payload.get("organism_initialized")),
        ),
        (
            "serve.organism_memory_telemetry",
            _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/organism/memory/telemetry"),
            lambda payload: bool(payload.get("ok")) and _memory_payload_ok(payload),
        ),
        (
            "ops.state_status",
            _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/ops/state/status"),
            lambda payload: payload.get("status") == "ready",
        ),
        (
            "ops.state_system_metrics",
            _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/ops/state/system-metrics"),
            lambda payload: bool(payload.get("success")) and _memory_metrics_ok(payload),
        ),
    ]

    for name, url, predicate in checks:
        try:
            payload = _get_json(url)
            results.append(
                CheckResult(
                    name=name,
                    ok=bool(predicate(payload)),
                    detail=json.dumps(payload, sort_keys=True),
                )
            )
        except urllib.error.HTTPError as exc:
            results.append(CheckResult(name=name, ok=False, detail=f"HTTP {exc.code}: {exc.reason}"))
        except Exception as exc:  # pragma: no cover - defensive runtime script
            results.append(CheckResult(name=name, ok=False, detail=str(exc)))

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")

    if failing:
        print(
            f"\nMemory runtime verification failed: {len(failing)} checks failed.",
            file=sys.stderr,
        )
        return 1

    print("\nMemory runtime verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
