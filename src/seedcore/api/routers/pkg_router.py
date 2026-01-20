from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from ...database import get_async_pg_session_factory, get_async_redis_client
from ...ops.pkg import PKGClient, get_global_pkg_manager, initialize_global_pkg_manager
from ...ops.pkg.manager import PKGMode

logger = logging.getLogger(__name__)

router = APIRouter()


class HotelTaskFacts(BaseModel):
    namespace: str = Field(..., description="Domain namespace (e.g., hospitality)")
    subject: str = Field(..., description="Entity identifier (e.g., guest:neil)")
    predicate: str = Field(..., description="Action/intent predicate (e.g., request_diy_print)")
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

    # Translate hotel payload to SeedCore PKG task_facts schema.
    tf = payload.task_facts
    task_facts: Dict[str, Any] = {
        "tags": [tf.namespace, tf.predicate, tf.subject],
        "signals": {},
        "context": {
            "namespace": tf.namespace,
            "subject": tf.subject,
            "predicate": tf.predicate,
            "object_data": tf.object_data,
            "snapshot_id": payload.snapshot_id,
            "current_time": payload.current_time.isoformat() if payload.current_time else None,
        },
    }

    # Evaluate (async hydration pipeline: semantic + governed facts + engine execution).
    result = await pkg_mgr.evaluate_task(task_facts, embedding=payload.embedding)

    # Convert SeedCore result to a stable "policy decision + emissions + provenance" bundle.
    subtasks = result.get("subtasks", []) or []
    rules = result.get("rules") or []
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
            "dag": result.get("dag", []),
        },
        "provenance": provenance,
        "meta": result.get("meta", {}),
    }

