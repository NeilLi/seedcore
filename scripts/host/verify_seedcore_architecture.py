#!/usr/bin/env python3
"""
Verify the canonical SeedCore API architecture for seedcore.ai.

This verifier is intentionally narrow and current:
- 7 active routers mounted under `/api/v1`
- 26 supported `/api/v1` endpoints
- no legacy router bleed-through
- optional live verification via `/health`, `/readyz`, and `/openapi.json`
- optional low-risk task smoke test

The smoke test uses a tighter seedcore.ai goal:
Expose a single canonical `/api/v1` control plane that durably accepts tasks,
reports system state clearly, and excludes legacy routes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
ROUTERS_DIR = SRC_ROOT / "seedcore" / "api" / "routers"
ROUTER_REGISTRY_FILE = ROUTERS_DIR / "__init__.py"
MAIN_FILE = SRC_ROOT / "seedcore" / "main.py"

API_PREFIX = "/api/v1"
DEFAULT_API_URL = os.getenv("SEEDCORE_API_URL", os.getenv("SEEDCORE_API", "http://127.0.0.1:8002"))
DEFAULT_TIMEOUT_S = float(os.getenv("SEEDCORE_API_TIMEOUT", "8.0"))

ACTIVE_ROUTER_SPECS = (
    ("Tasks", "tasks_router"),
    ("Source Registrations", "source_registrations_router"),
    ("Tracking Events", "tracking_events_router"),
    ("Control", "control_router"),
    ("Advisory", "advisory_router"),
    ("PKG", "pkg_router"),
    ("Capabilities", "capabilities_router"),
)

LEGACY_ROUTER_NAMES = (
    "dspy_router",
    "energy_router",
    "holon_router",
    "mfb_router",
    "ocps_router",
    "organism_router",
    "salience_router",
)

TIGHTENED_SEEDCORE_GOAL = (
    "Expose a single canonical /api/v1 control plane that durably accepts tasks, "
    "reports system state clearly, and excludes legacy routes."
)

SMOKE_TASK_DESCRIPTION = (
    "Verify the seedcore.ai canonical /api/v1 architecture and reject legacy route drift."
)


@dataclass(frozen=True, order=True)
class EndpointSpec:
    router_tag: str
    method: str
    path: str

    @property
    def operation(self) -> tuple[str, str]:
        return self.method, self.path


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


EXPECTED_ENDPOINTS = (
    EndpointSpec("Tasks", "POST", "/api/v1/tasks"),
    EndpointSpec("Tasks", "GET", "/api/v1/tasks"),
    EndpointSpec("Tasks", "GET", "/api/v1/tasks/{task_id}"),
    EndpointSpec("Tasks", "POST", "/api/v1/tasks/{task_id}/cancel"),
    EndpointSpec("Tasks", "GET", "/api/v1/tasks/{task_id}/logs"),
    EndpointSpec("Source Registrations", "POST", "/api/v1/source-registrations"),
    EndpointSpec("Source Registrations", "GET", "/api/v1/source-registrations/{registration_id}"),
    EndpointSpec("Source Registrations", "POST", "/api/v1/source-registrations/{registration_id}/artifacts"),
    EndpointSpec("Source Registrations", "POST", "/api/v1/source-registrations/{registration_id}/submit"),
    EndpointSpec("Source Registrations", "GET", "/api/v1/source-registrations/{registration_id}/verdict"),
    EndpointSpec("Tracking Events", "POST", "/api/v1/tracking-events"),
    EndpointSpec("Tracking Events", "GET", "/api/v1/tracking-events"),
    EndpointSpec("Tracking Events", "GET", "/api/v1/tracking-events/{event_id}"),
    EndpointSpec("Tracking Events", "GET", "/api/v1/source-registrations/{registration_id}/tracking-events"),
    EndpointSpec("Control", "GET", "/api/v1/facts"),
    EndpointSpec("Control", "GET", "/api/v1/facts/{fact_id}"),
    EndpointSpec("Control", "POST", "/api/v1/facts"),
    EndpointSpec("Control", "PATCH", "/api/v1/facts/{fact_id}"),
    EndpointSpec("Control", "DELETE", "/api/v1/facts/{fact_id}"),
    EndpointSpec("Advisory", "POST", "/api/v1/advisory"),
    EndpointSpec("PKG", "POST", "/api/v1/pkg/reload"),
    EndpointSpec("PKG", "GET", "/api/v1/pkg/status"),
    EndpointSpec("PKG", "POST", "/api/v1/pkg/evaluate_async"),
    EndpointSpec("PKG", "POST", "/api/v1/pkg/snapshots/compare"),
    EndpointSpec("PKG", "POST", "/api/v1/pkg/snapshots/{snapshot_id}/compile-rules"),
    EndpointSpec("Capabilities", "POST", "/api/v1/capabilities/register"),
)


def make_session(timeout: float, retries: int = 2, backoff: float = 0.25) -> requests.Session:
    """Create a small retrying session that other host scripts can reuse."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST", "PATCH", "DELETE", "HEAD", "OPTIONS"),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    original_request = session.request

    def with_default_timeout(method: str, url: str, **kwargs: Any):
        kwargs.setdefault("timeout", timeout)
        return original_request(method, url, **kwargs)

    session.request = with_default_timeout  # type: ignore[assignment]
    return session


