from __future__ import annotations

import asyncio
import json
import logging
from datetime import timezone
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException, Query  # pyright: ignore[reportMissingImports]
from fastapi.responses import StreamingResponse  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from ...models.pdp_hot_path import HotPathEvaluateRequest, HotPathEvaluateResponse
from ...database import get_async_pg_session_factory, get_async_redis_client
from ...ops.pkg import (
    PKGClient,
    PKGSnapshotCompareService,
    PolicyGateBlockedError,
    get_global_pkg_manager,
    initialize_global_pkg_manager,
    normalize_policy_result,
)
from ...ops.pkg.manager import PKGMode
from ...ops.pkg.manager import PKG_REDIS_CHANNEL
from ...ops.pdp_hot_path import evaluate_pdp_hot_path

logger = logging.getLogger(__name__)

router = APIRouter()


class PKGActivateSnapshotRequest(BaseModel):
    actor: str = Field(default="system", description="Actor id performing activation.")
    reason: Optional[str] = Field(default=None, description="Optional rollout reason.")
    target: str = Field(default="router", description="Primary rollout lane target.")
    region: str = Field(default="global", description="Deployment region.")
    rollout_percent: int = Field(default=100, ge=0, le=100, description="Rollout percent for target lane.")
    publish_update: bool = Field(default=True, description="Publish update to the runtime hot-update channel.")
    edge_targets: List[str] = Field(
        default_factory=list,
        description="Optional additional edge rollout lanes (for example edge:door, edge:robot).",
    )


class PKGOTAHeartbeatRequest(BaseModel):
    device_id: str = Field(..., description="Stable edge device identifier.")
    device_type: str = Field(..., description="Device class (for example door, robot, sensor).")
    region: str = Field(default="global", description="Region lane for rollout selection.")
    snapshot_id: Optional[int] = Field(default=None, description="Current snapshot ID on the device.")
    version: Optional[str] = Field(default=None, description="Current policy version on the device.")


@router.post("/pdp/hot-path/evaluate", response_model=HotPathEvaluateResponse)
async def pdp_hot_path_evaluate(
    payload: HotPathEvaluateRequest,
    debug: bool = Query(default=False, description="Include check-by-check diagnostics."),
) -> HotPathEvaluateResponse:
    """
    Evaluate the asset-centric PDP hot path contract for Restricted Custody Transfer.
    """
    result = evaluate_pdp_hot_path(payload)
    if debug:
        return result
    return result


async def _resolve_pkg_client() -> PKGClient:
    pkg_mgr = get_global_pkg_manager()
    manager_client = getattr(pkg_mgr, "_client", None) if pkg_mgr is not None else None
    if manager_client is not None:
        return manager_client
    return PKGClient(get_async_pg_session_factory())


def _resolve_ota_compliance(
    *,
    current_snapshot_id: Optional[int],
    current_version: Optional[str],
    desired_snapshot_id: Optional[int],
    desired_version: Optional[str],
) -> str:
    if desired_snapshot_id is None and not desired_version:
        return "unknown"
    if current_snapshot_id is not None and desired_snapshot_id is not None:
        return "compliant" if int(current_snapshot_id) == int(desired_snapshot_id) else "outdated"
    if current_version and desired_version:
        return "compliant" if str(current_version).strip() == str(desired_version).strip() else "outdated"
    return "unknown"


def _sse_encode(event: str, payload: Dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, separators=(',', ':'), default=str)}\n\n"
    )


def _parse_pkg_stream_message(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.startswith("activate:"):
        return {"kind": "activate", "version": text.split(":", 1)[1].strip()}
    if text.startswith("authz_graph_refresh:"):
        return {"kind": "authz_graph_refresh", "version": text.split(":", 1)[1].strip()}
    if text == "authz_graph_refresh":
        return {"kind": "authz_graph_refresh"}
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


@router.post("/pkg/reload", response_model=Dict[str, Any])
async def pkg_reload() -> Dict[str, Any]:
    """
    Manually reload the active PKG snapshot from the database.
    
    Useful for debugging or recovering from load failures.
    This will attempt to reload the active snapshot and create a new evaluator.
    """
    pkg_mgr = get_global_pkg_manager()
    
    if not pkg_mgr:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "PKG manager not initialized",
                "message": "PKG manager needs to be initialized before reloading snapshots.",
            },
        )
    
    result = await pkg_mgr.reload_active_snapshot()
    
    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result,
        )
    
    return result


