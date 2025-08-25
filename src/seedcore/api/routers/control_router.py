# src/seedcore/api/routers/control_router.py
# Copyright 2024 SeedCore Contributors
from __future__ import annotations

import os, json, time, asyncio, uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel, Field

router = APIRouter(tags=["control"])

# ---------- Storage helpers ----------
FACTS_STORE_PATH = os.getenv("FACTS_STORE_PATH", "/app/data/facts.json")
TASKS_STORE_PATH = os.getenv("TASKS_STORE_PATH", "/app/data/tasks.json")

# Internal locks to avoid concurrent writes
_facts_lock = asyncio.Lock()
_tasks_lock = asyncio.Lock()

def _ensure_parent(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default

def _dump_json(path: str, data: Any):
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _now() -> float:
    return float(time.time())

# ---------- Models ----------
class FactCreate(BaseModel):
    text: str = Field(..., description="Human or system supplied fact text")
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FactPatch(BaseModel):
    text: Optional[str] = None
    tags: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

class Fact(BaseModel):
    id: str
    text: str
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
    created_at: float
    updated_at: float

class TaskCreate(BaseModel):
    type: str = Field(..., description="Task kind, e.g. 'memory_loop', 'energy_calibrate', 'dspy.plan'")
    params: Dict[str, Any] = Field(default_factory=dict)
    description: Optional[str] = None
    attached_fact_ids: List[str] = Field(default_factory=list)
    run_immediately: bool = False

class Task(BaseModel):
    id: str
    type: str
    params: Dict[str, Any] = {}
    description: Optional[str] = None
    attached_fact_ids: List[str] = []
    status: str = "created"  # created | running | completed | failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = Field(default_factory=_now)
    updated_at: float = Field(default_factory=_now)

# ---------- In-memory registries (hydrated from disk) ----------
_facts_index: Dict[str, Fact] = {}
_tasks_index: Dict[str, Task] = {}

async def _hydrate():
    global _facts_index, _tasks_index
    # Facts
    raw_facts = _load_json(FACTS_STORE_PATH, {"facts": []})
    _facts_index = {f["id"]: Fact(**f) for f in raw_facts.get("facts", []) if "id" in f and "text" in f}
    # Tasks
    raw_tasks = _load_json(TASKS_STORE_PATH, {"tasks": []})
    _tasks_index = {t["id"]: Task(**t) for t in raw_tasks.get("tasks", []) if "id" in t and "type" in t}

async def _persist_facts():
    async with _facts_lock:
        _dump_json(FACTS_STORE_PATH, {"facts": [f.model_dump() for f in _facts_index.values()]})

async def _persist_tasks():
    async with _tasks_lock:
        _dump_json(TASKS_STORE_PATH, {"tasks": [t.model_dump() for t in _tasks_index.values()]})

@router.on_event("startup")
async def _startup():
    await _hydrate()

# ========== FACTS ==========
@router.get("/facts", response_model=Dict[str, Any])
async def list_facts(
    q: Optional[str] = Query(None, description="Substring match against text/metadata"),
    tag: Optional[str] = Query(None, description="Filter by a single tag"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items = list(_facts_index.values())
    if q:
        ql = q.lower()
        def hit(f: Fact) -> bool:
            if ql in f.text.lower():
                return True
            # search in metadata stringified
            try:
                return ql in json.dumps(f.metadata, ensure_ascii=False).lower()
            except Exception:
                return False
        items = [f for f in items if hit(f)]
    if tag:
        items = [f for f in items if tag in (f.tags or [])]
    total = len(items)
    items = items[offset: offset + limit]
    return {"total": total, "items": [f.model_dump() for f in items]}

@router.get("/facts/{fact_id}", response_model=Fact)
async def get_fact(fact_id: str):
    f = _facts_index.get(fact_id)
    if not f:
        raise HTTPException(404, f"fact '{fact_id}' not found")
    return f

@router.post("/facts", response_model=Fact)
async def create_fact(payload: FactCreate):
    fid = str(uuid.uuid4())
    now = _now()
    f = Fact(id=fid, text=payload.text, tags=payload.tags, metadata=payload.metadata, created_at=now, updated_at=now)
    _facts_index[fid] = f
    await _persist_facts()
    return f

@router.patch("/facts/{fact_id}", response_model=Fact)
async def patch_fact(fact_id: str, patch: FactPatch):
    f = _facts_index.get(fact_id)
    if not f:
        raise HTTPException(404, f"fact '{fact_id}' not found")
    updated = f.model_copy(update={
        "text": patch.text if patch.text is not None else f.text,
        "tags": patch.tags if patch.tags is not None else f.tags,
        "metadata": patch.metadata if patch.metadata is not None else f.metadata,
        "updated_at": _now()
    })
    _facts_index[fact_id] = updated
    await _persist_facts()
    return updated

@router.delete("/facts/{fact_id}", response_model=Dict[str, Any])
async def delete_fact(fact_id: str):
    if fact_id not in _facts_index:
        raise HTTPException(404, f"fact '{fact_id}' not found")
    _facts_index.pop(fact_id, None)
    await _persist_facts()
    return {"deleted": fact_id}

# ========== TASKS ==========
# NOTE: Task "run" uses httpx to call local endpoints to avoid import cycles.
try:
    import httpx
except Exception:
    httpx = None  # We'll error nicely if it's not available.

def _base_url() -> str:
    base = os.getenv("SEEDCORE_API_ADDRESS", "127.0.0.1:8002")
    if not base.startswith("http"):
        base = f"http://{base}"
    # Avoid hairpin via K8s Service name inside the pod
    svc_names = {
        os.getenv("SERVICE_NAME", "seedcore-api"),
        f'{os.getenv("SERVICE_NAME", "seedcore-api")}.{os.getenv("NAMESPACE", "default")}.svc',
    }
    if any(str(base).startswith(name) for name in svc_names):
        return "http://127.0.0.1:8002"
    return base

async def _run_task_and_capture(task: Task):
    # Mark running
    task.status = "running"
    task.updated_at = _now()
    await _persist_tasks()

    if httpx is None:
        task.status = "failed"
        task.error = "httpx not installed in image"
        task.updated_at = _now()
        await _persist_tasks()
        return

    url = _base_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            result: Dict[str, Any] | None = None

            if task.type == "memory_loop":
                r = await client.get(f"{url}/run_memory_loop")
                result = r.json()

            elif task.type == "slow_loop":
                r = await client.get(f"{url}/run_slow_loop")
                result = r.json()

            elif task.type == "energy_calibrate":
                r = await client.get(f"{url}/energy/calibrate")
                result = r.json()

            elif task.type == "energy_monitor":
                r = await client.get(f"{url}/energy/monitor")
                result = r.json()

            elif task.type == "dspy.plan":
                r = await client.post(
                    f"{url}/dspy/plan-task",
                    json={
                        "task_description": task.params.get("task_description", task.description or "No description"),
                        "agent_id": task.params.get("agent_id"),
                        "agent_capabilities": task.params.get("agent_capabilities"),
                        "available_resources": task.params.get("available_resources"),
                    },
                )
                result = r.json()

            elif task.type == "dspy.reason":
                r = await client.post(
                    f"{url}/dspy/reason-about-failure",
                    params={"incident_id": task.params.get("incident_id", "unknown"),
                            "agent_id": task.params.get("agent_id")}
                )
                result = r.json()

            elif task.type == "dspy.decide":
                r = await client.post(
                    f"{url}/dspy/make-decision",
                    json={
                        "decision_context": task.params.get("decision_context", {}),
                        "agent_id": task.params.get("agent_id"),
                        "historical_data": task.params.get("historical_data", {}),
                    },
                )
                result = r.json()

            elif task.type == "noop":
                result = {"ok": True, "note": "noop completed"}

            else:
                raise RuntimeError(f"Unsupported task type: {task.type}")

            task.status = "completed"
            task.result = result
            task.updated_at = _now()
            await _persist_tasks()

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        task.updated_at = _now()
        await _persist_tasks()

@router.post("/tasks", response_model=Task)
async def create_task(payload: TaskCreate):
    tid = str(uuid.uuid4())
    t = Task(
        id=tid,
        type=payload.type,
        params=payload.params,
        description=payload.description,
        attached_fact_ids=payload.attached_fact_ids,
        status="created",
    )
    _tasks_index[tid] = t
    await _persist_tasks()

    if payload.run_immediately:
        asyncio.create_task(_run_task_and_capture(t))

    return t

@router.get("/tasks", response_model=Dict[str, Any])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items = list(_tasks_index.values())
    if status:
        items = [t for t in items if t.status == status]
    total = len(items)
    items = items[offset: offset + limit]
    return {"total": total, "items": [t.model_dump() for t in items]}

@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str):
    t = _tasks_index.get(task_id)
    if not t:
        raise HTTPException(404, f"task '{task_id}' not found")
    return t

@router.get("/tasks/{task_id}/status", response_model=Dict[str, Any])
async def get_task_status(task_id: str):
    t = _tasks_index.get(task_id)
    if not t:
        raise HTTPException(404, f"task '{task_id}' not found")
    return {"id": t.id, "status": t.status, "updated_at": t.updated_at, "error": t.error}

@router.post("/tasks/{task_id}/run", response_model=Dict[str, Any])
async def run_task(task_id: str):
    t = _tasks_index.get(task_id)
    if not t:
        raise HTTPException(404, f"task '{task_id}' not found")
    if t.status in ("running",):
        return {"accepted": False, "message": "already running"}
    asyncio.create_task(_run_task_and_capture(t))
    return {"accepted": True, "id": t.id}

