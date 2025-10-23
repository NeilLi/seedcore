"""Core utilities for task normalization, redaction, and data processing."""

import uuid
import logging
import inspect
from typing import Any, Callable, Dict, Optional, Set, Tuple, Iterable, Union

# Import models for type hints
from seedcore.models import TaskPayload, Task

logger = logging.getLogger(__name__)


def normalize_task_dict(task: Any) -> Tuple[uuid.UUID, Dict[str, Any]]:
    """
    Normalize a task-like object to a (task_id, task_dict).

    Accepts:
      - dict-like objects
      - pydantic models (with .model_dump() or .dict())
      - objects with __dict__
    ID resolution order:
      - 'id'
      - 'task_id'
      - 'uuid' / 'uid'
      - otherwise generate a new UUID4
    Returns:
      (uuid.UUID, dict) — the dict will always include an 'id' string.
    """
    # 1) Convert to dict best-effort
    task_dict: Dict[str, Any] = {}
    if task is None:
        logger.warning("normalize_task_dict: got None")
    elif isinstance(task, dict):
        task_dict = dict(task)
    elif hasattr(task, "model_dump"):
        try:
            task_dict = task.model_dump()  # pydantic v2
        except Exception:
            task_dict = dict(getattr(task, "__dict__", {}))
    elif hasattr(task, "dict"):
        try:
            task_dict = task.dict()  # pydantic v1
        except Exception:
            task_dict = dict(getattr(task, "__dict__", {}))
    elif hasattr(task, "__dict__"):
        task_dict = dict(task.__dict__)
    else:
        logger.warning("Unknown task type: %s", type(task))

    # 2) Resolve/generate ID
    id_candidates = [
        task_dict.get("id"),
        task_dict.get("task_id"),
        task_dict.get("uuid"),
        task_dict.get("uid"),
    ]
    task_uuid: Optional[uuid.UUID] = None
    for cand in id_candidates:
        try:
            if isinstance(cand, uuid.UUID):
                task_uuid = cand
                break
            if isinstance(cand, (str, bytes)) and cand:
                task_uuid = uuid.UUID(str(cand))
                break
        except Exception:
            continue
    if task_uuid is None:
        task_uuid = uuid.uuid4()

    # 3) Normalize id in the dict as a string
    task_dict["id"] = str(task_uuid)
    return task_uuid, task_dict


def convert_task_to_dict(task: Any) -> Dict[str, Any]:
    """Convert task object to dictionary, handling TaskPayload and other types."""
    if isinstance(task, dict):
        return task.copy()
    elif hasattr(task, 'model_dump'):
        task_dict = task.model_dump()
        # Handle TaskPayload which has 'task_id' instead of 'id'
        if hasattr(task, 'task_id') and 'id' not in task_dict:
            task_dict['id'] = task.task_id
        return task_dict
    elif hasattr(task, 'dict'):
        task_dict = task.dict()
        # Handle TaskPayload which has 'task_id' instead of 'id'
        if hasattr(task, 'task_id') and 'id' not in task_dict:
            task_dict['id'] = task.task_id
        return task_dict
    elif hasattr(task, '__dict__'):
        return task.__dict__.copy()
    else:
        logger.warning(f"Unknown task type: {type(task)}")
        return {}


def canonicalize_identifier(value: Any) -> str:
    """Canonicalize an identifier-like value to a string (lossless where possible)."""
    if value is None:
        return ""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        # Int-like floats -> int string; otherwise preserve float repr
        return str(int(value)) if value.is_integer() else str(value)
    # Fallback: string normalize
    return str(value).strip()


def redact_sensitive_data(data: Any) -> Any:
    """Redact sensitive data from memory synthesis payload."""
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in ['password', 'token', 'key', 'secret', 'auth']):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_data(value)
        return redacted
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str) and len(data) > 1000:
        return data[:1000] + "... [TRUNCATED]"
    else:
        return data