@router.post("/pkg/snapshots/{snapshot_version}/activate", response_model=Dict[str, Any])
async def pkg_activate_snapshot(
    snapshot_version: str,
    payload: PKGActivateSnapshotRequest,
) -> Dict[str, Any]:
    """
    Activate a snapshot and broadcast hot-update events fleet-wide.
    """
    pkg_mgr = get_global_pkg_manager()
    if not pkg_mgr:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "PKG manager not initialized",
                "message": "PKG manager needs to be initialized before activating snapshots.",
            },
        )

    result = await pkg_mgr.activate_snapshot_version(
        version=snapshot_version,
        actor=payload.actor,
        reason=payload.reason,
        target=payload.target,
        region=payload.region,
        rollout_percent=payload.rollout_percent,
        publish_update=payload.publish_update,
        edge_targets=payload.edge_targets,
    )
    if not result.get("success"):
        error = str(result.get("error") or "").strip()
        if error == "snapshot_not_found":
            raise HTTPException(status_code=404, detail=result)
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/pkg/authz-graph/refresh", response_model=Dict[str, Any])
async def pkg_authz_graph_refresh() -> Dict[str, Any]:
    """
    Manually refresh the active compiled authorization graph for the current PKG snapshot.
    """
    pkg_mgr = get_global_pkg_manager()

    if not pkg_mgr:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "PKG manager not initialized",
                "message": "PKG manager needs to be initialized before refreshing the authz graph.",
            },
        )

    result = await pkg_mgr.refresh_active_authz_graph()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result)
    return result


@router.get("/pkg/authz-graph/status", response_model=Dict[str, Any])
async def pkg_authz_graph_status() -> Dict[str, Any]:
    """
    Get active authorization graph runtime status.
    """
    pkg_mgr = get_global_pkg_manager()
    if not pkg_mgr:
        return {
            "available": False,
            "manager_exists": False,
            "authz_graph_ready": False,
            "error": "PKG manager not initialized",
        }

    metadata = pkg_mgr.get_metadata()
    authz_status = metadata.get("authz_graph", {})
    compiled = pkg_mgr.get_active_compiled_authz_index()

    return {
        "available": bool(authz_status.get("healthy")),
        "manager_exists": True,
        "authz_graph_ready": compiled is not None and bool(authz_status.get("healthy")),
        "active_snapshot_id": authz_status.get("active_snapshot_id"),
        "active_snapshot_version": authz_status.get("active_snapshot_version"),
        "snapshot_hash": authz_status.get("snapshot_hash"),
        "compiled_at": authz_status.get("compiled_at"),
        "hot_path_workflow": authz_status.get("hot_path_workflow"),
        "restricted_transfer_ready": bool(authz_status.get("restricted_transfer_ready")),
        "trust_gap_taxonomy": list(authz_status.get("trust_gap_taxonomy") or []),
        "graph_nodes_count": authz_status.get("graph_nodes_count", 0),
        "graph_edges_count": authz_status.get("graph_edges_count", 0),
        "decision_graph_nodes_count": authz_status.get("decision_graph_nodes_count", 0),
        "decision_graph_edges_count": authz_status.get("decision_graph_edges_count", 0),
        "enrichment_graph_nodes_count": authz_status.get("enrichment_graph_nodes_count", 0),
        "enrichment_graph_edges_count": authz_status.get("enrichment_graph_edges_count", 0),
        "error": authz_status.get("error"),
    }


