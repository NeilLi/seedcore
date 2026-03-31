from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Query

from ...agents.roles.specialization import SpecializationManager
from ...database import get_async_redis_client
from ...models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from ...models.agent_action_gateway import (
    AgentActionEvaluateRequest,
    AgentActionEvaluateResponse,
    AgentActionRequestRecordResponse,
)
from ...models.pdp_hot_path import (
    HotPathAssetContext,
    HotPathEvaluateRequest,
    HotPathTelemetryContext,
)
from ...ops.pdp_hot_path import (
    HOT_PATH_CONTRACT_VERSION,
    evaluate_pdp_hot_path,
    resolve_authoritative_transfer_approval,
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


@dataclass
class _AgentActionIdempotencyEntry:
    request_id: str
    request_hash: str


_REQUEST_RECORDS_BY_ID: Dict[str, _AgentActionStoredRecord] = {}
_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_REQUEST_RECORDS_LOCK = Lock()
_REDIS_CLIENT: Any = None
_REDIS_CLIENT_LOCK = asyncio.Lock()
_REDIS_CLIENT_INITIALIZED = False

REQUEST_RECORD_TTL_SECONDS = int(
    os.getenv("SEEDCORE_AGENT_ACTION_REQUEST_RECORD_TTL_SECONDS", "86400")
)
REDIS_REQUEST_RECORD_KEY_PREFIX = "seedcore:agent_actions:req"
REDIS_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:idem"
ORGANISM_PREFLIGHT_REQUIRED = os.getenv(
    "SEEDCORE_AGENT_ACTION_REQUIRE_ORGANISM_READY",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}
ORGANISM_PREFLIGHT_TIMEOUT_SECONDS = float(
    os.getenv("SEEDCORE_AGENT_ACTION_ORGANISM_PREFLIGHT_TIMEOUT_S", "3")
)
DISABLE_REDIS_STORE = os.getenv(
    "SEEDCORE_AGENT_ACTION_DISABLE_REDIS_STORE",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}


def _to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _map_to_hot_path_request(payload: AgentActionEvaluateRequest) -> HotPathEvaluateRequest:
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
                "approval_context": {
                    "approval_envelope_id": payload.approval.approval_envelope_id,
                    "expected_envelope_version": payload.approval.expected_envelope_version,
                },
                "gateway": {
                    "idempotency_key": payload.idempotency_key,
                    "delegation_ref": payload.principal.delegation_ref,
                    "organization_ref": payload.principal.organization_ref,
                    "workflow_type": payload.workflow.type,
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
                }
            },
        ),
    )
    policy_snapshot_ref = payload.policy_snapshot_ref or payload.security_contract.version
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
    )


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


def _canonical_payload_hash(payload: AgentActionEvaluateRequest) -> str:
    canonical_payload = payload.model_dump(mode="json")
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _request_record_redis_key(request_id: str) -> str:
    return f"{REDIS_REQUEST_RECORD_KEY_PREFIX}:{request_id}"


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


def _record_to_json_payload(record: _AgentActionStoredRecord) -> Dict[str, Any]:
    return {
        "request_id": record.request_id,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "recorded_at": _to_utc_iso(record.recorded_at),
        "response": record.response.model_dump(mode="json"),
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


@router.post("/agent-actions/evaluate", response_model=AgentActionEvaluateResponse)
async def evaluate_agent_action(
    payload: AgentActionEvaluateRequest,
    debug: bool = Query(default=False, description="Include check-by-check diagnostics."),
) -> AgentActionEvaluateResponse:
    request_hash = _canonical_payload_hash(payload)
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
        hot_path_request = _map_to_hot_path_request(payload)
        # Keep v1 gateway semantics as a contract wrapper around the existing hot-path path.
        authoritative_transfer_approval = await resolve_authoritative_transfer_approval(hot_path_request)
        hot_path_result = evaluate_pdp_hot_path(
            hot_path_request,
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
        del debug  # kept for parity with existing hot-path router signature

        response = AgentActionEvaluateResponse(
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
            execution_token=hot_path_result.execution_token,
            governed_receipt=dict(hot_path_result.governed_receipt),
        )
        response = await _apply_organism_preflight(payload=payload, response=response)
        await _write_request_record(
            _AgentActionStoredRecord(
                request_id=payload.request_id,
                idempotency_key=payload.idempotency_key,
                request_hash=request_hash,
                recorded_at=datetime.now(timezone.utc),
                response=response,
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


def _clear_agent_action_request_store_for_tests() -> None:
    global _REDIS_CLIENT, _REDIS_CLIENT_INITIALIZED
    with _REQUEST_RECORDS_LOCK:
        _REQUEST_RECORDS_BY_ID.clear()
        _IDEMPOTENCY_ENTRIES_BY_KEY.clear()
    _REDIS_CLIENT = None
    _REDIS_CLIENT_INITIALIZED = False
