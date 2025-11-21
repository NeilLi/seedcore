from __future__ import annotations
import uuid
import logging
from time import perf_counter
from typing import Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Depends  # pyright: ignore[reportMissingImports]
import os
from pydantic import BaseModel, ConfigDict, field_validator  # pyright: ignore[reportMissingImports]
from prometheus_client import Counter, Histogram  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]
from sqlalchemy import select, String, text  # pyright: ignore[reportMissingImports]

from ...database import get_async_pg_session
from ...models import DatabaseTask as Task, TaskStatus

# --- Configuration ---
RUN_NOW_ENSURE_NODE = os.getenv("RUN_NOW_ENSURE_NODE", "true").lower() in ("1","true","yes")

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Observability ---
GNM_ENSURE_TASK_NODE_SUCCESS = Counter("gnm_ensure_task_node_success_total", "Success count", ["call_site"])
GNM_ENSURE_TASK_NODE_FAILURE = Counter("gnm_ensure_task_node_failure_total", "Failure count", ["call_site"])
GNM_ENSURE_TASK_NODE_LATENCY = Histogram("gnm_ensure_task_node_latency_seconds", "Latency seconds", ["call_site"])

# --- Response Models ---
class TaskRead(BaseModel):
    id: uuid.UUID
    type: str
    description: str | None
    params: Dict[str, Any]
    domain: str | None
    drift_score: float
    status: TaskStatus
    result: Dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
    
    @field_validator('result', mode='before')
    @classmethod
    def validate_result(cls, v):
        if v is None: return None  # noqa: E701
        if isinstance(v, dict): return v  # noqa: E701
        if isinstance(v, list) and v and isinstance(v[0], dict): return v[0]  # noqa: E701
        try:
            return v.model_dump() if hasattr(v, 'model_dump') else {"value": str(v)}
        except:  # noqa: E722
            return None

class TaskListResponse(BaseModel):
    total: int
    items: List[TaskRead]

# --- Helpers ---
async def _ensure_task_node_mapping(session: AsyncSession, task_id: uuid.UUID, call_site: str) -> int:
    """Invoke ensure_task_node SQL function to create graph node mapping."""
    started = perf_counter()
    try:
        result = await session.execute(
            text("SELECT ensure_task_node(CAST(:task_id AS uuid)) AS node_id"),
            {"task_id": task_id},
        )
        node_id = result.scalar_one()
        if node_id is None: raise RuntimeError("Returned NULL")  # noqa: E701
        
        GNM_ENSURE_TASK_NODE_SUCCESS.labels(call_site).inc()
        return node_id
    except Exception as exc:
        GNM_ENSURE_TASK_NODE_FAILURE.labels(call_site).inc()
        logger.exception(f"ensure_task_node failed: {exc}")
        raise
    finally:
        GNM_ENSURE_TASK_NODE_LATENCY.labels(call_site).observe(perf_counter() - started)

async def _resolve_task_id(session: AsyncSession, task_id_or_prefix: str) -> uuid.UUID:
    """Resolve full UUID from partial string."""
    try:
        return uuid.UUID(task_id_or_prefix)
    except ValueError:
        # Prefix Search
        query = select(Task.id).where(Task.id.cast(String).like(f"{task_id_or_prefix}%")).limit(2)
        rows = (await session.execute(query)).all()
        if len(rows) == 1: return rows[0][0]  # noqa: E701
        if len(rows) > 1: raise HTTPException(409, "Ambiguous task ID prefix")  # noqa: E701
        raise HTTPException(404, "Task ID not found")

def _task_to_task_read(task: Task) -> TaskRead:
    """Safe conversion from ORM to Pydantic."""
    return TaskRead.model_validate(task)

# --- Endpoints ---

@router.post("/tasks", response_model=TaskRead)
async def create_task(
    payload: Dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    """
    Create a new task.
    
    This endpoint is now a 'Thin Pipe'. It persists the task to Postgres
    with status=CREATED/QUEUED. 
    
    The 'QueueDispatcher' (background service) or 'Coordinator' will pick it up.
    We DO NOT run Eventizer here anymore. The Coordinator handles ingestion analysis.
    """
    # 1. Extract minimal fields
    task_type = payload.get("type", "unknown_task")
    description = payload.get("description", "")
    domain = payload.get("domain") # Optional, Coordinator will infer if missing
    params = payload.get("params", {})
    
    # 2. Handle 'run_immediately' flag
    # If true, we set status=QUEUED so the dispatcher picks it up ASAP.
    # If false, status defaults to CREATED (draft).
    run_immediately = bool(payload.get("run_immediately", True)) 

    # 3. Persist to DB
    new_task = Task(
        type=task_type,
        description=description,
        domain=domain,
        params=params,
        drift_score=0.0, # Calculated later by Coordinator
        status=TaskStatus.QUEUED if run_immediately else TaskStatus.CREATED
    )
    
    session.add(new_task)
    await session.flush()

    # 4. Ensure Graph Node (Critical for downstream HGNN)
    try:
        await _ensure_task_node_mapping(session, new_task.id, "api.create_task")
    except Exception as e:
        await session.rollback()
        logger.error(f"Graph node creation failed: {e}")
        raise HTTPException(500, "Failed to initialize task graph node")

    await session.commit()
    await session.refresh(new_task)

    logger.info(f"Task {new_task.id} created (status={new_task.status})")
    return _task_to_task_read(new_task)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    session: AsyncSession = Depends(get_async_pg_session),
    limit: int = 50,
    offset: int = 0
) -> TaskListResponse:
    # Added pagination for safety
    stmt = select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    tasks = result.scalars().all()
    
    items = [_task_to_task_read(t) for t in tasks]
    return TaskListResponse(total=len(items), items=items)


@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(
    task_id: str, 
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    uid = await _resolve_task_id(session, task_id)
    task = await session.get(Task, uid)
    if not task: raise HTTPException(404, "Task not found")  # noqa: E701
    return _task_to_task_read(task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: str,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    uid = await _resolve_task_id(session, task_id)
    task = await session.get(Task, uid)
    if not task: raise HTTPException(404, "Task not found")  # noqa: E701
    
    if task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
        task.status = TaskStatus.CANCELLED
        await session.commit()
        await session.refresh(task)
        
    return _task_to_task_read(task)