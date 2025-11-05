"""Core utilities for task normalization, redaction, and data processing."""

import uuid
import logging
import inspect
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Iterable, Union

# Import models for type hints
from seedcore.models import TaskPayload, Task

logger = logging.getLogger(__name__)

# Constants for maintainability
MAX_STRING_LENGTH = 1000  # Maximum string length before truncation in redaction
DEFAULT_RECURSION_DEPTH = 10  # Default maximum recursion depth for nested structure traversal


def sync_task_identity(task_like: Any, task_id: str) -> None:
    """Sync task identity by setting id/task_id on the task object or dict."""
    if isinstance(task_like, dict):
        task_like["id"] = task_id
        return
    for attr in ("id", "task_id"):
        if hasattr(task_like, attr):
            try:
                setattr(task_like, attr, task_id)
            except Exception:
                continue


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
    task_dict = convert_task_to_dict(task) or {}
    
    # 2) Resolve/generate ID
    raw_id = task_dict.get("id") or task_dict.get("task_id")
    try:
        task_uuid = uuid.UUID(str(raw_id)) if raw_id else uuid.uuid4()
    except (ValueError, TypeError):
        task_uuid = uuid.uuid4()
    
    task_id_str = str(task_uuid)
    task_dict["id"] = task_id_str
    
    # 3) Sync identity back to original object if possible
    sync_task_identity(task, task_id_str)
    
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
    elif isinstance(data, str) and len(data) > MAX_STRING_LENGTH:
        return data[:MAX_STRING_LENGTH] + "... [TRUNCATED]"
    else:
        return data


def extract_from_nested(
    data: Dict[str, Any],
    key_paths: List[Tuple[str, ...]],
    value_type: Optional[type] = None,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH
) -> Optional[Any]:
    """
    Unified pattern-based extractor for nested dictionary values.
    
    Searches through a dictionary using multiple key paths, returning the first
    matching value that satisfies the type constraint (if provided).
    
    Args:
        data: Dictionary to search in
        key_paths: List of tuples representing key paths to try (e.g., [("payload", "metadata", "decision")])
        value_type: Optional type constraint to validate the extracted value (e.g., str, dict)
        max_depth: Maximum depth to traverse (prevents infinite loops)
    
    Returns:
        First matching value found, or None if no match
    
    Example:
        >>> data = {"payload": {"metadata": {"decision": "planner"}}}
        >>> extract_from_nested(data, [("payload", "metadata", "decision"), ("payload", "decision")], str)
        'planner'
    """
    if not isinstance(data, dict) or max_depth is not None and max_depth <= 0:
        return None
    
    for key_path in key_paths:
        if not key_path:
            continue
        
        current = data
        for i, key in enumerate(key_path):
            if not isinstance(current, dict):
                break
            current = current.get(key)
            if current is None:
                break
            # If we've reached the last key in the path
            if i == len(key_path) - 1:
                # Check type constraint if provided
                if value_type is None or isinstance(current, value_type):
                    return current
        # If we got here, this path didn't match
        continue
    
    return None