@router.get("/pkg/status", response_model=Dict[str, Any])
async def pkg_status() -> Dict[str, Any]:
    """
    Get PKG manager and evaluator status.
    
    Useful for checking if PKG is ready before making evaluation requests.
    Returns detailed information about the PKG manager state, active evaluator,
    and any issues preventing evaluation.
    """
    pkg_mgr = get_global_pkg_manager()
    
    if not pkg_mgr:
        return {
            "available": False,
            "manager_exists": False,
            "evaluator_ready": False,
            "authz_graph_ready": False,
            "error": "PKG manager not initialized",
            "suggestion": "PKG manager needs to be initialized. Check application startup logs.",
        }
    
    evaluator = pkg_mgr.get_active_evaluator()
    metadata = pkg_mgr.get_metadata()
    
    if not evaluator:
        status_info = metadata.get("status", {})
        last_error = status_info.get("error")
        
        # Check if there was a specific error during loading
        if last_error:
            error_message = (
                f"PKG manager failed to load snapshot: {last_error}. "
                "This could be due to snapshot integrity issues, missing artifacts, or evaluator creation failures."
            )
            suggestion = (
                "To fix this issue:\n"
                "1. Check application logs for detailed error messages\n"
                "2. Verify snapshot integrity: SELECT * FROM pkg_snapshots WHERE is_active = TRUE;\n"
                "3. Check if snapshot has required artifacts: SELECT * FROM pkg_snapshot_artifacts WHERE snapshot_id = <id>;\n"
                "4. Try manually reloading: POST /api/v1/pkg/reload\n"
                "5. If snapshot is native engine, verify rules exist: SELECT COUNT(*) FROM pkg_policy_rules WHERE snapshot_id = <id>;"
            )
        else:
            error_message = (
                "PKG manager is initialized but no active policy snapshot is loaded. "
                "This usually means no snapshots exist in the database or none are marked as active."
            )
            suggestion = (
                "To fix this issue:\n"
                "1. Check if snapshots exist: SELECT * FROM pkg_snapshots;\n"
                "2. Activate a snapshot: UPDATE pkg_snapshots SET is_active = TRUE WHERE id = <snapshot_id>;\n"
                "3. Try manually reloading: POST /api/v1/pkg/reload"
            )
        
        return {
            "available": False,
            "manager_exists": True,
            "evaluator_ready": False,
            "authz_graph_ready": False,
            "mode": metadata.get("mode", "unknown"),
            "status": status_info,
            "active_version": metadata.get("active_version"),
            "cached_versions": metadata.get("cached_versions", []),
            "authz_graph": metadata.get("authz_graph", {}),
            "error": last_error or "No active evaluator available",
            "message": error_message,
            "suggestion": suggestion,
        }
    
    # PKG is ready
    # Check artifact status for diagnostic purposes
    artifact_info = None
    try:
        from ...database import get_async_pg_session_factory
        from sqlalchemy import text
        session_factory = get_async_pg_session_factory()
        async with session_factory() as session:
            artifact_sql = text("""
                SELECT artifact_type, 
                       CASE WHEN artifact_bytes IS NULL THEN 0 ELSE octet_length(artifact_bytes) END as size_bytes,
                       sha256
                FROM pkg_snapshot_artifacts
                WHERE snapshot_id = :snapshot_id
                LIMIT 1
            """)
            result = await session.execute(artifact_sql, {"snapshot_id": evaluator.snapshot_id})
            row = result.first()
            if row:
                artifact_info = {
                    "artifact_type": row[0],
                    "size_bytes": row[1],
                    "sha256": row[2][:16] + "..." if row[2] else None,
                }
    except Exception as e:
        logger.debug(f"Could not fetch artifact info: {e}")
    
    return {
        "available": True,
        "manager_exists": True,
        "evaluator_ready": True,
        "authz_graph_ready": bool(metadata.get("authz_graph", {}).get("healthy")),
        "version": evaluator.version,
        "engine_type": evaluator.engine_type,
        "snapshot_id": evaluator.snapshot_id,
        "mode": metadata.get("mode", "unknown"),
        "status": metadata.get("status", {}),
        "active_version": metadata.get("active_version"),
        "cached_versions": metadata.get("cached_versions", []),
        "cortex_enabled": metadata.get("cortex_enabled", False),
        "authz_graph": metadata.get("authz_graph", {}),
        "artifact_info": artifact_info,  # Diagnostic info about artifact
    }


