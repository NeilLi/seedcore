from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from seedcore.sdk import gated_action, reset_evaluator, using_evaluator
from seedcore.sdk.schema_exporter import export_schemas


DRILL_NAME = "agent_self_regulation_e2e"
REQUIRED_EVIDENCE = ["origin_scan", "delivery_scan", "signed_edge_telemetry"]


def _base_principal() -> dict[str, Any]:
    return {
        "agent_id": "agent:custody_runtime_01",
        "role_profile": "TRANSFER_COORDINATOR",
        "session_token": "session-agent-self-regulation",
        "owner_id": "did:seedcore:owner:self-regulation-buyer",
        "delegation_ref": "delegation:self-regulation-transfer",
        "organization_ref": "org:warehouse-north",
        "hardware_fingerprint": {
            "fingerprint_id": "fp:jetson-orin-01",
            "node_id": "node:jetson-orin-01",
            "public_key_fingerprint": "sha256:fingerprint-key",
            "attestation_type": "tpm",
            "key_ref": "tpm2:jetson-orin-01-ak",
        },
    }


def build_self_regulation_intent() -> dict[str, Any]:
    """Build the deterministic RCT intent used by the assistant drill."""
    return {
        "request_id": "req-agent-self-regulation-drill-001",
        "idempotency_key": "idem-agent-self-regulation-drill-001",
        "requested_at": "2026-05-21T10:00:00Z",
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31",
        "principal": _base_principal(),
        "workflow_valid_until": "2026-05-21T10:05:00Z",
        "asset_base": {
            "asset_id": "asset:self-regulation-lot-001",
            "lot_id": "self-regulation-lot-001",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:self-regulation-asset-provenance",
        },
        "approval_envelope_id": "approval-self-regulation-transfer-001",
        "approval_expected_envelope_version": "23",
        "authority_scope_base": {
            "scope_id": "scope:self-regulation-rct-001",
            "asset_ref": "asset:self-regulation-lot-001",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
            "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
        },
        "telemetry": {
            "observed_at": "2026-05-21T09:59:58Z",
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "current_zone": "vault_a",
            "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
            "evidence_refs": list(REQUIRED_EVIDENCE),
        },
        "security_contract": {
            "hash": "sha256:self-regulation-contract",
            "version": "rules@8.0.0",
        },
        "shopify_sandbox_transaction": {
            "product_ref": "shopify:gid://shopify/Product/1234567890",
            "order_ref": "shopify:gid://shopify/Order/1002003004",
            "quote_ref": "shopify:quote:self-regulation-2026-05-21-0001",
            "declared_value_usd": 2500.0,
            "economic_hash": "sha256:self-regulation-commerce",
        },
        "options": {"debug": False},
    }


@gated_action(
    policy="strict_custody",
    evidence_required=REQUIRED_EVIDENCE,
    fail_mode="quarantine",
    mode="shadow",
)
def shadow_transfer_custody(intent: dict[str, Any]) -> dict[str, Any]:
    return {"unexpected": "shadow_business_logic_executed", "request_id": intent["request_id"]}


@gated_action(
    policy="strict_custody",
    evidence_required=REQUIRED_EVIDENCE,
    fail_mode="quarantine",
    mode="enforce",
)
def enforce_transfer_custody(intent: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "governed_business_executed",
        "request_id": intent["request_id"],
        "asset_id": intent["asset_base"]["asset_id"],
    }


class _DrillRuntime:
    def __init__(self) -> None:
        self.evaluate_calls: list[dict[str, Any]] = []

    async def evaluate_agent_action(
        self,
        payload: dict[str, Any],
        *,
        debug: bool = False,
        no_execute: bool = False,
    ) -> dict[str, Any]:
        self.evaluate_calls.append({"payload": payload, "debug": debug, "no_execute": no_execute})
        return {
            "contract_version": "seedcore.agent_action_gateway.v1",
            "request_id": payload["request_id"],
            "decided_at": "2026-05-21T10:00:01Z",
            "latency_ms": 1,
            "decision": {
                "allowed": True,
                "disposition": "allow",
                "reason_code": "self_regulation_preflight_allowed",
            },
            "execution_token": None,
            "governed_receipt": {
                "audit_id": "11111111-1111-4111-8111-111111111111",
                "forensic_block_id": "fb:self-regulation-mcp",
            },
            "forensic_linkage": {
                "audit_id": "11111111-1111-4111-8111-111111111111",
                "replay_ref": "replay://workflow/agent-self-regulation/mcp-check-policy",
                "forensic_block_id": "fb:self-regulation-mcp",
            },
        }

    def api_url(self, path: str) -> str:
        return f"http://seedcore-drill.local/api/v1{path}"


def _mock_mcp_context(runtime: _DrillRuntime) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(runtime=runtime)
        )
    )


