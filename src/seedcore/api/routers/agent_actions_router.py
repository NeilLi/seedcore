from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, List, Mapping, Tuple

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import text

from ...api.external_authority import (
    OwnerContextPreflightRequest,
    build_owner_twin_snapshot,
    get_delegation,
)
from ...agents.roles.specialization import SpecializationManager
from ...coordinator.core.governance import prepare_policy_case
from ...database import get_async_pg_session_factory, get_async_redis_client
from ...coordinator.dao import GovernedExecutionAuditDAO
from ...infra.kafka.delegated_intent import (
    DelegatedIntentPayload,
    build_delegated_intent_envelope,
)
from ...integrations.rust_kernel import mint_execution_token_with_rust
from ...models.action_intent import (
    ActionIntent,
    ExecutionPreconditions,
    ExecutionToken,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from ...models.agent_action_gateway import (
    AgentActionClosureRecordResponse,
    AgentActionClosureRequest,
    AgentActionClosureResponse,
    AgentActionExecuteResponse,
    AgentActionEvaluateRequest,
    AgentActionEvaluateResponse,
    AgentActionExecutionPlan,
    AgentActionRequestRecordResponse,
    PLANNER_TYPE_CONDITIONAL_ESCROW,
    PLANNER_TYPE_DELEGATED_AUTHORITY,
)
from ...models.evidence_bundle import EvidenceBundle
from ...models.pdp_hot_path import (
    HotPathAssetContext,
    HotPathEvaluateRequest,
    HotPathTelemetryContext,
)
from ...ops.pdp_hot_path import (
    HOT_PATH_CONTRACT_VERSION,
    build_governance_context_from_hot_path_response,
    evaluate_pdp_hot_path,
    resolve_authoritative_transfer_approval,
)
from ...hal.custody.transition_receipts import build_transition_receipt
from ...ops.evidence.verification import build_signed_artifact
from ...ops.pkg import get_global_pkg_manager
from ...ops.evidence.forensic_block_contract import FORENSIC_BLOCK_CONTEXT
from ...ops.execution_planners import build_execution_plan, executable_directives_from_plan
from ...services.digital_twin_service import (
    DigitalTwinService,
    build_result_verifier_gate_failure_verdict,
)
from ...serve.organism_client import OrganismServiceClient


router = APIRouter(tags=["agent-actions"])
logger = logging.getLogger(__name__)


@dataclass
class _AgentActionStoredRecord:
    request_id: str
    idempotency_key: str
    request_hash: str
    recorded_at: datetime
    response: AgentActionEvaluateResponse
    request_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _AgentActionIdempotencyEntry:
    request_id: str
    request_hash: str


@dataclass
class _AgentActionClosureStoredRecord:
    closure_id: str
    request_id: str
    idempotency_key: str
    request_hash: str
    recorded_at: datetime
    response: AgentActionClosureResponse


@dataclass
class _AgentActionExecuteStoredRecord:
    request_id: str
    idempotency_key: str
    request_hash: str
    recorded_at: datetime
    response: AgentActionExecuteResponse


_REQUEST_RECORDS_BY_ID: Dict[str, _AgentActionStoredRecord] = {}
_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_CLOSURE_RECORDS_BY_ID: Dict[str, _AgentActionClosureStoredRecord] = {}
_CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_EXECUTE_RECORDS_BY_REQUEST_ID: Dict[str, _AgentActionExecuteStoredRecord] = {}
_EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_REQUEST_RECORDS_LOCK = Lock()
_REDIS_CLIENT: Any = None
_REDIS_CLIENT_LOCK = asyncio.Lock()
_REDIS_CLIENT_INITIALIZED = False
_DIGITAL_TWIN_SERVICE: DigitalTwinService | None = None
_DIGITAL_TWIN_SERVICE_LOCK = Lock()

REQUEST_RECORD_TTL_SECONDS = max(
    86400,
    int(os.getenv("SEEDCORE_AGENT_ACTION_REQUEST_RECORD_TTL_SECONDS", "86400")),
)
REDIS_REQUEST_RECORD_KEY_PREFIX = "seedcore:agent_actions:req"
REDIS_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:idem"
REDIS_CLOSURE_RECORD_KEY_PREFIX = "seedcore:agent_actions:closure"
REDIS_CLOSURE_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:closure:idem"
REDIS_EXECUTE_RECORD_KEY_PREFIX = "seedcore:agent_actions:execute"
REDIS_EXECUTE_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:execute:idem"
ORGANISM_PREFLIGHT_REQUIRED = os.getenv(
    "SEEDCORE_AGENT_ACTION_REQUIRE_ORGANISM_READY",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}
ORGANISM_PREFLIGHT_TIMEOUT_SECONDS = float(
    os.getenv("SEEDCORE_AGENT_ACTION_ORGANISM_PREFLIGHT_TIMEOUT_S", "3")
)
ORGANISM_EXECUTE_TIMEOUT_SECONDS = float(
    os.getenv("SEEDCORE_AGENT_ACTION_ORGANISM_EXECUTE_TIMEOUT_S", "30")
)
DISABLE_REDIS_STORE = os.getenv(
    "SEEDCORE_AGENT_ACTION_DISABLE_REDIS_STORE",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}
SETTLEMENT_HANDOFF_ENABLED = os.getenv(
    "SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _map_to_hot_path_request(
    payload: AgentActionEvaluateRequest,
    *,
    request_hash: str | None = None,
    payload_hash_override: str | None = None,
    plan_dag_hash_override: str | None = None,
    prefer_plan_binding: bool = False,
) -> HotPathEvaluateRequest:
    hardware_fingerprint = payload.principal.hardware_fingerprint
    execution_endpoint_id = (
        str(hardware_fingerprint.endpoint_id or hardware_fingerprint.node_id or "").strip()
        or None
    )
    gateway_parameters: Dict[str, Any] = {
        "idempotency_key": payload.idempotency_key,
        "owner_id": payload.principal.owner_id,
        "delegation_ref": payload.principal.delegation_ref,
        "organization_ref": payload.principal.organization_ref,
        "workflow_type": payload.workflow.type,
    }
    if hardware_fingerprint is not None:
        gateway_parameters["hardware_fingerprint_id"] = hardware_fingerprint.fingerprint_id
        gateway_parameters["hardware_public_key_fingerprint"] = hardware_fingerprint.public_key_fingerprint
        gateway_parameters["hardware_node_id"] = hardware_fingerprint.node_id
        gateway_parameters["hardware_endpoint_id"] = hardware_fingerprint.endpoint_id
    if request_hash:
        gateway_parameters["request_hash"] = request_hash
    if isinstance(plan_dag_hash_override, str) and plan_dag_hash_override.strip():
        gateway_parameters["execution_plan_hash"] = plan_dag_hash_override.strip()
    if payload.authority_scope is not None:
        gateway_parameters["scope_id"] = payload.authority_scope.scope_id
        gateway_parameters["asset_ref"] = payload.authority_scope.asset_ref
        gateway_parameters["product_ref"] = payload.authority_scope.product_ref
        gateway_parameters["order_ref"] = payload.asset.order_ref
        gateway_parameters["facility_ref"] = payload.authority_scope.facility_ref
        gateway_parameters["expected_from_zone"] = payload.authority_scope.expected_from_zone
        gateway_parameters["expected_to_zone"] = payload.authority_scope.expected_to_zone
        gateway_parameters["expected_coordinate_ref"] = payload.authority_scope.expected_coordinate_ref
        gateway_parameters["max_radius_meters"] = payload.authority_scope.max_radius_meters
    if payload.forensic_context is not None:
        gateway_parameters["reason_trace_ref"] = payload.forensic_context.reason_trace_ref
        if payload.forensic_context.fingerprint_components is not None:
            gateway_parameters["fingerprint_components"] = payload.forensic_context.fingerprint_components.model_dump(
                mode="json",
                exclude_none=True,
            )
    resolved_payload_hash = (
        f"sha256:{payload_hash_override}"
        if payload_hash_override
        else f"sha256:{request_hash}"
        if request_hash and not prefer_plan_binding
        else None
    )
    resolved_plan_dag_hash = (
        str(plan_dag_hash_override).strip()
        if isinstance(plan_dag_hash_override, str) and str(plan_dag_hash_override).strip()
        else None
    )
    action_intent = ActionIntent(
        intent_id=payload.request_id,
        timestamp=_to_utc_iso(payload.requested_at),
        valid_until=_to_utc_iso(payload.workflow.valid_until),
        principal=IntentPrincipal(
            agent_id=payload.principal.agent_id,
            role_profile=payload.principal.role_profile,
            session_token=payload.principal.session_token or "",
            actor_token=payload.principal.actor_token,
        ),
        action=IntentAction(
            type=payload.workflow.action_type,
            security_contract=SecurityContract(
                hash=payload.security_contract.hash,
                version=payload.security_contract.version,
            ),
            parameters={
                "endpoint_id": execution_endpoint_id,
                "payload_hash": resolved_payload_hash,
                "plan_dag_hash": resolved_plan_dag_hash,
                "approval_context": {
                    "approval_envelope_id": payload.approval.approval_envelope_id,
                    "expected_envelope_version": payload.approval.expected_envelope_version,
                },
                "gateway": {
                    **gateway_parameters,
                },
            },
        ),
        resource=IntentResource(
            asset_id=payload.asset.asset_id,
            target_zone=payload.asset.to_zone,
            provenance_hash=payload.asset.provenance_hash,
            lot_id=payload.asset.lot_id,
            category_envelope={
                "transfer_context": {
                    "from_custodian_ref": payload.asset.from_custodian_ref,
                    "to_custodian_ref": payload.asset.to_custodian_ref,
                    "from_zone": payload.asset.from_zone,
                    "to_zone": payload.asset.to_zone,
                    "product_ref": payload.asset.product_ref,
                    "order_ref": payload.asset.order_ref,
                    "quote_ref": payload.asset.quote_ref,
                    "expected_coordinate_ref": (
                        payload.authority_scope.expected_coordinate_ref
                        if payload.authority_scope is not None
                        else None
                    ),
                }
            },
        ),
    )
    if payload.asset.declared_value_usd is not None:
        action_intent.action.parameters["value_usd"] = float(payload.asset.declared_value_usd)
    policy_snapshot_ref = payload.policy_snapshot_ref or payload.security_contract.version
    request_schema_bundle, taxonomy_bundle = _resolve_active_contract_bundles(policy_snapshot_ref)
    return HotPathEvaluateRequest(
        contract_version=HOT_PATH_CONTRACT_VERSION,
        request_id=payload.request_id,
        requested_at=payload.requested_at,
        policy_snapshot_ref=policy_snapshot_ref,
        action_intent=action_intent,
        asset_context=HotPathAssetContext(
            asset_ref=payload.asset.asset_id,
            current_custodian_ref=payload.asset.from_custodian_ref,
            current_zone=payload.asset.from_zone,
        ),
        telemetry_context=HotPathTelemetryContext(
            observed_at=_to_utc_iso(payload.telemetry.observed_at),
            freshness_seconds=payload.telemetry.freshness_seconds,
            max_allowed_age_seconds=payload.telemetry.max_allowed_age_seconds,
            evidence_refs=list(payload.telemetry.evidence_refs),
        ),
        request_schema_bundle=request_schema_bundle,
        taxonomy_bundle=taxonomy_bundle,
    )


def _resolve_active_contract_bundles(
    policy_snapshot_ref: str | None,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    manager = get_global_pkg_manager()
    if manager is None:
        return None, None

    metadata_getter = getattr(manager, "get_metadata", None)
    active_version = None
    if callable(metadata_getter):
        metadata = metadata_getter() or {}
        if isinstance(metadata, dict):
            active_version = metadata.get("active_version")
    if policy_snapshot_ref and active_version and str(policy_snapshot_ref).strip() != str(active_version).strip():
        return None, None

    request_schema_getter = getattr(manager, "get_active_request_schema_bundle", None)
    taxonomy_getter = getattr(manager, "get_active_taxonomy_bundle", None)
    request_schema_bundle = request_schema_getter() if callable(request_schema_getter) else None
    taxonomy_bundle = taxonomy_getter() if callable(taxonomy_getter) else None
    return (
        dict(request_schema_bundle)
        if isinstance(request_schema_bundle, dict) and request_schema_bundle
        else None,
        dict(taxonomy_bundle)
        if isinstance(taxonomy_bundle, dict) and taxonomy_bundle
        else None,
    )


def _build_authority_scope_verdict(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    scope = payload.authority_scope
    if scope is None:
        return {
            "status": "unverified",
            "scope_id": None,
            "mismatch_keys": [],
        }
    mismatches: List[str] = []
    if scope.asset_ref != payload.asset.asset_id:
        mismatches.append("asset_scope_mismatch")
    if scope.product_ref and payload.asset.product_ref and scope.product_ref != payload.asset.product_ref:
        mismatches.append("asset_product_scope_mismatch")
    if scope.expected_from_zone and payload.asset.from_zone and scope.expected_from_zone != payload.asset.from_zone:
        mismatches.append("from_zone_scope_mismatch")
    if scope.expected_to_zone and payload.asset.to_zone and scope.expected_to_zone != payload.asset.to_zone:
        mismatches.append("to_zone_scope_mismatch")
    if (
        scope.expected_coordinate_ref
        and payload.telemetry.current_coordinate_ref
        and scope.expected_coordinate_ref != payload.telemetry.current_coordinate_ref
    ):
        mismatches.append("coordinate_scope_mismatch")
    if (
        payload.telemetry.current_zone
        and scope.expected_from_zone
        and scope.expected_to_zone
        and payload.telemetry.current_zone not in {scope.expected_from_zone, scope.expected_to_zone}
    ):
        mismatches.append("telemetry_zone_out_of_scope")
    return {
        "status": "mismatch" if mismatches else "matched",
        "scope_id": scope.scope_id,
        "mismatch_keys": mismatches,
    }


def _build_fingerprint_verdict(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    missing_components: List[str] = []
    if payload.principal.hardware_fingerprint is None:
        missing_components.append("hardware_fingerprint")
    components = payload.forensic_context.fingerprint_components if payload.forensic_context is not None else None
    if components is None:
        missing_components.extend(
            [
                "economic_hash",
                "physical_presence_hash",
                "reasoning_hash",
                "actuator_hash",
            ]
        )
    else:
        if not components.economic_hash:
            missing_components.append("economic_hash")
        if not components.physical_presence_hash:
            missing_components.append("physical_presence_hash")
        if not components.reasoning_hash:
            missing_components.append("reasoning_hash")
        if not components.actuator_hash:
            missing_components.append("actuator_hash")
    return {
        "status": "incomplete" if missing_components else "matched",
        "missing_components": missing_components,
        "mismatch_keys": [],
    }


def _apply_forensic_scope_guards(
    *,
    payload: AgentActionEvaluateRequest,
    response: AgentActionEvaluateResponse,
) -> AgentActionEvaluateResponse:
    if payload.authority_scope is None:
        return response
    disposition = str(response.decision.disposition or "").strip().lower()
    if disposition != "allow":
        return response

    scope_verdict = response.authority_scope_verdict if isinstance(response.authority_scope_verdict, dict) else {}
    mismatch_keys = [
        str(item).strip()
        for item in list(scope_verdict.get("mismatch_keys") or [])
        if str(item).strip()
    ]
    if mismatch_keys:
        trust_gaps = list(response.trust_gaps)
        if "authority_scope_mismatch" not in trust_gaps:
            trust_gaps.append("authority_scope_mismatch")
        minted_artifacts = [item for item in response.minted_artifacts if item != "ExecutionToken"]
        return response.model_copy(
            update={
                "decision": response.decision.model_copy(
                    update={
                        "allowed": False,
                        "disposition": "deny",
                        "reason_code": (
                            "coordinate_scope_mismatch"
                            if "coordinate_scope_mismatch" in mismatch_keys
                            else "authority_scope_mismatch"
                        ),
                        "reason": "Authority scope mismatch detected for the requested transfer.",
                    }
                ),
                "execution_token": None,
                "trust_gaps": trust_gaps,
                "minted_artifacts": minted_artifacts,
            }
        )

    expected_coordinate_ref = str(payload.authority_scope.expected_coordinate_ref or "").strip()
    if expected_coordinate_ref and not str(payload.telemetry.current_coordinate_ref or "").strip():
        trust_gaps = list(response.trust_gaps)
        if "coordinate_scope_unverified" not in trust_gaps:
            trust_gaps.append("coordinate_scope_unverified")
        minted_artifacts = [item for item in response.minted_artifacts if item != "ExecutionToken"]
        return response.model_copy(
            update={
                "decision": response.decision.model_copy(
                    update={
                        "allowed": False,
                        "disposition": "quarantine",
                        "reason_code": "coordinate_scope_unverified",
                        "reason": "Coordinate-bound authority cannot be verified from current telemetry.",
                    }
                ),
                "execution_token": None,
                "trust_gaps": trust_gaps,
                "minted_artifacts": minted_artifacts,
            }
        )
    return response


def _build_forensic_linkage(
    *,
    payload: AgentActionEvaluateRequest,
    response: AgentActionEvaluateResponse,
) -> Dict[str, Any]:
    forensic_block_id = None
    if isinstance(response.governed_receipt, dict):
        forensic_block_id = response.governed_receipt.get("forensic_block_id")
    return {
        "forensic_block_id": forensic_block_id,
        "reason_trace_ref": (
            payload.forensic_context.reason_trace_ref
            if payload.forensic_context is not None
            else None
        ),
        "public_replay_ready": False,
    }


def _minted_artifacts_from_hot_path_result(
    *,
    execution_token: Any,
    governed_receipt: Dict[str, Any],
    signer_provenance: List[Any],
) -> List[str]:
    minted: List[str] = []
    if execution_token is not None:
        minted.append("ExecutionToken")
    if governed_receipt:
        minted.append("PolicyReceipt")
    for provenance in signer_provenance:
        artifact_type = str(getattr(provenance, "artifact_type", "")).strip()
        if not artifact_type:
            continue
        normalized = artifact_type.replace("_", " ").title().replace(" ", "")
        if normalized and normalized not in minted:
            minted.append(normalized)
    return minted


def _execution_context_from_hot_path_result(
    *,
    execution_token: Any,
    governed_receipt: Mapping[str, Any] | None = None,
) -> ExecutionPreconditions | None:
    if execution_token is not None:
        preconditions = getattr(execution_token, "execution_preconditions", None)
        if isinstance(preconditions, ExecutionPreconditions):
            return preconditions
        if isinstance(preconditions, Mapping):
            try:
                return ExecutionPreconditions(**dict(preconditions))
            except Exception:
                return None

        token_payload = (
            execution_token.model_dump(mode="json")
            if hasattr(execution_token, "model_dump")
            else dict(execution_token)
            if isinstance(execution_token, Mapping)
            else {}
        )
        if isinstance(token_payload.get("execution_preconditions"), Mapping):
            try:
                return ExecutionPreconditions(**dict(token_payload["execution_preconditions"]))
            except Exception:
                return None

    if isinstance(governed_receipt, Mapping):
        advisory = governed_receipt.get("advisory") if isinstance(governed_receipt.get("advisory"), Mapping) else {}
        preconditions_payload = (
            governed_receipt.get("execution_preconditions")
            if isinstance(governed_receipt.get("execution_preconditions"), Mapping)
            else advisory.get("execution_preconditions")
            if isinstance(advisory.get("execution_preconditions"), Mapping)
            else {}
        )
        if isinstance(preconditions_payload, Mapping) and preconditions_payload:
            try:
                return ExecutionPreconditions(**dict(preconditions_payload))
            except Exception:
                return None
    return None


def _bind_plan_hash_to_execution_token(
    execution_token: ExecutionToken | None,
    *,
    execution_plan: AgentActionExecutionPlan | None,
) -> ExecutionToken | None:
    if execution_token is None or execution_plan is None:
        return execution_token
    constraints = (
        dict(execution_token.constraints)
        if isinstance(execution_token.constraints, dict)
        else {}
    )
    constraints["plan_dag_hash"] = execution_plan.plan_dag_hash
    preconditions = execution_token.execution_preconditions.model_dump(mode="json")
    preconditions["plan_dag_hash"] = execution_plan.plan_dag_hash
    return execution_token.model_copy(
        update={
            "constraints": constraints,
            "execution_preconditions": ExecutionPreconditions(**preconditions),
        }
    )


def _bind_plan_hash_to_execution_context(
    execution_context: ExecutionPreconditions | None,
    *,
    execution_plan: AgentActionExecutionPlan | None,
) -> ExecutionPreconditions | None:
    if execution_context is None or execution_plan is None:
        return execution_context
    updated = execution_context.model_dump(mode="json")
    updated["plan_dag_hash"] = execution_plan.plan_dag_hash
    return ExecutionPreconditions(**updated)


def _apply_execution_plan_bindings_to_hot_path_result(
    hot_path_result: HotPathEvaluateResponse,
    *,
    execution_plan: AgentActionExecutionPlan | None,
) -> HotPathEvaluateResponse:
    if execution_plan is None:
        return hot_path_result
    execution_token = _bind_plan_hash_to_execution_token(
        hot_path_result.execution_token,
        execution_plan=execution_plan,
    )
    execution_preconditions = _bind_plan_hash_to_execution_context(
        hot_path_result.execution_preconditions,
        execution_plan=execution_plan,
    )
    governed_receipt = dict(hot_path_result.governed_receipt)
    if governed_receipt:
        existing = (
            dict(governed_receipt.get("execution_preconditions"))
            if isinstance(governed_receipt.get("execution_preconditions"), Mapping)
            else {}
        )
        existing["plan_dag_hash"] = execution_plan.plan_dag_hash
        governed_receipt["execution_preconditions"] = existing
        advisory = governed_receipt.get("advisory")
        if isinstance(advisory, Mapping):
            advisory_payload = dict(advisory)
            advisory_preconditions = (
                dict(advisory_payload.get("execution_preconditions"))
                if isinstance(advisory_payload.get("execution_preconditions"), Mapping)
                else {}
            )
            advisory_preconditions["plan_dag_hash"] = execution_plan.plan_dag_hash
            advisory_payload["execution_preconditions"] = advisory_preconditions
            governed_receipt["advisory"] = advisory_payload
    return hot_path_result.model_copy(
        update={
            "execution_token": execution_token,
            "execution_preconditions": execution_preconditions,
            "governed_receipt": governed_receipt,
        }
    )


def _apply_no_execute_preflight(
    response: AgentActionEvaluateResponse,
    *,
    requested: bool,
) -> AgentActionEvaluateResponse:
    if not requested:
        return response
    retained_artifacts = [item for item in response.minted_artifacts if item != "ExecutionToken"]
    return response.model_copy(
        update={
            "execution_token": None,
            "execution_context": None,
            "minted_artifacts": retained_artifacts,
        }
    )


def _normalize_delegation_id(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.startswith("delegation:"):
        normalized = normalized.split(":", 1)[1].strip()
    return normalized or None


async def _resolve_owner_twin_snapshot_for_payload(payload: AgentActionEvaluateRequest) -> dict[str, Any] | None:
    owner_id = str(payload.principal.owner_id or "").strip() or None
    delegation_id = _normalize_delegation_id(payload.principal.delegation_ref)
    session_factory = get_async_pg_session_factory()
    if session_factory is None:
        return None
    try:
        async with session_factory() as session:
            if owner_id is None and delegation_id is not None:
                delegation = await get_delegation(session, delegation_id)
                if delegation is not None:
                    owner_id = delegation.owner_id
            if owner_id is None:
                return None
            owner_twin = await build_owner_twin_snapshot(session, owner_id)
            return owner_twin.model_dump(mode="json")
    except Exception:
        logger.debug(
            "Failed to resolve owner twin snapshot for agent action request_id=%s",
            payload.request_id,
            exc_info=True,
        )
        return None


def _annotate_owner_context_in_response(
    response: AgentActionEvaluateResponse,
    owner_twin_snapshot: Mapping[str, Any] | None,
) -> AgentActionEvaluateResponse:
    if not isinstance(owner_twin_snapshot, Mapping):
        return response
    provenance = (
        owner_twin_snapshot.get("provenance")
        if isinstance(owner_twin_snapshot.get("provenance"), Mapping)
        else {}
    )
    identity = (
        owner_twin_snapshot.get("identity")
        if isinstance(owner_twin_snapshot.get("identity"), Mapping)
        else {}
    )
    creator_profile_ref = (
        dict(provenance.get("creator_profile_ref"))
        if isinstance(provenance.get("creator_profile_ref"), Mapping)
        else None
    )
    trust_preferences_ref = (
        dict(provenance.get("trust_preferences_ref"))
        if isinstance(provenance.get("trust_preferences_ref"), Mapping)
        else None
    )
    if creator_profile_ref is None and trust_preferences_ref is None:
        return response
    governed_receipt = dict(response.governed_receipt or {})
    governed_receipt["owner_context"] = {
        "owner_id": identity.get("did") or identity.get("owner_id"),
        "creator_profile_ref": creator_profile_ref,
        "trust_preferences_ref": trust_preferences_ref,
    }
    return response.model_copy(update={"governed_receipt": governed_receipt})


def _canonical_gateway_payload_hash(
    payload: AgentActionEvaluateRequest,
    *,
    requested_no_execute: bool,
) -> str:
    canonical_payload = {
        "contract_version": payload.contract_version,
        "request_id": payload.request_id,
        "requested_at": _to_utc_iso(payload.requested_at),
        "idempotency_key": payload.idempotency_key,
        "policy_snapshot_ref": payload.policy_snapshot_ref,
        "principal": {
            "agent_id": payload.principal.agent_id,
            "role_profile": payload.principal.role_profile,
            "owner_id": payload.principal.owner_id,
            "delegation_ref": payload.principal.delegation_ref,
            "organization_ref": payload.principal.organization_ref,
            "session_token": payload.principal.session_token,
            "actor_token": payload.principal.actor_token,
            "hardware_fingerprint": payload.principal.hardware_fingerprint.model_dump(mode="json"),
        },
        "workflow": payload.workflow.model_dump(mode="json"),
        "asset": payload.asset.model_dump(mode="json"),
        "approval": payload.approval.model_dump(mode="json"),
        "authority_scope": payload.authority_scope.model_dump(mode="json"),
        "telemetry": payload.telemetry.model_dump(mode="json"),
        "security_contract": payload.security_contract.model_dump(mode="json"),
        "options": {
            "no_execute": bool(requested_no_execute),
            "debug": bool(payload.options.debug),
        },
    }
    if payload.forensic_context is not None:
        canonical_payload["forensic_context"] = payload.forensic_context.model_dump(mode="json")
    if payload.execution is not None:
        canonical_payload["execution"] = payload.execution.model_dump(mode="json")
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _canonical_tool_args_hash(tool_args: Mapping[str, Any]) -> str:
    canonical_payload = {
        str(key): value
        for key, value in tool_args.items()
        if key not in {"execution_token", "execution_context", "_governance"}
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _canonical_gateway_execute_payload_hash(
    payload: AgentActionEvaluateRequest,
    *,
    execution_plan: AgentActionExecutionPlan,
) -> str:
    canonical_payload = {
        "request_hash": _canonical_gateway_payload_hash(payload, requested_no_execute=False),
        "mode": "execute",
        "execution_plan": execution_plan.model_dump(mode="json"),
    }
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _canonical_payload_hash(payload: Any) -> str:
    canonical_payload = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload or {})
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _hash_or_passthrough(value: Any, *, fallback: str) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    return f"sha256:{hashlib.sha256(fallback.encode('utf-8')).hexdigest()}"


def _request_record_redis_key(request_id: str) -> str:
    return f"{REDIS_REQUEST_RECORD_KEY_PREFIX}:{request_id}"


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


def _closure_record_redis_key(closure_id: str) -> str:
    return f"{REDIS_CLOSURE_RECORD_KEY_PREFIX}:{closure_id}"


def _closure_idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_CLOSURE_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


def _execute_record_redis_key(request_id: str) -> str:
    return f"{REDIS_EXECUTE_RECORD_KEY_PREFIX}:{request_id}"


def _execute_idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_EXECUTE_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


def _record_to_json_payload(record: _AgentActionStoredRecord) -> Dict[str, Any]:
    return {
        "request_id": record.request_id,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "recorded_at": _to_utc_iso(record.recorded_at),
        "response": record.response.model_dump(mode="json"),
        "request_payload": dict(record.request_payload or {}),
    }


def _idempotency_entry_from_json(payload: Dict[str, Any]) -> _AgentActionIdempotencyEntry | None:
    request_id = str(payload.get("request_id") or "").strip()
    request_hash = str(payload.get("request_hash") or "").strip()
    if not request_id:
        return None
    return _AgentActionIdempotencyEntry(request_id=request_id, request_hash=request_hash)


def _record_from_json_payload(payload: Dict[str, Any]) -> _AgentActionStoredRecord:
    response = AgentActionEvaluateResponse.model_validate(payload.get("response") or {})
    recorded_at_raw = payload.get("recorded_at")
    if isinstance(recorded_at_raw, datetime):
        recorded_at = recorded_at_raw
    else:
        recorded_at = datetime.fromisoformat(str(recorded_at_raw).replace("Z", "+00:00"))
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    return _AgentActionStoredRecord(
        request_id=str(payload.get("request_id") or "").strip(),
        idempotency_key=str(payload.get("idempotency_key") or "").strip(),
        request_hash=str(payload.get("request_hash") or "").strip(),
        recorded_at=recorded_at.astimezone(timezone.utc),
        response=response,
        request_payload=(
            dict(payload.get("request_payload"))
            if isinstance(payload.get("request_payload"), dict)
            else {}
        ),
    )


def _closure_record_to_json_payload(record: _AgentActionClosureStoredRecord) -> Dict[str, Any]:
    return {
        "closure_id": record.closure_id,
        "request_id": record.request_id,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "recorded_at": _to_utc_iso(record.recorded_at),
        "response": record.response.model_dump(mode="json"),
    }


def _closure_record_from_json_payload(payload: Dict[str, Any]) -> _AgentActionClosureStoredRecord:
    response = AgentActionClosureResponse.model_validate(payload.get("response") or {})
    recorded_at_raw = payload.get("recorded_at")
    if isinstance(recorded_at_raw, datetime):
        recorded_at = recorded_at_raw
    else:
        recorded_at = datetime.fromisoformat(str(recorded_at_raw).replace("Z", "+00:00"))
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    return _AgentActionClosureStoredRecord(
        closure_id=str(payload.get("closure_id") or "").strip(),
        request_id=str(payload.get("request_id") or "").strip(),
        idempotency_key=str(payload.get("idempotency_key") or "").strip(),
        request_hash=str(payload.get("request_hash") or "").strip(),
        recorded_at=recorded_at.astimezone(timezone.utc),
        response=response,
    )


def _execute_record_to_json_payload(record: _AgentActionExecuteStoredRecord) -> Dict[str, Any]:
    return {
        "request_id": record.request_id,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "recorded_at": _to_utc_iso(record.recorded_at),
        "response": record.response.model_dump(mode="json"),
    }


def _execute_record_from_json_payload(payload: Dict[str, Any]) -> _AgentActionExecuteStoredRecord:
    response = AgentActionExecuteResponse.model_validate(payload.get("response") or {})
    recorded_at_raw = payload.get("recorded_at")
    if isinstance(recorded_at_raw, datetime):
        recorded_at = recorded_at_raw
    else:
        recorded_at = datetime.fromisoformat(str(recorded_at_raw).replace("Z", "+00:00"))
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    return _AgentActionExecuteStoredRecord(
        request_id=str(payload.get("request_id") or "").strip(),
        idempotency_key=str(payload.get("idempotency_key") or "").strip(),
        request_hash=str(payload.get("request_hash") or "").strip(),
        recorded_at=recorded_at.astimezone(timezone.utc),
        response=response,
    )


async def _resolve_redis_client() -> Any:
    global _REDIS_CLIENT, _REDIS_CLIENT_INITIALIZED
    if DISABLE_REDIS_STORE:
        return None
    if _REDIS_CLIENT_INITIALIZED:
        return _REDIS_CLIENT
    async with _REDIS_CLIENT_LOCK:
        if _REDIS_CLIENT_INITIALIZED:
            return _REDIS_CLIENT
        try:
            _REDIS_CLIENT = await get_async_redis_client()
        except Exception:
            logger.debug("Agent action Redis client resolution failed; using in-memory fallback.", exc_info=True)
            _REDIS_CLIENT = None
        _REDIS_CLIENT_INITIALIZED = True
        return _REDIS_CLIENT


async def _read_idempotency_entry(idempotency_key: str) -> Dict[str, Any] | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_idempotency_redis_key(idempotency_key))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    parsed_entry = _idempotency_entry_from_json(parsed)
                    if parsed_entry is not None:
                        return {
                            "request_id": parsed_entry.request_id,
                            "request_hash": parsed_entry.request_hash,
                        }
        except Exception:
            logger.warning("Agent action Redis idempotency read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            return None
    return {
        "request_id": existing_entry.request_id,
        "request_hash": existing_entry.request_hash,
    }


async def _read_request_record(request_id: str) -> _AgentActionStoredRecord | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_request_record_redis_key(request_id))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    return _record_from_json_payload(parsed)
        except Exception:
            logger.warning("Agent action Redis request-record read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        return _REQUEST_RECORDS_BY_ID.get(request_id)


async def _write_request_record(record: _AgentActionStoredRecord) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        record_payload = _record_to_json_payload(record)
        try:
            await redis_client.setex(
                _request_record_redis_key(record.request_id),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(record_payload, sort_keys=True, separators=(",", ":"), default=str),
            )
            await redis_client.setex(
                _idempotency_redis_key(record.idempotency_key),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(
                    {
                        "request_id": record.request_id,
                        "request_hash": record.request_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            )
            return
        except Exception:
            logger.warning("Agent action Redis write failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        _REQUEST_RECORDS_BY_ID[record.request_id] = record
        _IDEMPOTENCY_ENTRIES_BY_KEY[record.idempotency_key] = _AgentActionIdempotencyEntry(
            request_id=record.request_id,
            request_hash=record.request_hash,
        )


async def _claim_idempotency_key(
    *,
    idempotency_key: str,
    request_id: str,
    request_hash: str,
) -> Tuple[bool, Dict[str, Any] | None]:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        serialized_entry = json.dumps(
            {
                "request_id": request_id,
                "request_hash": request_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            claimed = await redis_client.set(
                _idempotency_redis_key(idempotency_key),
                serialized_entry,
                ex=REQUEST_RECORD_TTL_SECONDS,
                nx=True,
            )
            if bool(claimed):
                return True, None
            return False, await _read_idempotency_entry(idempotency_key)
        except Exception:
            logger.warning("Agent action Redis idempotency claim failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            _IDEMPOTENCY_ENTRIES_BY_KEY[idempotency_key] = _AgentActionIdempotencyEntry(
                request_id=request_id,
                request_hash=request_hash,
            )
            return True, None
        return False, {
            "request_id": existing_entry.request_id,
            "request_hash": existing_entry.request_hash,
        }


async def _release_idempotency_claim(
    *,
    idempotency_key: str,
    request_id: str,
    request_hash: str,
) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            existing = await _read_idempotency_entry(idempotency_key)
            if existing and existing.get("request_id") == request_id and existing.get("request_hash") == request_hash:
                await redis_client.delete(_idempotency_redis_key(idempotency_key))
            return
        except Exception:
            logger.warning("Agent action Redis idempotency release failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if (
            existing_entry is not None
            and existing_entry.request_id == request_id
            and existing_entry.request_hash == request_hash
        ):
            _IDEMPOTENCY_ENTRIES_BY_KEY.pop(idempotency_key, None)


async def _read_closure_idempotency_entry(idempotency_key: str) -> Dict[str, Any] | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_closure_idempotency_redis_key(idempotency_key))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    parsed_entry = _idempotency_entry_from_json(parsed)
                    if parsed_entry is not None:
                        return {
                            "request_id": parsed_entry.request_id,
                            "request_hash": parsed_entry.request_hash,
                        }
        except Exception:
            logger.warning("Agent action Redis closure idempotency read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            return None
    return {
        "request_id": existing_entry.request_id,
        "request_hash": existing_entry.request_hash,
    }


async def _read_closure_record(closure_id: str) -> _AgentActionClosureStoredRecord | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_closure_record_redis_key(closure_id))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    return _closure_record_from_json_payload(parsed)
        except Exception:
            logger.warning("Agent action Redis closure-record read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        return _CLOSURE_RECORDS_BY_ID.get(closure_id)


async def _read_execute_idempotency_entry(idempotency_key: str) -> Dict[str, Any] | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_execute_idempotency_redis_key(idempotency_key))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    parsed_entry = _idempotency_entry_from_json(parsed)
                    if parsed_entry is not None:
                        return {
                            "request_id": parsed_entry.request_id,
                            "request_hash": parsed_entry.request_hash,
                        }
        except Exception:
            logger.warning("Agent action Redis execute idempotency read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            return None
    return {
        "request_id": existing_entry.request_id,
        "request_hash": existing_entry.request_hash,
    }


async def _read_execute_record(request_id: str) -> _AgentActionExecuteStoredRecord | None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            raw_value = await redis_client.get(_execute_record_redis_key(request_id))
            if raw_value:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    return _execute_record_from_json_payload(parsed)
        except Exception:
            logger.warning("Agent action Redis execute-record read failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        return _EXECUTE_RECORDS_BY_REQUEST_ID.get(request_id)


async def _write_closure_record(record: _AgentActionClosureStoredRecord) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        record_payload = _closure_record_to_json_payload(record)
        try:
            await redis_client.setex(
                _closure_record_redis_key(record.closure_id),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(record_payload, sort_keys=True, separators=(",", ":"), default=str),
            )
            await redis_client.setex(
                _closure_idempotency_redis_key(record.idempotency_key),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(
                    {
                        "request_id": record.closure_id,
                        "request_hash": record.request_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            )
            return
        except Exception:
            logger.warning("Agent action Redis closure write failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        _CLOSURE_RECORDS_BY_ID[record.closure_id] = record
        _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY[record.idempotency_key] = _AgentActionIdempotencyEntry(
            request_id=record.closure_id,
            request_hash=record.request_hash,
        )


async def _write_execute_record(record: _AgentActionExecuteStoredRecord) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        record_payload = _execute_record_to_json_payload(record)
        try:
            await redis_client.setex(
                _execute_record_redis_key(record.request_id),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(record_payload, sort_keys=True, separators=(",", ":"), default=str),
            )
            await redis_client.setex(
                _execute_idempotency_redis_key(record.idempotency_key),
                REQUEST_RECORD_TTL_SECONDS,
                json.dumps(
                    {
                        "request_id": record.request_id,
                        "request_hash": record.request_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            )
            return
        except Exception:
            logger.warning("Agent action Redis execute write failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        _EXECUTE_RECORDS_BY_REQUEST_ID[record.request_id] = record
        _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY[record.idempotency_key] = _AgentActionIdempotencyEntry(
            request_id=record.request_id,
            request_hash=record.request_hash,
        )


async def _claim_closure_idempotency_key(
    *,
    idempotency_key: str,
    closure_id: str,
    request_hash: str,
) -> Tuple[bool, Dict[str, Any] | None]:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        serialized_entry = json.dumps(
            {
                "request_id": closure_id,
                "request_hash": request_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            claimed = await redis_client.set(
                _closure_idempotency_redis_key(idempotency_key),
                serialized_entry,
                ex=REQUEST_RECORD_TTL_SECONDS,
                nx=True,
            )
            if bool(claimed):
                return True, None
            return False, await _read_closure_idempotency_entry(idempotency_key)
        except Exception:
            logger.warning("Agent action Redis closure idempotency claim failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY[idempotency_key] = _AgentActionIdempotencyEntry(
                request_id=closure_id,
                request_hash=request_hash,
            )
            return True, None
        return False, {
            "request_id": existing_entry.request_id,
            "request_hash": existing_entry.request_hash,
        }


async def _claim_execute_idempotency_key(
    *,
    idempotency_key: str,
    request_id: str,
    request_hash: str,
) -> Tuple[bool, Dict[str, Any] | None]:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        serialized_entry = json.dumps(
            {
                "request_id": request_id,
                "request_hash": request_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            claimed = await redis_client.set(
                _execute_idempotency_redis_key(idempotency_key),
                serialized_entry,
                ex=REQUEST_RECORD_TTL_SECONDS,
                nx=True,
            )
            if bool(claimed):
                return True, None
            return False, await _read_execute_idempotency_entry(idempotency_key)
        except Exception:
            logger.warning("Agent action Redis execute idempotency claim failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if existing_entry is None:
            _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY[idempotency_key] = _AgentActionIdempotencyEntry(
                request_id=request_id,
                request_hash=request_hash,
            )
            return True, None
        return False, {
            "request_id": existing_entry.request_id,
            "request_hash": existing_entry.request_hash,
        }


async def _release_closure_idempotency_claim(
    *,
    idempotency_key: str,
    closure_id: str,
    request_hash: str,
) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            existing = await _read_closure_idempotency_entry(idempotency_key)
            if existing and existing.get("request_id") == closure_id and existing.get("request_hash") == request_hash:
                await redis_client.delete(_closure_idempotency_redis_key(idempotency_key))
            return
        except Exception:
            logger.warning("Agent action Redis closure idempotency release failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if (
            existing_entry is not None
            and existing_entry.request_id == closure_id
            and existing_entry.request_hash == request_hash
        ):
            _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY.pop(idempotency_key, None)


async def _release_execute_idempotency_claim(
    *,
    idempotency_key: str,
    request_id: str,
    request_hash: str,
) -> None:
    redis_client = await _resolve_redis_client()
    if redis_client is not None:
        try:
            existing = await _read_execute_idempotency_entry(idempotency_key)
            if existing and existing.get("request_id") == request_id and existing.get("request_hash") == request_hash:
                await redis_client.delete(_execute_idempotency_redis_key(idempotency_key))
            return
        except Exception:
            logger.warning("Agent action Redis execute idempotency release failed; falling back to in-memory.", exc_info=True)
    with _REQUEST_RECORDS_LOCK:
        existing_entry = _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY.get(idempotency_key)
        if (
            existing_entry is not None
            and existing_entry.request_id == request_id
            and existing_entry.request_hash == request_hash
        ):
            _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY.pop(idempotency_key, None)


def _resolve_digital_twin_service() -> DigitalTwinService | None:
    global _DIGITAL_TWIN_SERVICE
    with _DIGITAL_TWIN_SERVICE_LOCK:
        if _DIGITAL_TWIN_SERVICE is not None:
            return _DIGITAL_TWIN_SERVICE
        session_factory = get_async_pg_session_factory()
        if session_factory is None:
            return None
        _DIGITAL_TWIN_SERVICE = DigitalTwinService(session_factory=session_factory)
        return _DIGITAL_TWIN_SERVICE


def _prefixed_twin_id(kind: str, raw_value: str | None) -> str | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    prefix = f"{kind}:"
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _evaluate_gate_subject_refs_for_request(
    *,
    payload: AgentActionEvaluateRequest,
) -> List[Tuple[str, str]]:
    refs: List[Tuple[str, str]] = []
    asset_ref = _prefixed_twin_id("asset", payload.asset.asset_id)
    if asset_ref:
        refs.append(("asset", asset_ref))
    lot_id = str(payload.asset.lot_id or "").strip()
    batch_ref = _prefixed_twin_id("batch", lot_id)
    if batch_ref:
        refs.append(("batch", batch_ref))
    transaction_ref = _prefixed_twin_id("transaction", payload.request_id)
    if transaction_ref:
        refs.append(("transaction", transaction_ref))
    return refs


def _closure_gate_subject_refs(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
) -> List[Tuple[str, str]]:
    refs: List[Tuple[str, str]] = []
    asset_id = _closure_request_asset_id(request_record=request_record)
    asset_ref = _prefixed_twin_id("asset", asset_id)
    if asset_ref:
        refs.append(("asset", asset_ref))
    request_payload = (
        dict(request_record.request_payload)
        if isinstance(request_record.request_payload, dict)
        else {}
    )
    request_asset = (
        request_payload.get("asset")
        if isinstance(request_payload.get("asset"), dict)
        else {}
    )
    lot_id = str(request_asset.get("lot_id") or "").strip()
    batch_ref = _prefixed_twin_id("batch", lot_id)
    if batch_ref:
        refs.append(("batch", batch_ref))
    transaction_ref = _prefixed_twin_id("transaction", closure_payload.request_id)
    if transaction_ref:
        refs.append(("transaction", transaction_ref))
    return refs


async def _evaluate_result_verifier_gate_for_twin_refs(
    *,
    twin_refs: List[Tuple[str, str]],
    twin_service: DigitalTwinService | None = None,
) -> Dict[str, Any]:
    normalized_refs = [
        (str(twin_type).strip(), str(twin_id).strip())
        for twin_type, twin_id in twin_refs
        if str(twin_type).strip() and str(twin_id).strip()
    ]
    if not normalized_refs:
        return {"blocked": False, "checked_refs": 0}

    checked = len(normalized_refs)
    service = twin_service or _resolve_digital_twin_service()
    if service is None:
        return build_result_verifier_gate_failure_verdict(
            reason_code="result_verifier_gate_service_unavailable",
            checked_refs=checked,
        )
    evaluator = getattr(service, "evaluate_result_verifier_gate", None)
    if not callable(evaluator):
        return build_result_verifier_gate_failure_verdict(
            reason_code="result_verifier_gate_unavailable",
            checked_refs=checked,
        )
    try:
        verdict = await evaluator(twin_refs=normalized_refs)
    except Exception:
        logger.warning("RESULT_VERIFIER policy/closure gate evaluation failed", exc_info=True)
        return build_result_verifier_gate_failure_verdict(
            reason_code="result_verifier_gate_eval_failed",
            checked_refs=checked,
        )
    if isinstance(verdict, dict):
        return dict(verdict)
    return build_result_verifier_gate_failure_verdict(
        reason_code="result_verifier_gate_invalid_verdict",
        checked_refs=checked,
    )


async def _apply_result_verifier_policy_gate(
    *,
    payload: AgentActionEvaluateRequest,
    response: AgentActionEvaluateResponse,
) -> AgentActionEvaluateResponse:
    disposition = str(response.decision.disposition or "").strip().lower()
    if disposition != "allow":
        return response

    verdict = await _evaluate_result_verifier_gate_for_twin_refs(
        twin_refs=_evaluate_gate_subject_refs_for_request(payload=payload),
    )
    if not bool(verdict.get("blocked")):
        return response

    reason_code = str(verdict.get("reason_code") or "result_verifier_lockout").strip()
    reason = str(verdict.get("reason") or "").strip()
    twin_type = str(verdict.get("twin_type") or "").strip()
    twin_id = str(verdict.get("twin_id") or "").strip()
    if not reason:
        target = f"{twin_type}:{twin_id}" if twin_type and twin_id else "authoritative subject twin"
        reason = f"RESULT_VERIFIER lockout blocks transfer execution for {target}."

    trust_gaps = list(response.trust_gaps)
    for marker in ("result_verifier_lockout", reason_code):
        if marker and marker not in trust_gaps:
            trust_gaps.append(marker)
    minted_artifacts = [item for item in response.minted_artifacts if item != "ExecutionToken"]

    return response.model_copy(
        update={
            "decision": response.decision.model_copy(
                update={
                    "allowed": False,
                    "disposition": "deny",
                    "reason_code": reason_code,
                    "reason": reason,
                }
            ),
            "execution_token": None,
            "trust_gaps": trust_gaps,
            "minted_artifacts": minted_artifacts,
        }
    )


async def _enforce_result_verifier_closure_gate(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
    twin_service: DigitalTwinService | None = None,
) -> None:
    verdict = await _evaluate_result_verifier_gate_for_twin_refs(
        twin_refs=_closure_gate_subject_refs(
            request_record=request_record,
            closure_payload=closure_payload,
        ),
        twin_service=twin_service,
    )
    if not bool(verdict.get("blocked")):
        return

    reason_code = str(verdict.get("reason_code") or "result_verifier_lockout").strip()
    message = str(verdict.get("reason") or "").strip() or (
        "Closure blocked by authoritative RESULT_VERIFIER lockout state."
    )
    twin_ref = None
    twin_type = str(verdict.get("twin_type") or "").strip()
    twin_id = str(verdict.get("twin_id") or "").strip()
    if twin_type and twin_id:
        twin_ref = f"{twin_type}:{twin_id}"

    detail: Dict[str, Any] = {
        "error_code": "closure_blocked_by_result_verifier",
        "message": message,
        "request_id": closure_payload.request_id,
        "gate_reason_code": reason_code,
    }
    if twin_ref:
        detail["twin_ref"] = twin_ref
    raise HTTPException(status_code=409, detail=detail)


def _closure_request_asset_id(
    *,
    request_record: _AgentActionStoredRecord,
) -> str:
    request_payload = (
        dict(request_record.request_payload)
        if isinstance(request_record.request_payload, dict)
        else {}
    )
    request_asset = (
        request_payload.get("asset")
        if isinstance(request_payload.get("asset"), dict)
        else {}
    )
    governed_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )
    return str(
        request_asset.get("asset_id")
        or governed_receipt.get("asset_ref")
        or governed_receipt.get("resource_ref")
        or ""
    ).strip()


def _validate_closure_telemetry_refs_asset_binding(
    *,
    closure_payload: AgentActionClosureRequest,
    request_record: _AgentActionStoredRecord,
) -> None:
    if not closure_payload.telemetry_refs:
        return
    asset_id = _closure_request_asset_id(request_record=request_record)
    if not asset_id:
        raise HTTPException(
            status_code=422,
            detail=_invalid_request_envelope(
                message="telemetry_refs require a resolvable request asset_id for binding validation",
                request_id=closure_payload.request_id,
            ),
        )
    for ref in closure_payload.telemetry_refs:
        if str(ref.asset_ref).strip() != asset_id:
            raise HTTPException(
                status_code=422,
                detail=_invalid_request_envelope(
                    message="telemetry_refs.asset_ref must match the evaluated request asset_id",
                    request_id=closure_payload.request_id,
                ),
            )


def _derive_closure_relevant_twin_snapshot(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
) -> Dict[str, Dict[str, Any]]:
    request_payload = (
        dict(request_record.request_payload)
        if isinstance(request_record.request_payload, dict)
        else {}
    )
    asset_payload = request_payload.get("asset") if isinstance(request_payload.get("asset"), dict) else {}
    governed_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )

    asset_ref = str(
        asset_payload.get("asset_id")
        or governed_receipt.get("asset_ref")
        or governed_receipt.get("resource_ref")
        or ""
    ).strip()
    lot_id = str(asset_payload.get("lot_id") or "").strip()
    node_id = str(closure_payload.node_id or "").strip()

    snapshots: Dict[str, Dict[str, Any]] = {
        "transaction": {
            "twin_kind": "transaction",
            "twin_id": _prefixed_twin_id("transaction", closure_payload.request_id) or f"transaction:{closure_payload.request_id}",
            "lifecycle_state": "IN_TRANSIT",
            "identity": {"request_id": closure_payload.request_id},
            "custody": {"pending_authority": True},
        }
    }
    if asset_ref:
        snapshots["asset"] = {
            "twin_kind": "asset",
            "twin_id": _prefixed_twin_id("asset", asset_ref) or f"asset:{asset_ref}",
            "lifecycle_state": "IN_TRANSIT",
            "identity": {"asset_id": asset_ref},
            "custody": {"asset_id": asset_ref, "pending_authority": True},
        }
    if lot_id:
        snapshots["batch"] = {
            "twin_kind": "batch",
            "twin_id": _prefixed_twin_id("batch", lot_id) or f"batch:{lot_id}",
            "lifecycle_state": "IN_TRANSIT",
            "identity": {"lot_id": lot_id},
            "custody": {"lot_id": lot_id, "pending_authority": True},
        }
    if node_id:
        snapshots["edge"] = {
            "twin_kind": "edge",
            "twin_id": _prefixed_twin_id("edge", node_id) or f"edge:{node_id}",
            "lifecycle_state": "ACTUATED",
            "identity": {"node_id": node_id},
            "custody": {"authoritative_node_id": node_id},
        }
    return snapshots


def _build_closure_evidence_bundle(
    *,
    closure_payload: AgentActionClosureRequest,
    request_record: _AgentActionStoredRecord,
) -> Dict[str, Any]:
    execution_token_constraints = (
        dict(request_record.response.execution_token.constraints)
        if request_record.response.execution_token is not None
        else {}
    )
    request_payload = (
        dict(request_record.request_payload)
        if isinstance(request_record.request_payload, dict)
        else {}
    )
    request_principal = (
        request_payload.get("principal")
        if isinstance(request_payload.get("principal"), dict)
        else {}
    )
    request_asset = (
        request_payload.get("asset")
        if isinstance(request_payload.get("asset"), dict)
        else {}
    )
    request_authority_scope = (
        request_payload.get("authority_scope")
        if isinstance(request_payload.get("authority_scope"), dict)
        else {}
    )
    request_workflow = request_payload.get("workflow") if isinstance(request_payload.get("workflow"), dict) else {}
    request_approval = (
        request_payload.get("approval")
        if isinstance(request_payload.get("approval"), dict)
        else {}
    )
    hardware = (
        request_principal.get("hardware_fingerprint")
        if isinstance(request_principal.get("hardware_fingerprint"), dict)
        else {}
    )
    governed_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )
    endpoint_node_id = str(execution_token_constraints.get("endpoint_id") or "").strip()
    resolved_node_id = str(closure_payload.node_id or "").strip() or endpoint_node_id
    disposition = str(request_record.response.decision.disposition or "").strip().lower() or "unknown"
    request_id = str(closure_payload.request_id or "").strip() or "unknown_request"
    audit_id = (
        str(governed_receipt.get("audit_id") or request_id).strip()
        or request_id
    )
    decision_hash = _hash_or_passthrough(
        governed_receipt.get("decision_hash"),
        fallback=f"decision:{request_id}:{closure_payload.forensic_block.forensic_block_id}",
    )
    asset_id = str(request_asset.get("asset_id") or governed_receipt.get("asset_ref") or "").strip() or "asset:unknown"
    principal_id = str(request_principal.get("agent_id") or "").strip() or "unknown_principal"
    delegation_ref = str(request_principal.get("delegation_ref") or "").strip()
    if not delegation_ref:
        delegation_ref = _hash_or_passthrough(
            None,
            fallback=f"delegation:{principal_id}:{asset_id}:{request_id}",
        )
    hardware_fingerprint = str(hardware.get("public_key_fingerprint") or "").strip()
    if not hardware_fingerprint:
        hardware_fingerprint = _hash_or_passthrough(
            None,
            fallback=f"hardware:{principal_id}:{request_id}",
        )
    coordinate_ref = str(
        closure_payload.forensic_block.current_coordinate_ref
        or request_authority_scope.get("expected_coordinate_ref")
        or ""
    ).strip()
    if not coordinate_ref:
        coordinate_ref = f"coordinate:unknown:{asset_id}"
    forensic_block = {
        "@context": FORENSIC_BLOCK_CONTEXT,
        "@type": "ForensicBlock",
        "forensic_block_id": closure_payload.forensic_block.forensic_block_id,
        "block_header": {
            "forensic_block_id": closure_payload.forensic_block.forensic_block_id,
            "audit_id": audit_id,
            "timestamp": _to_utc_iso(closure_payload.closed_at),
            "version": "seedcore.forensic_block.v1",
        },
        "decision_linkage": {
            "request_id": request_id,
            "disposition": disposition.upper(),
            "decision_hash": decision_hash,
            "policy_receipt_id": str(governed_receipt.get("policy_receipt_id") or "").strip() or None,
            "policy_snapshot_ref": str(request_record.response.decision.policy_snapshot_ref or "").strip() or None,
        },
        "asset_identity": {
            "asset_id": asset_id,
            "lot_id": str(request_asset.get("lot_id") or "").strip() or None,
            "product_ref": str(request_asset.get("product_ref") or "").strip() or None,
            "quote_ref": str(request_asset.get("quote_ref") or "").strip() or None,
        },
        "authority_context": {
            "@type": "DelegatedAuthority",
            "principal_id": principal_id,
            "owner_id": str(request_principal.get("owner_id") or "").strip() or None,
            "hardware_fingerprint": hardware_fingerprint,
            "kms_key_ref": str(hardware.get("key_ref") or "").strip() or None,
            "delegation_chain_hash": delegation_ref,
            "execution_token_id": (
                request_record.response.execution_token.token_id
                if request_record.response.execution_token is not None
                else None
            ),
            "organization_ref": str(request_principal.get("organization_ref") or "").strip() or None,
        },
        "fingerprint_components": closure_payload.forensic_block.fingerprint_components.model_dump(mode="json"),
        "economic_evidence": {
            "@type": "CommerceTransaction",
            "platform": "seedcore_rct",
            "order_id": str(request_asset.get("order_ref") or "").strip() or None,
            "transaction_hash": closure_payload.forensic_block.fingerprint_components.economic_hash,
            "quote_hash": str(request_asset.get("quote_ref") or "").strip() or None,
            "asset_identity": asset_id,
        },
        "spatial_evidence": {
            "coordinate_binding": {
                "coordinate_ref": coordinate_ref,
                "system": "seedcore",
            },
            "current_zone": str(
                closure_payload.forensic_block.current_zone
                or request_authority_scope.get("expected_to_zone")
                or ""
            ).strip()
            or None,
            "presence_proof_hash": closure_payload.forensic_block.fingerprint_components.physical_presence_hash,
        },
        "cognitive_evidence": {
            "@type": "PolicyReasoning",
            "policy_receipt_id": str(governed_receipt.get("policy_receipt_id") or "").strip() or None,
            "decision": disposition.upper(),
            "reasoning_trace_hash": closure_payload.forensic_block.fingerprint_components.reasoning_hash,
            "matched_policy_refs": list(governed_receipt.get("matched_policy_refs") or []),
        },
        "physical_evidence": {
            "@type": "ActuatorProof",
            "device_actor": resolved_node_id or None,
            "edge_node": resolved_node_id or None,
            "trajectory_hash": _hash_or_passthrough(
                governed_receipt.get("decision_hash"),
                fallback=f"trajectory:{request_id}:{asset_id}",
            ),
            "actuator_telemetry": {
                "motor_torque_hash": closure_payload.forensic_block.fingerprint_components.actuator_hash,
            },
            "sensor_signatures": [],
            "telemetry_refs": [ref.model_dump(mode="json") for ref in closure_payload.telemetry_refs],
        },
        "settlement_status": {
            "is_finalized": closure_payload.outcome == "completed",
            "twin_mutation_id": None,
            "forensic_integrity_hash": _hash_or_passthrough(
                governed_receipt.get("decision_hash"),
                fallback=f"settlement:{request_id}:{closure_payload.closure_id}",
            ),
        },
    }
    state_binding_hash = _hash_or_passthrough(
        governed_receipt.get("state_binding_hash"),
        fallback=f"state-binding:{request_id}:{asset_id}:{closure_payload.closure_id}",
    )
    resolved_policy_receipt_id = (
        str(governed_receipt.get("policy_receipt_id") or "").strip()
        or f"policy-receipt:{request_id}"
    )
    resolved_policy_snapshot_hash = str(
        governed_receipt.get("snapshot_hash")
        or governed_receipt.get("policy_snapshot_hash")
        or request_record.response.decision.policy_snapshot_hash
        or ""
    ).strip() or None
    resolved_decision_graph_snapshot_hash = str(
        governed_receipt.get("decision_graph_snapshot_hash")
        or governed_receipt.get("snapshot_hash")
        or request_record.response.decision.policy_snapshot_hash
        or ""
    ).strip() or None
    resolved_decision_graph_snapshot_version = str(
        governed_receipt.get("snapshot_version")
        or request_record.response.decision.policy_snapshot_ref
        or ""
    ).strip() or None

    requested_transition_receipts = [
        str(ref).strip()
        for ref in closure_payload.transition_receipt_ids
        if str(ref).strip()
    ]
    if not requested_transition_receipts:
        requested_transition_receipts = [f"transition:{request_id}:{closure_payload.closure_id}"]
    causal_parent_refs = _closure_causal_parent_refs(
        request_approval=request_approval,
        governed_receipt=governed_receipt,
    )

    resolved_execution_token_id = (
        request_record.response.execution_token.token_id
        if request_record.response.execution_token is not None
        else f"execution-token:{request_id}"
    )
    resolved_hardware_uuid = str(
        hardware.get("fingerprint_id")
        or hardware.get("node_id")
        or "hardware:unknown"
    ).strip() or "hardware:unknown"

    transition_receipts: List[Dict[str, Any]] = []
    for index, requested_transition_receipt_id in enumerate(requested_transition_receipts):
        transition_receipt = build_transition_receipt(
            intent_id=request_id,
            token_id=resolved_execution_token_id,
            actuator_endpoint=resolved_node_id or "hal://seedcore/unknown",
            hardware_uuid=resolved_hardware_uuid,
            actuator_result_hash=closure_payload.forensic_block.fingerprint_components.actuator_hash,
            target_zone=str(request_asset.get("to_zone") or "").strip() or None,
            from_zone=str(request_asset.get("from_zone") or "").strip() or None,
            to_zone=str(request_asset.get("to_zone") or "").strip() or None,
            executed_at=_to_utc_iso(closure_payload.closed_at),
            receipt_nonce=f"{closure_payload.closure_id}:{index}",
            # Keep workflow_type unset so local showcase receipts can validate
            # without restricted attestation requirements.
            workflow_type=None,
        )
        if requested_transition_receipt_id != str(transition_receipt.get("transition_receipt_id") or "").strip():
            transition_receipt["requested_transition_receipt_id"] = requested_transition_receipt_id
        transition_receipts.append(transition_receipt)

    bundle: Dict[str, Any] = {
        "evidence_bundle_id": closure_payload.evidence_bundle_id,
        "task_id": request_id,
        "intent_id": request_id,
        "intent_ref": f"governance://action-intent/{request_id}",
        "execution_token_id": (
            request_record.response.execution_token.token_id
            if request_record.response.execution_token is not None
            else None
        ),
        "policy_receipt_id": resolved_policy_receipt_id,
        "policy_snapshot_hash": resolved_policy_snapshot_hash,
        "decision_graph_snapshot_hash": resolved_decision_graph_snapshot_hash,
        "decision_graph_snapshot_version": resolved_decision_graph_snapshot_version,
        "state_binding_hash": state_binding_hash,
        "co_sign_required": bool(governed_receipt.get("co_sign_required")),
        "co_sign_status": str(governed_receipt.get("co_sign_status") or "").strip() or None,
        "transfer_outcome": str(governed_receipt.get("transfer_outcome") or "").strip() or None,
        "co_sign_binding_hash": str(governed_receipt.get("co_sign_binding_hash") or "").strip() or None,
        "expected_co_signers": [
            dict(item)
            for item in list(governed_receipt.get("expected_co_signers") or [])
            if isinstance(item, dict)
        ],
        "co_signatures": [
            dict(item)
            for item in list(governed_receipt.get("co_signatures") or [])
            if isinstance(item, dict)
        ],
        "causal_parent_refs": causal_parent_refs,
        "transition_receipt_ids": [
            str(item.get("transition_receipt_id"))
            for item in transition_receipts
            if str(item.get("transition_receipt_id") or "").strip()
        ],
        "node_id": resolved_node_id or None,
        "execution_receipt": {"node_id": resolved_node_id} if resolved_node_id else {},
        "forensic_block": forensic_block,
        "evidence_inputs": {
            "execution_summary": {"node_id": resolved_node_id} if resolved_node_id else {},
            "transition_receipts": transition_receipts,
            "summary": dict(closure_payload.summary or {}),
        },
        "media_refs": [],
        "created_at": _to_utc_iso(closure_payload.closed_at),
    }
    if closure_payload.telemetry_refs:
        bundle["telemetry_refs"] = [ref.model_dump(mode="json") for ref in closure_payload.telemetry_refs]
    else:
        bundle["telemetry_refs"] = []

    normalized_for_signing = dict(bundle)
    normalized_for_signing["signer_metadata"] = {
        "signer_type": "service",
        "signer_id": "seedcore-verify",
        "signing_scheme": "hmac_sha256",
        "key_ref": "seedcore-evidence-hmac",
        "attestation_level": "baseline",
        "node_id": resolved_node_id or None,
    }
    normalized_for_signing["signature"] = "pending"
    normalized_model = EvidenceBundle(**normalized_for_signing)
    signed_payload = normalized_model.model_dump(
        mode="json",
        exclude={"signature", "signer_metadata", "trust_proof"},
        exclude_unset=True,
    )
    _, signer_metadata, signature, trust_proof = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=signed_payload,
        endpoint_id=resolved_node_id or None,
        node_id=resolved_node_id or None,
    )
    bundle["signer_metadata"] = signer_metadata.model_dump(mode="json")
    bundle["signature"] = signature
    if trust_proof is not None:
        bundle["trust_proof"] = trust_proof.model_dump(mode="json")
    return bundle


def _closure_causal_parent_refs(
    *,
    request_approval: Mapping[str, Any],
    governed_receipt: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _append(relation: str, artifact_type: str, artifact_id: Any) -> None:
        normalized_id = str(artifact_id or "").strip()
        if not normalized_id:
            return
        key = (relation, artifact_type, normalized_id)
        if key in seen:
            return
        seen.add(key)
        refs.append(
            {
                "relation": relation,
                "artifact_type": artifact_type,
                "artifact_id": normalized_id,
            }
        )

    _append("approved_by", "approval_envelope", request_approval.get("approval_envelope_id"))
    _append("authorized_by", "policy_receipt", governed_receipt.get("policy_receipt_id"))
    _append("authorized_by", "governed_receipt", governed_receipt.get("decision_hash"))
    return refs


def _build_closure_policy_receipt(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
    evidence_bundle: Mapping[str, Any],
) -> Dict[str, Any]:
    request_payload = dict(request_record.request_payload) if isinstance(request_record.request_payload, dict) else {}
    request_asset = request_payload.get("asset") if isinstance(request_payload.get("asset"), dict) else {}
    governed_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )
    request_id = str(closure_payload.request_id or "").strip() or "unknown_request"
    asset_ref = str(request_asset.get("asset_id") or governed_receipt.get("asset_ref") or "").strip() or None
    policy_receipt_id = str(
        evidence_bundle.get("policy_receipt_id")
        or governed_receipt.get("policy_receipt_id")
        or f"policy-receipt:{request_id}"
    ).strip()
    policy_payload: Dict[str, Any] = {
        "policy_receipt_id": policy_receipt_id,
        "policy_decision_id": str(governed_receipt.get("decision_hash") or f"decision:{request_id}").strip(),
        "task_id": request_id,
        "intent_id": request_id,
        "policy_version": str(
            request_record.response.decision.policy_snapshot_ref
            or governed_receipt.get("snapshot_version")
            or ""
        ).strip() or None,
        "decision": {
            "allowed": bool(request_record.response.decision.allowed),
            "disposition": request_record.response.decision.disposition,
            "reason": request_record.response.decision.reason,
            "reason_code": request_record.response.decision.reason_code,
        },
        "evaluated_rules": list(request_record.response.required_approvals or []),
        "subject_ref": asset_ref,
        "asset_ref": asset_ref,
        "authz_disposition": request_record.response.decision.disposition,
        "governed_receipt_hash": _hash_or_passthrough(
            governed_receipt.get("decision_hash"),
            fallback=f"governed-receipt:{policy_receipt_id}",
        ),
        "policy_snapshot_hash": str(
            evidence_bundle.get("policy_snapshot_hash")
            or request_record.response.decision.policy_snapshot_hash
            or ""
        ).strip() or None,
        "decision_graph_snapshot_hash": str(
            evidence_bundle.get("decision_graph_snapshot_hash")
            or request_record.response.decision.policy_snapshot_hash
            or ""
        ).strip() or None,
        "decision_graph_snapshot_version": str(
            evidence_bundle.get("decision_graph_snapshot_version")
            or request_record.response.decision.policy_snapshot_ref
            or ""
        ).strip() or None,
        "state_binding_hash": str(evidence_bundle.get("state_binding_hash") or "").strip() or None,
        "co_sign_required": bool(evidence_bundle.get("co_sign_required")),
        "co_sign_status": str(evidence_bundle.get("co_sign_status") or "").strip() or None,
        "transfer_outcome": str(evidence_bundle.get("transfer_outcome") or "").strip() or None,
        "co_sign_binding_hash": str(evidence_bundle.get("co_sign_binding_hash") or "").strip() or None,
        "expected_co_signers": [
            dict(item)
            for item in list(evidence_bundle.get("expected_co_signers") or [])
            if isinstance(item, dict)
        ],
        "trust_gap_codes": list(request_record.response.trust_gaps or []),
        "timestamp": _to_utc_iso(closure_payload.closed_at),
    }
    payload_hash, signer_metadata, signature, trust_proof = build_signed_artifact(
        artifact_type="policy_receipt",
        payload=dict(policy_payload),
        endpoint_id=str(closure_payload.node_id or "").strip() or None,
        workflow_type="restricted_custody_transfer",
        disposition=str(request_record.response.decision.disposition or "").strip() or None,
    )
    policy_payload["signature"] = signature
    policy_payload["signer_metadata"] = signer_metadata.model_dump(mode="json")
    policy_payload["payload_hash"] = payload_hash
    if trust_proof is not None:
        policy_payload["trust_proof"] = trust_proof.model_dump(mode="json")
    return policy_payload


def _closure_task_uuid(request_id: str) -> str:
    raw = str(request_id or "").strip()
    if not raw:
        return str(uuid.uuid4())
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


async def _resolve_existing_task_id_for_governed_audit(session: Any, request_id: str) -> str | None:
    candidate = _closure_task_uuid(request_id)
    found = await session.execute(
        text("SELECT id FROM tasks WHERE id = CAST(:task_id AS uuid) LIMIT 1"),
        {"task_id": candidate},
    )
    row = found.mappings().first()
    if row and row.get("id") is not None:
        return str(row["id"])

    fallback = await session.execute(
        text("SELECT id FROM tasks ORDER BY created_at DESC NULLS LAST, id DESC LIMIT 1")
    )
    row = fallback.mappings().first()
    if row and row.get("id") is not None:
        return str(row["id"])
    return None


async def _persist_closure_governed_audit_record(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
    evidence_bundle: Dict[str, Any],
) -> Dict[str, Any] | None:
    session_factory = get_async_pg_session_factory()
    if session_factory is None:
        return None

    request_payload = (
        dict(request_record.request_payload)
        if isinstance(request_record.request_payload, dict)
        else {}
    )
    request_asset = request_payload.get("asset") if isinstance(request_payload.get("asset"), dict) else {}
    request_workflow = request_payload.get("workflow") if isinstance(request_payload.get("workflow"), dict) else {}
    request_principal = request_payload.get("principal") if isinstance(request_payload.get("principal"), dict) else {}

    decision = request_record.response.decision
    governed_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )
    action_intent = {
        "intent_id": closure_payload.request_id,
        "principal": {
            "agent_id": request_principal.get("agent_id"),
            "role_profile": request_principal.get("role_profile"),
        },
        "resource": {
            "asset_id": request_asset.get("asset_id"),
            "lot_id": request_asset.get("lot_id"),
            "target_zone": request_asset.get("to_zone"),
        },
        "action": {
            "type": request_workflow.get("action_type"),
            "operation": request_workflow.get("type"),
            "parameters": {
                "endpoint_id": closure_payload.node_id,
            },
        },
    }
    policy_receipt = _build_closure_policy_receipt(
        request_record=request_record,
        closure_payload=closure_payload,
        evidence_bundle=evidence_bundle,
    )
    policy_decision = {
        "allowed": bool(decision.allowed),
        "disposition": decision.disposition,
        "reason": decision.reason,
        "reason_code": decision.reason_code,
        "policy_snapshot": decision.policy_snapshot_ref,
        "required_approvals": list(request_record.response.required_approvals or []),
        "authz_graph": {
            "workflow_type": "restricted_custody_transfer",
            "disposition": decision.disposition,
            "reason": decision.reason,
            "snapshot_hash": decision.policy_snapshot_hash,
            "snapshot_version": decision.policy_snapshot_ref,
            "policy_snapshot_hash": decision.policy_snapshot_hash,
            "state_binding_hash": evidence_bundle.get("state_binding_hash"),
        },
        "governed_receipt": {
            **governed_receipt,
            "audit_id": governed_receipt.get("audit_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, closure_payload.request_id)),
            "state_binding_hash": evidence_bundle.get("state_binding_hash"),
            "policy_snapshot_hash": evidence_bundle.get("policy_snapshot_hash"),
            "decision_graph_snapshot_hash": evidence_bundle.get("decision_graph_snapshot_hash"),
            "policy_receipt_id": policy_receipt.get("policy_receipt_id"),
        },
    }
    policy_case = {
        "required_approvals": list(request_record.response.required_approvals or []),
        "trust_gaps": list(request_record.response.trust_gaps or []),
        "obligations": [dict(item) for item in list(request_record.response.obligations or []) if isinstance(item, dict)],
        "workflow_hints": {
            "workflow_type": "restricted_custody_transfer",
            "strict_state_transition_fields": True,
        },
    }

    dao = GovernedExecutionAuditDAO()
    try:
        async with session_factory() as session:
            begin_ctx = session.begin()
            if asyncio.iscoroutine(begin_ctx):
                begin_ctx = await begin_ctx
            async with begin_ctx:
                resolved_task_id = await _resolve_existing_task_id_for_governed_audit(
                    session,
                    closure_payload.request_id,
                )
                if not resolved_task_id:
                    return None
                return await dao.append_record(
                    session,
                    task_id=resolved_task_id,
                    record_type="execution_receipt",
                    intent_id=closure_payload.request_id,
                    token_id=(
                        request_record.response.execution_token.token_id
                        if request_record.response.execution_token is not None
                        else None
                    ),
                    policy_snapshot=decision.policy_snapshot_ref,
                    policy_decision=policy_decision,
                    action_intent=action_intent,
                    policy_case=policy_case,
                    policy_receipt=policy_receipt,
                    evidence_bundle=evidence_bundle,
                    actor_agent_id=str(request_principal.get("agent_id") or "").strip() or None,
                    actor_organ_id=None,
                )
    except Exception:
        logger.warning(
            "Failed to persist closure governed audit record for request_id=%s closure_id=%s",
            closure_payload.request_id,
            closure_payload.closure_id,
            exc_info=True,
        )
        return None


async def _apply_closure_settlement_handoff(
    *,
    request_record: _AgentActionStoredRecord,
    closure_payload: AgentActionClosureRequest,
) -> Tuple[str, Dict[str, Any]]:
    if not SETTLEMENT_HANDOFF_ENABLED:
        return "pending", {"enabled": False, "reason": "feature_flag_disabled"}

    twin_service = _resolve_digital_twin_service()
    if twin_service is None:
        return "rejected", {"enabled": True, "error_code": "settlement_session_unavailable"}

    gate_verdict = await _evaluate_result_verifier_gate_for_twin_refs(
        twin_refs=_closure_gate_subject_refs(
            request_record=request_record,
            closure_payload=closure_payload,
        ),
        twin_service=twin_service,
    )
    if bool(gate_verdict.get("blocked")):
        return "rejected", {
            "enabled": True,
            "error_code": "settlement_blocked_by_result_verifier",
            "gate_reason_code": str(gate_verdict.get("reason_code") or "result_verifier_lockout"),
            "reason": str(gate_verdict.get("reason") or ""),
            "twin_type": gate_verdict.get("twin_type"),
            "twin_id": gate_verdict.get("twin_id"),
        }

    policy_receipt = (
        dict(request_record.response.governed_receipt)
        if isinstance(request_record.response.governed_receipt, dict)
        else {}
    )
    execution_token = (
        request_record.response.execution_token.model_dump(mode="json")
        if request_record.response.execution_token is not None
        else {}
    )
    evidence_bundle = _build_closure_evidence_bundle(
        closure_payload=closure_payload,
        request_record=request_record,
    )
    relevant_twin_snapshot = _derive_closure_relevant_twin_snapshot(
        request_record=request_record,
        closure_payload=closure_payload,
    )

    try:
        settlement_result = await twin_service.settle_from_evidence_bundle(
            relevant_twin_snapshot=relevant_twin_snapshot,
            task_id=closure_payload.request_id,
            intent_id=closure_payload.request_id,
            policy_receipt=policy_receipt,
            execution_token=execution_token,
            evidence_summary={
                "outcome": closure_payload.outcome,
                "evidence_bundle_id": closure_payload.evidence_bundle_id,
            },
            evidence_bundle=evidence_bundle,
        )
    except Exception as exc:
        logger.warning(
            "Agent action closure settlement handoff failed for request_id=%s closure_id=%s",
            closure_payload.request_id,
            closure_payload.closure_id,
            exc_info=True,
        )
        return "rejected", {
            "enabled": True,
            "error_code": "settlement_exception",
            "detail": type(exc).__name__,
        }

    rejected_reason = str(settlement_result.get("rejected_reason") or "").strip()
    if rejected_reason:
        return "rejected", dict(settlement_result)
    append_result = await _persist_closure_governed_audit_record(
        request_record=request_record,
        closure_payload=closure_payload,
        evidence_bundle=evidence_bundle,
    )
    settled = dict(settlement_result)
    if isinstance(append_result, dict):
        settled["governed_audit_entry"] = append_result
    if int(settlement_result.get("updated", 0)) > 0:
        return "applied", settled
    return "pending", settled


def _normalize_specialization_candidate(value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def _resolve_preflight_specialization(payload: AgentActionEvaluateRequest) -> str | None:
    manager = SpecializationManager.get_instance()
    role_profile_candidate = _normalize_specialization_candidate(payload.principal.role_profile)
    if role_profile_candidate and manager.is_registered(role_profile_candidate):
        return role_profile_candidate

    agent_id_lower = str(payload.principal.agent_id or "").strip().lower()
    best_match: str | None = None
    for specialization in manager.list_all():
        value = _normalize_specialization_candidate(
            str(getattr(specialization, "value", specialization))
        )
        if not value:
            continue
        if value in agent_id_lower:
            if best_match is None or len(value) > len(best_match):
                best_match = value
    return best_match


def _build_organism_preflight_task(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    routing: Dict[str, Any] = {}
    preflight_specialization = _resolve_preflight_specialization(payload)
    if preflight_specialization:
        routing["required_specialization"] = preflight_specialization

    return {
        "task_id": payload.request_id,
        "type": "action",
        "domain": "custody",
        "description": "agent action gateway preflight",
        "params": {
            "interaction": {
                "mode": "coordinator_routed",
                "conversation_id": payload.request_id,
            },
            "routing": routing,
            "risk": {
                "is_high_stakes": True,
            },
            "agent_action_gateway": {
                "request_id": payload.request_id,
                "workflow_type": payload.workflow.type,
                "action_type": payload.workflow.action_type,
            },
        },
    }


def _telemetry_summary_from_payload(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    return {
        "observed_at": _to_utc_iso(payload.telemetry.observed_at),
        "freshness_seconds": payload.telemetry.freshness_seconds,
        "max_allowed_age_seconds": payload.telemetry.max_allowed_age_seconds,
        "current_zone": payload.telemetry.current_zone,
        "current_coordinate_ref": payload.telemetry.current_coordinate_ref,
        "evidence_refs": list(payload.telemetry.evidence_refs),
    }


def _evidence_summary_from_payload(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    return {
        "evidence_refs": list(payload.telemetry.evidence_refs),
        "reason_trace_ref": (
            payload.forensic_context.reason_trace_ref
            if payload.forensic_context is not None
            else None
        ),
    }


def _planner_inputs(payload: AgentActionEvaluateRequest) -> Dict[str, Any]:
    if payload.execution is None:
        return {}
    return dict(payload.execution.planner_inputs)


def _mint_delegated_subtoken(
    *,
    parent_token: ExecutionToken,
    payload: AgentActionEvaluateRequest,
    execution_plan: AgentActionExecutionPlan,
) -> ExecutionToken:
    planner_inputs = _planner_inputs(payload)
    now = datetime.now(timezone.utc)
    parent_valid_until = datetime.fromisoformat(str(parent_token.valid_until).replace("Z", "+00:00"))
    if parent_valid_until.tzinfo is None:
        parent_valid_until = parent_valid_until.replace(tzinfo=timezone.utc)
    subtoken_ttl_seconds = int(
        execution_plan.metadata.get("subtoken_ttl_seconds")
        or planner_inputs.get("subtoken_ttl_seconds")
        or 90
    )
    desired_valid_until = now + timedelta(seconds=max(30, subtoken_ttl_seconds))
    parent_bound_valid_until = parent_valid_until.astimezone(timezone.utc)
    if parent_bound_valid_until <= now:
        parent_bound_valid_until = desired_valid_until
    valid_until = min(parent_bound_valid_until, desired_valid_until)
    delegate_agent_id = str(
        execution_plan.metadata.get("delegate_agent_id")
        or planner_inputs.get("delegate_agent_id")
        or payload.principal.agent_id
    ).strip()
    delegate_endpoint_id = str(
        execution_plan.metadata.get("delegate_endpoint_id")
        or planner_inputs.get("delegate_endpoint_id")
        or payload.principal.hardware_fingerprint.endpoint_id
        or payload.principal.hardware_fingerprint.node_id
        or ""
    ).strip()
    parent_constraints = (
        dict(parent_token.constraints)
        if isinstance(parent_token.constraints, dict)
        else {}
    )
    subtoken_constraints = {
        **parent_constraints,
        "action_type": parent_constraints.get("action_type") or payload.workflow.action_type,
        "target_zone": parent_constraints.get("target_zone") or payload.asset.to_zone,
        "asset_id": parent_constraints.get("asset_id") or payload.asset.asset_id,
        "principal_agent_id": delegate_agent_id,
        "source_registration_id": parent_constraints.get("source_registration_id"),
        "registration_decision_id": parent_constraints.get("registration_decision_id"),
        "endpoint_id": delegate_endpoint_id or parent_constraints.get("endpoint_id"),
        "plan_dag_hash": execution_plan.plan_dag_hash,
        "payload_hash": None,
    }
    preconditions = parent_token.execution_preconditions.model_dump(mode="json")
    preconditions["plan_dag_hash"] = execution_plan.plan_dag_hash
    preconditions["endpoint_id"] = delegate_endpoint_id or preconditions.get("endpoint_id")
    preconditions["payload_hash"] = None
    minted = mint_execution_token_with_rust(
        {
            "token_id": str(uuid.uuid4()),
            "intent_id": payload.request_id,
            "issued_at": _to_utc_iso(now),
            "valid_until": _to_utc_iso(valid_until),
            "contract_version": parent_token.contract_version,
            "constraints": subtoken_constraints,
            "execution_preconditions": preconditions,
        }
    )
    if minted.get("error") is not None:
        raise ValueError(f"rust_subtoken_mint_failed:{minted.get('error')}")
    return ExecutionToken(**minted)


def _build_delegated_intent_execution_result(
    *,
    payload: AgentActionEvaluateRequest,
    execution_plan: AgentActionExecutionPlan,
    subtoken: ExecutionToken,
) -> Dict[str, Any]:
    planner_inputs = _planner_inputs(payload)
    delegate_agent_id = str(
        execution_plan.metadata.get("delegate_agent_id")
        or planner_inputs.get("delegate_agent_id")
        or payload.principal.agent_id
    ).strip()
    delegate_endpoint_id = str(
        execution_plan.metadata.get("delegate_endpoint_id")
        or planner_inputs.get("delegate_endpoint_id")
        or payload.principal.hardware_fingerprint.endpoint_id
        or payload.principal.hardware_fingerprint.node_id
        or ""
    ).strip()
    delegated_payload = payload.model_dump(mode="json")
    delegated_payload["principal"]["agent_id"] = delegate_agent_id
    if delegate_endpoint_id:
        delegated_payload["principal"]["hardware_fingerprint"]["endpoint_id"] = delegate_endpoint_id
    delegated_gateway_request = AgentActionEvaluateRequest.model_validate(delegated_payload)
    owner_preflight = OwnerContextPreflightRequest(
        owner_id=payload.principal.owner_id,
        assistant_id=delegate_agent_id,
        delegation_id=_normalize_delegation_id(payload.principal.delegation_ref),
        declared_value_usd=payload.asset.declared_value_usd,
        required_modalities=[payload.workflow.type],
        available_modalities=["delegated_execute"],
        observed_provenance_level=payload.asset.provenance_hash,
    )
    envelope = build_delegated_intent_envelope(
        DelegatedIntentPayload(
            request_id=payload.request_id,
            workflow_id=payload.request_id,
            correlation_id=payload.request_id,
            assistant_namespace=delegate_agent_id,
            owner_context_preflight=owner_preflight,
            gateway_request=delegated_gateway_request,
            metadata={
                "plan_id": execution_plan.plan_id,
                "plan_dag_hash": execution_plan.plan_dag_hash,
                "sub_execution_token": subtoken.model_dump(mode="json"),
            },
        ),
        producer="seedcore.agent_action_gateway",
    )
    return {
        "status": "delegated_ready",
        "delegate_agent_id": delegate_agent_id,
        "delegate_endpoint_id": delegate_endpoint_id or None,
        "plan_dag_hash": execution_plan.plan_dag_hash,
        "sub_execution_token": subtoken.model_dump(mode="json"),
        "delegated_intent_envelope": envelope,
    }


def _build_planned_only_execution_result(
    *,
    execution_plan: AgentActionExecutionPlan,
) -> Dict[str, Any]:
    if execution_plan.planner_type == PLANNER_TYPE_CONDITIONAL_ESCROW:
        return {
            "status": "awaiting_condition",
            "dispatched": False,
            "plan_id": execution_plan.plan_id,
            "plan_dag_hash": execution_plan.plan_dag_hash,
            "dead_mans_switch_seconds": execution_plan.metadata.get("dead_mans_switch_seconds"),
            "next_action": "poll_release_condition",
        }
    return {
        "status": "planned_only",
        "dispatched": False,
        "plan_id": execution_plan.plan_id,
        "plan_dag_hash": execution_plan.plan_dag_hash,
    }


def _build_organism_execute_task(
    *,
    payload: AgentActionEvaluateRequest,
    governance: Mapping[str, Any],
    execution_plan: AgentActionExecutionPlan,
) -> Dict[str, Any]:
    routing: Dict[str, Any] = {}
    preflight_specialization = _resolve_preflight_specialization(payload)
    if preflight_specialization:
        routing["required_specialization"] = preflight_specialization
    directives = executable_directives_from_plan(execution_plan)
    tool_calls = [
        {
            "name": directive.tool_name,
            "args": directive.args,
        }
        for directive in directives
    ]
    primary_tool_name = directives[0].tool_name if directives else None

    return {
        "task_id": payload.request_id,
        "type": "action",
        "domain": "custody",
        "description": "agent action gateway execute",
        "params": {
            "interaction": {
                "mode": "coordinator_routed",
                "conversation_id": payload.request_id,
            },
            "routing": routing,
            "risk": {
                "is_high_stakes": True,
            },
            "multimodal": {
                "location_context": payload.asset.to_zone or payload.telemetry.current_zone,
            },
            "resource": {
                "asset_id": payload.asset.asset_id,
                "lot_id": payload.asset.lot_id,
                "target_zone": payload.asset.to_zone,
            },
            "tool_calls": tool_calls,
            "governance": dict(governance),
            "agent_action_gateway": {
                "request_id": payload.request_id,
                "workflow_type": payload.workflow.type,
                "action_type": payload.workflow.action_type,
                "planner_type": execution_plan.planner_type,
                "plan_id": execution_plan.plan_id,
                "plan_dag_hash": execution_plan.plan_dag_hash,
                "tool_name": primary_tool_name,
            },
        },
    }


async def _organism_preflight_check(payload: AgentActionEvaluateRequest) -> Tuple[bool, str]:
    client = OrganismServiceClient(timeout=ORGANISM_PREFLIGHT_TIMEOUT_SECONDS)
    try:
        health = await client.health()
    except Exception as exc:
        return False, f"organism_health_unavailable:{type(exc).__name__}"
    try:
        initialized = bool(health.get("organism_initialized"))
        status = str(health.get("status") or "").strip().lower()
        if not (initialized and status == "healthy"):
            return False, f"organism_not_ready:{status or 'unknown'}"

        route_task = _build_organism_preflight_task(payload)
        route_response = await client.route_only(task=route_task)
        if not isinstance(route_response, dict):
            return False, "organism_route_invalid_response"

        resolved_agent = str(route_response.get("agent_id") or "").strip()
        resolved_organ = str(route_response.get("organ_id") or "").strip()
        route_reason = str(route_response.get("reason") or "").strip().lower()
        if not resolved_agent or not resolved_organ:
            return False, "organism_route_unresolved"
        if route_reason == "service_error_fallback":
            return False, "organism_route_fallback_error"
        return True, f"ok:{resolved_organ}:{resolved_agent}"
    except Exception as exc:
        return False, f"organism_route_unavailable:{type(exc).__name__}"
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _apply_organism_preflight(
    *,
    payload: AgentActionEvaluateRequest,
    response: AgentActionEvaluateResponse,
) -> AgentActionEvaluateResponse:
    if not ORGANISM_PREFLIGHT_REQUIRED:
        return response
    if str(response.decision.disposition or "").strip().lower() != "allow":
        return response
    ok, detail = await _organism_preflight_check(payload)
    if ok:
        return response
    trust_gaps = list(response.trust_gaps)
    if "organism_not_ready" not in trust_gaps:
        trust_gaps.append("organism_not_ready")
    retained_artifacts = [item for item in response.minted_artifacts if item != "ExecutionToken"]
    return response.model_copy(
        update={
            "decision": response.decision.model_copy(
                update={
                    "allowed": False,
                    "disposition": "quarantine",
                    "reason_code": "organism_not_ready",
                    "reason": (
                        "Organism service is not ready for routed agent execution "
                        f"({detail})."
                    ),
                }
            ),
            "trust_gaps": trust_gaps,
            "execution_token": None,
            "minted_artifacts": retained_artifacts,
        }
    )


def _as_request_record_response(record: _AgentActionStoredRecord) -> AgentActionRequestRecordResponse:
    return AgentActionRequestRecordResponse(
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        recorded_at=record.recorded_at,
        response=record.response,
    )


def _as_closure_record_response(record: _AgentActionClosureStoredRecord) -> AgentActionClosureRecordResponse:
    return AgentActionClosureRecordResponse(
        closure_id=record.closure_id,
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        recorded_at=record.recorded_at,
        response=record.response,
    )


def _build_agent_action_evaluate_response(
    *,
    payload: AgentActionEvaluateRequest,
    hot_path_result: HotPathEvaluateResponse,
    execution_plan: AgentActionExecutionPlan | None = None,
) -> AgentActionEvaluateResponse:
    bound_execution_token = _bind_plan_hash_to_execution_token(
        hot_path_result.execution_token,
        execution_plan=execution_plan,
    )
    bound_execution_context = _bind_plan_hash_to_execution_context(
        _execution_context_from_hot_path_result(
            execution_token=hot_path_result.execution_token,
            governed_receipt=dict(hot_path_result.governed_receipt),
        ),
        execution_plan=execution_plan,
    )
    return AgentActionEvaluateResponse(
        request_id=hot_path_result.request_id,
        decided_at=hot_path_result.decided_at,
        latency_ms=hot_path_result.latency_ms,
        decision=hot_path_result.decision,
        required_approvals=list(hot_path_result.required_approvals),
        trust_gaps=list(hot_path_result.trust_gaps),
        obligations=[dict(item) for item in hot_path_result.obligations],
        minted_artifacts=_minted_artifacts_from_hot_path_result(
            execution_token=hot_path_result.execution_token,
            governed_receipt=dict(hot_path_result.governed_receipt),
            signer_provenance=list(hot_path_result.signer_provenance),
        ),
        authority_scope_verdict=_build_authority_scope_verdict(payload),
        fingerprint_verdict=_build_fingerprint_verdict(payload),
        execution_plan=execution_plan,
        execution_token=bound_execution_token,
        execution_context=bound_execution_context,
        governed_receipt=dict(hot_path_result.governed_receipt),
        forensic_linkage={},
        request_schema_bundle=hot_path_result.request_schema_bundle,
        taxonomy_bundle=hot_path_result.taxonomy_bundle,
    )


def _invalid_request_envelope(
    *,
    message: str,
    request_id: str | None,
    errors: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error_code": "request_validation_failed",
        "message": message,
    }
    if request_id:
        payload["request_id"] = request_id
    if errors:
        payload["issues"] = errors
    return payload


def _parse_validate_payload(
    payload_body: Dict[str, Any],
    *,
    model: Any,
    request_id_hint: str | None = None,
) -> Any:
    try:
        return model.model_validate(payload_body)
    except ValidationError as exc:
        issues = []
        for issue in exc.errors():
            location = ".".join(str(item) for item in issue.get("loc", []))
            issues.append(
                {
                    "path": location or "$",
                    "type": issue.get("type"),
                    "message": issue.get("msg"),
                }
            )
        request_id = request_id_hint or str(payload_body.get("request_id") or "").strip() or None
        raise HTTPException(
            status_code=422,
            detail=_invalid_request_envelope(
                message="request payload failed schema validation",
                request_id=request_id,
                errors=issues,
            ),
        ) from exc


@router.post("/agent-actions/evaluate", response_model=AgentActionEvaluateResponse)
async def evaluate_agent_action(
    payload_body: Dict[str, Any] = Body(...),
    debug: bool = Query(default=False, description="Include check-by-check diagnostics."),
    no_execute: bool = Query(
        default=False,
        description="Preflight mode: evaluate policy and trust gaps without minting ExecutionToken.",
    ),
) -> AgentActionEvaluateResponse:
    payload = _parse_validate_payload(payload_body, model=AgentActionEvaluateRequest)
    requested_no_execute = bool(no_execute or payload.options.no_execute)
    request_hash = _canonical_gateway_payload_hash(payload, requested_no_execute=requested_no_execute)
    if get_async_pg_session_factory() is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "dependency_unavailable",
                "message": "approval_store_unavailable",
                "request_id": payload.request_id,
            },
        )
    claimed, idempotency_entry = await _claim_idempotency_key(
        idempotency_key=payload.idempotency_key,
        request_id=payload.request_id,
        request_hash=request_hash,
    )
    if not claimed and idempotency_entry is not None:
        existing_request_hash = str(idempotency_entry.get("request_hash") or "").strip()
        existing_request_id = str(idempotency_entry.get("request_id") or "").strip()
        if existing_request_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "idempotency_conflict",
                    "message": "idempotency key already used with different request body",
                    "request_id": payload.request_id,
                },
            )
        if existing_request_id:
            existing_record = await _read_request_record(existing_request_id)
            if existing_record is not None:
                return existing_record.response
            if existing_request_id != payload.request_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_in_progress",
                        "message": "idempotency key already claimed by an in-flight request",
                        "request_id": existing_request_id,
                    },
                )

    try:
        owner_twin_snapshot = await _resolve_owner_twin_snapshot_for_payload(payload)
        relevant_twin_snapshot = (
            {"owner": owner_twin_snapshot}
            if isinstance(owner_twin_snapshot, dict)
            else None
        )
        preliminary_hot_path_request = _map_to_hot_path_request(payload, request_hash=request_hash)
        # Keep v1 gateway semantics as a contract wrapper around the existing hot-path path.
        authoritative_transfer_approval = await resolve_authoritative_transfer_approval(
            preliminary_hot_path_request
        )
        execution_plan = build_execution_plan(
            payload,
            owner_twin_snapshot=owner_twin_snapshot,
            authoritative_transfer_approval=authoritative_transfer_approval,
        )
        hot_path_request = _map_to_hot_path_request(
            payload,
            request_hash=request_hash,
            plan_dag_hash_override=execution_plan.plan_dag_hash,
            prefer_plan_binding=True,
        )
        hot_path_result = evaluate_pdp_hot_path(
            hot_path_request,
            relevant_twin_snapshot=relevant_twin_snapshot,
            authoritative_approval_envelope=(
                authoritative_transfer_approval.get("authoritative_approval_envelope")
                if isinstance(authoritative_transfer_approval.get("authoritative_approval_envelope"), dict)
                else None
            ),
            authoritative_approval_transition_history=(
                authoritative_transfer_approval.get("authoritative_approval_transition_history")
                if isinstance(authoritative_transfer_approval.get("authoritative_approval_transition_history"), list)
                else None
            ),
            authoritative_approval_transition_head=(
                str(authoritative_transfer_approval.get("authoritative_approval_transition_head"))
                if authoritative_transfer_approval.get("authoritative_approval_transition_head") is not None
                else None
            ),
        )
        hot_path_result = _apply_execution_plan_bindings_to_hot_path_result(
            hot_path_result,
            execution_plan=execution_plan,
        )
        del debug  # kept for parity with existing hot-path router signature

        response = _build_agent_action_evaluate_response(
            payload=payload,
            hot_path_result=hot_path_result,
            execution_plan=execution_plan,
        )
        response = _apply_forensic_scope_guards(payload=payload, response=response)
        response = await _apply_organism_preflight(payload=payload, response=response)
        response = await _apply_result_verifier_policy_gate(payload=payload, response=response)
        response = _apply_no_execute_preflight(response, requested=requested_no_execute)
        response = _annotate_owner_context_in_response(response, owner_twin_snapshot)
        response = response.model_copy(
            update={"forensic_linkage": _build_forensic_linkage(payload=payload, response=response)}
        )
        await _write_request_record(
            _AgentActionStoredRecord(
                request_id=payload.request_id,
                idempotency_key=payload.idempotency_key,
                request_hash=request_hash,
                recorded_at=datetime.now(timezone.utc),
                response=response,
                request_payload=payload.model_dump(mode="json"),
            )
        )
        return response
    except Exception:
        if claimed:
            await _release_idempotency_claim(
                idempotency_key=payload.idempotency_key,
                request_id=payload.request_id,
                request_hash=request_hash,
            )
        raise


@router.post("/agent-actions/execute", response_model=AgentActionExecuteResponse)
async def execute_agent_action(
    payload_body: Dict[str, Any] = Body(...),
    debug: bool = Query(default=False, description="Include check-by-check diagnostics."),
) -> AgentActionExecuteResponse:
    payload = _parse_validate_payload(payload_body, model=AgentActionEvaluateRequest)
    claimed = False
    execute_request_hash = _canonical_gateway_payload_hash(payload, requested_no_execute=False)
    try:
        owner_twin_snapshot = await _resolve_owner_twin_snapshot_for_payload(payload)
        relevant_twin_snapshot = (
            {"owner": owner_twin_snapshot}
            if isinstance(owner_twin_snapshot, dict)
            else None
        )
        preliminary_request_hash = _canonical_gateway_payload_hash(
            payload,
            requested_no_execute=False,
        )
        preliminary_hot_path_request = _map_to_hot_path_request(
            payload,
            request_hash=preliminary_request_hash,
        )
        authoritative_transfer_approval = await resolve_authoritative_transfer_approval(
            preliminary_hot_path_request
        )
        execution_plan = build_execution_plan(
            payload,
            owner_twin_snapshot=owner_twin_snapshot,
            authoritative_transfer_approval=authoritative_transfer_approval,
        )
        execute_request_hash = _canonical_gateway_execute_payload_hash(
            payload,
            execution_plan=execution_plan,
        )

        claimed, idempotency_entry = await _claim_execute_idempotency_key(
            idempotency_key=payload.idempotency_key,
            request_id=payload.request_id,
            request_hash=execute_request_hash,
        )
        if not claimed and idempotency_entry is not None:
            existing_request_hash = str(idempotency_entry.get("request_hash") or "").strip()
            existing_request_id = str(idempotency_entry.get("request_id") or "").strip()
            if existing_request_hash != execute_request_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_conflict",
                        "message": "idempotency key already used with different execute request body",
                        "request_id": payload.request_id,
                    },
                )
            if existing_request_id:
                existing_record = await _read_execute_record(existing_request_id)
                if existing_record is not None:
                    return existing_record.response
                if existing_request_id != payload.request_id:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error_code": "idempotency_in_progress",
                            "message": "idempotency key already claimed by an in-flight execute request",
                            "request_id": existing_request_id,
                        },
                    )

        hot_path_request = _map_to_hot_path_request(
            payload,
            request_hash=execute_request_hash,
            plan_dag_hash_override=execution_plan.plan_dag_hash,
            prefer_plan_binding=True,
        )
        hot_path_result = evaluate_pdp_hot_path(
            hot_path_request,
            relevant_twin_snapshot=relevant_twin_snapshot,
            authoritative_approval_envelope=(
                authoritative_transfer_approval.get("authoritative_approval_envelope")
                if isinstance(authoritative_transfer_approval.get("authoritative_approval_envelope"), dict)
                else None
            ),
            authoritative_approval_transition_history=(
                authoritative_transfer_approval.get("authoritative_approval_transition_history")
                if isinstance(authoritative_transfer_approval.get("authoritative_approval_transition_history"), list)
                else None
            ),
            authoritative_approval_transition_head=(
                str(authoritative_transfer_approval.get("authoritative_approval_transition_head"))
                if authoritative_transfer_approval.get("authoritative_approval_transition_head") is not None
                else None
            ),
        )
        hot_path_result = _apply_execution_plan_bindings_to_hot_path_result(
            hot_path_result,
            execution_plan=execution_plan,
        )
        del debug

        evaluation = _build_agent_action_evaluate_response(
            payload=payload,
            hot_path_result=hot_path_result,
            execution_plan=execution_plan,
        )
        evaluation = _apply_forensic_scope_guards(payload=payload, response=evaluation)
        evaluation = await _apply_organism_preflight(payload=payload, response=evaluation)
        evaluation = await _apply_result_verifier_policy_gate(payload=payload, response=evaluation)
        evaluation = _annotate_owner_context_in_response(evaluation, owner_twin_snapshot)
        evaluation = evaluation.model_copy(
            update={"forensic_linkage": _build_forensic_linkage(payload=payload, response=evaluation)}
        )

        execution_task: Dict[str, Any] | None = None
        execution_result: Dict[str, Any] | None = None
        disposition = str(evaluation.decision.disposition or "").strip().lower()
        if disposition == "allow" and evaluation.execution_token is not None:
            policy_case = prepare_policy_case(
                hot_path_request.action_intent,
                policy_snapshot=hot_path_request.policy_snapshot_ref,
                relevant_twin_snapshot=relevant_twin_snapshot,
                telemetry_summary=_telemetry_summary_from_payload(payload),
                evidence_summary=_evidence_summary_from_payload(payload),
                authoritative_approval_envelope=(
                    authoritative_transfer_approval.get("authoritative_approval_envelope")
                    if isinstance(authoritative_transfer_approval.get("authoritative_approval_envelope"), dict)
                    else None
                ),
                authoritative_approval_transition_history=(
                    authoritative_transfer_approval.get("authoritative_approval_transition_history")
                    if isinstance(authoritative_transfer_approval.get("authoritative_approval_transition_history"), list)
                    else None
                ),
                authoritative_approval_transition_head=(
                    str(authoritative_transfer_approval.get("authoritative_approval_transition_head"))
                    if authoritative_transfer_approval.get("authoritative_approval_transition_head") is not None
                    else None
                ),
            )
            governance = dict(
                build_governance_context_from_hot_path_response(
                    policy_case,
                    hot_path_result,
                )
            )
            governance["execution_plan"] = execution_plan.model_dump(mode="json")
            execution_task = _build_organism_execute_task(
                payload=payload,
                governance=governance,
                execution_plan=execution_plan,
            )
            if execution_plan.planner_type == PLANNER_TYPE_DELEGATED_AUTHORITY:
                delegated_subtoken = _mint_delegated_subtoken(
                    parent_token=evaluation.execution_token,
                    payload=payload,
                    execution_plan=execution_plan,
                )
                governance["delegated_subtoken"] = delegated_subtoken.model_dump(mode="json")
                execution_task["params"]["governance"] = dict(governance)
                execution_result = _build_delegated_intent_execution_result(
                    payload=payload,
                    execution_plan=execution_plan,
                    subtoken=delegated_subtoken,
                )
            elif execution_plan.planner_type == PLANNER_TYPE_CONDITIONAL_ESCROW:
                execution_result = _build_planned_only_execution_result(
                    execution_plan=execution_plan
                )
            elif executable_directives_from_plan(execution_plan):
                client = OrganismServiceClient(timeout=ORGANISM_EXECUTE_TIMEOUT_SECONDS)
                try:
                    routed_result = await client.route_and_execute(task=execution_task)
                finally:
                    try:
                        await client.close()
                    except Exception:
                        pass
                execution_result = (
                    dict(routed_result)
                    if isinstance(routed_result, Mapping)
                    else {"result": routed_result}
                )
            else:
                execution_result = _build_planned_only_execution_result(
                    execution_plan=execution_plan
                )

        response = AgentActionExecuteResponse(
            request_id=payload.request_id,
            executed_at=datetime.now(timezone.utc),
            evaluation=evaluation,
            execution_plan=execution_plan,
            execution_task=execution_task,
            execution_result=execution_result,
        )
        await _write_execute_record(
            _AgentActionExecuteStoredRecord(
                request_id=payload.request_id,
                idempotency_key=payload.idempotency_key,
                request_hash=execute_request_hash,
                recorded_at=datetime.now(timezone.utc),
                response=response,
            )
        )
        return response
    except Exception:
        if claimed:
            await _release_execute_idempotency_claim(
                idempotency_key=payload.idempotency_key,
                request_id=payload.request_id,
                request_hash=execute_request_hash,
            )
        raise


@router.get(
    "/agent-actions/requests/{request_id}",
    response_model=AgentActionRequestRecordResponse,
)
async def get_agent_action_request_record(request_id: str) -> AgentActionRequestRecordResponse:
    request_key = str(request_id).strip()
    record = await _read_request_record(request_key)
    if record is None:
        raise HTTPException(status_code=404, detail=f"agent action request '{request_key}' not found")
    return _as_request_record_response(record)


@router.post(
    "/agent-actions/{request_id}/closures",
    response_model=AgentActionClosureResponse,
)
async def close_agent_action(
    request_id: str,
    payload_body: Dict[str, Any] = Body(...),
) -> AgentActionClosureResponse:
    payload = _parse_validate_payload(
        payload_body,
        model=AgentActionClosureRequest,
        request_id_hint=str(request_id).strip() or None,
    )
    request_key = str(request_id).strip()
    if request_key != payload.request_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "request_id_mismatch",
                "message": "request_id path parameter must match payload.request_id",
            },
        )

    request_record = await _read_request_record(request_key)
    if request_record is None:
        raise HTTPException(status_code=404, detail=f"agent action request '{request_key}' not found")

    _validate_closure_telemetry_refs_asset_binding(
        closure_payload=payload,
        request_record=request_record,
    )

    linked_disposition = str(request_record.response.decision.disposition or "").strip().lower()
    if linked_disposition != "allow":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "closure_not_allowed",
                "message": "closure is only supported for allow decisions in this contract slice",
                "request_id": request_key,
                "linked_disposition": linked_disposition or "unknown",
            },
        )
    await _enforce_result_verifier_closure_gate(
        request_record=request_record,
        closure_payload=payload,
    )

    closure_hash = _canonical_payload_hash(payload)
    claimed, idempotency_entry = await _claim_closure_idempotency_key(
        idempotency_key=payload.idempotency_key,
        closure_id=payload.closure_id,
        request_hash=closure_hash,
    )
    if not claimed and idempotency_entry is not None:
        existing_request_hash = str(idempotency_entry.get("request_hash") or "").strip()
        existing_closure_id = str(idempotency_entry.get("request_id") or "").strip()
        if existing_request_hash != closure_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "idempotency_conflict",
                    "message": "idempotency key already used with different closure body",
                    "closure_id": payload.closure_id,
                },
            )
        if existing_closure_id:
            existing_closure_record = await _read_closure_record(existing_closure_id)
            if existing_closure_record is not None:
                return existing_closure_record.response
            if existing_closure_id != payload.closure_id:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error_code": "idempotency_in_progress",
                        "message": "closure idempotency key already claimed by an in-flight request",
                        "closure_id": existing_closure_id,
                    },
                )

    try:
        settlement_status, settlement_result = await _apply_closure_settlement_handoff(
            request_record=request_record,
            closure_payload=payload,
        )
        replay_status = "ready" if settlement_status == "applied" else "pending"
        settlement_with_refs = dict(settlement_result)
        if payload.telemetry_refs:
            settlement_with_refs["telemetry_refs"] = [ref.model_dump(mode="json") for ref in payload.telemetry_refs]

        response = AgentActionClosureResponse(
            request_id=payload.request_id,
            closure_id=payload.closure_id,
            accepted_at=datetime.now(timezone.utc),
            linked_disposition=linked_disposition,
            forensic_block_id=payload.forensic_block.forensic_block_id,
            settlement_status=settlement_status,
            replay_status=replay_status,
            telemetry_refs=list(payload.telemetry_refs),
            settlement_result=settlement_with_refs,
            next_actions=(
                ["assemble_replay_record", "publish_verification_surface"]
                if settlement_status == "applied"
                else [
                    "settle_digital_twin",
                    "assemble_replay_record",
                    "publish_verification_surface",
                ]
            ),
        )
        await _write_closure_record(
            _AgentActionClosureStoredRecord(
                closure_id=payload.closure_id,
                request_id=payload.request_id,
                idempotency_key=payload.idempotency_key,
                request_hash=closure_hash,
                recorded_at=datetime.now(timezone.utc),
                response=response,
            )
        )
        return response
    except Exception:
        if claimed:
            await _release_closure_idempotency_claim(
                idempotency_key=payload.idempotency_key,
                closure_id=payload.closure_id,
                request_hash=closure_hash,
            )
        raise


@router.get(
    "/agent-actions/closures/{closure_id}",
    response_model=AgentActionClosureRecordResponse,
)
async def get_agent_action_closure_record(closure_id: str) -> AgentActionClosureRecordResponse:
    closure_key = str(closure_id).strip()
    record = await _read_closure_record(closure_key)
    if record is None:
        raise HTTPException(status_code=404, detail=f"agent action closure '{closure_key}' not found")
    return _as_closure_record_response(record)


def _clear_agent_action_request_store_for_tests() -> None:
    global _REDIS_CLIENT, _REDIS_CLIENT_INITIALIZED, _DIGITAL_TWIN_SERVICE
    with _REQUEST_RECORDS_LOCK:
        _REQUEST_RECORDS_BY_ID.clear()
        _IDEMPOTENCY_ENTRIES_BY_KEY.clear()
        _CLOSURE_RECORDS_BY_ID.clear()
        _CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY.clear()
        _EXECUTE_RECORDS_BY_REQUEST_ID.clear()
        _EXECUTE_IDEMPOTENCY_ENTRIES_BY_KEY.clear()
    _REDIS_CLIENT = None
    _REDIS_CLIENT_INITIALIZED = False
    _DIGITAL_TWIN_SERVICE = None
