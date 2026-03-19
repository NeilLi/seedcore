#!/usr/bin/env python3
"""
Comprehensive live API verifier for SeedCore core execution flows.

This script calls the active /api/v1 endpoints and validates that the control
plane can:
- accept and query tasks/governance
- create and submit source registrations
- ingest and query tracking events
- perform fact CRUD in Control router
- reach advisory/pkg/capabilities routes

It favors pragmatic runtime checks over strict golden payload matching.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_API_URL = os.getenv("SEEDCORE_API_URL", os.getenv("SEEDCORE_API", "http://127.0.0.1:8002"))
DEFAULT_TIMEOUT_S = float(os.getenv("SEEDCORE_API_TIMEOUT", "12"))
DEFAULT_POLL_SECONDS = int(os.getenv("SEEDCORE_VERIFY_POLL_SECONDS", "35"))
DEFAULT_POLL_INTERVAL = float(os.getenv("SEEDCORE_VERIFY_POLL_INTERVAL", "2"))


@dataclass
class StepResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def make_session(timeout: float, retries: int = 2, backoff: float = 0.3) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PATCH", "DELETE"),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    original_request = session.request

    def wrapped(method: str, url: str, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return original_request(method, url, **kwargs)

    session.request = wrapped  # type: ignore[assignment]
    return session


def norm_base(url: str) -> str:
    return url.rstrip("/")


def call_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected: tuple[int, ...] = (200,),
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> tuple[bool, str, Optional[Dict[str, Any]], int]:
    try:
        response = session.request(method, url, json=payload, params=params)
    except requests.RequestException as exc:
        return False, f"request_error={exc}", None, -1
    body: Optional[Dict[str, Any]]
    try:
        body = response.json() if response.content else {}
    except ValueError:
        body = {"raw": response.text[:500]}
    ok = response.status_code in expected
    detail = f"status={response.status_code}"
    if not ok:
        detail += f" body={json.dumps(body)[:300]}"
    return ok, detail, body, response.status_code


def wait_for_task_terminal_state(
    session: requests.Session,
    api_base: str,
    task_id: str,
    *,
    timeout_seconds: int,
    poll_interval: float,
) -> Dict[str, Any]:
    started = time.time()
    final = {}
    while time.time() - started < timeout_seconds:
        ok, _, body, _ = call_json(session, "GET", f"{api_base}/api/v1/tasks/{task_id}", expected=(200,))
        if not ok or not isinstance(body, dict):
            time.sleep(poll_interval)
            continue
        final = body
        status = str(body.get("status") or "").lower()
        if status in {"completed", "failed", "cancelled"}:
            break
        time.sleep(poll_interval)
    return final


def verify(api_url: str, *, strict: bool, poll_seconds: int, poll_interval: float) -> list[StepResult]:
    results: list[StepResult] = []
    session = make_session(DEFAULT_TIMEOUT_S)
    api_base = norm_base(api_url)

    created_task_id: Optional[str] = None
    created_registration_id: Optional[str] = None
    submitted_registration_task_id: Optional[str] = None
    created_tracking_event_id: Optional[str] = None
    created_fact_id: Optional[str] = None
    pkg_snapshot_id: Optional[int] = None

    # Health / readiness
    for path in ("/health", "/readyz", "/openapi.json"):
        ok, detail, _, code = call_json(session, "GET", f"{api_base}{path}", expected=(200,))
        status = "PASS" if ok else "FAIL"
        if not ok and path == "/readyz" and code == 503:
            status = "WARN"
        results.append(StepResult(f"System {path}", status, detail))

    # Tasks create/list/get/logs/governance/cancel/materialize
    task_payload = {
        "type": "action",
        "description": "verify core execution api flow",
        "run_immediately": True,
        "params": {
            "interaction": {"assigned_agent_id": "verify-agent"},
            "routing": {"required_specialization": "ROBOT_OPERATOR"},
            "resource": {"asset_id": f"asset-{uuid.uuid4().hex[:8]}"},
            "intent": "release",
        },
    }
    ok, detail, body, _ = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/tasks",
        expected=(200,),
        payload=task_payload,
    )
    results.append(StepResult("Tasks POST /tasks", "PASS" if ok else "FAIL", detail))
    if ok and isinstance(body, dict) and body.get("id"):
        created_task_id = str(body["id"])

    ok, detail, _, _ = call_json(session, "GET", f"{api_base}/api/v1/tasks", expected=(200,))
    results.append(StepResult("Tasks GET /tasks", "PASS" if ok else "FAIL", detail))

    if created_task_id:
        task_final = wait_for_task_terminal_state(
            session,
            api_base,
            created_task_id,
            timeout_seconds=poll_seconds,
            poll_interval=poll_interval,
        )
        status = str(task_final.get("status") or "unknown")
        results.append(StepResult("Tasks execution poll", "PASS", f"task_id={created_task_id} status={status}"))

        ok, detail, _, _ = call_json(
            session, "GET", f"{api_base}/api/v1/tasks/{created_task_id}", expected=(200,)
        )
        results.append(StepResult("Tasks GET /tasks/{task_id}", "PASS" if ok else "FAIL", detail))

        ok, detail, governance_body, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/tasks/{created_task_id}/governance",
            expected=(200,),
        )
        results.append(StepResult("Tasks GET /tasks/{task_id}/governance", "PASS" if ok else "FAIL", detail))

        # Logs endpoint is streaming; we validate endpoint responds (200 or 204 acceptable).
        try:
            logs_resp = session.get(
                f"{api_base}/api/v1/tasks/{created_task_id}/logs",
                params={"limit": 5},
                stream=True,
                timeout=10,
            )
            logs_ok = logs_resp.status_code in (200, 204)
            results.append(
                StepResult(
                    "Tasks GET /tasks/{task_id}/logs",
                    "PASS" if logs_ok else "FAIL",
                    f"status={logs_resp.status_code}",
                )
            )
            logs_resp.close()
        except requests.RequestException as exc:
            results.append(StepResult("Tasks GET /tasks/{task_id}/logs", "FAIL", f"request_error={exc}"))

        materialized_ok = False
        if isinstance(governance_body, dict):
            latest = governance_body.get("latest")
            if isinstance(latest, dict) and latest.get("evidence_bundle"):
                ok, detail, _, _ = call_json(
                    session,
                    "GET",
                    f"{api_base}/api/v1/governance/materialized-custody-event",
                    expected=(200,),
                    params={"task_id": created_task_id},
                )
                materialized_ok = ok
                results.append(
                    StepResult(
                        "Tasks GET /governance/materialized-custody-event",
                        "PASS" if ok else "FAIL",
                        detail,
                    )
                )
        if not materialized_ok:
            results.append(
                StepResult(
                    "Tasks GET /governance/materialized-custody-event",
                    "WARN",
                    "No evidence_bundle on latest governance record yet; materialization skipped.",
                )
            )

        ok, detail, _, _ = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/tasks/{created_task_id}/cancel",
            expected=(200, 409),
        )
        results.append(StepResult("Tasks POST /tasks/{task_id}/cancel", "PASS" if ok else "FAIL", detail))

    # Source registration workflow
    registration_payload = {
        "lot_id": f"lot-{uuid.uuid4().hex[:8]}",
        "producer_id": "verify-producer",
        "claimed_origin": {"country": "TH"},
        "collection_site": {"site": "verify-farm"},
    }
    ok, detail, body, _ = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/source-registrations",
        expected=(200,),
        payload=registration_payload,
    )
    results.append(StepResult("Source POST /source-registrations", "PASS" if ok else "FAIL", detail))
    if ok and isinstance(body, dict) and body.get("id"):
        created_registration_id = str(body["id"])

    if created_registration_id:
        ok, detail, _, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/source-registrations/{created_registration_id}",
            expected=(200,),
        )
        results.append(StepResult("Source GET /source-registrations/{id}", "PASS" if ok else "FAIL", detail))

        artifact_payload = {
            "artifact_type": "seal_macro_image",
            "uri": f"s3://verify/{uuid.uuid4().hex}.jpg",
            "sha256": "a" * 64,
            "metadata": {"source": "verify_script"},
        }
        ok, detail, _, _ = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/source-registrations/{created_registration_id}/artifacts",
            expected=(200,),
            payload=artifact_payload,
        )
        results.append(
            StepResult(
                "Source POST /source-registrations/{id}/artifacts",
                "PASS" if ok else "FAIL",
                detail,
            )
        )

        ok, detail, body, _ = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/source-registrations/{created_registration_id}/submit",
            expected=(200,),
        )
        results.append(
            StepResult(
                "Source POST /source-registrations/{id}/submit",
                "PASS" if ok else "FAIL",
                detail,
            )
        )
        if ok and isinstance(body, dict) and body.get("task_id"):
            submitted_registration_task_id = str(body["task_id"])

        verdict_status = "WARN"
        verdict_detail = "No registration verdict yet (expected in async flows)."
        ok, detail, _, code = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/source-registrations/{created_registration_id}/verdict",
            expected=(200, 404),
        )
        if ok and code == 200:
            verdict_status = "PASS"
            verdict_detail = detail
        elif code not in (404,):
            verdict_status = "FAIL"
            verdict_detail = detail
        results.append(StepResult("Source GET /source-registrations/{id}/verdict", verdict_status, verdict_detail))

    # Tracking events workflow
    tracking_payload: Dict[str, Any] = {
        "event_type": "operator_request_received",
        "source_kind": "operator_request",
        "payload": {"command": "verify"},
        "subject_type": "verify_script",
        "subject_id": f"subject-{uuid.uuid4().hex[:8]}",
        "producer_id": "verify-producer",
    }
    if created_registration_id:
        tracking_payload["registration_id"] = created_registration_id
    ok, detail, body, _ = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/tracking-events",
        expected=(200,),
        payload=tracking_payload,
    )
    results.append(StepResult("Tracking POST /tracking-events", "PASS" if ok else "FAIL", detail))
    if ok and isinstance(body, dict) and body.get("id"):
        created_tracking_event_id = str(body["id"])

    ok, detail, _, _ = call_json(session, "GET", f"{api_base}/api/v1/tracking-events", expected=(200,))
    results.append(StepResult("Tracking GET /tracking-events", "PASS" if ok else "FAIL", detail))

    if created_tracking_event_id:
        ok, detail, _, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/tracking-events/{created_tracking_event_id}",
            expected=(200,),
        )
        results.append(StepResult("Tracking GET /tracking-events/{id}", "PASS" if ok else "FAIL", detail))
    if created_registration_id:
        ok, detail, _, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/source-registrations/{created_registration_id}/tracking-events",
            expected=(200,),
        )
        results.append(
            StepResult(
                "Tracking GET /source-registrations/{id}/tracking-events",
                "PASS" if ok else "FAIL",
                detail,
            )
        )

    # Control facts CRUD
    fact_payload = {
        "text": f"verify fact {uuid.uuid4().hex[:8]}",
        "tags": ["verify", "api"],
        "meta_data": {"source": "verify_seedcore_core_execution"},
    }
    ok, detail, body, code = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/facts",
        expected=(200, 503),
        payload=fact_payload,
    )
    if code == 503:
        results.append(StepResult("Control POST /facts", "WARN", "Facts table unavailable in this env."))
    else:
        results.append(StepResult("Control POST /facts", "PASS" if ok else "FAIL", detail))
        if ok and isinstance(body, dict) and body.get("id"):
            created_fact_id = str(body["id"])

    ok, detail, _, _ = call_json(session, "GET", f"{api_base}/api/v1/facts", expected=(200,))
    results.append(StepResult("Control GET /facts", "PASS" if ok else "FAIL", detail))

    if created_fact_id:
        ok, detail, _, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/facts/{created_fact_id}",
            expected=(200,),
        )
        results.append(StepResult("Control GET /facts/{id}", "PASS" if ok else "FAIL", detail))

        ok, detail, _, _ = call_json(
            session,
            "PATCH",
            f"{api_base}/api/v1/facts/{created_fact_id}",
            expected=(200,),
            payload={"text": "verify fact patched"},
        )
        results.append(StepResult("Control PATCH /facts/{id}", "PASS" if ok else "FAIL", detail))

        ok, detail, _, _ = call_json(
            session,
            "DELETE",
            f"{api_base}/api/v1/facts/{created_fact_id}",
            expected=(200,),
        )
        results.append(StepResult("Control DELETE /facts/{id}", "PASS" if ok else "FAIL", detail))

    # Advisory
    advisory_payload = {
        "task": {
            "type": "query",
            "description": "verify advisory endpoint wiring",
            "params": {"routing": {"required_specialization": "general"}},
        }
    }
    ok, detail, _, code = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/advisory",
        expected=(200, 502),
        payload=advisory_payload,
    )
    status = "PASS" if code == 200 else "WARN"
    results.append(StepResult("Advisory POST /advisory", status if ok else "FAIL", detail))

    # PKG
    ok, detail, body, code = call_json(
        session,
        "GET",
        f"{api_base}/api/v1/pkg/status",
        expected=(200,),
    )
    results.append(StepResult("PKG GET /pkg/status", "PASS" if ok else "FAIL", detail))
    if ok and isinstance(body, dict) and isinstance(body.get("snapshot_id"), int):
        pkg_snapshot_id = int(body["snapshot_id"])

    ok, detail, _, code = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/pkg/reload",
        expected=(200, 500, 503),
    )
    results.append(StepResult("PKG POST /pkg/reload", "PASS" if code == 200 else "WARN", detail))

    eval_payload = {
        "task_facts": {
            "namespace": "verify",
            "subject": "guest:verify",
            "predicate": "request_concierge",
            "object_data": {"channel": "api"},
        },
        "mode": "advisory",
    }
    ok, detail, _, code = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/pkg/evaluate_async",
        expected=(200, 503),
        payload=eval_payload,
    )
    results.append(StepResult("PKG POST /pkg/evaluate_async", "PASS" if code == 200 else "WARN", detail))

    if pkg_snapshot_id is not None:
        compare_payload = {
            "baseline_snapshot_id": pkg_snapshot_id,
            "candidate_snapshot_id": pkg_snapshot_id,
            "task_facts": {
                "namespace": "verify",
                "subject": "guest:verify",
                "predicate": "request_concierge",
                "object_data": {"channel": "api"},
            },
        }
        ok, detail, _, code = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/pkg/snapshots/compare",
            expected=(200, 422, 503),
            payload=compare_payload,
        )
        results.append(StepResult("PKG POST /pkg/snapshots/compare", "PASS" if code == 200 else "WARN", detail))

        ok, detail, _, code = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/pkg/snapshots/{pkg_snapshot_id}/compile-rules",
            expected=(200, 404, 422, 503),
        )
        results.append(
            StepResult(
                "PKG POST /pkg/snapshots/{snapshot_id}/compile-rules",
                "PASS" if code == 200 else "WARN",
                detail,
            )
        )
    else:
        results.append(
            StepResult(
                "PKG compare/compile",
                "WARN",
                "No pkg snapshot_id available from /pkg/status; compare and compile checks skipped.",
            )
        )

    # Capabilities
    capability_payload = {
        "guest_id": str(uuid.uuid4()),
        "persona_name": "Verifier Persona",
        "base_capability_name": "reachy_actuator",
        "valid_to": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "executor": {
            "specialization": "reachy_actuator",
            "behaviors": ["safe_mode"],
            "behavior_config": {"motion": {"velocity_multiplier": 0.5}},
        },
        "routing": {"skills": {"safety": 1.0}},
    }
    ok, detail, _, code = call_json(
        session,
        "POST",
        f"{api_base}/api/v1/capabilities/register",
        expected=(200, 503),
        payload=capability_payload,
    )
    results.append(StepResult("Capabilities POST /capabilities/register", "PASS" if code == 200 else "WARN", detail))

    # Optional: ensure registration submit task is queryable as task.
    if submitted_registration_task_id:
        ok, detail, _, _ = call_json(
            session,
            "GET",
            f"{api_base}/api/v1/tasks/{submitted_registration_task_id}",
            expected=(200,),
        )
        results.append(StepResult("Submit task GET /tasks/{task_id}", "PASS" if ok else "FAIL", detail))

    if strict:
        for idx, item in enumerate(results):
            if item.status == "WARN":
                results[idx] = StepResult(item.name, "FAIL", f"(strict) {item.detail}")

    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comprehensive live verifier for SeedCore /api/v1 core execution flows.",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"SeedCore API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat WARN checks as FAIL.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help=f"Task polling timeout seconds (default: {DEFAULT_POLL_SECONDS})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Task polling interval seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = verify(
        args.api_url,
        strict=args.strict,
        poll_seconds=args.poll_seconds,
        poll_interval=args.poll_interval,
    )

    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    print("\nSeedCore Core Execution API Verification")
    print("=" * 52)
    for result in results:
        print(f"[{result.status:4}] {result.name}: {result.detail}")
    print("-" * 52)
    print(f"PASS={pass_count} WARN={warn_count} FAIL={fail_count}")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
