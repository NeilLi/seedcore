#!/usr/bin/env python3
"""Verify the host-local SeedCore runtime surfaces impacted by recent commits."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _url(base_env: str, default: str, path: str) -> str:
    base = os.getenv(base_env, default).rstrip("/")
    return f"{base}{path}"


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _post_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    response = requests.post(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def main() -> int:
    results: list[CheckResult] = []

    api_health_url = _url("SEEDCORE_API_URL", "http://127.0.0.1:8002", "/health")
    api_ready_url = _url("SEEDCORE_API_URL", "http://127.0.0.1:8002", "/readyz")
    pkg_status_url = _url("SEEDCORE_API_URL", "http://127.0.0.1:8002", "/api/v1/pkg/status")
    hal_status_url = _url("HAL_BASE_URL", "http://127.0.0.1:8003", "/status")
    organism_health_url = _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/organism/health")
    organism_init_status_url = _url("SERVE_GATEWAY", "http://127.0.0.1:8000", "/organism/init-status")

    try:
        payload = _get_json(api_health_url)
        ok = payload.get("status") == "healthy"
        results.append(CheckResult("api.health", ok, json.dumps(payload, sort_keys=True)))
    except Exception as exc:  # pragma: no cover - defensive
        results.append(CheckResult("api.health", False, str(exc)))

    try:
        payload = _get_json(api_ready_url)
        ok = payload.get("status") == "ready"
        results.append(CheckResult("api.readyz", ok, json.dumps(payload, sort_keys=True)))
    except Exception as exc:
        results.append(CheckResult("api.readyz", False, str(exc)))

    try:
        payload = _get_json(pkg_status_url)
        ok = bool(payload.get("available")) and bool(payload.get("evaluator_ready"))
        detail = json.dumps(
            {
                "available": payload.get("available"),
                "evaluator_ready": payload.get("evaluator_ready"),
                "authz_graph_ready": payload.get("authz_graph_ready"),
                "active_version": payload.get("active_version"),
                "error": payload.get("error"),
            },
            sort_keys=True,
        )
        results.append(CheckResult("api.pkg_status", ok, detail))
    except Exception as exc:
        results.append(CheckResult("api.pkg_status", False, str(exc)))

    try:
        payload = _get_json(hal_status_url)
        ok = payload.get("state") == "connected"
        results.append(CheckResult("hal.status", ok, json.dumps(payload, sort_keys=True)))
    except Exception as exc:
        results.append(CheckResult("hal.status", False, str(exc)))

    try:
        payload = _get_json(organism_health_url)
        ok = payload.get("status") == "healthy" and bool(payload.get("organism_initialized"))
        results.append(CheckResult("serve.organism_health", ok, json.dumps(payload, sort_keys=True)))
    except Exception as exc:
        results.append(CheckResult("serve.organism_health", False, str(exc)))

    try:
        payload = _get_json(organism_init_status_url)
        ok = bool(payload.get("initialized")) and payload.get("init_error") in (None, "")
        results.append(CheckResult("serve.organism_init_status", ok, json.dumps(payload, sort_keys=True)))
    except Exception as exc:
        results.append(CheckResult("serve.organism_init_status", False, str(exc)))

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")

    if failing:
        print(f"\nRuntime verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nRuntime verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