@router.post("/pkg/ota/heartbeat", response_model=Dict[str, Any])
async def pkg_ota_heartbeat(payload: PKGOTAHeartbeatRequest) -> Dict[str, Any]:
    """
    Edge runtime heartbeat + desired policy resolution for OTA compliance.
    """
    pkg_client = await _resolve_pkg_client()
    desired = await pkg_client.resolve_desired_snapshot_for_device(
        device_type=payload.device_type,
        region=payload.region,
    )

    await pkg_client.update_device_heartbeat(
        device_id=payload.device_id,
        device_type=payload.device_type,
        snapshot_id=payload.snapshot_id,
        version=payload.version,
        region=payload.region,
    )

    desired_snapshot_id = desired.get("snapshot_id") if isinstance(desired, dict) else None
    desired_version = desired.get("snapshot_version") if isinstance(desired, dict) else None
    compliance = _resolve_ota_compliance(
        current_snapshot_id=payload.snapshot_id,
        current_version=payload.version,
        desired_snapshot_id=desired_snapshot_id,
        desired_version=desired_version,
    )

    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True,
        "device_id": payload.device_id,
        "device_type": payload.device_type,
        "region": payload.region,
        "observed_at": now,
        "current": {
            "snapshot_id": payload.snapshot_id,
            "version": payload.version,
        },
        "desired": desired,
        "compliance": compliance,
        "next_action": "hold" if compliance == "compliant" else "upgrade",
        "ota_stream": {
            "channel": PKG_REDIS_CHANNEL,
            "path": (
                f"/api/v1/pkg/ota/stream?"
                f"device_id={payload.device_id}&device_type={payload.device_type}&region={payload.region}"
            ),
        },
    }


@router.get("/pkg/ota/stream")
async def pkg_ota_stream(
    device_id: str = Query(..., description="Edge runtime identifier."),
    device_type: str = Query(..., description="Edge device type."),
    region: str = Query(default="global", description="Deployment region."),
    snapshot_id: Optional[int] = Query(default=None, description="Current edge snapshot ID."),
    version: Optional[str] = Query(default=None, description="Current edge policy version."),
):
    """
    Always-on OTA policy stream for edge runtimes.

    Sends:
    - initial desired policy payload
    - policy update events whenever `pkg_updates` receives snapshot activation messages.
    """
    pkg_client = await _resolve_pkg_client()

    # Record startup heartbeat for immediate compliance visibility.
    await pkg_client.update_device_heartbeat(
        device_id=device_id,
        device_type=device_type,
        snapshot_id=snapshot_id,
        version=version,
        region=region,
    )

    async def _desired_policy_payload() -> Dict[str, Any]:
        desired = await pkg_client.resolve_desired_snapshot_for_device(
            device_type=device_type,
            region=region,
        )
        desired_snapshot_id = desired.get("snapshot_id") if isinstance(desired, dict) else None
        desired_version = desired.get("snapshot_version") if isinstance(desired, dict) else None
        return {
            "device_id": device_id,
            "device_type": device_type,
            "region": region,
            "current": {
                "snapshot_id": snapshot_id,
                "version": version,
            },
            "desired": desired,
            "compliance": _resolve_ota_compliance(
                current_snapshot_id=snapshot_id,
                current_version=version,
                desired_snapshot_id=desired_snapshot_id,
                desired_version=desired_version,
            ),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _event_stream():
        pubsub = None
        redis_client = None
        try:
            initial_payload = await _desired_policy_payload()
            yield _sse_encode("desired_policy", initial_payload)
            yield _sse_encode(
                "stream_ready",
                {
                    "channel": PKG_REDIS_CHANNEL,
                    "device_id": device_id,
                    "device_type": device_type,
                    "region": region,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            try:
                redis_client = await get_async_redis_client()
            except Exception:
                redis_client = None

            if redis_client is None:
                # Poll fallback when Redis is unavailable.
                while True:
                    await asyncio.sleep(10.0)
                    yield _sse_encode(
                        "desired_policy",
                        await _desired_policy_payload(),
                    )
                    yield _sse_encode(
                        "ping",
                        {"observed_at": datetime.now(timezone.utc).isoformat()},
                    )

            pubsub = redis_client.pubsub()
            await pubsub.subscribe(PKG_REDIS_CHANNEL)
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=10.0,
                )
                if msg is None:
                    yield _sse_encode(
                        "ping",
                        {"observed_at": datetime.now(timezone.utc).isoformat()},
                    )
                    continue

                parsed = _parse_pkg_stream_message(msg.get("data"))
                if not parsed:
                    continue
                kind = str(parsed.get("kind") or "").strip()
                if kind in {"activate", "authz_graph_refresh"}:
                    yield _sse_encode(
                        "policy_update",
                        {
                            "event": parsed,
                            "policy": await _desired_policy_payload(),
                        },
                    )
        except asyncio.CancelledError:
            raise
        finally:
            if pubsub is not None:
                try:
                    await pubsub.close()
                except Exception:
                    pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# Common hotel simulator predicates (extensible via Literal + str fallback)
HotelPredicate = Literal[
    "request_diy_print",
    "request_magic_atelier",
    "request_journey_studio",
    "request_hvac_adjustment",
    "request_elevator_control",
    "request_vip_service",
    "request_security_check",
    "request_maintenance",
    "request_room_service",
    "request_concierge",
]


class HotelTaskFacts(BaseModel):
    namespace: str = Field(..., description="Domain namespace (e.g., hospitality)")
    subject: str = Field(..., description="Entity identifier (e.g., guest:neil)")
    predicate: Union[HotelPredicate, str] = Field(
        ...,
        description="Action/intent predicate (e.g., request_diy_print). Common values are typed, but custom predicates are allowed.",
    )
    object_data: Dict[str, Any] = Field(default_factory=dict)


class PKGEvaluateAsyncRequest(BaseModel):
    task_facts: HotelTaskFacts
    signals: Optional[Dict[str, float]] = Field(
        default=None,
        description=(
            "Optional numeric policy signals merged into PKG task_facts.signals "
            "(e.g., identity_verified=1, release_window_open=1, seal_integrity=0.98)."
        ),
    )
    snapshot_id: Optional[int] = Field(
        default=None,
        description="Optional PKG snapshot_id for governed-facts scoping/hydration",
    )
    current_time: Optional[datetime] = Field(
        default=None,
        description="Optional current time (ISO8601). Passed through as context for temporal policies.",
    )
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Optional 1024d embedding for semantic context hydration.",
    )
    mode: PKGMode = Field(
        default=PKGMode.ADVISORY,
        description="CONTROL blocks semantic hydration; ADVISORY enables hydration.",
    )
    zone_id: Optional[str] = Field(
        default=None,
        description="Optional zone identifier (e.g., 'magic_atelier', 'journey_studio') for immediate scoping of the Contextual Brain to a specific studio.",
    )


class PKGSnapshotCompareRequest(BaseModel):
    baseline_snapshot_id: int = Field(..., description="Baseline snapshot ID.")
    candidate_snapshot_id: int = Field(..., description="Candidate snapshot ID.")
    task_facts: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Closed-world task_facts payload. Provide exactly one of task_facts or fixture_id.",
    )
    fixture_id: Optional[int] = Field(
        default=None,
        description="Validation fixture ID. Provide exactly one of task_facts or fixture_id.",
    )
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Optional embedding used for shared semantic hydration.",
    )
    mode: PKGMode = Field(
        default=PKGMode.ADVISORY,
        description="CONTROL blocks semantic hydration; ADVISORY enables it.",
    )


