from __future__ import annotations
import uuid
import logging
import json
import asyncio
from time import perf_counter
from typing import Dict, Any, List, AsyncGenerator
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Depends  # pyright: ignore[reportMissingImports]
from fastapi.responses import StreamingResponse  # pyright: ignore[reportMissingImports]
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
    snapshot_id: int | None
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
    
    Automatically sets snapshot_id from the active PKG snapshot if available.
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

    # 3. Get active snapshot_id (if PKG is available)
    snapshot_id = payload.get("snapshot_id")  # Allow explicit override
    if snapshot_id is None:
        try:
            # Use SQL function for efficient lookup (migration 015)
            result = await session.execute(text("SELECT pkg_active_snapshot_id('prod')"))
            snapshot_id = result.scalar_one_or_none()
            if snapshot_id is None:
                logger.debug("No active PKG snapshot found. Task will be created without snapshot_id.")
        except Exception as e:
            logger.warning(f"Could not get active snapshot_id: {e}. Task will be created without snapshot_id.")
            snapshot_id = None

    # 4. Persist to DB
    new_task = Task(
        type=task_type,
        description=description,
        domain=domain,
        params=params,
        drift_score=0.0, # Calculated later by Coordinator
        status=TaskStatus.QUEUED if run_immediately else TaskStatus.CREATED,
        snapshot_id=snapshot_id
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
    offset: int = 0,
    snapshot_id: int | None = None
) -> TaskListResponse:
    """
    List tasks with optional snapshot_id filtering.
    
    If snapshot_id is provided, only tasks belonging to that snapshot are returned.
    This enables snapshot-aware queries for reproducible runs and multi-world isolation.
    """
    # Build query with optional snapshot filtering
    stmt = select(Task)
    
    if snapshot_id is not None:
        stmt = stmt.where(Task.snapshot_id == snapshot_id)
    
    stmt = stmt.order_by(Task.created_at.desc()).limit(limit).offset(offset)
    
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


async def _stream_task_logs(
    task_id: uuid.UUID,
    session_factory,
    poll_interval: float = 1.0,
    max_duration: float = 300.0  # 5 minutes max
) -> AsyncGenerator[str, None]:
    """
    Stream task logs from result.meta as Server-Sent Events.
    
    Polls the task's result.meta field for updates and streams them as JSON events.
    Continues polling while the task is in a running state (CREATED, QUEUED, RUNNING).
    """
    start_time = perf_counter()
    last_meta_hash = None
    
    try:
        # Send initial connection message
        yield f"data: {json.dumps({'type': 'connected', 'task_id': str(task_id), 'message': 'Streaming logs...'})}\n\n"
        
        while (perf_counter() - start_time) < max_duration:
            async with session_factory()() as session:
                task = await session.get(Task, task_id)
                
                if not task:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
                    break
                
                # Extract logs from result.meta
                result_meta = {}
                if task.result and isinstance(task.result, dict):
                    result_meta = task.result.get("meta", {})
                
                # Create a hash of the current meta to detect changes
                current_meta_str = json.dumps(result_meta, sort_keys=True)
                current_meta_hash = hash(current_meta_str)
                
                # Only send if meta has changed
                if current_meta_hash != last_meta_hash:
                    # Format logs for streaming
                    log_entry = {
                        "type": "log",
                        "task_id": str(task_id),
                        "status": task.status.value,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "meta": result_meta
                    }
                    
                    # Extract specific log sections for better readability
                    if result_meta:
                        # Routing decision logs
                        if "routing_decision" in result_meta:
                            routing = result_meta["routing_decision"]
                            log_entry["routing"] = {
                                "selected_agent_id": routing.get("selected_agent_id"),
                                "selected_organ_id": routing.get("selected_organ_id"),
                                "router_score": routing.get("router_score"),
                                "routed_at": routing.get("routed_at")
                            }
                        
                        # Execution telemetry
                        if "exec" in result_meta:
                            exec_meta = result_meta["exec"]
                            log_entry["execution"] = {
                                "started_at": exec_meta.get("started_at"),
                                "finished_at": exec_meta.get("finished_at"),
                                "latency_ms": exec_meta.get("latency_ms"),
                                "attempt": exec_meta.get("attempt")
                            }
                        
                        # Cognitive trace
                        if "cognitive_trace" in result_meta:
                            cog_trace = result_meta["cognitive_trace"]
                            log_entry["cognitive"] = {
                                "chosen_model": cog_trace.get("chosen_model"),
                                "decision_path": cog_trace.get("decision_path"),
                                "planner_timings_ms": cog_trace.get("planner_timings_ms")
                            }
                        
                        # Solution steps (if available)
                        if "solution_steps" in result_meta:
                            log_entry["solution_steps"] = result_meta["solution_steps"]
                        
                        # Escalation reasons (if available)
                        if "escalation_reasons" in result_meta:
                            log_entry["escalation_reasons"] = result_meta["escalation_reasons"]
                    
                    yield f"data: {json.dumps(log_entry)}\n\n"
                    last_meta_hash = current_meta_hash
                
                # Check if task is in a terminal state
                if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                    # Send final status update
                    yield f"data: {json.dumps({'type': 'status', 'status': task.status.value, 'message': f'Task {task.status.value}'})}\n\n"
                    
                    # If there's an error, include it
                    if task.error:
                        yield f"data: {json.dumps({'type': 'error', 'message': task.error})}\n\n"
                    
                    break
            
            # Wait before next poll
            await asyncio.sleep(poll_interval)
        
        # Send completion message
        yield f"data: {json.dumps({'type': 'complete', 'message': 'Stream ended'})}\n\n"
        
    except Exception as e:
        logger.exception(f"Error streaming logs for task {task_id}: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': f'Stream error: {str(e)}'})}\n\n"


@router.get("/tasks/{task_id}/logs")
async def stream_task_logs(
    task_id: str,
    poll_interval: float = 1.0
):
    """
    Stream task logs via Server-Sent Events (SSE).
    
    This endpoint streams the "Thought Trace" from tasks.result.meta, providing
    real-time visibility into:
    - Routing decisions (selected agent/organ, scores)
    - Execution telemetry (latency, timestamps, attempts)
    - Cognitive traces (model choices, decision paths, planner timings)
    - Solution steps and escalation reasons
    
    The stream continues while the task is running and automatically closes
    when the task reaches a terminal state (completed, failed, cancelled).
    
    **Usage:**
    ```javascript
    const eventSource = new EventSource('/api/v1/tasks/{id}/logs');
    eventSource.onmessage = (event) => {
        const log = JSON.parse(event.data);
        console.log(log);
    };
    ```
    
    **Query Parameters:**
    - `poll_interval`: Seconds between polls (default: 1.0)
    """
    # Resolve task ID and verify task exists
    from ...database import get_async_pg_session_factory
    session_factory = get_async_pg_session_factory()
    
    async with session_factory()() as session:
        uid = await _resolve_task_id(session, task_id)
        task = await session.get(Task, uid)
        
        if not task:
            raise HTTPException(404, "Task not found")
    
    # Stream logs using a separate session factory for polling
    return StreamingResponse(
        _stream_task_logs(uid, session_factory, poll_interval),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )