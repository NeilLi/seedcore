from __future__ import annotations
import uuid
import asyncio
from typing import Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, String

# --- IMPORTS FROM YOUR OTHER MODULES ---
from ...database import get_async_pg_session, get_async_pg_session_factory
from ...models.task import Task, TaskStatus
from ...models.result_schema import (
    TaskResult, ResultKind, create_fast_path_result, create_escalated_result,
    create_cognitive_result, create_error_result, from_legacy_result
)

router = APIRouter()

# --- NEW: Pydantic model for API responses ---
class TaskRead(BaseModel):
    # This model mirrors your SQLAlchemy model for clean serialization
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
    # The 'from_attributes=True' setting tells Pydantic to read data from 
    # ORM object attributes instead of dictionary keys.
    
    @field_validator('result', mode='before')
    @classmethod
    def validate_result(cls, v):
        """Ensure result is always a dictionary or None."""
        if v is None:
            return v
        
        if isinstance(v, dict):
            return v
        
        if isinstance(v, list) and v and isinstance(v[0], dict):
            # If it's a list containing dicts, extract the first one
            return v[0]
        
        # For other types, try to convert to dict or return None
        try:
            if hasattr(v, '__dict__'):
                return v.__dict__
            elif hasattr(v, 'dict'):
                return v.model_dump()
            else:
                # Create structured wrapper instead of raw_result
                return {
                    "type": "other_result",
                    "value": str(v),
                    "original_type": str(type(v))
                }
        except:
            return None

# --- NEW: Response model for list_tasks endpoint ---
class TaskListResponse(BaseModel):
    total: int
    items: List[TaskRead]

def _task_to_task_read(task: Task) -> TaskRead:
    """Helper function to convert Task object to TaskRead with proper datetime formatting."""
    # Ensure result is a dictionary or None
    result = task.result
    if result is not None and not isinstance(result, dict):
        # If result is not a dict, convert it to a dict or set to None
        if isinstance(result, list):
            # If it's a list, try to extract the first item if it's a dict
            if result and isinstance(result[0], dict):
                result = result[0]
            else:
                # If we can't extract a dict, set to None and log the issue
                print(f"Warning: Task {task.id} has non-dict result: {type(result)} - {result}")
                result = None
        else:
            # For other types, try to convert to dict or set to None
            try:
                if hasattr(result, '__dict__'):
                    result = result.__dict__
                else:
                    result = None
            except:
                result = None
    
    return TaskRead(
        id=task.id,
        type=task.type,
        description=task.description,
        params=task.params or {},
        domain=task.domain,
        drift_score=task.drift_score,
        status=task.status,
        result=result,
        error=task.error,
        created_at=task.created_at,  # Let Pydantic handle datetime serialization
        updated_at=task.updated_at   # Let Pydantic handle datetime serialization
    )

def _get_task_queue(request: Request) -> asyncio.Queue:
    if not hasattr(request.app.state, "task_queue"):
        request.app.state.task_queue = asyncio.Queue()
    return request.app.state.task_queue

# REMOVED: _get_organism function - this is no longer needed since we don't hold OrganismManager locally

# --- NEW: Short-ID Resolution Helper ---
async def _resolve_task_id(session: AsyncSession, task_id_or_prefix: str) -> uuid.UUID:
    """Resolve a task ID from either a full UUID or a short prefix."""
    try:
        # Try to parse as full UUID first
        return uuid.UUID(task_id_or_prefix)
    except ValueError:
        # Treat as prefix - find tasks that start with this prefix
        query = select(Task.id).where(
            Task.id.cast(String).like(f"{task_id_or_prefix}%")
        ).limit(2)
        
        result = await session.execute(query)
        rows = result.all()
        
        if len(rows) == 1:
            return rows[0][0]
        elif len(rows) > 1:
            raise HTTPException(
                status_code=409, 
                detail=f"Ambiguous short ID '{task_id_or_prefix}' - multiple tasks match"
            )
        else:
            raise HTTPException(
                status_code=404, 
                detail=f"Task not found with ID prefix '{task_id_or_prefix}'"
            )