@router.post("/pkg/evaluate_async", response_model=Dict[str, Any])
async def pkg_evaluate_async(payload: PKGEvaluateAsyncRequest) -> Dict[str, Any]:
    """
    Hotel-simulator friendly wrapper around PKGManager/PKGEvaluator async evaluation.

    Input contract is a simple SPO-ish triple (namespace/subject/predicate/object_data)
    plus optional numeric policy signals.
    Internally we translate to the PKGManager closed-world `task_facts` schema:
      { "tags": [...], "signals": {...}, "context": {...} }
    """
    # Ensure PKG manager is available (initialize lazily if API started without it).
    pkg_mgr = get_global_pkg_manager()
    if not pkg_mgr:
        try:
            session_factory = get_async_pg_session_factory()
            pkg_client = PKGClient(session_factory)
            try:
                redis_client = await get_async_redis_client()
            except Exception:
                redis_client = None
            pkg_mgr = await initialize_global_pkg_manager(pkg_client, redis_client, mode=payload.mode)
        except Exception as e:
            logger.exception("PKG manager initialization failed")
            raise HTTPException(status_code=503, detail=f"PKG not available: {e}")
    
    # Check if PKG manager has an active evaluator before attempting evaluation
    evaluator = pkg_mgr.get_active_evaluator()
    if not evaluator:
        # Provide helpful error message with suggestions
        metadata = pkg_mgr.get_metadata()
        raise HTTPException(
            status_code=503,
            detail={
                "error": "PKG evaluator not available",
                "message": (
                    "No active policy snapshot loaded. "
                    "The PKG manager may still be initializing or no snapshots are available in the database. "
                    "Please ensure at least one snapshot exists in `pkg_snapshots` with `is_active = TRUE`."
                ),
                "mode": metadata.get("mode", "unknown"),
                "status": metadata.get("status", {}),
                "suggestion": (
                    "To fix this issue:\n"
                    "1. Check if snapshots exist: SELECT * FROM pkg_snapshots;\n"
                    "2. Activate a snapshot: UPDATE pkg_snapshots SET is_active = TRUE WHERE id = <snapshot_id>;\n"
                    "3. The PKG manager will automatically load the active snapshot on next request."
                ),
            },
        )

    # Translate hotel payload to SeedCore PKG task_facts schema.
    # Enrich tags with zone and semantic keywords for policy-compatible matching.
    tf = payload.task_facts
    enriched_tags = [tf.namespace, tf.predicate, tf.subject]
    
    # Add zone tags if zone_id is provided (enables TAG-based zone matching in policies)
    if payload.zone_id:
        enriched_tags.append("zone")
        enriched_tags.append(payload.zone_id.lower())  # Normalize to lowercase for consistent matching
    
    # Map common predicates to semantic keywords for policy matching
    # This allows policies to match on semantic concepts rather than specific predicate names
    predicate_lower = tf.predicate.lower()
    if "preview" in predicate_lower or "print" in predicate_lower:
        enriched_tags.append("access")  # Accessing studio/print services
    if "request" in predicate_lower:
        enriched_tags.append("request")  # General request pattern
    
    task_facts: Dict[str, Any] = {
        "tags": enriched_tags,
        "signals": dict(payload.signals or {}),
        "context": {
            "namespace": tf.namespace,
            "subject": tf.subject,
            "predicate": tf.predicate,
            "object_data": tf.object_data,
            "snapshot_id": payload.snapshot_id,
            "current_time": payload.current_time.isoformat() if payload.current_time else None,
            "zone_id": payload.zone_id,
        },
    }

    # Evaluate (async hydration pipeline: semantic + governed facts + engine execution).
    result = await pkg_mgr.evaluate_task(task_facts, embedding=payload.embedding, mode=payload.mode)

    # Check for evaluation errors (e.g., no active evaluator, validation failures)
    if not result.get("ok", True):
        error_meta = result.get("meta", {})
        error_msg = error_meta.get("error", "unknown_error")
        
        # Return 503 Service Unavailable for infrastructure issues (no active policy)
        if error_msg == "no_active_policy":
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "PKG evaluator not available",
                    "message": "No active policy snapshot loaded. The PKG manager may still be initializing or no snapshots are available.",
                    "mode": error_meta.get("mode"),
                },
            )
        
        # Return 400 Bad Request for validation errors
        if "validation" in error_msg.lower():
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Task facts validation failed",
                    "message": error_msg,
                    "mode": error_meta.get("mode"),
                },
            )

        # Explicit policy deny in CONTROL mode (deny-by-default).
        if error_msg == "policy_denied":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Request blocked by policy gate",
                    "message": error_meta.get("deny_reason") or "policy_denied",
                    "mode": error_meta.get("mode"),
                },
            )
        
        # Generic error handling for other failures
        raise HTTPException(
            status_code=500,
            detail={
                "error": "PKG evaluation failed",
                "message": error_msg,
                "mode": error_meta.get("mode"),
            },
        )

    try:
        return normalize_policy_result(result, raise_on_gate_block=(payload.mode == PKGMode.CONTROL))
    except PolicyGateBlockedError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Request blocked by policy gate",
                "rule_id": exc.rule_id or exc.rule_name or "unknown_gate",
                "rule_name": exc.rule_name,
                "reason": exc.reason,
            },
        ) from exc