def _sdk_evaluator_response(
    *,
    payload: dict[str, Any],
    reason_code: str,
    replay_suffix: str,
    include_execution_token: bool,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": payload["request_id"],
        "decided_at": "2026-05-21T10:00:02Z",
        "latency_ms": 1,
        "decision": {"allowed": True, "disposition": "allow", "reason_code": reason_code},
        "governed_receipt": {
            "audit_id": f"audit:{replay_suffix}",
            "forensic_block_id": f"fb:{replay_suffix}",
        },
        "forensic_linkage": {
            "audit_id": f"audit:{replay_suffix}",
            "replay_ref": f"replay://workflow/agent-self-regulation/{replay_suffix}",
            "forensic_block_id": f"fb:{replay_suffix}",
        },
    }
    if include_execution_token:
        response["execution_token"] = {"token_id": f"token:{replay_suffix}"}
    return response


async def run_agent_self_regulation_drill(
    *,
    manifest_path: str | Path,
    evidence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the local end-to-end assistant self-regulation drill.

    The drill intentionally avoids live mutation: MCP policy checking is
    preflight-only, SDK shadow mode bypasses business logic, and SDK enforce mode
    runs only against injected evaluator/executor functions.
    """
    manifest_path = Path(manifest_path)
    manifest = export_schemas(str(Path(__file__).parent), str(manifest_path))

    from seedcore.plugin.mcp_server import seedcore_agent_action_check_policy

    runtime = _DrillRuntime()
    mcp_result = await seedcore_agent_action_check_policy(
        _mock_mcp_context(runtime),
        action_name="TRANSFER_CUSTODY",
        asset_ref="asset:self-regulation-lot-001",
        declared_value_usd=2500.0,
        telemetry_evidence=list(REQUIRED_EVIDENCE),
        buyer_did="did:seedcore:owner:self-regulation-buyer",
        delegation_id="delegation:self-regulation-transfer",
        session_token="session-agent-self-regulation",
    )
    mcp_call = runtime.evaluate_calls[0]

    intent = build_self_regulation_intent()
    shadow_payloads: list[dict[str, Any]] = []
    enforce_payloads: list[dict[str, Any]] = []
    closure_payloads: list[dict[str, Any]] = []

    def shadow_evaluator(payload: dict[str, Any]) -> dict[str, Any]:
        shadow_payloads.append(payload)
        return _sdk_evaluator_response(
            payload=payload,
            reason_code="self_regulation_shadow_allowed",
            replay_suffix="sdk-shadow",
            include_execution_token=False,
        )

    def enforce_evaluator(payload: dict[str, Any]) -> dict[str, Any]:
        enforce_payloads.append(payload)
        return _sdk_evaluator_response(
            payload=payload,
            reason_code="self_regulation_enforce_allowed",
            replay_suffix="sdk-enforce",
            include_execution_token=True,
        )

    def close_execution(payload: dict[str, Any]) -> None:
        closure_payloads.append(payload)

    reset_evaluator()
    try:
        with using_evaluator(shadow_evaluator):
            shadow_result = shadow_transfer_custody(intent)
        with using_evaluator(enforce_evaluator, close_execution):
            enforce_result = enforce_transfer_custody(intent)
    finally:
        reset_evaluator()

    evidence = {
        "drill": DRILL_NAME,
        "manifest_path": str(manifest_path),
        "manifest_action_ids": sorted(manifest["gated_actions"].keys()),
        "mcp_check_policy": {
            "ok": mcp_result["ok"],
            "decision": mcp_result["decision"],
            "no_execute": mcp_call["no_execute"],
            "execution_token_present": mcp_result.get("execution_token") is not None,
            "replay_ref": (mcp_result.get("forensic_linkage") or {}).get("replay_ref"),
            "forensic_block_id": (mcp_result.get("forensic_linkage") or {}).get("forensic_block_id"),
            "owner_id": mcp_call["payload"]["principal"]["owner_id"],
            "delegation_ref": mcp_call["payload"]["principal"]["delegation_ref"],
            "session_token": mcp_call["payload"]["principal"]["session_token"],
        },
        "sdk_shadow": {
            **asdict(shadow_result),
            "payload_no_execute": shadow_payloads[0]["options"]["no_execute"],
            "business_logic_executed": shadow_result.execution_result is not None,
        },
        "sdk_enforce": {
            **asdict(enforce_result),
            "payload_no_execute": enforce_payloads[0]["options"]["no_execute"],
            "closure_called": len(closure_payloads) == 1,
            "closure_request_id": closure_payloads[0]["request_id"] if closure_payloads else None,
        },
    }

    if evidence_path is not None:
        evidence_path = Path(evidence_path)
        evidence["evidence_path"] = str(evidence_path)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        with open(evidence_path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2, sort_keys=True)

    return evidence
