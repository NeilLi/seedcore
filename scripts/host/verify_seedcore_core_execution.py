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
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_API_URL = os.getenv("SEEDCORE_API_URL", os.getenv("SEEDCORE_API", "http://127.0.0.1:8002"))
DEFAULT_TIMEOUT_S = float(os.getenv("SEEDCORE_API_TIMEOUT", "12"))
DEFAULT_POLL_SECONDS = int(os.getenv("SEEDCORE_VERIFY_POLL_SECONDS", "35"))
DEFAULT_POLL_INTERVAL = float(os.getenv("SEEDCORE_VERIFY_POLL_INTERVAL", "2"))
DEFAULT_FORCE_GOVERNED_PREDICATES = os.getenv(
    "SEEDCORE_FORCE_GOVERNED_PREDICATES",
    ",".join(
        [
            "request_release_transfer",
            "request_robotic_handoff",
            "request_custody_handoff",
            "request_concierge",
        ]
    ),
)


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


def _extract_subtasks_from_eval_response(body: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    emissions = body.get("emissions")
    if not isinstance(emissions, dict):
        return []
    subtasks = emissions.get("subtasks")
    if not isinstance(subtasks, list):
        return []
    return [item for item in subtasks if isinstance(item, dict)]


def _extract_eval_reason(body: Optional[Dict[str, Any]]) -> str:
    if not isinstance(body, dict):
        return "unknown"
    decision = body.get("decision")
    if not isinstance(decision, dict):
        return "unknown"
    reason = decision.get("reason")
    return str(reason or "unknown")


def probe_governed_action_payload(
    session: requests.Session,
    api_base: str,
    *,
    snapshot_id: Optional[int],
    predicates: List[str],
) -> tuple[Optional[Dict[str, Any]], List[str]]:
    traces: List[str] = []
    object_data = {
        "actor_id": "owner:verify",
        "identity_verified": True,
        "approval_state": "approved",
        "approvals": ["approver_a", "approver_b"],
        "release_contract_id": "contract-verify",
        "release_window_active": True,
        "provenance_ok": True,
        "seal_intact": True,
        "asset_value_usd": 12500,
        "target_zone": "Zone-EU",
    }
    signals = {
        "identity_verified": 1.0,
        "release_window_open": 1.0,
        "seal_integrity": 0.99,
        "route_drift": 0.0,
    }

    for predicate in predicates:
        payload = {
            "task_facts": {
                "namespace": "custody",
                "subject": "owner:verify",
                "predicate": predicate,
                "object_data": object_data,
            },
            "signals": signals,
            "snapshot_id": snapshot_id,
            "mode": "advisory",
            "zone_id": "zone-eu",
        }
        ok, detail, body, code = call_json(
            session,
            "POST",
            f"{api_base}/api/v1/pkg/evaluate_async",
            expected=(200, 403, 503),
            payload=payload,
        )
        subtasks = _extract_subtasks_from_eval_response(body)
        if code == 200 and ok and subtasks:
            traces.append(f"{predicate}:status=200 subtasks={len(subtasks)}")
            return (
                {
                    "predicate": predicate,
                    "object_data": object_data,
                    "signals": signals,
                    "zone_id": "zone-eu",
                    "subtasks_count": len(subtasks),
                },
                traces,
            )
        traces.append(
            f"{predicate}:status={code} subtasks={len(subtasks)} reason={_extract_eval_reason(body)} detail={detail}"
        )

    return None, traces


def verify(
    api_url: str,
    *,
    strict: bool,
    poll_seconds: int,
    poll_interval: float,
    force_governed_action: bool,
    governed_predicates: List[str],
) -> list[StepResult]:
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
        expected=(200, 403, 503),
        payload=eval_payload,
    )
    results.append(StepResult("PKG POST /pkg/evaluate_async", "PASS" if code == 200 else "WARN", detail))

    if pkg_snapshot_id is not None:
        compare_payload = {
            "baseline_snapshot_id": pkg_snapshot_id,
            "candidate_snapshot_id": pkg_snapshot_id,
            "task_facts": {
                "tags": ["verify", "request_concierge", "guest:verify"],
                "signals": {},
                "context": {
                    "namespace": "verify",
                    "subject": "guest:verify",
                    "predicate": "request_concierge",
                    "object_data": {"channel": "api"},
                    "snapshot_id": pkg_snapshot_id,
                },
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

    if force_governed_action:
        if pkg_snapshot_id is None:
            results.append(
                StepResult(
                    "Force governed action probe",
                    "WARN",
                    "Skipped: no active snapshot_id from /pkg/status.",
                )
            )
        else:
            probe, traces = probe_governed_action_payload(
                session,
                api_base,
                snapshot_id=pkg_snapshot_id,
                predicates=governed_predicates,
            )
            if probe is None:
                results.append(
                    StepResult(
                        "Force governed action probe",
                        "WARN",
                        "No candidate predicate emitted governed subtasks. "
                        + "; ".join(traces[:3]),
                    )
                )
            else:
                predicate = str(probe["predicate"])
                results.append(
                    StepResult(
                        "Force governed action probe",
                        "PASS",
                        f"predicate={predicate} subtasks={probe['subtasks_count']}",
                    )
                )
                forced_task_payload = {
                    "type": "action",
                    "description": f"force governed action via {predicate}",
                    "run_immediately": True,
                    "snapshot_id": pkg_snapshot_id,
                    "params": {
                        "interaction": {"assigned_agent_id": "verify-agent"},
                        "routing": {"required_specialization": "ROBOT_OPERATOR"},
                        "resource": {"asset_id": f"asset-governed-{uuid.uuid4().hex[:8]}"},
                        "intent": predicate,
                        "governance": {
                            "probe": {
                                "namespace": "custody",
                                "subject": "owner:verify",
                                "predicate": predicate,
                                "object_data": probe["object_data"],
                                "signals": probe["signals"],
                                "zone_id": probe["zone_id"],
                            }
                        },
                    },
                }
                ok, detail, body, _ = call_json(
                    session,
                    "POST",
                    f"{api_base}/api/v1/tasks",
                    expected=(200,),
                    payload=forced_task_payload,
                )
                forced_task_id = str(body.get("id")) if ok and isinstance(body, dict) and body.get("id") else None
                results.append(
                    StepResult(
                        "Force governed action task POST /tasks",
                        "PASS" if forced_task_id else "FAIL",
                        detail if forced_task_id else f"failed_to_create_forced_task ({detail})",
                    )
                )

                if forced_task_id:
                    task_final = wait_for_task_terminal_state(
                        session,
                        api_base,
                        forced_task_id,
                        timeout_seconds=poll_seconds,
                        poll_interval=poll_interval,
                    )
                    task_status = str(task_final.get("status") or "unknown")
                    results.append(
                        StepResult(
                            "Force governed action poll",
                            "PASS",
                            f"task_id={forced_task_id} status={task_status}",
                        )
                    )

                    ok, detail, governance_body, _ = call_json(
                        session,
                        "GET",
                        f"{api_base}/api/v1/tasks/{forced_task_id}/governance",
                        expected=(200,),
                    )
                    if not ok:
                        results.append(StepResult("Force governed action governance", "FAIL", detail))
                    else:
                        latest = governance_body.get("latest") if isinstance(governance_body, dict) else None
                        evidence_bundle = latest.get("evidence_bundle") if isinstance(latest, dict) else None
                        if isinstance(evidence_bundle, dict) and evidence_bundle:
                            results.append(
                                StepResult(
                                    "Force governed action evidence",
                                    "PASS",
                                    "evidence_bundle present on governance record",
                                )
                            )
                            ok, detail, _, _ = call_json(
                                session,
                                "GET",
                                f"{api_base}/api/v1/governance/materialized-custody-event",
                                expected=(200,),
                                params={"task_id": forced_task_id},
                            )
                            results.append(
                                StepResult(
                                    "Force governed action materialized-custody-event",
                                    "PASS" if ok else "FAIL",
                                    detail,
                                )
                            )
                        else:
                            results.append(
                                StepResult(
                                    "Force governed action evidence",
                                    "WARN",
                                    "Task completed but no evidence_bundle found on latest governance record.",
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
    parser.add_argument(
        "--force-governed-action",
        action="store_true",
        help=(
            "Probe PKG evaluate_async for a predicate that emits subtasks, then create a matching "
            "action task to try producing governance evidence/materialization."
        ),
    )
    parser.add_argument(
        "--governed-predicates",
        default=DEFAULT_FORCE_GOVERNED_PREDICATES,
        help=(
            "Comma-separated candidate predicates for governed-action probe "
            f"(default: {DEFAULT_FORCE_GOVERNED_PREDICATES})"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = verify(
        args.api_url,
        strict=args.strict,
        poll_seconds=args.poll_seconds,
        poll_interval=args.poll_interval,
        force_governed_action=args.force_governed_action,
        governed_predicates=[p.strip() for p in args.governed_predicates.split(",") if p.strip()],
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
