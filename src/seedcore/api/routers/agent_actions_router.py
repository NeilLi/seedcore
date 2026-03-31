from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, HTTPException, Query

from ...agents.roles.specialization import SpecializationManager
from ...database import get_async_pg_session_factory, get_async_redis_client
from ...models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from ...models.agent_action_gateway import (
    AgentActionClosureRecordResponse,
    AgentActionClosureRequest,
    AgentActionClosureResponse,
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
from ...services.digital_twin_service import DigitalTwinService
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


_REQUEST_RECORDS_BY_ID: Dict[str, _AgentActionStoredRecord] = {}
_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_CLOSURE_RECORDS_BY_ID: Dict[str, _AgentActionClosureStoredRecord] = {}
_CLOSURE_IDEMPOTENCY_ENTRIES_BY_KEY: Dict[str, _AgentActionIdempotencyEntry] = {}
_REQUEST_RECORDS_LOCK = Lock()
_REDIS_CLIENT: Any = None
_REDIS_CLIENT_LOCK = asyncio.Lock()
_REDIS_CLIENT_INITIALIZED = False
_DIGITAL_TWIN_SERVICE: DigitalTwinService | None = None
_DIGITAL_TWIN_SERVICE_LOCK = Lock()

REQUEST_RECORD_TTL_SECONDS = int(
    os.getenv("SEEDCORE_AGENT_ACTION_REQUEST_RECORD_TTL_SECONDS", "86400")
)
REDIS_REQUEST_RECORD_KEY_PREFIX = "seedcore:agent_actions:req"
REDIS_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:idem"
REDIS_CLOSURE_RECORD_KEY_PREFIX = "seedcore:agent_actions:closure"
REDIS_CLOSURE_IDEMPOTENCY_KEY_PREFIX = "seedcore:agent_actions:closure:idem"
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
SETTLEMENT_HANDOFF_ENABLED = os.getenv(
    "SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF",
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


def _canonical_payload_hash(payload: Any) -> str:
    canonical_payload = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload or {})
    canonical_json = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _request_record_redis_key(request_id: str) -> str:
    return f"{REDIS_REQUEST_RECORD_KEY_PREFIX}:{request_id}"


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


def _closure_record_redis_key(closure_id: str) -> str:
    return f"{REDIS_CLOSURE_RECORD_KEY_PREFIX}:{closure_id}"


def _closure_idempotency_redis_key(idempotency_key: str) -> str:
    return f"{REDIS_CLOSURE_IDEMPOTENCY_KEY_PREFIX}:{idempotency_key}"


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
    transition_receipts = [
        {"transition_receipt_id": str(ref).strip()}
        for ref in closure_payload.transition_receipt_ids
        if str(ref).strip()
    ]
    execution_token_constraints = (
        dict(request_record.response.execution_token.constraints)
        if request_record.response.execution_token is not None
        else {}
    )
    endpoint_node_id = str(execution_token_constraints.get("endpoint_id") or "").strip()
    resolved_node_id = str(closure_payload.node_id or "").strip() or endpoint_node_id
    return {
        "evidence_bundle_id": closure_payload.evidence_bundle_id,
        "node_id": resolved_node_id or None,
        "execution_receipt": {"node_id": resolved_node_id} if resolved_node_id else {},
        "evidence_inputs": {
            "execution_summary": {"node_id": resolved_node_id} if resolved_node_id else {},
            "transition_receipts": transition_receipts,
            "summary": dict(closure_payload.summary or {}),
        },
    }


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
    if int(settlement_result.get("updated", 0)) > 0:
        return "applied", dict(settlement_result)
    return "pending", dict(settlement_result)


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


def _as_closure_record_response(record: _AgentActionClosureStoredRecord) -> AgentActionClosureRecordResponse:
    return AgentActionClosureRecordResponse(
        closure_id=record.closure_id,
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
    payload: AgentActionClosureRequest,
) -> AgentActionClosureResponse:
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
        response = AgentActionClosureResponse(
            request_id=payload.request_id,
            closure_id=payload.closure_id,
            accepted_at=datetime.now(timezone.utc),
            linked_disposition=linked_disposition,
            settlement_status=settlement_status,
            replay_status=replay_status,
            settlement_result=settlement_result,
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
    _REDIS_CLIENT = None
    _REDIS_CLIENT_INITIALIZED = False
    _DIGITAL_TWIN_SERVICE = None