def normalize_base_url(raw: str) -> str:
    return raw.rstrip("/")


def check_api_health(session: requests.Session, api_base: str) -> bool:
    """Compatibility helper reused by `hotel_os_simulator.py`."""
    url = normalize_base_url(api_base)
    for path in ("/health", "/readyz", "/openapi.json"):
        try:
            response = session.get(f"{url}{path}")
        except requests.RequestException:
            continue
        if response.status_code < 500:
            return True
    return False


def parse_python_literal(path: Path, variable_name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable_name:
                    return ast.literal_eval(node.value)
    raise RuntimeError(f"Could not find {variable_name} in {path}")


def extract_main_prefixes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prefixes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
            continue
        for keyword in node.keywords:
            if keyword.arg != "prefix":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefixes.add(keyword.value.value)
    return prefixes


def extract_router_endpoints(path: Path, router_tag: str) -> set[EndpointSpec]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    endpoints: set[EndpointSpec] = set()
    supported_methods = {"get", "post", "patch", "delete"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if decorator.func.attr.lower() not in supported_methods:
                continue
            if not isinstance(decorator.func.value, ast.Name):
                continue
            if decorator.func.value.id != "router":
                continue
            if not decorator.args:
                continue
            first_arg = decorator.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            endpoints.add(
                EndpointSpec(
                    router_tag=router_tag,
                    method=decorator.func.attr.upper(),
                    path=f"{API_PREFIX}{first_arg.value}",
                )
            )

    return endpoints


def expected_endpoint_operations() -> set[tuple[str, str]]:
    return {endpoint.operation for endpoint in EXPECTED_ENDPOINTS}


def expected_endpoints_by_router() -> dict[str, list[EndpointSpec]]:
    grouped: dict[str, list[EndpointSpec]] = {}
    for endpoint in EXPECTED_ENDPOINTS:
        grouped.setdefault(endpoint.router_tag, []).append(endpoint)
    return grouped


def actual_router_file(module_name: str) -> Path:
    return ROUTERS_DIR / f"{module_name}.py"


def format_endpoint_lines(endpoints: Iterable[EndpointSpec]) -> str:
    return "\n".join(f"  {endpoint.method:6} {endpoint.path}" for endpoint in sorted(endpoints))


def format_operation_diff(
    missing: Iterable[tuple[str, str]],
    extra: Iterable[tuple[str, str]],
) -> str:
    lines: list[str] = []
    missing_list = sorted(missing)
    extra_list = sorted(extra)
    if missing_list:
        lines.append("Missing:")
        lines.extend(f"  {method:6} {path}" for method, path in missing_list)
    if extra_list:
        lines.append("Extra:")
        lines.extend(f"  {method:6} {path}" for method, path in extra_list)
    return "\n".join(lines) if lines else "No diff"


def verify_static_contract() -> list[CheckResult]:
    results: list[CheckResult] = []

    registry_specs = parse_python_literal(ROUTER_REGISTRY_FILE, "ACTIVE_ROUTER_SPECS")
    legacy_names = parse_python_literal(ROUTER_REGISTRY_FILE, "LEGACY_ROUTER_NAMES")

    results.append(
        CheckResult(
            name="router-registry",
            ok=tuple(registry_specs) == ACTIVE_ROUTER_SPECS,
            detail=(
                f"expected {ACTIVE_ROUTER_SPECS}, found {tuple(registry_specs)}"
                if tuple(registry_specs) != ACTIVE_ROUTER_SPECS
                else f"{len(ACTIVE_ROUTER_SPECS)} active routers in canonical order"
            ),
        )
    )
    results.append(
        CheckResult(
            name="legacy-router-archive",
            ok=tuple(legacy_names) == LEGACY_ROUTER_NAMES,
            detail=(
                f"expected {LEGACY_ROUTER_NAMES}, found {tuple(legacy_names)}"
                if tuple(legacy_names) != LEGACY_ROUTER_NAMES
                else f"{len(LEGACY_ROUTER_NAMES)} legacy routers remain archived"
            ),
        )
    )

    prefixes = extract_main_prefixes(MAIN_FILE)
    results.append(
        CheckResult(
            name="main-prefix",
            ok=API_PREFIX in prefixes,
            detail=(
                f"main.py include_router prefixes: {sorted(prefixes)}"
                if API_PREFIX not in prefixes
                else f"main.py mounts active routers at {API_PREFIX}"
            ),
        )
    )

    actual_endpoints: set[EndpointSpec] = set()
    for router_tag, module_name in ACTIVE_ROUTER_SPECS:
        router_file = actual_router_file(module_name)
        actual_endpoints.update(extract_router_endpoints(router_file, router_tag))

    expected = set(EXPECTED_ENDPOINTS)
    missing = expected - actual_endpoints
    extra = actual_endpoints - expected

    results.append(
        CheckResult(
            name="source-endpoint-inventory",
            ok=not missing and not extra and len(actual_endpoints) == 26,
            detail=(
                "26 /api/v1 endpoints matched across 7 active routers"
                if not missing and not extra and len(actual_endpoints) == 26
                else format_operation_diff(
                    ((endpoint.method, endpoint.path) for endpoint in missing),
                    ((endpoint.method, endpoint.path) for endpoint in extra),
                )
            ),
        )
    )

    return results


def verify_health_endpoints(session: requests.Session, api_url: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for path in ("/health", "/readyz"):
        url = f"{api_url}{path}"
        try:
            response = session.get(url)
            ok = response.status_code == 200
            detail = f"HTTP {response.status_code}"
            if ok:
                try:
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("status"):
                        detail = f"HTTP 200 status={payload.get('status')}"
                except ValueError:
                    pass
        except requests.RequestException as exc:
            ok = False
            detail = str(exc)
        results.append(CheckResult(name=f"live{path}", ok=ok, detail=detail))
    return results


def parse_openapi_operations(document: dict[str, Any]) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path, path_item in (document.get("paths") or {}).items():
        if not path.startswith(API_PREFIX):
            continue
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "patch", "delete"}:
                continue
            if isinstance(operation, dict):
                operations.add((method.upper(), path))
    return operations


def verify_openapi_contract(session: requests.Session, api_url: str) -> list[CheckResult]:
    url = f"{api_url}/openapi.json"
    try:
        response = session.get(url)
        response.raise_for_status()
        document = response.json()
    except (requests.RequestException, ValueError) as exc:
        return [CheckResult(name="live-openapi", ok=False, detail=str(exc))]

    actual_operations = parse_openapi_operations(document)
    expected_operations = expected_endpoint_operations()
    missing = expected_operations - actual_operations
    extra = actual_operations - expected_operations

    return [
        CheckResult(
            name="live-openapi",
            ok=not missing and not extra and len(actual_operations) == 26,
            detail=(
                "OpenAPI exposes the canonical 26 /api/v1 operations"
                if not missing and not extra and len(actual_operations) == 26
                else format_operation_diff(missing, extra)
            ),
        )
    ]


def smoke_task_payload() -> dict[str, Any]:
    return {
        "type": "query",
        "description": SMOKE_TASK_DESCRIPTION,
        "domain": "seedcore.ai",
        "run_immediately": False,
        "params": {
            "goal": TIGHTENED_SEEDCORE_GOAL,
            "verification_mode": "architecture",
            "api_version": "v1",
            "expected_active_router_count": len(ACTIVE_ROUTER_SPECS),
            "expected_endpoint_count": len(EXPECTED_ENDPOINTS),
            "legacy_routes_allowed": False,
        },
    }


def parse_json_response(response: requests.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object, received {type(payload).__name__}")
    return payload


def smoke_test_tasks(session: requests.Session, api_url: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    base = f"{api_url}{API_PREFIX}"
    created_task_id: str | None = None

    try:
        create_response = session.post(f"{base}/tasks", json=smoke_task_payload())
        create_payload = parse_json_response(create_response)
        created_task_id = str(create_payload["id"])
        uuid.UUID(created_task_id)
        results.append(
            CheckResult(
                name="smoke-create-task",
                ok=create_response.status_code == 200,
                detail=f"created task {created_task_id} status={create_payload.get('status')}",
            )
        )
    except Exception as exc:
        results.append(CheckResult(name="smoke-create-task", ok=False, detail=str(exc)))
        return results

    try:
        get_response = session.get(f"{base}/tasks/{created_task_id}")
        get_payload = parse_json_response(get_response)
        ok = get_response.status_code == 200 and str(get_payload.get("id")) == created_task_id
        detail = f"task status={get_payload.get('status')}"
        results.append(CheckResult(name="smoke-get-task", ok=ok, detail=detail))
    except Exception as exc:
        results.append(CheckResult(name="smoke-get-task", ok=False, detail=str(exc)))

    try:
        list_response = session.get(f"{base}/tasks", params={"limit": 10, "offset": 0})
        list_payload = parse_json_response(list_response)
        items = list_payload.get("items") or []
        found = any(str(item.get("id")) == created_task_id for item in items if isinstance(item, dict))
        detail = f"listed {len(items)} tasks"
        results.append(CheckResult(name="smoke-list-tasks", ok=list_response.status_code == 200 and found, detail=detail))
    except Exception as exc:
        results.append(CheckResult(name="smoke-list-tasks", ok=False, detail=str(exc)))

    try:
        cancel_response = session.post(f"{base}/tasks/{created_task_id}/cancel")
        cancel_payload = parse_json_response(cancel_response)
        status = str(cancel_payload.get("status"))
        ok = cancel_response.status_code == 200 and status in {"cancelled", "completed", "failed"}
        results.append(CheckResult(name="smoke-cancel-task", ok=ok, detail=f"status={status}"))
    except Exception as exc:
        results.append(CheckResult(name="smoke-cancel-task", ok=False, detail=str(exc)))

    try:
        with session.get(
            f"{base}/tasks/{created_task_id}/logs",
            params={"poll_interval": 0.05},
            stream=True,
            timeout=max(DEFAULT_TIMEOUT_S, 5.0),
        ) as log_response:
            log_response.raise_for_status()
            content_type = log_response.headers.get("content-type", "")
            lines: list[str] = []
            for line in log_response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                lines.append(line)
                if len(lines) >= 6:
                    break
            ok = "text/event-stream" in content_type and any(line.startswith("data: ") for line in lines)
            detail = f"content-type={content_type}, events={len(lines)}"
            results.append(CheckResult(name="smoke-task-logs", ok=ok, detail=detail))
    except Exception as exc:
        results.append(CheckResult(name="smoke-task-logs", ok=False, detail=str(exc)))

    return results


def normalize_task_payload(line_obj: dict[str, Any], *, default_run_immediately: bool) -> dict[str, Any]:
    """Normalize a JSONL task object into the task-create API payload shape."""
    obj = dict(line_obj)

    if "type" not in obj and "task_type" in obj:
        obj["type"] = obj.pop("task_type")
    if "description" not in obj and "desc" in obj:
        obj["description"] = obj.pop("desc")

    if "type" not in obj or "description" not in obj:
        raise ValueError("Task must include 'type' and 'description'")

    if "params" not in obj or obj["params"] is None:
        obj["params"] = {}

    if "run_immediately" not in obj:
        obj["run_immediately"] = default_run_immediately

    allowed = {"type", "description", "params", "domain", "run_immediately", "snapshot_id"}
    return {key: value for key, value in obj.items() if key in allowed}


def load_jsonl_tasks(
    scenario_file: Path,
    *,
    default_run_immediately: bool,
    limit: int | None,
) -> list[tuple[int, dict[str, Any]]]:
    loaded: list[tuple[int, dict[str, Any]]] = []
    with scenario_file.open("r", encoding="utf-8") as handle:
        for lineno, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            payload = normalize_task_payload(json.loads(line), default_run_immediately=default_run_immediately)
            loaded.append((lineno, payload))
            if limit is not None and limit > 0 and len(loaded) >= limit:
                break
    return loaded


def fetch_task(session: requests.Session, api_url: str, task_id: str) -> dict[str, Any]:
    response = session.get(f"{api_url}{API_PREFIX}/tasks/{task_id}")
    response.raise_for_status()
    return parse_json_response(response)


def wait_for_terminal_status(
    session: requests.Session,
    api_url: str,
    task_id: str,
    *,
    timeout_s: float,
    poll_interval_s: float,
) -> tuple[str, dict[str, Any]]:
    deadline = time.time() + timeout_s
    last_payload: dict[str, Any] | None = None
    while time.time() <= deadline:
        payload = fetch_task(session, api_url, task_id)
        last_payload = payload
        status = str(payload.get("status", "")).lower()
        if status in {"completed", "failed", "cancelled"}:
            return status, payload
        time.sleep(poll_interval_s)

    if last_payload is None:
        raise RuntimeError(f"Task {task_id} could not be fetched during wait")
    return str(last_payload.get("status", "unknown")).lower(), last_payload


def summarize_statuses(statuses: list[str]) -> str:
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{status}={counts[status]}" for status in sorted(counts))


def run_scenario_file(
    session: requests.Session,
    api_url: str,
    scenario_file: Path,
    *,
    default_run_immediately: bool,
    limit: int | None,
    timeout_s: float,
    poll_interval_s: float,
    require_terminal: bool,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    base = f"{api_url}{API_PREFIX}"

    if not scenario_file.exists():
        return [CheckResult(name="scenario-load", ok=False, detail=f"File not found: {scenario_file}")]

    try:
        tasks = load_jsonl_tasks(
            scenario_file,
            default_run_immediately=default_run_immediately,
            limit=limit,
        )
    except Exception as exc:
        return [CheckResult(name="scenario-load", ok=False, detail=str(exc))]

    if not tasks:
        return [CheckResult(name="scenario-load", ok=False, detail=f"No runnable JSONL tasks found in {scenario_file}")]

    results.append(
        CheckResult(
            name="scenario-load",
            ok=True,
            detail=f"loaded {len(tasks)} tasks from {scenario_file}",
        )
    )

    submitted: list[tuple[int, str, str]] = []
    submit_failures: list[str] = []

    for lineno, payload in tasks:
        try:
            response = session.post(f"{base}/tasks", json=payload)
            response.raise_for_status()
            created = parse_json_response(response)
            task_id = str(created["id"])
            uuid.UUID(task_id)
            submitted.append((lineno, task_id, payload["description"]))
        except Exception as exc:
            submit_failures.append(f"line {lineno}: {exc}")

    results.append(
        CheckResult(
            name="scenario-submit",
            ok=not submit_failures,
            detail=(
                f"submitted {len(submitted)}/{len(tasks)} tasks"
                if not submit_failures
                else "; ".join(submit_failures[:5])
            ),
        )
    )

    if not submitted:
        return results

    observed_statuses: list[str] = []
    not_started: list[str] = []
    failures: list[str] = []

    for lineno, task_id, description in submitted:
        try:
            status, payload = wait_for_terminal_status(
                session,
                api_url,
                task_id,
                timeout_s=timeout_s,
                poll_interval_s=poll_interval_s,
            )
            observed_statuses.append(status)
            short_description = description[:48] + ("..." if len(description) > 48 else "")
            if status in {"created", "queued", "unknown", ""}:
                not_started.append(f"line {lineno} {task_id[:8]} status={status} desc={short_description}")
            elif status in {"failed", "cancelled"}:
                failures.append(f"line {lineno} {task_id[:8]} status={status} desc={short_description}")
        except Exception as exc:
            failures.append(f"line {lineno} {task_id[:8]} error={exc}")

    results.append(
        CheckResult(
            name="scenario-progress",
            ok=not not_started,
            detail=(
                summarize_statuses(observed_statuses)
                if not not_started
                else "; ".join(not_started[:5])
            ),
        )
    )
    if require_terminal:
        results.append(
            CheckResult(
                name="scenario-completed",
                ok=not failures and observed_statuses and all(status == "completed" for status in observed_statuses),
                detail=(
                    f"all {len(observed_statuses)} scenario tasks completed"
                    if not failures and observed_statuses and all(status == "completed" for status in observed_statuses)
                    else "; ".join(failures[:5]) if failures else summarize_statuses(observed_statuses)
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                name="scenario-outcome",
                ok=not failures and observed_statuses and all(status in {"running", "completed"} for status in observed_statuses),
                detail=(
                    summarize_statuses(observed_statuses)
                    if not failures and observed_statuses and all(status in {"running", "completed"} for status in observed_statuses)
                    else "; ".join(failures[:5]) if failures else summarize_statuses(observed_statuses)
                ),
            )
        )

    return results


def print_expected_inventory() -> None:
    print("Canonical /api/v1 endpoint inventory")
    for router_tag, endpoints in expected_endpoints_by_router().items():
        print(f"[{router_tag}]")
        for endpoint in endpoints:
            print(f"  {endpoint.method:6} {endpoint.path}")


def print_results(results: list[CheckResult]) -> None:
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {result.detail}")


def summarize(results: list[CheckResult]) -> tuple[int, int]:
    failures = sum(1 for result in results if not result.ok)
    passes = len(results) - failures
    return passes, failures


def build_json_report(results: list[CheckResult], api_url: str, strict: bool) -> str:
    passes, failures = summarize(results)
    payload = {
        "goal": TIGHTENED_SEEDCORE_GOAL,
        "api_url": api_url,
        "strict": strict,
        "expected_active_router_count": len(ACTIVE_ROUTER_SPECS),
        "expected_endpoint_count": len(EXPECTED_ENDPOINTS),
        "results": [result.__dict__ for result in results],
        "summary": {
            "passes": passes,
            "failures": failures,
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the canonical SeedCore /api/v1 architecture for seedcore.ai.",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"SeedCore API base URL (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT_S})",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip live HTTP checks and only verify source files.",
    )
    parser.add_argument(
        "--skip-smoke-task",
        action="store_true",
        help="Skip the low-risk task lifecycle smoke test.",
    )
    parser.add_argument(
        "--show-endpoints",
        action="store_true",
        help="Print the canonical endpoint inventory before running checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verification report as JSON.",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="Exit 0 even if checks fail.",
    )
    parser.add_argument(
        "--scenario-file",
        type=Path,
        help="Run a real scenario by loading task payloads from a JSONL file.",
    )
    parser.add_argument(
        "--scenario-limit",
        type=int,
        help="Only submit the first N runnable tasks from the scenario file.",
    )
    parser.add_argument(
        "--scenario-timeout",
        type=float,
        default=float(os.getenv("SEEDCORE_SCENARIO_TIMEOUT", "60.0")),
        help="Seconds to wait for each scenario task to reach a terminal state.",
    )
    parser.add_argument(
        "--scenario-poll-interval",
        type=float,
        default=float(os.getenv("SEEDCORE_SCENARIO_POLL_INTERVAL", "2.0")),
        help="Seconds between scenario task status polls.",
    )
    parser.add_argument(
        "--scenario-draft",
        action="store_true",
        help="Default scenario tasks without run_immediately to draft mode instead of execution mode.",
    )
    parser.add_argument(
        "--scenario-require-terminal",
        action="store_true",
        help="Require every scenario task to complete within the timeout instead of only proving execution started.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    api_url = normalize_base_url(args.api_url)
    strict = not args.no_strict

    if args.show_endpoints and not args.json:
        print_expected_inventory()
        print()

    results = verify_static_contract()

    if not args.skip_live:
        session = make_session(timeout=args.timeout)
        results.extend(verify_health_endpoints(session, api_url))
        results.extend(verify_openapi_contract(session, api_url))
        if not args.skip_smoke_task:
            results.extend(smoke_test_tasks(session, api_url))
        if args.scenario_file:
            results.extend(
                run_scenario_file(
                    session,
                    api_url,
                    args.scenario_file,
                    default_run_immediately=not args.scenario_draft,
                    limit=args.scenario_limit,
                    timeout_s=args.scenario_timeout,
                    poll_interval_s=args.scenario_poll_interval,
                    require_terminal=args.scenario_require_terminal,
                )
            )

    if args.json:
        print(build_json_report(results, api_url=api_url, strict=strict))
    else:
        print(f"SeedCore API verification target: {api_url}")
        print(f"Tightened seedcore.ai goal: {TIGHTENED_SEEDCORE_GOAL}")
        print_results(results)
        passes, failures = summarize(results)
        print(f"Summary: {passes} passed, {failures} failed")

    if strict and any(not result.ok for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