async def _task_worker(app_state: Any):
    """Background consumer that submits tasks to the Coordinator actor."""
    task_queue = app_state.task_queue
    async_session_factory = get_async_pg_session_factory()

    while True:
        task_id = await task_queue.get()
        task = None
        
        try:
            async with async_session_factory() as session:
                task_result = await session.execute(select(Task).where(Task.id == task_id))
                task = task_result.scalar_one_or_none()

                if not task or task.status in {TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    continue
                
                # REMOVED: Local OrganismManager check - this is now handled by the Coordinator actor
                # The API should not bootstrap or hold a live OrganismManager
                
                task.status = TaskStatus.RUNNING
                await session.commit()
                # A refresh is not needed here as no new data is being generated by the DB

                payload = {
                    "type": task.type,
                    "params": task.params or {},
                    "description": task.description or "",
                    "domain": task.domain,
                    "drift_score": task.drift_score,
                }
                
                # ✅ FIX: Submit task to OrganismManager Serve deployment instead of raw Ray actor
                try:
                    from ray import serve
                    # Get the Serve deployment handle for OrganismManager
                    coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
                    result = await coord.handle_incoming_task.remote(payload)
                    
                    # Log the result type for debugging
                    print(f"Task {task.id} result type: {type(result)}, value: {result}")
                    
                except Exception as e:
                    # If OrganismManager Serve deployment is not available, mark task as failed
                    result = {"success": False, "error": f"OrganismManager not available: {str(e)}"}
                    print(f"Task {task.id} failed with error: {str(e)}")

                # Use the new unified result schema
                try:
                    if isinstance(result, dict):
                        # Check if this is already a TaskResult
                        if "kind" in result and "payload" in result:
                            task.result = result  # Already in new format
                        else:
                            # Use the centralized conversion function
                            task_result = from_legacy_result(result)
                            task.result = task_result.model_dump()
                    elif hasattr(result, 'kind') and hasattr(result, 'payload'):
                        # This is already a TaskResult object
                        task.result = result.model_dump()
                    elif isinstance(result, list):
                        # Handle list results (common for HGNN decomposition)
                        if result and isinstance(result[0], dict):
                            # Convert list to escalated result using the new schema
                            task_steps = []
                            for step in result:
                                if isinstance(step, dict):
                                    task_steps.append(TaskStep(
                                        organ_id=step.get("organ_id", "unknown"),
                                        success=step.get("success", True),
                                        task=step.get("task"),
                                        result=step.get("result"),
                                        error=step.get("error"),
                                        metadata=step
                                    ))
                                else:
                                    task_steps.append(TaskStep(
                                        organ_id="unknown",
                                        success=False,
                                        error=f"Invalid step format: {step}"
                                    ))
                            
                            escalated_result = create_escalated_result(
                                solution_steps=task_steps,
                                plan_source="list_conversion"
                            )
                            task.result = escalated_result.model_dump()
                        else:
                            # Other list types
                            error_result = create_error_result(
                                error="Unsupported list result format",
                                error_type="unsupported_list",
                                original_type=str(type(result))
                            )
                            task.result = error_result.model_dump()
                    elif hasattr(result, '__dict__'):
                        # Handle objects with __dict__
                        fast_path_result = create_fast_path_result(
                            routed_to="unknown",
                            organ_id="unknown",
                            result=result.__dict__
                        )
                        task.result = fast_path_result.dict()
                    elif hasattr(result, 'dict'):
                        # Handle Pydantic models
                        fast_path_result = create_fast_path_result(
                            routed_to="unknown",
                            organ_id="unknown",
                            result=result.model_dump()
                        )
                        task.result = fast_path_result.model_dump()
                    else:
                        # For other types, create error result
                        error_result = create_error_result(
                            error="Unsupported result type",
                            error_type="unsupported_type",
                            original_type=str(type(result))
                        )
                        task.result = error_result.model_dump()
                        
                except Exception as e:
                    # Fallback to error result if conversion fails
                    error_result = create_error_result(
                        error=f"Failed to convert result: {str(e)}",
                        error_type="conversion_error",
                        original_type=str(type(result))
                    )
                    task.result = error_result.model_dump()
                
                task.status = TaskStatus.COMPLETED if task.result.get("success") else TaskStatus.FAILED
                task.error = None if task.result.get("success") else str(task.result.get("error", "Unknown error"))
                await session.commit()

        except Exception as e:
            if task_id:
                async with async_session_factory() as error_session:
                    task_to_fail = await error_session.get(Task, task_id)
                    if task_to_fail:
                        task_to_fail.status = TaskStatus.FAILED
                        task_to_fail.error = str(e)
                        await error_session.commit()
        finally:
            task_queue.task_done()

@router.post("/tasks", response_model=TaskRead)
async def create_task(
    payload: Dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    task_queue = _get_task_queue(request)

    new_task = Task(
        type=payload.get("type"),
        params=payload.get("params") or {},
        description=payload.get("description") or "",
        domain=payload.get("domain"),
        drift_score=payload.get("drift_score", 0.0),
        # status defaults to TaskStatus.CREATED
    )
    session.add(new_task)
    await session.commit()
    # --- OPTIMIZED: Use refresh to get DB-generated fields like created_at/id ---
    await session.refresh(new_task)

    if payload.get("run_immediately"):
        new_task.status = TaskStatus.QUEUED
        await session.commit()
        await session.refresh(new_task)  # <-- add this refresh after second commit
        await task_queue.put(new_task.id)

    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(new_task)
    except Exception as e:
        print(f"Error converting new task to TaskRead: {e}")
        # Return a basic TaskRead with safe values
        return TaskRead(
            id=new_task.id,
            type=new_task.type or "unknown",
            description=new_task.description,
            params=new_task.params or {},
            domain=new_task.domain,
            drift_score=new_task.drift_score or 0.0,
            status=new_task.status,
            result=None,
            error=None,
            created_at=new_task.created_at,
            updated_at=new_task.updated_at
        )

@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(session: AsyncSession = Depends(get_async_pg_session)) -> TaskListResponse:
    result = await session.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = result.scalars().all()
    
    # Convert tasks to TaskRead objects with proper datetime formatting
    task_reads = []
    for task in tasks:
        try:
            task_read = _task_to_task_read(task)
            task_reads.append(task_read)
        except Exception as e:
            print(f"Error converting task {task.id} to TaskRead: {e}")
            print(f"Task result type: {type(task.result)}, value: {task.result}")
            # Create a fallback TaskRead with safe values
            try:
                task_read = TaskRead(
                    id=task.id,
                    type=task.type or "unknown",
                    description=task.description,
                    params=task.params or {},
                    domain=task.domain,
                    drift_score=task.drift_score or 0.0,
                    status=task.status,
                    result=None,  # Set to None for problematic results
                    error=f"Conversion error: {str(e)}",
                    created_at=task.created_at,
                    updated_at=task.updated_at
                )
                task_reads.append(task_read)
            except Exception as fallback_error:
                print(f"Fallback conversion also failed for task {task.id}: {fallback_error}")
                continue
    
    return TaskListResponse(total=len(tasks), items=task_reads)

@router.get("/tasks/{task_id}", response_model=TaskRead)
async def get_task(task_id: str, session: AsyncSession = Depends(get_async_pg_session)) -> TaskRead:
    # Use short-ID resolution to handle both full UUIDs and prefixes
    resolved_id = await _resolve_task_id(session, task_id)
    task = await session.get(Task, resolved_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(task)
    except Exception as e:
        print(f"Error converting task {task.id} to TaskRead: {e}")
        # Return a basic TaskRead with safe values
        return TaskRead(
            id=task.id,
            type=task.type or "unknown",
            description=task.description,
            params=task.params or {},
            domain=task.domain,
            drift_score=task.drift_score or 0.0,
            status=task.status,
            result=None,
            error=f"Conversion error: {str(e)}",
            created_at=task.created_at,
            updated_at=task.updated_at
        )

@router.post("/tasks/{task_id}/run", response_model=TaskRead)
async def run_task_now(
    task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    task_queue = _get_task_queue(request)
    
    # Use short-ID resolution to handle both full UUIDs and prefixes
    resolved_id = await _resolve_task_id(session, task_id)
    task = await session.get(Task, resolved_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in {TaskStatus.RUNNING, TaskStatus.COMPLETED}:
        # Convert to TaskRead with proper datetime formatting
        try:
            return _task_to_task_read(task)
        except Exception as e:
            print(f"Error converting task {task.id} to TaskRead: {e}")
            # Return a basic TaskRead with safe values
            return TaskRead(
                id=task.id,
                type=task.type or "unknown",
                description=task.description,
                params=task.params or {},
                domain=task.domain,
                drift_score=task.drift_score or 0.0,
                status=task.status,
                result=None,
                error=f"Conversion error: {str(e)}",
                created_at=task.created_at,
                updated_at=task.updated_at
            )

    task.status = TaskStatus.QUEUED
    await session.commit()
    await session.refresh(task)  # <-- add this refresh after commit
    await task_queue.put(task.id)
    
    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(task)
    except Exception as e:
        print(f"Error converting task {task.id} to TaskRead: {e}")
        # Return a basic TaskRead with safe values
        return TaskRead(
            id=task.id,
            type=task.type or "unknown",
            description=task.description,
            params=task.params or {},
            domain=task.domain,
            drift_score=task.drift_score or 0.0,
            status=task.status,
            result=None,
            error=f"Conversion error: {str(e)}",
            created_at=task.created_at,
            updated_at=task.updated_at
        )

@router.post("/tasks/{task_id}/cancel", response_model=TaskRead)
async def cancel_task(
    task_id: str,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    # Use short-ID resolution to handle both full UUIDs and prefixes
    resolved_id = await _resolve_task_id(session, task_id)
    task = await session.get(Task, resolved_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        # Convert to TaskRead with proper datetime formatting
        try:
            return _task_to_task_read(task)
        except Exception as e:
            print(f"Error converting task {task.id} to TaskRead: {e}")
            # Return a basic TaskRead with safe values
            return TaskRead(
                id=task.id,
                type=task.type or "unknown",
                description=task.description,
                params=task.params or {},
                domain=task.domain,
                drift_score=task.drift_score or 0.0,
                status=task.status,
                result=None,
                error=f"Conversion error: {str(e)}",
                created_at=task.created_at,
                updated_at=task.updated_at
            )
    
    task.status = TaskStatus.CANCELLED
    await session.commit()
    await session.refresh(task)  # <-- add this refresh after commit
    
    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(task)
    except Exception as e:
        print(f"Error converting task {task.id} to TaskRead: {e}")
        # Return a basic TaskRead with safe values
        return TaskRead(
            id=task.id,
            type=task.type or "unknown",
            description=task.description,
            params=task.params or {},
            domain=task.domain,
            drift_score=task.drift_score or 0.0,
            status=task.status,
            result=None,
            error=f"Conversion error: {str(e)}",
            created_at=task.created_at,
            updated_at=task.updated_at
        )

@router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def task_status(
    task_id: str,
    session: AsyncSession = Depends(get_async_pg_session)
) -> Dict[str, Any]:
    # Use short-ID resolution to handle both full UUIDs and prefixes
    resolved_id = await _resolve_task_id(session, task_id)
    task = await session.get(Task, resolved_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # This convenience endpoint can still return a manual dict for simplicity
    return {
        "id": str(task.id), 
        "status": task.status.value, 
        "updated_at": task.updated_at.isoformat() if task.updated_at else None, 
        "error": task.error
    }

# --- NEW: OrganismManager Serve Deployment Health Check Endpoint ---
@router.get("/coordinator/health")
async def coordinator_health():
    """Check the health of the OrganismManager Serve deployment."""
    try:
        from ray import serve
        # Get the Serve deployment handle for OrganismManager
        coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
        
        # Use the health endpoint of the Serve deployment
        health_result = await coord.health.remote()
        
        if health_result.get("status") == "healthy":
            return {
                "status": "healthy",
                "coordinator": "available",
                "message": "OrganismManager Serve deployment is healthy",
                "organism_initialized": health_result.get("organism_initialized", False)
            }
        else:
            return {
                "status": "degraded",
                "coordinator": "unresponsive",
                "message": f"OrganismManager health check failed: {health_result}"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "coordinator": "unavailable",
            "message": f"OrganismManager Serve deployment not available: {str(e)}"
        }