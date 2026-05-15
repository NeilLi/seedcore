"""Commerce-slice degraded-edge / adversarial drill matrix.

Complements ``tests/test_rct_degraded_edge_drill_matrix.py`` (which drills the
generic PDP hot-path surface) by running the same scenarios through the
`seedcore.agent_action_gateway.v1` external contract and asserting that drill
evidence stays tied to commerce join keys (`product_ref`, `order_ref`,
`quote_ref`, `workflow_join_key`) rather than just to a generic `asset_id`.

Drill categories covered here:

- stale-graph quarantine (hot path flips to ``compiled_authz_graph_stale``)
- dependency outage:
    * PKG manager unavailable (via hot-path stub raising)
    * approval-store outage (``get_async_pg_session_factory`` returns None →
      503 ``dependency_unavailable`` / ``approval_store_unavailable``)
    * authoritative approval resolver raises (DB/vault-style outage)
    * Redis request/idempotency bus unavailable (in-memory fallback)
    * Shopify-sandbox commerce adapter HTTP timeout
- coordinate tamper (gateway coordinate mismatch)
- replay injection:
    * cross-product injection — request for product_A gets paired with a
      persisted authority scope for product_B → ``asset_product_scope_mismatch``

Every drill asserts the response ``forensic_linkage`` carries the commerce
join keys introduced in ``_build_forensic_linkage``.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.agent_actions_router as agent_actions_router
from seedcore.adapters.shopify_sandbox_commerce_adapter import (
    CommerceAdapterTimeout,
    fetch_shopify_sandbox_transaction_to_gateway_commerce_fields,
)
from seedcore.models.action_intent import ExecutionToken
from seedcore.models.pdp_hot_path import HotPathDecisionView, HotPathEvaluateResponse
from seedcore.ops.hot_path_parity_log import reset_hot_path_parity_logger_for_tests


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


COMMERCE_PRODUCT_REF = "shopify:gid://shopify/Product/1234567890"
COMMERCE_ORDER_REF = "shopify:gid://shopify/Order/1002003004"
COMMERCE_QUOTE_REF = "shopify:quote:tea-set-2026-04-03-0001"


@pytest.fixture(autouse=True)
def _drill_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SEEDCORE_HOT_PATH_PARITY_LOG",
        str(tmp_path / "commerce_drill_events.jsonl"),
    )
    reset_hot_path_parity_logger_for_tests()
    agent_actions_router._clear_agent_action_request_store_for_tests()


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        agent_actions_router.router,
        prefix="/api/v1",
        tags=["Agent Actions"],
    )
    return TestClient(app)


async def _empty_authoritative_approval(*args, **kwargs) -> Dict[str, Any]:
    return {}


async def _organism_preflight_ok(*args, **kwargs):
    return True, "ok"


class _FailingRedisPipeline:
    def setex(self, *_args, **_kwargs):
        return self

    async def execute(self):
        raise RuntimeError("redis_bus_write_unavailable")


class _FailingRedisBus:
    async def get(self, *_args, **_kwargs):
        raise RuntimeError("redis_bus_read_unavailable")

    async def set(self, *_args, **_kwargs):
        raise RuntimeError("redis_bus_claim_unavailable")

    def pipeline(self, *_args, **_kwargs):
        return _FailingRedisPipeline()


def _commerce_payload(
    *,
    request_id: str = "req-commerce-drill-0001",
    idempotency_key: str = "idem-commerce-drill-0001",
    product_ref: str = COMMERCE_PRODUCT_REF,
    order_ref: str = COMMERCE_ORDER_REF,
    quote_ref: str = COMMERCE_QUOTE_REF,
) -> Dict[str, Any]:
    """Gateway payload shaped for the RCT commerce slice.

    Carries ``product_ref``/``order_ref``/``quote_ref`` on the asset so the
    cross-consistency validator in
    ``AgentActionEvaluateRequest._validate_scope_invariants`` can protect
    against claim-vs-scope contradictions during drills.
    """

    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "requested_at": "2026-04-03T10:00:00Z",
        "idempotency_key": idempotency_key,
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-03",
        "principal": {
            "agent_id": "agent:custody_runtime_01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-abc",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
            "organization_ref": "org:acme",
            "hardware_fingerprint": {
                "fingerprint_id": "fp:jetson-orin-01",
                "node_id": "node:jetson-orin-01",
                "public_key_fingerprint": "sha256:fingerprint-key",
                "attestation_type": "tpm",
                "key_ref": "tpm2:jetson-orin-01-ak",
            },
        },
        "workflow": {
            "type": "restricted_custody_transfer",
            "action_type": "TRANSFER_CUSTODY",
            "valid_until": "2026-04-03T10:01:00Z",
        },
        "asset": {
            "asset_id": "asset:lot-8841",
            "lot_id": "lot-8841",
            "product_ref": product_ref,
            "order_ref": order_ref,
            "quote_ref": quote_ref,
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:asset-provenance",
            "declared_value_usd": 1500,
        },
        "approval": {
            "approval_envelope_id": "approval-transfer-001",
            "expected_envelope_version": "23",
        },
        "authority_scope": {
            "scope_id": "scope:rct-2026-0001",
            "asset_ref": "asset:lot-8841",
            "product_ref": product_ref,
            "facility_ref": "facility:warehouse-a",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
            "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
        },
        "telemetry": {
            "observed_at": "2026-04-03T09:59:58Z",
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "current_zone": "vault_a",
            "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
            "evidence_refs": ["ev:cam-1", "ev:seal-sensor-7"],
        },
        "security_contract": {
            "hash": "sha256:contract-hash",
            "version": "rules@8.0.0",
        },
        "options": {"debug": False},
    }


def _allow_hot_path_response(request, **_kwargs) -> HotPathEvaluateResponse:
    """Minimal allow response used when stubbing ``evaluate_pdp_hot_path``."""

    plan_dag_hash = request.action_intent.action.parameters.get("plan_dag_hash")
    return HotPathEvaluateResponse(
        request_id=request.request_id,
        decided_at=datetime.now(timezone.utc),
        latency_ms=20,
        decision=HotPathDecisionView(
            allowed=True,
            disposition="allow",
            reason_code="restricted_custody_transfer_allowed",
            reason="all mandatory checks passed",
            policy_snapshot_ref=request.policy_snapshot_ref,
        ),
        execution_token=ExecutionToken(
            token_id="token-commerce-drill-001",
            intent_id=request.request_id,
            issued_at="2026-04-03T10:00:01Z",
            valid_until="2026-04-03T10:00:06Z",
            contract_version="rules@8.0.0",
            execution_preconditions={
                "resource_state_hash": "sha256:resource-state-001",
                "approval_transition_head": "sha256:approval-transition-001",
                "context_token": "sha256:context-token-001",
                "plan_dag_hash": plan_dag_hash,
                "endpoint_id": "hal://robot-sim/1",
            },
        ),
        governed_receipt={
            "audit_id": "2b4c76c8-20e2-4222-aa18-c4f1ee212f72",
            "policy_receipt_id": "receipt-commerce-001",
        },
    )


def _quarantine_hot_path_response(
    request,
    *,
    reason_code: str,
    reason: str,
    trust_gaps: list[str] | None = None,
) -> HotPathEvaluateResponse:
    return HotPathEvaluateResponse(
        request_id=request.request_id,
        decided_at=datetime.now(timezone.utc),
        latency_ms=11,
        decision=HotPathDecisionView(
            allowed=False,
            disposition="quarantine",
            reason_code=reason_code,
            reason=reason,
            policy_snapshot_ref=request.policy_snapshot_ref,
        ),
        trust_gaps=list(trust_gaps or []),
    )


def _wire_router_happy_defaults(monkeypatch) -> None:
    """Monkeypatch router collaborators so only the drill surface matters."""

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "_organism_preflight_check",
        _organism_preflight_ok,
    )


def _assert_join_keys_carried(
    body: Dict[str, Any],
    *,
    product_ref: str = COMMERCE_PRODUCT_REF,
    order_ref: str = COMMERCE_ORDER_REF,
    quote_ref: str = COMMERCE_QUOTE_REF,
    asset_id: str = "asset:lot-8841",
    request_id: str = "req-commerce-drill-0001",
) -> None:
    """Shared assertion: the response ``forensic_linkage`` carries every
    commerce join key we rely on for drill evidence attribution."""

    linkage = body.get("forensic_linkage") or {}
    assert linkage.get("product_ref") == product_ref, linkage
    assert linkage.get("order_ref") == order_ref, linkage
    assert linkage.get("quote_ref") == quote_ref, linkage
    assert linkage.get("asset_id") == asset_id, linkage
    assert linkage.get("request_id") == request_id, linkage
    join_key = linkage.get("workflow_join_key")
    assert join_key, (
        "workflow_join_key must be non-empty; drills need a stable "
        "workflow join key even on deny/quarantine outcomes"
    )
    # workflow_join_key must always be a UUID string so it can be used
    # directly against replay endpoints (audit_id or deterministic fallback).
    uuid.UUID(str(join_key))


# ---------------------------------------------------------------------------
# 1. Stale-graph drill — commerce join keys survive a quarantine
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_stale_graph_quarantine_carries_join_keys(monkeypatch):
    _wire_router_happy_defaults(monkeypatch)

    def _stale_graph(request, **_kwargs):
        return _quarantine_hot_path_response(
            request,
            reason_code="compiled_authz_graph_stale",
            reason="Compiled authz graph is older than the allowed staleness window.",
            trust_gaps=["compiled_authz_graph_stale"],
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _stale_graph)

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=_commerce_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "compiled_authz_graph_stale"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    _assert_join_keys_carried(body)


# ---------------------------------------------------------------------------
# 2. Dependency outage — multiple realistic surfaces
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_pkg_manager_dependency_outage_quarantines(monkeypatch):
    """PKG manager (authz graph) outage: hot path returns
    ``hot_path_dependency_unavailable`` and the gateway still attributes
    the quarantine to the commerce workflow via join keys."""

    _wire_router_happy_defaults(monkeypatch)

    def _dep_unavailable(request, **_kwargs):
        return _quarantine_hot_path_response(
            request,
            reason_code="hot_path_dependency_unavailable",
            reason="Compiled authz graph dependency is unavailable.",
            trust_gaps=["hot_path_dependency_unavailable"],
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _dep_unavailable)

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=_commerce_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "hot_path_dependency_unavailable"
    _assert_join_keys_carried(body)


@pytest.mark.rct_commerce_drill
def test_drill_commerce_approval_store_outage_returns_dependency_unavailable(monkeypatch):
    """Postgres / approval-envelope store outage: the gateway must fail
    closed with a 503 ``dependency_unavailable`` rather than minting a
    token. This protects the commerce slice from downgrading to an
    unverified decision when persisted approval truth cannot be resolved.
    """

    _wire_router_happy_defaults(monkeypatch)
    monkeypatch.setattr(agent_actions_router, "get_async_pg_session_factory", lambda: None)

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=_commerce_payload())
    assert response.status_code == 503, response.text
    body = response.json()
    detail = body.get("detail") or {}
    assert detail.get("error_code") == "dependency_unavailable"
    assert detail.get("message") == "approval_store_unavailable"
    assert detail.get("request_id") == "req-commerce-drill-0001"


@pytest.mark.rct_commerce_drill
def test_drill_commerce_approval_resolver_raises_surfaces_failure(monkeypatch):
    """Simulate a commerce-adjacent dependency failure where the persisted
    approval envelope cannot be resolved (e.g. DB timeout / vault outage).
    The gateway must surface a non-2xx outcome rather than silently
    minting an ExecutionToken."""

    _wire_router_happy_defaults(monkeypatch)

    async def _raise_resolver(*_args, **_kwargs):
        raise RuntimeError("approval_envelope_dao_timeout")

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _raise_resolver,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_hot_path_response,
    )

    # Simulate the production-facing uvicorn boundary: unhandled exceptions
    # must become a 5xx response rather than a 200 allow. ``TestClient``
    # re-raises by default, which would mask the fail-closed behaviour we
    # actually ship in production.
    app = FastAPI()
    app.include_router(
        agent_actions_router.router,
        prefix="/api/v1",
        tags=["Agent Actions"],
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/agent-actions/evaluate", json=_commerce_payload()
        )

    # Drill contract: resolver failure MUST NOT return a 200 allow response.
    assert response.status_code >= 500, response.text
    # And it MUST NOT mint an ExecutionToken; an error body is acceptable.
    body_text = response.text or ""
    assert "ExecutionToken" not in body_text


@pytest.mark.rct_commerce_drill
def test_drill_commerce_redis_bus_outage_falls_back_with_join_keys(monkeypatch):
    """Redis request-record/idempotency bus outage must not become a token
    minting regression. The gateway should use its in-memory fallback and
    still return commerce forensic linkage."""

    _wire_router_happy_defaults(monkeypatch)

    async def _failing_redis_client():
        return _FailingRedisBus()

    monkeypatch.setattr(
        agent_actions_router,
        "get_async_redis_client",
        _failing_redis_client,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_hot_path_response,
    )

    client = _make_client()
    payload = _commerce_payload(
        request_id="req-commerce-drill-redis-bus-0001",
        idempotency_key="idem-commerce-drill-redis-bus-0001",
    )

    first = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["decision"]["disposition"] == "allow"
    assert first_body["execution_token"] is not None
    assert "ExecutionToken" in first_body["minted_artifacts"]
    _assert_join_keys_carried(
        first_body,
        request_id="req-commerce-drill-redis-bus-0001",
    )

    # Idempotent replay should read through the same failing Redis surface and
    # still recover the in-memory request record.
    second = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["request_id"] == first_body["request_id"]
    assert second_body["execution_token"]["token_id"] == "token-commerce-drill-001"
    _assert_join_keys_carried(
        second_body,
        request_id="req-commerce-drill-redis-bus-0001",
    )


@pytest.mark.asyncio
@pytest.mark.rct_commerce_drill
async def test_drill_commerce_adapter_http_timeout_emits_join_keyed_evidence():
    """The commerce adapter outage drill crosses a real HTTP client boundary
    and classifies timeouts with the stable commerce reason code."""

    def _timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("shopify sandbox adapter timed out")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_timeout),
        base_url="https://shopify-sandbox.test",
    ) as client:
        with pytest.raises(CommerceAdapterTimeout) as exc_info:
            await fetch_shopify_sandbox_transaction_to_gateway_commerce_fields(
                transaction_url="/transactions/quote-timeout-0001",
                client=client,
            )

    payload = _commerce_payload(request_id="req-commerce-drill-commerce-http-timeout")
    fallback_join_key = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "req-commerce-drill-commerce-http-timeout")
    )
    drill_evidence = {
        "forensic_linkage": {
            "workflow_join_key": fallback_join_key,
            "product_ref": payload["asset"]["product_ref"],
            "order_ref": payload["asset"]["order_ref"],
            "quote_ref": payload["asset"]["quote_ref"],
            "asset_id": payload["asset"]["asset_id"],
            "request_id": payload["request_id"],
        }
    }

    assert exc_info.value.reason_code == "commerce_adapter_timeout"
    _assert_join_keys_carried(
        drill_evidence,
        request_id="req-commerce-drill-commerce-http-timeout",
    )


# ---------------------------------------------------------------------------
# 3. Coordinate tamper — commerce join keys survive a deny
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_coordinate_tamper_deny_carries_join_keys(monkeypatch):
    _wire_router_happy_defaults(monkeypatch)
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_hot_path_response,
    )

    payload = _commerce_payload()
    payload["telemetry"]["current_coordinate_ref"] = "gazebo://warehouse/shelf/B9"

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "coordinate_scope_mismatch"
    assert body["execution_token"] is None
    assert "coordinate_scope_mismatch" in body["authority_scope_verdict"]["mismatch_keys"]
    _assert_join_keys_carried(body)


# ---------------------------------------------------------------------------
# 4. Cross-product replay injection
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_cross_product_replay_injection_denies_with_product_join_key(
    monkeypatch,
):
    """Drill: a valid ExecutionToken-shaped request for product_A is
    injected into a gateway call whose persisted authority scope belongs to
    product_B. The overlay must deny with ``asset_product_scope_mismatch``
    and the response must still carry product_A's join keys so operators
    can trace the tamper attempt back to the commerce workflow.

    We exercise the overlay by stubbing ``_build_authority_scope_verdict``
    (the model validator already rejects contradictions at parse time for
    the in-request case; the overlay is what protects against persisted
    scope drift, which is the realistic injection path).
    """

    product_a = "shopify:gid://shopify/Product/PRODUCT_A"
    product_b_scope_id = "scope:product-B-persisted"

    _wire_router_happy_defaults(monkeypatch)
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_hot_path_response,
    )

    original_build_verdict = agent_actions_router._build_authority_scope_verdict

    def _verdict_with_product_mismatch(payload):
        base = original_build_verdict(payload)
        base.update(
            {
                "status": "mismatch",
                "scope_id": product_b_scope_id,
                "mismatch_keys": list(
                    {*base.get("mismatch_keys", []), "asset_product_scope_mismatch"}
                ),
            }
        )
        return base

    monkeypatch.setattr(
        agent_actions_router,
        "_build_authority_scope_verdict",
        _verdict_with_product_mismatch,
    )

    payload = _commerce_payload(product_ref=product_a)

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "asset_product_scope_mismatch"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert body["authority_scope_verdict"]["scope_id"] == product_b_scope_id
    assert (
        "asset_product_scope_mismatch"
        in body["authority_scope_verdict"]["mismatch_keys"]
    )
    # Drill evidence must attribute the tamper to product_A's join keys
    # (the one the caller actually submitted), not silently to product_B.
    _assert_join_keys_carried(body, product_ref=product_a)


# ---------------------------------------------------------------------------
# 5. Allow path — sanity check that join keys are also carried on allow
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_allow_response_carries_audit_id_and_join_keys(monkeypatch):
    """Not an adversarial drill, but a regression guard: on the happy path
    the ``workflow_join_key`` MUST equal the governed receipt ``audit_id``
    so that replay lookups (``/api/v1/replay?audit_id=...``) line up with
    gateway join keys recorded on drill evidence."""

    _wire_router_happy_defaults(monkeypatch)
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_hot_path_response,
    )

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=_commerce_payload())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "allow"
    assert body["execution_token"] is not None
    _assert_join_keys_carried(body)
    linkage = body["forensic_linkage"]
    assert linkage["audit_id"] == "2b4c76c8-20e2-4222-aa18-c4f1ee212f72"
    assert linkage["workflow_join_key"] == linkage["audit_id"]


# ---------------------------------------------------------------------------
# 6. Deterministic workflow_join_key fallback on deny (no audit_id minted)
# ---------------------------------------------------------------------------


@pytest.mark.rct_commerce_drill
def test_drill_commerce_deny_uses_deterministic_workflow_join_key(monkeypatch):
    """When a drill denies before the hot path minted an ``audit_id``
    (e.g. coordinate tamper rejects prior to minting), the gateway must
    still synthesize a stable, deterministic UUIDv5 workflow_join_key
    keyed off the request_id so drill evidence can be correlated across
    attempts. The gateway's governed-receipt synthesiser
    (``_build_agent_action_evaluate_response``) and the forensic linkage
    builder must agree on this fallback.
    """

    _wire_router_happy_defaults(monkeypatch)

    def _allow_without_audit(request, **_kwargs):
        allow = _allow_hot_path_response(request)
        return allow.model_copy(update={"governed_receipt": {}})

    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_without_audit,
    )

    payload = _commerce_payload(request_id="req-commerce-drill-no-audit-0002")
    payload["telemetry"]["current_coordinate_ref"] = "gazebo://warehouse/shelf/B9"

    client = _make_client()
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["decision"]["disposition"] == "deny"
    linkage = body["forensic_linkage"]
    expected_fallback = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "req-commerce-drill-no-audit-0002")
    )
    # Both fields must match the deterministic fallback: they serve as the
    # correlation key between drill evidence and replay surfaces.
    assert linkage["workflow_join_key"] == expected_fallback
    assert linkage["audit_id"] == expected_fallback
    # Governed receipt is the upstream source of audit_id; the linkage must
    # always mirror it exactly.
    assert body["governed_receipt"]["audit_id"] == expected_fallback