def extract_proto_plan(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract 'proto_plan' from a route/execute payload.
    Looks under payload['metadata']['proto_plan'] and payload['proto_plan'].
    """
    return extract_from_nested(
        payload,
        key_paths=[
            ("metadata", "proto_plan"),
            ("proto_plan",),
        ],
        value_type=dict
    )


def extract_decision(route_result: Dict[str, Any]) -> Optional[str]:
    """
    Extract 'decision' from a route result dict.
    Checks result['payload']['metadata']['decision'], result['payload']['decision'], and result['decision'].
    """
    return extract_from_nested(
        route_result,
        key_paths=[
            ("payload", "metadata", "decision"),
            ("payload", "decision"),
            ("decision",),
        ],
        value_type=str
    )


def extract_dependency_token(
    ref: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    visited: Optional[Set[int]] = None
) -> Any:
    """
    Extract a "dependency token" from a reference value.
    Recursively searches through nested structures to find task identifiers.
    
    Uses memoization (via visited set) and depth-limiting to handle very deep structures
    efficiently and prevent infinite loops from circular references.
    
    Args:
        ref: The reference value to extract a token from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        visited: Set of object IDs already processed (for memoization/circular reference detection)
    
    Returns:
        Extracted token or None if not found
    """
    if ref is None:
        return None
    
    # Depth limit check
    if max_depth is not None and max_depth <= 0:
        return None
    
    # Initialize visited set on first call
    if visited is None:
        visited = set()
    
    # Memoization: Check if we've already processed this object (prevents circular references)
    # Use id() for objects that can be hashed in sets (handles mutable objects)
    ref_id = id(ref)
    if ref_id in visited:
        return None  # Circular reference detected
    visited.add(ref_id)
    
    try:
        # Handle collections
        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                token = extract_dependency_token(
                    item,
                    max_depth - 1 if max_depth is not None else None,
                    visited
                )
                if token is not None:
                    return token
            return None

        # Handle dictionaries
        if isinstance(ref, dict):
            for key in ("task_id", "id", "parent_task_id", "source_task_id", "step_id", "child_task_id", "task"):
                if key in ref:
                    token = extract_dependency_token(
                        ref[key],
                        max_depth - 1 if max_depth is not None else None,
                        visited
                    )
                    if token is not None:
                        return token
            return None

        # Handle objects with attributes
        for attr in ("task_id", "id", "parent_task_id", "source_task_id", "step_id", "child_task_id"):
            if hasattr(ref, attr):
                token = extract_dependency_token(
                    getattr(ref, attr),
                    max_depth - 1 if max_depth is not None else None,
                    visited
                )
                if token is not None:
                    return token

        # Handle numeric types
        if isinstance(ref, float) and ref.is_integer():
            return int(ref)

        # Return the value itself if it's a primitive we can use
        return ref
    finally:
        # Remove from visited set when we're done processing this branch
        # This allows the same object to be visited again in a different branch
        visited.discard(ref_id)


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
    
    domain = str(domain).strip().lower()
    
    # Map common variations to standard domains
    domain_map = {
        "fact": "facts",
        "admin": "management", 
        "mgmt": "management",
        "util": "utility",
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
    
    return domain_map.get(domain, domain)


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
    if not isinstance(task_dict, dict):
        return None
    
    # Try top-level fields first
    candidate = task_dict.get("agent_id") or task_dict.get("agent")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()

    # Check in params
    params = task_dict.get("params")
    if isinstance(params, dict):
        for key in ("agent_id", "agent", "owner_agent_id"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    # Check in metadata
    metadata = task_dict.get("metadata")
    if isinstance(metadata, dict):
        for key in ("agent_id", "agent"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    
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


# ============================================================================
# Dependency Management Utility Functions
# ============================================================================

def iter_dependency_entries(dependencies: Any) -> Iterable[Any]:
    """Iterate over dependency entries, handling nested structures."""
    if dependencies is None:
        return []

    if isinstance(dependencies, (list, tuple, set)):
        for item in dependencies:
            if isinstance(item, (list, tuple, set)):
                for nested in iter_dependency_entries(item):
                    yield nested
            else:
                yield item
    else:
        yield dependencies


def resolve_child_task_id(record: Any, fallback_step: Any) -> Any:
    """Extract the task identifier for a persisted subtask."""
    if record is not None:
        if isinstance(record, dict):
            for key in ("task_id", "id", "child_task_id", "subtask_id"):
                if key in record:
                    token = extract_dependency_token(record[key])
                    if token is not None:
                        return token
            if "task" in record:
                token = extract_dependency_token(record["task"])
                if token is not None:
                    return token
        else:
            for attr in ("task_id", "id", "child_task_id", "subtask_id"):
                if hasattr(record, attr):
                    token = extract_dependency_token(getattr(record, attr))
                    if token is not None:
                        return token
            if hasattr(record, "task"):
                token = extract_dependency_token(getattr(record, "task"))
                if token is not None:
                    return token

    if fallback_step is not None:
        if isinstance(fallback_step, dict):
            for key in ("task_id", "id", "step_id"):
                if key in fallback_step:
                    token = extract_dependency_token(fallback_step[key])
                    if token is not None:
                        return token
            if "task" in fallback_step:
                token = extract_dependency_token(fallback_step["task"])
                if token is not None:
                    return token
        else:
            for attr in ("task_id", "id", "step_id"):
                if hasattr(fallback_step, attr):
                    token = extract_dependency_token(getattr(fallback_step, attr))
                    if token is not None:
                        return token
            if hasattr(fallback_step, "task"):
                token = extract_dependency_token(getattr(fallback_step, "task"))
                if token is not None:
                    return token

    return None


def _collect_aliases_from_item(
    item: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True
) -> Set[str]:
    """
    Unified helper to collect identifier aliases from a record or step.
    
    Args:
        item: The record or step to extract aliases from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        include_metadata: Whether to traverse metadata sections (default: True)
    
    Returns:
        Set of canonicalized identifier strings
    """
    aliases: Set[str] = set()

    if isinstance(item, dict):
        aliases.update(collect_aliases_from_mapping(item, max_depth, include_metadata))
        maybe_task = item.get("task")
        if isinstance(maybe_task, dict):
            aliases.update(collect_aliases_from_mapping(maybe_task, max_depth, include_metadata))
        if include_metadata:
            maybe_meta = item.get("metadata")
            if isinstance(maybe_meta, dict):
                aliases.update(collect_aliases_from_mapping(maybe_meta, max_depth, include_metadata))
    else:
        aliases.update(collect_aliases_from_object(item, max_depth, include_metadata))

    return aliases


def collect_record_aliases(
    record: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True
) -> Set[str]:
    """
    Collect all possible identifier aliases from a record.
    
    Args:
        record: The record to extract aliases from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        include_metadata: Whether to traverse metadata sections (default: True)
    
    Returns:
        Set of canonicalized identifier strings
    """
    return _collect_aliases_from_item(record, max_depth, include_metadata)


def collect_step_aliases(
    step: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True
) -> Set[str]:
    """
    Collect all possible identifier aliases from a step.
    
    Args:
        step: The step to extract aliases from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        include_metadata: Whether to traverse metadata sections (default: True)
    
    Returns:
        Set of canonicalized identifier strings
    """
    return _collect_aliases_from_item(step, max_depth, include_metadata)


def collect_aliases_from_mapping(
    mapping: Dict[str, Any],
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True
) -> Set[str]:
    """
    Collect identifier aliases from a dictionary mapping.
    
    Args:
        mapping: Dictionary to extract aliases from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        include_metadata: Whether to traverse metadata sections (default: True)
    
    Returns:
        Set of canonicalized identifier strings
    """
    if max_depth is not None and max_depth <= 0:
        return set()
    
    aliases: Set[str] = set()
    alias_keys = {"task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id"}

    for key in alias_keys:
        if key in mapping:
            token = extract_dependency_token(mapping[key], max_depth)
            if token is not None:
                aliases.add(canonicalize_identifier(token))

    if max_depth is not None and max_depth > 1:
        for key, value in mapping.items():
            # Skip metadata if include_metadata is False
            if not include_metadata and key == "metadata":
                continue
            if isinstance(value, dict):
                aliases.update(collect_aliases_from_mapping(value, max_depth - 1, include_metadata))

    return aliases


def collect_aliases_from_object(
    obj: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True
) -> Set[str]:
    """
    Collect identifier aliases from an object.
    
    Args:
        obj: Object to extract aliases from
        max_depth: Maximum recursion depth to prevent infinite loops (default: DEFAULT_RECURSION_DEPTH)
        include_metadata: Whether to traverse metadata sections (default: True)
    
    Returns:
        Set of canonicalized identifier strings
    """
    if max_depth is not None and max_depth <= 0:
        return set()
    
    aliases: Set[str] = set()
    alias_keys = ("task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id")

    for key in alias_keys:
        if hasattr(obj, key):
            token = extract_dependency_token(getattr(obj, key), max_depth)
            if token is not None:
                aliases.add(canonicalize_identifier(token))

    if max_depth is not None and max_depth > 1:
        # Always process "task" attribute
        if hasattr(obj, "task"):
            value = getattr(obj, "task")
            if isinstance(value, dict):
                aliases.update(collect_aliases_from_mapping(value, max_depth - 1, include_metadata))
        
        # Conditionally process "metadata" attribute
        if include_metadata and hasattr(obj, "metadata"):
            value = getattr(obj, "metadata")
            if isinstance(value, dict):
                aliases.update(collect_aliases_from_mapping(value, max_depth - 1, include_metadata))

    return aliases
