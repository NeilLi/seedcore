from __future__ import annotations
import uuid
import asyncio
import logging
from time import perf_counter
from typing import Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, Depends
import os
from pydantic import BaseModel, ConfigDict, field_validator
from prometheus_client import Counter, Histogram
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, String, text

# --- IMPORTS FROM YOUR OTHER MODULES ---
from ...database import get_async_pg_session, get_async_pg_session_factory
from ...models.task import Task, TaskStatus
from ...models.result_schema import (
    TaskResult, ResultKind, TaskStep, create_fast_path_result, create_escalated_result,
    create_cognitive_result, create_error_result, from_legacy_result
)
from ...serve.eventizer_client import EventizerServiceClient
from ...serve.coordinator_client import CoordinatorServiceClient
from ...ops.eventizer.fast_eventizer import process_text_fast
from ...graph.task_embedding_worker import enqueue_task_embedding_job

router = APIRouter()

# Kill switch: coordinator should be the single enqueuer for LTM embeddings.
# Default false to avoid duplicate enqueue from the router.
ENQUEUE_LTM_FROM_ROUTER = os.getenv("ENQUEUE_LTM_FROM_ROUTER", "false").lower() in ("1","true","yes")
RUN_NOW_ENSURE_NODE = os.getenv("RUN_NOW_ENSURE_NODE", "false").lower() in ("1","true","yes")

# Global service client instances (singletons)
_eventizer_client: EventizerServiceClient | None = None
_coordinator_client: CoordinatorServiceClient | None = None
logger = logging.getLogger(__name__)

GNM_ENSURE_TASK_NODE_SUCCESS = Counter(
    "gnm_ensure_task_node_success_total",
    "Number of successful ensure_task_node invocations.",
    ["call_site"],
)
GNM_ENSURE_TASK_NODE_FAILURE = Counter(
    "gnm_ensure_task_node_failure_total",
    "Number of failed ensure_task_node invocations.",
    ["call_site"],
)
GNM_ENSURE_TASK_NODE_LATENCY = Histogram(
    "gnm_ensure_task_node_latency_seconds",
    "Latency of ensure_task_node invocations in seconds.",
    ["call_site"],
)


async def _ensure_task_node_mapping(
    session: AsyncSession, task_id: uuid.UUID, call_site: str
) -> int:
    """Invoke ensure_task_node with observability and error handling."""

    node_id: int | None = None
    started = perf_counter()
    try:
        result = await session.execute(
            text("SELECT ensure_task_node(CAST(:task_id AS uuid)) AS node_id"),
            {"task_id": task_id},
        )
        node_id = result.scalar_one()
    except Exception as exc:
        GNM_ENSURE_TASK_NODE_FAILURE.labels(call_site).inc()
        logger.exception(
            "ensure_task_node failed for task %s at %s: %s",
            task_id,
            call_site,
            exc,
        )
        raise
    finally:
        duration = perf_counter() - started
        GNM_ENSURE_TASK_NODE_LATENCY.labels(call_site).observe(duration)

    if node_id is None:
        GNM_ENSURE_TASK_NODE_FAILURE.labels(call_site).inc()
        logger.error(
            "ensure_task_node returned NULL for task %s at %s",
            task_id,
            call_site,
        )
        raise RuntimeError("ensure_task_node returned NULL")

    GNM_ENSURE_TASK_NODE_SUCCESS.labels(call_site).inc()
    logger.info(
        "Ensured graph node mapping for task %s -> node_id %s (call_site=%s)",
        task_id,
        node_id,
        call_site,
    )
    return node_id


def _is_result_success(r: dict) -> bool:
    """Helper function to determine if a result indicates success."""
    if isinstance(r, dict):
        # Prefer explicit "success" at top-level
        if "success" in r and isinstance(r["success"], bool):
            return r["success"]
        
        # Check nested payload for success
        if isinstance(r.get("payload"), dict) and isinstance(r["payload"].get("success"), bool):
            return r["payload"]["success"]
        
        # Check for error field (presence indicates failure)
        if "error" in r and r["error"]:
            return False
        
        # Check for result kind
        if "kind" in r:
            return r["kind"] in ["fast_path", "escalated", "cognitive"]
    
    return False

async def get_coordinator_client() -> CoordinatorServiceClient:
    """Get or create the global coordinator service client instance."""
    global _coordinator_client
    if _coordinator_client is None:
        _coordinator_client = CoordinatorServiceClient()
        logger.info("Coordinator service client initialized")
    return _coordinator_client

async def get_eventizer_client() -> EventizerServiceClient:
    """Get or create the global eventizer service client instance."""
    global _eventizer_client
    if _eventizer_client is None:
        _eventizer_client = EventizerServiceClient()
        logger.info("Eventizer service client initialized")
    return _eventizer_client