@router.post("/pkg/snapshots/compare", response_model=Dict[str, Any])
async def compare_snapshots(payload: PKGSnapshotCompareRequest) -> Dict[str, Any]:
    """Compare one simulator input across a baseline and candidate snapshot."""
    try:
        session_factory = get_async_pg_session_factory()
        pkg_client = PKGClient(session_factory)
        compare_service = PKGSnapshotCompareService(pkg_client)
        return await compare_service.compare_snapshots(
            baseline_snapshot_id=payload.baseline_snapshot_id,
            candidate_snapshot_id=payload.candidate_snapshot_id,
            task_facts=payload.task_facts,
            fixture_id=payload.fixture_id,
            embedding=payload.embedding,
            mode=payload.mode,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid snapshot compare request",
                "message": str(exc),
            },
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Snapshot compare resource not found",
                "message": str(exc),
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Snapshot comparison failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Snapshot comparison failed",
                "message": str(exc),
            },
        ) from exc


class CompileRulesRequest(BaseModel):
    entrypoint: Optional[str] = Field(
        default="data.pkg.allow",
        description="OPA entrypoint path (default: data.pkg.allow)"
    )
    opa_binary_path: Optional[str] = Field(
        default=None,
        description="Optional path to OPA binary (default: uses 'opa' from PATH)"
    )


