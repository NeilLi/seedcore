from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from ...database import get_async_pg_session_factory, get_async_redis_client
from ...ops.pkg import PKGClient, get_global_pkg_manager, initialize_global_pkg_manager
from ...ops.pkg.manager import PKGMode

logger = logging.getLogger(__name__)

router = APIRouter()


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
            "mode": metadata.get("mode", "unknown"),
            "status": status_info,
            "active_version": metadata.get("active_version"),
            "cached_versions": metadata.get("cached_versions", []),
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
        "version": evaluator.version,
        "engine_type": evaluator.engine_type,
        "snapshot_id": evaluator.snapshot_id,
        "mode": metadata.get("mode", "unknown"),
        "status": metadata.get("status", {}),
        "active_version": metadata.get("active_version"),
        "cached_versions": metadata.get("cached_versions", []),
        "cortex_enabled": metadata.get("cortex_enabled", False),
        "artifact_info": artifact_info,  # Diagnostic info about artifact
    }

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


@router.post("/pkg/evaluate_async", response_model=Dict[str, Any])
async def pkg_evaluate_async(payload: PKGEvaluateAsyncRequest) -> Dict[str, Any]:
    """
    Hotel-simulator friendly wrapper around PKGManager/PKGEvaluator async evaluation.

    Input contract is a simple SPO-ish triple (namespace/subject/predicate/object_data).
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
        "signals": {},
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
    result = await pkg_mgr.evaluate_task(task_facts, embedding=payload.embedding)

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
        
        # Generic error handling for other failures
        raise HTTPException(
            status_code=500,
            detail={
                "error": "PKG evaluation failed",
                "message": error_msg,
                "mode": error_meta.get("mode"),
            },
        )

    # Convert SeedCore result to a stable "policy decision + emissions + provenance" bundle.
    subtasks = result.get("subtasks", []) or []
    rules = result.get("rules") or []
    dag = result.get("dag", []) or []
    
    # Check for GATE emissions that block the request (Enhanced Rejection Logic)
    # GATE emissions indicate conditional blocking - if present and no subtasks emitted, return 403
    # Check both DAG edges and rule emissions for GATE relationships
    gate_emissions_in_dag = [edge for edge in dag if isinstance(edge, dict) and edge.get("type") == "gate"]
    
    # Also check rules for GATE emissions (in case gate blocked before DAG construction)
    gate_rules = []
    for rule in rules:
        emissions = rule.get("emissions", [])
        if emissions:
            for emission in emissions:
                if isinstance(emission, dict) and emission.get("relationship_type") == "GATE":
                    gate_rules.append(rule)
                    break
    
    # If GATE emissions present and no subtasks emitted, request was blocked
    has_gate_emissions = len(gate_emissions_in_dag) > 0 or len(gate_rules) > 0
    if has_gate_emissions and len(subtasks) == 0:
        # Find the rule that triggered the GATE
        gate_rule_id = None
        gate_rule_name = None
        
        # Prefer rule from gate_rules list, fallback to DAG edge rule name
        if gate_rules:
            gate_rule = gate_rules[0]
            gate_rule_id = gate_rule.get("rule_id") or gate_rule.get("rule_name")
            gate_rule_name = gate_rule.get("rule_name")
        elif gate_emissions_in_dag:
            gate_rule_name = gate_emissions_in_dag[0].get("rule")
            # Try to find the rule ID from the rules list
            for rule in rules:
                if rule.get("rule_name") == gate_rule_name:
                    gate_rule_id = rule.get("rule_id") or rule.get("rule_name")
                    break
        
        # Return 403 Forbidden with specific rule ID for improved UX in Simulator Sandbox
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Request blocked by policy gate",
                "rule_id": gate_rule_id or gate_rule_name or "unknown_gate",
                "rule_name": gate_rule_name,
                "reason": f"Policy gate blocked request: {gate_rule_name or 'unknown'}",
            },
        )
    
    reason: str
    if rules:
        reason = rules[0].get("rule_name") or rules[0].get("rule_id") or "matched_rule"
    else:
        reason = "blocked_by_default" if len(subtasks) == 0 else "no_policy_emissions"

    provenance: Dict[str, Any] = {
        "rules": rules,
        "snapshot": result.get("snapshot"),
    }
    # Provide audit visibility into hydrated temporal facts / memory bundles if present.
    # (These are added during the async hydration steps.)
    hydrated = result.get("_hydrated") if isinstance(result.get("_hydrated"), dict) else {}
    if hydrated.get("governed_facts") is not None:
        provenance["governed_facts"] = hydrated.get("governed_facts")
    if hydrated.get("semantic_context") is not None:
        provenance["semantic_context"] = hydrated.get("semantic_context")

    return {
        "decision": {
            # For hotel-simulator semantics we define Allowed as "emits at least one subtask".
            "allowed": len(subtasks) > 0,
            "reason": reason,
        },
        "emissions": {
            "subtasks": subtasks,
            "dag": dag,
        },
        "provenance": provenance,
        "meta": result.get("meta", {}),
    }


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