async def _enrich_with_remote_eventizer(
    task_id: uuid.UUID,
    text: str,
    task_type: str,
    domain: str,
    fast_result_data: Dict[str, Any]
):
    """
    Async enrichment with remote eventizer service.
    
    This runs in the background and updates task params or creates facts
    with enhanced results from the full eventizer service.
    """
    try:
        eventizer_client = await get_eventizer_client()
        
        # Create eventizer request payload for HTTP call
        eventizer_payload = {
            "text": text,
            "task_type": task_type,
            "domain": domain,
            "preserve_pii": False,
            "include_metadata": True
        }
        
        # Process through remote eventizer
        remote_result = await eventizer_client.process_eventizer_request(eventizer_payload)
        
        # Compare with fast-path results
        fast_confidence = fast_result_data["confidence"]["overall_confidence"]
        remote_confidence = remote_result.get("confidence", {}).get("overall_confidence", 0.0)
        
        # If remote result is significantly better, log the improvement
        if remote_confidence > fast_confidence + 0.2:
            logger.info(
                "Remote eventizer enrichment improved confidence from %.3f to %.3f for task %s",
                fast_confidence, remote_confidence, task_id
            )
        
        # Store enriched results (could update task params or create facts)
        # For now, just log the enrichment completion
        logger.debug(
            "Remote enrichment completed for task %s: remote_confidence=%.3f, patterns=%d",
            task_id,
            remote_confidence,
            remote_result.get("patterns_applied", 0)
        )
        
    except Exception as e:
        logger.warning(f"Remote eventizer enrichment failed for task {task_id}: {e}")
        # Non-blocking - task creation already succeeded with fast-path results

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
            elif hasattr(v, 'model_dump'):
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
                logger.warning(f"Task {task.id} has non-dict result: {type(result)} - {result}")
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

    logger.info("🚀 Task worker started and waiting for tasks...")
    
    while True:
        logger.debug("⏳ Task worker waiting for next task...")
        task_id = await task_queue.get()
        logger.info(f"📥 Task worker received task ID: {task_id}")
        task = None
        
        try:
            async with async_session_factory() as session:
                task_result = await session.execute(select(Task).where(Task.id == task_id))
                task = task_result.scalar_one_or_none()

                if not task or task.status in {TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    continue
                
                # REMOVED: Local OrganismManager check - this is now handled by the Coordinator actor
                # The API should not bootstrap or hold a live OrganismManager
                
                try:
                    worker_node_id = await _ensure_task_node_mapping(
                        session, task.id, "tasks_router.worker"
                    )
                except Exception as exc:
                    logger.error(
                        "Worker failed to ensure graph node for task %s: %s",
                        task.id,
                        exc,
                    )
                    raise

                task.status = TaskStatus.RUNNING
                await session.commit()
                logger.debug(
                    "Worker mapped task %s to graph node_id %s before execution",
                    task.id,
                    worker_node_id,
                )
                # A refresh is not needed here as no new data is being generated by the DB

                payload = {
                    "type": task.type,
                    "params": task.params or {},
                    "description": task.description or "",
                    "domain": task.domain,
                    "drift_score": task.drift_score,
                    "task_id": str(task.id),
                }
                
                # ✅ FIX: Submit task to Coordinator service via client
                try:
                    # Use coordinator service client
                    coord_client = await get_coordinator_client()
                    result = await coord_client.process_task(payload)
                    
                    # Log the result for debugging (IMPORTANT: check if result is actually returned)
                    logger.info(f"Task {task.id} coordinator response type: {type(result)}")
                    if result is None:
                        logger.error(f"Task {task.id} coordinator returned None!")
                    elif isinstance(result, dict):
                        logger.info(f"Task {task.id} result keys: {list(result.keys())}, success: {result.get('success')}")
                        logger.info(f"Task {task.id} result content (first 500 chars): {str(result)[:500]}")
                    
                except Exception as e:
                    # If Coordinator service is not available, mark task as failed
                    result = {"success": False, "error": f"Coordinator service not available: {str(e)}"}
                    logger.error(f"Task {task.id} failed with error: {str(e)}")

                # Use the new unified result schema
                try:
                    # Guard against None/empty results
                    if result is None:
                        logger.warning(f"Task {task.id} returned None result, creating default fast_path result")
                        result = create_fast_path_result(
                            routed_to="coordinator",
                            organ_id="coordinator",
                            result={"status": "completed", "message": "Task routed successfully"}
                        ).model_dump()
                    
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
                        task.result = fast_path_result.model_dump()
                    elif hasattr(result, 'model_dump'):
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
                
                # Log before commit to verify result is set
                logger.info(f"✅ Task {task.id} before commit: status={task.status}, result_is_none={task.result is None}, result_has_content={bool(task.result)}, result_type={type(task.result)}")
                if task.result:
                    logger.info(f"✅ Task {task.id} result keys: {list(task.result.keys()) if isinstance(task.result, dict) else 'not-a-dict'}")
                
                await session.commit()
                logger.info(f"✅ Task {task.id} committed to database with result")

        except Exception as e:
            logger.error(f"Task worker error for task {task_id}: {e}")
            if task_id:
                async with async_session_factory() as error_session:
                    task_to_fail = await error_session.get(Task, task_id)
                    if task_to_fail:
                        task_to_fail.status = TaskStatus.FAILED
                        task_to_fail.error = str(e)
                        await error_session.commit()
            # Add small backoff to avoid tight error loops
            await asyncio.sleep(0.05)
        finally:
            task_queue.task_done()

@router.post("/tasks", response_model=TaskRead)
async def create_task(
    payload: Dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(get_async_pg_session)
) -> TaskRead:
    task_queue = _get_task_queue(request)
    run_immediately = bool(payload.get("run_immediately"))

    # Extract text for eventizer processing
    task_description = payload.get("description") or ""
    task_type = payload.get("type", "")
    domain = payload.get("domain")
    
    # Initialize enriched params with original params
    enriched_params = dict(payload.get("params") or {})
    
    # Process text through eventizer if description is provided
    should_enrich = False
    fast_result_data = None
    
    if task_description.strip():
        try:
            # HYBRID APPROACH: Fast-path for hot path, remote for enrichment
            
            # Always use fast-path first for PKG policy inputs (<1ms)
            # Use the enhanced process_text_fast with proper to_dict() methods
            fast_result_data = process_text_fast(
                text=task_description,
                task_type=task_type,
                domain=domain,
                include_original_text=payload.get("preserve_original_text", False)
            )
            
            # Use fast-path results for immediate task creation
            # IMPORTANT: Extract event_types as flat list for coordinator compatibility
            # Coordinator expects event_tags to be List[str], not a nested dict
            event_tags_list = fast_result_data["event_tags"].get("event_types", [])
            
            # Add domain as a tag if available (helps fallback planner)
            domain_value = fast_result_data["event_tags"].get("domain")
            if domain_value and domain_value not in event_tags_list:
                event_tags_list = event_tags_list + [domain_value]
            
            # Infer domain from event tags if not explicitly set
            # This helps the coordinator route to domain-specific organs
            if not domain:
                if any(tag in event_tags_list for tag in ["vip", "allergen", "luggage_custody", "hvac_fault", "privacy"]):
                    domain = "hotel_ops"
                elif any(tag in event_tags_list for tag in ["fraud", "chargeback", "payment"]):
                    domain = "fintech"
                elif any(tag in event_tags_list for tag in ["healthcare", "medical", "allergy"]):
                    domain = "healthcare"
                elif any(tag in event_tags_list for tag in ["robotics", "iot", "fault"]):
                    domain = "robotics"
                
                if domain:
                    logger.info(f"Inferred domain '{domain}' from event tags: {event_tags_list}")
            
            enriched_params.update({
                "event_tags": event_tags_list,  # Flat list of event type strings
                "event_tags_full": fast_result_data["event_tags"],  # Keep full structure for reference
                "domain": domain,  # Store inferred domain
                "attributes": fast_result_data["attributes"],
                "confidence": fast_result_data["confidence"],
                "needs_ml_fallback": fast_result_data["confidence"]["needs_ml_fallback"],
                "eventizer_metadata": {
                    "processing_time_ms": fast_result_data["processing_time_ms"],
                    "patterns_applied": fast_result_data["patterns_applied"],
                    "pii_redacted": fast_result_data["pii_redacted"],
                    "processing_log": [f"Fast-path: {fast_result_data['patterns_applied']} patterns applied"],
                    "fast_path": True,
                    "event_tags_extracted": len(event_tags_list),
                    "domain_inferred": bool(domain and not payload.get("domain"))
                }
            })
            
            # Store PII handling (safer approach - don't persist original text by default)
            if fast_result_data["pii_redacted"]:
                enriched_params["pii"] = {
                    "redacted": fast_result_data["processed_text"],
                    "was_redacted": True
                }
                # Only store original if explicitly requested for debugging
                if payload.get("preserve_original_text", False) and "original_text" in fast_result_data:
                    enriched_params["original_text"] = fast_result_data["original_text"]
            
            # Store enrichment trigger condition (serializable)
            should_enrich = fast_result_data["confidence"]["needs_ml_fallback"] or len(task_description) > 200
            enriched_params["_async_enrichment_needed"] = should_enrich
            
            logger.info(
                "Task %s processed by fast eventizer: confidence=%.3f, needs_ml_fallback=%s, patterns=%d, time=%.3fms",
                task_type, 
                fast_result_data["confidence"]["overall_confidence"],
                fast_result_data["confidence"]["needs_ml_fallback"],
                fast_result_data["patterns_applied"],
                fast_result_data["processing_time_ms"]
            )
            
        except Exception as e:
            logger.error("Eventizer processing failed for task %s: %s", task_type, e)
            # Continue with original params if eventizer fails
            enriched_params["eventizer_error"] = str(e)
            enriched_params["needs_ml_fallback"] = True

    new_task = Task(
        type=task_type,
        params=enriched_params,
        description=task_description,
        domain=domain,
        drift_score=payload.get("drift_score", 0.0),
        # status defaults to TaskStatus.CREATED
    )
    session.add(new_task)
    await session.flush()

    graph_node_id: int | None = None
    try:
        graph_node_id = await _ensure_task_node_mapping(
            session, new_task.id, "tasks_router.create_task"
        )
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to ensure graph node for task %s: %s", new_task.id, exc)
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to map task into graph node registry. "
                "Apply migration 007_hgnn_graph_schema.sql or later and retry."
            ),
        ) from exc

    if run_immediately:
        new_task.status = TaskStatus.QUEUED

    await session.commit()
    # --- OPTIMIZED: Use refresh to get DB-generated fields like created_at/id ---
    await session.refresh(new_task)

    if ENQUEUE_LTM_FROM_ROUTER:
        await enqueue_task_embedding_job(request.app.state, new_task.id, reason="create")

    if run_immediately:
        await task_queue.put(new_task.id)
        if graph_node_id is not None:
            logger.debug(
                "Queued task %s with graph node_id %s for immediate execution",
                new_task.id,
                graph_node_id,
            )

    # Trigger async enrichment if needed (using locals, not DB params)
    if should_enrich:
        asyncio.create_task(_enrich_with_remote_eventizer(
            task_id=new_task.id,
            text=task_description,
            task_type=task_type,
            domain=domain or "",
            fast_result_data=fast_result_data
        ))
        logger.debug(f"Triggered async enrichment for task {new_task.id}")

    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(new_task)
    except Exception as e:
        logger.error(f"Error converting new task to TaskRead: {e}")
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
            logger.error(f"Error converting task {task.id} to TaskRead: {e}")
            logger.error(f"Task result type: {type(task.result)}, value: {task.result}")
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
                logger.error(f"Fallback conversion also failed for task {task.id}: {fallback_error}")
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
        logger.error(f"Error converting task {task.id} to TaskRead: {e}")
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
            logger.error(f"Error converting task {task.id} to TaskRead: {e}")
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

    graph_node_id: int | None = None
    try:
        task.status = TaskStatus.QUEUED
        if RUN_NOW_ENSURE_NODE:
            graph_node_id = await _ensure_task_node_mapping(
                session, task.id, "tasks_router.run_task_now"
            )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error(
            "Failed to queue task %s (ensure_node=%s): %s",
            task.id,
            RUN_NOW_ENSURE_NODE,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to queue task. If ensure-node is enabled, verify ensure_task_node(uuid) exists and retry."
            ),
        ) from exc

    await session.refresh(task)  # <-- add this refresh after commit
    await task_queue.put(task.id)
    if graph_node_id is not None:
        logger.debug(
            "Re-queued task %s with graph node_id %s",
            task.id,
            graph_node_id,
        )
    
    # Convert to TaskRead with proper datetime formatting
    try:
        return _task_to_task_read(task)
    except Exception as e:
        logger.error(f"Error converting task {task.id} to TaskRead: {e}")
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
            logger.error(f"Error converting task {task.id} to TaskRead: {e}")
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
        logger.error(f"Error converting task {task.id} to TaskRead: {e}")
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

# --- NEW: Coordinator Service Health Check Endpoint ---
@router.get("/coordinator/health")
async def coordinator_health():
    """Check the health of the Coordinator service."""
    try:
        # Use coordinator service client
        coord_client = await get_coordinator_client()
        
        # Use the health endpoint of the coordinator service
        health_result = await coord_client.get_health_status()
        
        if health_result.get("status") == "healthy":
            return {
                "status": "healthy",
                "coordinator": "available",
                "message": "Coordinator service is healthy",
                "organism_initialized": health_result.get("organism_initialized", False)
            }
        else:
            return {
                "status": "degraded",
                "coordinator": "unresponsive",
                "message": f"Coordinator health check failed: {health_result}"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "coordinator": "unavailable",
            "message": f"Coordinator service not available: {str(e)}"
        }