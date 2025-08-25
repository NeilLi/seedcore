from __future__ import annotations
import time, uuid, asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# --- ADDED: Import DB session and the new Task model ---
from ...database import get_async_pg_session, get_async_pg_session_factory
from ...models.task import Task, TaskStatus

router = APIRouter()

# --- REFACTORED: State management is now just for the queue ---
def _get_task_queue(request: Request) -> asyncio.Queue:
    if not hasattr(request.app.state, "task_queue"):
        request.app.state.task_queue = asyncio.Queue()
    return request.app.state.task_queue

def _get_organism(request: Request):
    # This helper remains the same
    org = getattr(request.app.state, "organism", None)
    if org is None or not getattr(org, "is_initialized", lambda: False)():
        return None
    return org

async def _task_worker(app_state: Any):
    """Background consumer that submits tasks to the OrganismManager."""
    task_queue = app_state.task_queue
    
    # --- ADDED: Get the session factory for the worker ---
    async_session_factory = get_async_pg_session_factory()

    while True:
        task_id = await task_queue.get()
        task = None
        
        try:
            # --- ADDED: Create a dedicated session for this task ---
            async with async_session_factory() as session:
                task_result = await session.execute(select(Task).where(Task.id == task_id))
                task = task_result.scalar_one_or_none()

                if not task or task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    continue
                
                # If organism not ready, requeue with a delay
                org = getattr(app_state, "organism", None)
                if org is None or not org.is_initialized():
                    await asyncio.sleep(1.0)
                    await task_queue.put(task_id)
                    continue

                task.status = TaskStatus.RUNNING
                await session.commit()
                await session.refresh(task)

                # Build the payload for OrganismManager
                payload = {
                    "type": task.type,
                    "params": task.params or {},
                    "description": task.description or "",
                    "domain": task.domain,
                    "drift_score": task.drift_score,
                }

                # Execute the task
                result = await org.route_and_execute(payload) # Use the correct COA method

                # Update the task with the result
                task.result = result
                task.status = TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
                task.error = None if result.get("success") else str(result.get("error", "Unknown error"))
                await session.commit()

        except Exception as e:
            # Defensive error handling
            if task_id:
                async with async_session_factory() as error_session:
                    task_result = await error_session.execute(select(Task).where(Task.id == task_id))
                    task_to_fail = task_result.scalar_one_or_none()
                    if task_to_fail:
                        task_to_fail.status = TaskStatus.FAILED
                        task_to_fail.error = str(e)
                        await error_session.commit()
        finally:
            task_queue.task_done()

# --- REFACTORED: Use lifespan event in main app to start the worker ---
# The old _ensure_worker logic is now handled globally.

@router.post("/tasks", response_model=Dict[str, Any])
async def create_task(
    payload: Dict[str, Any], 
    session: AsyncSession = Depends(get_async_pg_session),
    request: Request = None,
) -> Dict[str, Any]:
    task_queue = _get_task_queue(request)

    new_task = Task(
        type=payload.get("type"),
        params=payload.get("params") or {},
        description=payload.get("description") or "",
        domain=payload.get("domain"),
        drift_score=payload.get("drift_score", 0.0),
        status=TaskStatus.CREATED
    )
    session.add(new_task)
    await session.commit()
    await session.refresh(new_task)

    if payload.get("run_immediately"):
        new_task.status = TaskStatus.QUEUED
        await session.commit()
        await task_queue.put(new_task.id)

    return new_task.to_dict()

@router.get("/tasks", response_model=Dict[str, Any])
async def list_tasks(session: AsyncSession = Depends(get_async_pg_session)) -> Dict[str, Any]:
    result = await session.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = result.scalars().all()
    return {"total": len(tasks), "items": [task.to_dict() for task in tasks]}

@router.get("/tasks/{task_id}", response_model=Dict[str, Any])
async def get_task(task_id: uuid.UUID, session: AsyncSession = Depends(get_async_pg_session)) -> Dict[str, Any]:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()

@router.post("/tasks/{task_id}/run", response_model=Dict[str, Any])
async def run_task_now(
    task_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session)
) -> Dict[str, Any]:
    task_queue = _get_task_queue(request)
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status in {TaskStatus.RUNNING, TaskStatus.COMPLETED}:
        return task.to_dict()

    task.status = TaskStatus.QUEUED
    await session.commit()
    await task_queue.put(task.id)
    
    return task.to_dict()

@router.post("/tasks/{task_id}/cancel", response_model=Dict[str, Any])
async def cancel_task(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session)
) -> Dict[str, Any]:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
        return task.to_dict()
    
    task.status = TaskStatus.CANCELLED
    await session.commit()
    
    return task.to_dict()

@router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def task_status(
    task_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_pg_session)
) -> Dict[str, Any]:
    """Get just the status of a task (convenience endpoint)."""
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return {
        "id": str(task.id), 
        "status": task.status.value, 
        "updated_at": task.updated_at.isoformat() if task.updated_at else None, 
        "error": task.error
    }