@router.post("/pkg/snapshots/{snapshot_id}/compile-rules", response_model=Dict[str, Any])
async def compile_rules(
    snapshot_id: int,
    request: CompileRulesRequest = CompileRulesRequest()
) -> Dict[str, Any]:
    """
    Compile PKG snapshot rules to WASM using OPA build pipeline.
    
    This endpoint:
    1. Fetches all rules, conditions, and emissions for the snapshot
    2. Compiles them to Rego format
    3. Uses OPA build to generate WASM binary
    4. Stores WASM artifact in pkg_snapshot_artifacts
    5. Updates snapshot checksum
    
    Args:
        snapshot_id: Snapshot ID to compile
        request: Compilation options (entrypoint, opa_binary_path)
        
    Returns:
        Dictionary with:
        - success: bool
        - snapshot_id: int
        - wasm_size_bytes: int (if success)
        - sha256: str (if success)
        - error: str (if failure)
    """
    from ...ops.pkg.compiler_service import PKGCompilerService
    from ...ops.pkg.dao import PKGSnapshotsDAO
    from ...database import get_async_pg_session_factory
    
    try:
        # Initialize compiler service (lazy OPA verification)
        session_factory = get_async_pg_session_factory()
        compiler_service = PKGCompilerService(
            session_factory=session_factory,
            opa_binary_path=request.opa_binary_path
        )
        
        # Compile snapshot to WASM
        result = await compiler_service.compile_snapshot_to_wasm(
            snapshot_id=snapshot_id,
            entrypoint=request.entrypoint
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Compilation failed",
                    "message": result.get("error", "Unknown error"),
                    "error_type": result.get("error_type"),
                    "snapshot_id": snapshot_id
                }
            )
        
        # Store WASM artifact in database
        dao = PKGSnapshotsDAO(session_factory)
        await dao.store_wasm_artifact(
            snapshot_id=snapshot_id,
            wasm_bytes=result["wasm_bytes"],
            sha256=result["sha256"],
            created_by="api"
        )
        
        # Update snapshot checksum to match artifact
        await dao.update_snapshot_checksum(
            snapshot_id=snapshot_id,
            checksum=result["sha256"]
        )
        
        logger.info(
            f"Successfully compiled and stored WASM for snapshot {snapshot_id}: "
            f"{result['size_bytes']} bytes, checksum: {result['sha256'][:16]}..."
        )
        
        return {
            "success": True,
            "snapshot_id": snapshot_id,
            "wasm_size_bytes": result["size_bytes"],
            "sha256": result["sha256"],
            "validation": result.get("validation", {}),
            "message": f"Successfully compiled snapshot {snapshot_id} to WASM"
        }
        
    except HTTPException:
        raise
    except RuntimeError as e:
        # OPA-related errors get special handling with helpful messages
        error_msg = str(e)
        if "OPA binary not found" in error_msg or "OPA binary" in error_msg:
            logger.error(f"OPA binary issue for snapshot {snapshot_id}: {e}")
            raise HTTPException(
                status_code=503,  # Service Unavailable
                detail={
                    "error": "OPA compiler not available",
                    "message": error_msg,
                    "error_type": "OPA_NOT_FOUND",
                    "snapshot_id": snapshot_id,
                    "suggestion": (
                        "Please install OPA binary. See installation instructions in the error message above, "
                        "or visit: https://www.openpolicyagent.org/docs/latest/#running-opa"
                    )
                }
            )
        else:
            # Other runtime errors
            logger.error(f"Compilation runtime error for snapshot {snapshot_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Compilation failed",
                    "message": error_msg,
                    "error_type": type(e).__name__,
                    "snapshot_id": snapshot_id
                }
            )
    except Exception as e:
        logger.error(f"Failed to compile snapshot {snapshot_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Compilation failed",
                "message": str(e),
                "error_type": type(e).__name__,
                "snapshot_id": snapshot_id
            }
        )
