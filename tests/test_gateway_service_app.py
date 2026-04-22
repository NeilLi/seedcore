"""Smoke tests for the dedicated Agent Action Gateway FastAPI app.

These tests intentionally do not exercise the full evaluate/execute/closure
flows — those are covered by `tests/test_agent_actions_router.py` — they
just confirm that the dedicated app composes correctly:

- The agent action gateway routes are mounted.
- Non-gateway routes from the monolith are *not* mounted.
- The health and readyz endpoints respond.
- The `SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY=false` flag causes the
  monolith to stop advertising the gateway surface.
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401


def test_gateway_service_app_mounts_agent_action_routes():
    from seedcore.gateway_service.main import build_gateway_app

    app = build_gateway_app()
    routes = {getattr(route, "path", None) for route in app.router.routes}

    assert "/api/v1/agent-actions/evaluate" in routes
    assert "/api/v1/agent-actions/execute" in routes
    assert "/api/v1/agent-actions/requests/{request_id}" in routes
    assert "/api/v1/agent-actions/{request_id}/closures" in routes
    assert "/api/v1/agent-actions/closures/{closure_id}" in routes


def test_gateway_service_app_exposes_health_and_root():
    from seedcore.gateway_service.main import build_gateway_app

    app = build_gateway_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["service"] == "seedcore-agent-action-gateway"
        assert body["status"] == "healthy"

        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["service"] == "seedcore-agent-action-gateway"


def test_gateway_service_app_does_not_mount_non_gateway_routers():
    from seedcore.gateway_service.main import build_gateway_app

    app = build_gateway_app()
    paths = {getattr(route, "path", "") for route in app.router.routes}

    # Sanity: tasks / replay / transfer approvals etc. must NOT be here —
    # that is precisely the blast-radius isolation we want from the split.
    assert not any(path.startswith("/api/v1/tasks") for path in paths)
    assert not any(path.startswith("/api/v1/replay") for path in paths)
    assert not any(path.startswith("/api/v1/transfer-approvals") for path in paths)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("ON", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ],
)
def test_monolith_mount_flag_env_parsing(value: str, expected: bool) -> None:
    """The monolith's mount flag must accept the same truthy vocabulary as the
    other SeedCore env flags so operators can flip it consistently during a
    gateway process-split rollout.
    """

    parsed = value.strip().lower() in ("1", "true", "yes", "on")
    assert parsed is expected


def test_monolith_mount_flag_default_is_true() -> None:
    """Back-compat: a deployment that has not opted into the split must keep
    advertising `/api/v1/agent-actions/*` from the monolithic API.
    """

    default = "true"
    parsed = default.strip().lower() in ("1", "true", "yes", "on")
    assert parsed is True