def extract_proto_plan(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract 'proto_plan' from a route/execute payload.
    Looks under payload['metadata']['proto_plan'] and payload['proto_plan'].
    """
    if not isinstance(payload, dict):
        return None
    md = payload.get("metadata")
    if isinstance(md, dict):
        pp = md.get("proto_plan")
        if isinstance(pp, dict):
            return pp
    pp = payload.get("proto_plan")
    return pp if isinstance(pp, dict) else None


def extract_decision(route_result: Dict[str, Any]) -> Optional[str]:
    """
    Extract 'decision' from a route result dict.
    Checks result['payload']['metadata']['decision'], result['payload']['decision'], and result['decision'].
    """
    if not isinstance(route_result, dict):
        return None
    # Common nesting: {"payload": {"metadata": {"decision": "planner"}}}
    payload = route_result.get("payload")
    if isinstance(payload, dict):
        md = payload.get("metadata")
        if isinstance(md, dict):
            d = md.get("decision")
            if isinstance(d, str):
                return d
        d = payload.get("decision")
        if isinstance(d, str):
            return d
    d = route_result.get("decision")
    return d if isinstance(d, str) else None


def extract_dependency_token(ref: Any) -> Any:
    """
    Extract a "dependency token" from a reference value.
    If given a list/tuple/set, return the first non-empty element; otherwise return ref as-is.
    """
    if ref is None:
        return None
    if isinstance(ref, (list, tuple, set)):
        for x in ref:
            if x not in (None, "", []):
                return x
        return None
    return ref


def build_task_from_dict(task_data: Dict[str, Any]) -> Task:
    """
    Build a Task model from a dict. Ensures required fields, populates sensible defaults.
    """
    if not isinstance(task_data, dict):
        raise TypeError("task_data must be a dict")

    # ID
    tid = task_data.get("id") or task_data.get("task_id")
    try:
        tid = str(uuid.UUID(str(tid))) if tid else str(uuid.uuid4())
    except Exception:
        tid = str(uuid.uuid4())

    return Task(
        id=tid,
        type=str(task_data.get("type") or "").strip() or "unknown",
        description=str(task_data.get("description") or ""),
        params=task_data.get("params") or {},
        domain=task_data.get("domain"),
        features=task_data.get("features") or {},
        history_ids=task_data.get("history_ids") or [],
    )


def normalize_string(x: Optional[str]) -> Optional[str]:
    """Normalize string for consistent matching."""
    return x.strip().lower() if x else None


def normalize_domain(domain: Optional[str]) -> Optional[str]:
    """Normalize domain to standard taxonomy."""
    if not domain:
        return None
    
    # Map common domain variations to standard taxonomy
    domain_map = {
        "hospitality": "hospitality",
        "hotel": "hospitality", 
        "hospitality_service": "hospitality",
        "customer_service": "customer_service",
        "support": "customer_service",
        "guest_services": "customer_service",
        "operations": "operations",
        "ops": "operations",
        "maintenance": "maintenance",
        "facilities": "maintenance",
        "security": "security",
        "safety": "security",
        "food_service": "food_service",
        "f&b": "food_service",
        "food_and_beverage": "food_service",
        "housekeeping": "housekeeping",
        "cleaning": "housekeeping",
        "concierge": "concierge",
        "guest_experience": "guest_experience",
        "guest_relations": "guest_relations"
    }
    
    normalized = normalize_string(domain)
    return domain_map.get(normalized, normalized)


def validate_task_payload(payload: Dict[str, Any]) -> TaskPayload:
    """Validate and convert dict to TaskPayload model."""
    try:
        return TaskPayload(**payload)
    except Exception as e:
        logger.warning(f"Failed to validate TaskPayload: {e}")
        # Return a minimal valid TaskPayload
        return TaskPayload(
            type=payload.get("type", "unknown"),
            params=payload.get("params", {}),
            description=payload.get("description", ""),
            domain=payload.get("domain"),
            drift_score=payload.get("drift_score", 0.0),
            task_id=payload.get("task_id", str(uuid.uuid4()))
        )


def validate_task(task_data: Dict[str, Any]) -> Task:
    """Validate and convert dict to Task model."""
    try:
        return Task(**task_data)
    except Exception as e:
        logger.warning(f"Failed to validate Task: {e}")
        # Return a minimal valid Task
        return Task(
            type=task_data.get("type", "unknown"),
            description=task_data.get("description", ""),
            params=task_data.get("params", {}),
            domain=task_data.get("domain"),
            features=task_data.get("features", {}),
            history_ids=task_data.get("history_ids", [])
        )


def task_to_payload(task: Task) -> TaskPayload:
    """Convert Task -> TaskPayload (preserving ID as task_id)."""
    return TaskPayload(
        type=task.type,
        params=task.params,
        description=task.description or "",
        domain=task.domain,
        drift_score=0.0,  # or pass-through if you compute it upstream
        task_id=task.id,
    )


def payload_to_task(payload: TaskPayload) -> Task:
    """Convert TaskPayload -> Task (symmetric to task_to_payload)."""
    return Task(
        id=payload.task_id,
        type=payload.type,
        description=payload.description or "",
        params=payload.params or {},
        domain=payload.domain,
        features={},       # default empty
        history_ids=[],    # default empty
    )


def extract_agent_id(task_dict: Dict[str, Any]) -> Optional[str]:
    """Extract agent ID from task dictionary."""
    # Try multiple possible locations for agent ID
    agent_id = task_dict.get("agent_id")
    if agent_id:
        return str(agent_id)
    
    # Check in params
    params = task_dict.get("params", {})
    agent_id = params.get("agent_id")
    if agent_id:
        return str(agent_id)
    
    # Check in features
    features = task_dict.get("features", {})
    agent_id = features.get("agent_id")
    if agent_id:
        return str(agent_id)
    
    return None


def normalize_type(task_type: Optional[str]) -> str:
    """
    Normalize common type aliases to canonical names.
    Falls back to the cleaned original if no mapping applies.
    """
    if not task_type:
        return "unknown"
    
    # Convert to lowercase and strip whitespace
    normalized = str(task_type).strip().lower()
    
    # Map common variations to standard types
    type_map = {
        # Anomaly detection
        "anomaly_triage": "anomaly_triage",
        "anomaly": "anomaly_triage",
        "triage": "anomaly_triage",
        
        # Execution
        "execute": "execute",
        "exec": "execute",
        "run": "execute",
        
        # Graph operations
        "graph_fact_embed": "graph_fact_embed",
        "fact_embed": "graph_fact_embed",
        "graph_fact_query": "graph_fact_query",
        "fact_query": "graph_fact_query",
        "graph_embed": "graph_embed",
        "embed": "graph_embed",
        "graph_rag_query": "graph_rag_query",
        "rag_query": "graph_rag_query",
        "graph_embed_v2": "graph_embed_v2",
        "embed_v2": "graph_embed_v2",
        "graph_rag_query_v2": "graph_rag_query_v2",
        "rag_query_v2": "graph_rag_query_v2",
        
        # Resource management
        "artifact_manage": "artifact_manage",
        "artifact": "artifact_manage",
        "capability_manage": "capability_manage",
        "capability": "capability_manage",
        "memory_cell_manage": "memory_cell_manage",
        "memory_cell": "memory_cell_manage",
        "model_manage": "model_manage",
        "model": "model_manage",
        "policy_manage": "policy_manage",
        "policy": "policy_manage",
        "service_manage": "service_manage",
        "service": "service_manage",
        "skill_manage": "skill_manage",
        "skill": "skill_manage",
        
        # Generic operations
        "retrieval": "retrieval",
        "ranking": "ranking",
        "generation": "generation",
        "routing": "routing",
        "route": "routing",
        "router": "routing",
        "orchestration": "orchestration",
    }
    
    return type_map.get(normalized, normalized)


def _is_nonstring_iterable(x: Any) -> bool:
    """Check if x is an iterable but not a string or bytes."""
    return isinstance(x, Iterable) and not isinstance(x, (str, bytes))


async def _init_inputs_and_eventizer(
    self,
    task: Union["TaskPayload", Dict[str, Any]],
    *,
    eventizer_helper: Optional[Callable[[Any], Any]] = None,
) -> Tuple["TaskPayload", Dict[str, Any]]:
    """
    Normalize task input and collect eventizer-derived metadata.

    Returns:
      (task: TaskPayload, ctx: Dict[str, Any]) where ctx has:
        - tags: Set[str]
        - eventizer_data: Dict[str, Any]
        - eventizer_tags: Dict[str, Any]
        - attributes: Dict[str, Any]
        - confidence: Dict[str, Any]
        - pii_redacted: bool
        - eventizer_summary: Optional[Dict[str, Any]]
    """
    # ---- 1) Task normalization (dict -> TaskPayload)
    if not isinstance(task, TaskPayload):
        task = TaskPayload.model_validate(task)

    params: Dict[str, Any] = task.params or {}

    # ---- 2) Resolve eventizer helper (supports sync or async)
    helper = eventizer_helper
    if helper is None:
        # fall back to a default on self if present (optional)
        helper = getattr(self, "default_features_from_payload", None)

    eventizer_data: Dict[str, Any] = {}
    if helper is not None:
        maybe_features = helper(task)
        if inspect.isawaitable(maybe_features):
            maybe_features = await maybe_features
        if isinstance(maybe_features, dict):
            eventizer_data = maybe_features  # only accept dict

    # ---- 3) Tags: params.event_tags ⊎ eventizer_data.event_tags.event_types (set semantics)
    tags: Set[str] = set()
    param_tags = params.get("event_tags") or []
    if _is_nonstring_iterable(param_tags):
        tags.update(str(t) for t in param_tags)

    eventizer_tags: Dict[str, Any] = {}
    if isinstance(eventizer_data.get("event_tags"), dict):
        eventizer_tags = eventizer_data["event_tags"]
        evt_types = eventizer_tags.get("event_types")
        if _is_nonstring_iterable(evt_types):
            tags.update(str(t) for t in evt_types)

        # Domain inference: only when task.domain is unset
        evt_domain = eventizer_tags.get("domain")
        if evt_domain and not task.domain:
            task.domain = str(evt_domain)

    # ---- 3.5) Additional domain inference from tags if still unset
    if not task.domain:
        # Map domain-specific tags to domains
        if any(tag in tags for tag in ["vip", "allergen", "luggage_custody", "hvac_fault", "privacy"]):
            task.domain = "hotel_ops"
        elif any(tag in tags for tag in ["fraud", "chargeback", "payment"]):
            task.domain = "fintech"
        elif any(tag in tags for tag in ["healthcare", "medical", "allergy"]):
            task.domain = "healthcare"
        elif any(tag in tags for tag in ["robotics", "iot", "fault"]):
            task.domain = "robotics"

    # ---- 4) Attributes & Confidence merges (params override eventizer)
    attributes: Dict[str, Any] = {}
    if isinstance(eventizer_data.get("attributes"), dict):
        attributes.update(eventizer_data["attributes"])
    if isinstance(params.get("attributes"), dict):
        attributes.update(params["attributes"])  # params win

    confidence: Dict[str, Any] = {}
    if isinstance(eventizer_data.get("confidence"), dict):
        confidence.update(eventizer_data["confidence"])
    if isinstance(params.get("confidence"), dict):
        confidence.update(params["confidence"])  # params win

    # ---- 5) PII flag with correct precedence
    pii_redacted = bool(params.get("pii", {}).get("was_redacted", False))
    if "pii_redacted" in eventizer_data:
        pii_redacted = bool(eventizer_data.get("pii_redacted"))

    # ---- 6) Compact eventizer summary (optional, for payloads/logs)
    eventizer_summary: Optional[Dict[str, Any]] = None
    if eventizer_data:
        eventizer_summary = {
            "event_tags": eventizer_tags.get("event_types") if eventizer_tags else None,
            "attributes": eventizer_data.get("attributes"),
            "confidence": eventizer_data.get("confidence"),
            "patterns_applied": eventizer_data.get("patterns_applied"),
            "pii_redacted": eventizer_data.get("pii_redacted"),
        }

    ctx = {
        "tags": tags,
        "eventizer_data": eventizer_data,
        "eventizer_tags": eventizer_tags,
        "attributes": attributes,
        "confidence": confidence,
        "pii_redacted": pii_redacted,
        "eventizer_summary": eventizer_summary,
    }
    return task, ctx


# ============================================================================
# PKG (Policy Graph Kernel) Utility Functions
# ============================================================================

def _normalise_sequence_length(value: Any) -> Optional[int]:
    """Best-effort helper to compute the length of a sequence for logging."""
    if hasattr(value, "__len__"):
        try:
            return len(value)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _coerce_pkg_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a PKG result mapping into a mutable dictionary."""
    coerced = dict(result)
    coerced.setdefault("version", result.get("version"))
    return coerced
