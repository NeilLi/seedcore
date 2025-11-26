"""
Core utilities for task normalization, redaction, and data processing.
Acts as the Coordinator layer's entry point for sanitizing, unpacking, and scoring tasks.
"""

import uuid
import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Import models
from seedcore.models.task_payload import TaskPayload
from seedcore.models.task import TaskType

logger = logging.getLogger(__name__)

# Constants
MAX_STRING_LENGTH = 1000
DEFAULT_RECURSION_DEPTH = 10

# ============================================================================
# 1. PRIMARY NORMALIZATION PIPELINE
# ============================================================================


def coerce_task_payload(task: Any) -> Tuple[TaskPayload, Dict[str, Any]]:
    """
    The robust entry point for normalizing ANY task input into a TaskPayload.

    It handles three distinct input formats:
    1. **TaskPayload Object**: Internal calls.
    2. **Dispatcher Dump** (via `model_dump`): Hybrid dict with `task_id` AND packed `params`.
    3. **DB Row** (via `to_db_row`): Strict dict with `id` AND packed `params`.
    4. **Raw API Input**: Dict with top-level fields only, NO packed `params`.

    Returns:
        (TaskPayload object, Merged Dict for DB/API)
    """
    # --- Step 1: Structural Normalization ---
    # This standardizes ID to 'id' key in the dict, but we track the value separately.
    task_id, raw_dict = normalize_task_dict(task)

    # --- Step 2: Type Normalization ---
    raw_type = raw_dict.get("type") or raw_dict.get("task_type")
    canonical_type = normalize_type(raw_type)
    raw_dict["type"] = canonical_type

    # --- Step 3: Decompose Params (Hydration) ---

    # Case A: Input is already a TaskPayload object
    if isinstance(task, TaskPayload):
        payload = task
        if str(task_id) != payload.task_id:
            payload.task_id = str(task_id)

    # Case B: Input is a Dict (Dispatcher Dump, DB Row, or Raw)
    else:
        try:
            params = raw_dict.get("params")

            # CRITICAL DECISION LOGIC:
            # The Dispatcher sends `model_dump()`, which contains `params` populated with
            # envelopes (graph, routing, chat).
            # If `params` has these envelopes, we MUST treat it as a DB-style row
            # and unpack from `params` to ensure consistency.

            is_packed_payload = isinstance(params, dict) and (
                "graph" in params
                or "routing" in params
                or "cognitive" in params
                or "chat" in params
            )

            if is_packed_payload:
                # ROUTE 1: TRUST PARAMS (Dispatcher/DB Source)
                # TaskPayload.from_db() handles both 'id' and 'task_id' keys safely.
                # It unpacks params -> top-level fields.
                payload = TaskPayload.from_db(raw_dict)
            else:
                # ROUTE 2: TRUST TOP-LEVEL (External API Source)
                # Standard Pydantic load. params might be empty, so it builds
                # envelopes from top-level fields (e.g. chat_message).
                payload = TaskPayload.model_validate(raw_dict)

        except Exception as e:
            logger.warning(
                f"Task payload validation warning: {e}. Falling back to permissive load."
            )
            payload = _permissive_load(raw_dict, task_id, canonical_type)

    # --- Step 4: Compute / Backfill Scores ---
    _compute_scoring_features(payload)

    # --- Step 5: Generate Output Formats ---
    # We generate a clean DB row format for downstream persistence.
    db_row = payload.to_db_row()

    # We mix in extra fields from the input (like correlation_id) that aren't in the DB schema
    # but are needed for passing context to the next service.
    original_extras = {
        k: v for k, v in raw_dict.items() if k not in db_row and k != "params"
    }

    # Priority overwrite: The calculated payload values (db_row) should overwrite raw input,
    # EXCEPT for ID, where we want to ensure we keep the normalized ID.
    merged_dict = {**original_extras, **db_row}

    return payload, merged_dict


def _compute_scoring_features(payload: TaskPayload) -> None:
    """
    Compute derived scores (Drift, Priority) based on the HYDRATED payload.
    """
    # 1. Priority Calculation (if not set)
    if payload.priority == 0:
        # Domain heuristics
        if payload.domain in ("security", "fintech", "compliance"):
            payload.priority = 3

        # Unpacked Check: Risk
        risk = payload.params.get("risk", {})
        if isinstance(risk, dict) and risk.get("is_high_stakes"):
            payload.priority = 5

        # Unpacked Check: Routing Hints
        if payload.params.get("routing", {}).get("hints", {}).get("priority"):
            payload.priority = int(payload.params["routing"]["hints"]["priority"])

    # 2. Drift Score (Complexity Baseline)
    if payload.type == TaskType.GRAPH and payload.drift_score == 0.0:
        # Example: Large top_k implies heavy search
        if payload.graph_config.get("top_k", 0) > 20:
            payload.drift_score = 0.5


def _permissive_load(data: Dict[str, Any], task_id: Any, t_type: str) -> TaskPayload:
    """Fallback loader for malformed inputs to prevent crash loops."""
    # Try to grab ID from anywhere
    tid = str(task_id)
    if not tid or tid == "None":
        tid = str(uuid.uuid4())

    return TaskPayload(
        task_id=tid,
        type=t_type,
        params=data.get("params") or {},
        description=data.get("description") or data.get("prompt") or "",
        domain=data.get("domain"),
    )


# ============================================================================
# 2. DICT & ID NORMALIZATION
# ============================================================================


def normalize_task_dict(task: Any) -> Tuple[Union[uuid.UUID, str], Dict[str, Any]]:
    """
    Normalize a task-like object to a (task_id, task_dict).
    """
    task_dict = convert_task_to_dict(task) or {}

    # Resolve ID: Prioritize 'id', then 'task_id'
    raw_id = task_dict.get("id") or task_dict.get("task_id")
    task_id_str: str
    task_id_value: Union[uuid.UUID, str]

    if raw_id:
        try:
            task_uuid = uuid.UUID(str(raw_id))
            task_id_value = task_uuid
            task_id_str = str(task_uuid)
        except (ValueError, TypeError):
            task_id_str = canonicalize_identifier(raw_id)
            task_id_value = task_id_str
    else:
        task_uuid = uuid.uuid4()
        task_id_value = task_uuid
        task_id_str = str(task_uuid)

    # Ensure both keys exist for compatibility
    task_dict["id"] = task_id_str
    task_dict.setdefault("task_id", task_id_str)

    sync_task_identity(task, task_id_str)
    return task_id_value, task_dict


def convert_task_to_dict(task: Any) -> Dict[str, Any]:
    """Convert task object to dictionary."""
    if isinstance(task, dict):
        return task.copy()
    elif hasattr(task, "model_dump"):  # Pydantic v2
        return task.model_dump()
    elif hasattr(task, "dict"):  # Pydantic v1
        return task.dict()
    elif hasattr(task, "__dict__"):
        return task.__dict__.copy()
    return {}


def canonicalize_identifier(value: Any) -> str:
    """Canonicalize an identifier-like value to a string."""
    if value is None:
        return ""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def sync_task_identity(task_like: Any, task_id: str) -> None:
    """Sync task identity by setting id/task_id on the object."""
    if isinstance(task_like, dict):
        task_like["id"] = task_id
        task_like.setdefault("task_id", task_id)
        return
    for attr in ("id", "task_id"):
        if hasattr(task_like, attr):
            try:
                setattr(task_like, attr, task_id)
            except Exception:
                pass


# ============================================================================
# 3. TYPE NORMALIZATION
# ============================================================================


def normalize_type(task_type: Optional[str]) -> str:
    """
    Normalize common type aliases to canonical TaskType enum values.
    """
    if not task_type:
        return "unknown"

    normalized = str(task_type).strip().lower()

    # 1. Check if valid Enum value
    try:
        return TaskType(normalized).value
    except ValueError:
        pass

    # 2. Alias Mapping
    type_map = {
        # Graph / Memory
        "embed": TaskType.GRAPH.value,
        "rag": TaskType.GRAPH.value,
        "knowledge": TaskType.GRAPH.value,
        "graph_query": TaskType.GRAPH.value,
        "graph_embed": TaskType.GRAPH.value,
        # Action
        "execute": TaskType.ACTION.value,
        "tool": TaskType.ACTION.value,
        "function": TaskType.ACTION.value,
        # Chat
        "conversation": TaskType.CHAT.value,
        "message": TaskType.CHAT.value,
        # Query (Reasoning)
        "search": TaskType.QUERY.value,
        "plan": TaskType.QUERY.value,
        "reasoning": TaskType.QUERY.value,
        "triage": TaskType.QUERY.value,
        "anomaly_triage": TaskType.QUERY.value,
        # Maintenance
        "health": TaskType.MAINTENANCE.value,
        "cron": TaskType.MAINTENANCE.value,
    }

    return type_map.get(normalized, normalized)


def normalize_domain(domain: Optional[str]) -> Optional[str]:
    """Normalize domain to standard taxonomy."""
    if not domain:
        return None
    d = str(domain).strip().lower()

    aliases = {
        "admin": "management",
        "hotel": "hospitality",
        "ops": "operations",
        "f&b": "food_service",
        "finance": "fintech",
        "med": "healthcare",
        "security": "security",
    }
    return aliases.get(d, d)


# ============================================================================
# 4. EXTRACTION, REDACTION & UTILS
# ============================================================================


def redact_sensitive_data(data: Any) -> Any:
    """Redact sensitive keys (password, token, etc) from dicts."""
    if isinstance(data, dict):
        return {
            k: (
                "[REDACTED]"
                if any(s in k.lower() for s in ["password", "token", "secret", "key"])
                else redact_sensitive_data(v)
            )
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    return data


def extract_from_nested(
    data: Dict[str, Any],
    key_paths: List[Tuple[str, ...]],
    value_type: Optional[type] = None,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
) -> Optional[Any]:
    """Unified pattern-based extractor for nested dictionary values."""
    if not isinstance(data, dict) or (max_depth is not None and max_depth <= 0):
        return None

    for path in key_paths:
        curr = data
        for i, key in enumerate(path):
            if not isinstance(curr, dict):
                break
            curr = curr.get(key)
            if curr is None:
                break
            if i == len(path) - 1:
                if value_type is None or isinstance(curr, value_type):
                    return curr
    return None


def extract_dependency_token(
    ref: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    visited: Optional[Set[int]] = None,
) -> Any:
    """Recursively searches through nested structures to find task identifiers."""
    if ref is None or (max_depth is not None and max_depth <= 0):
        return None

    visited = visited or set()
    if id(ref) in visited:
        return None
    visited.add(id(ref))

    try:
        if isinstance(ref, (list, tuple, set)):
            for item in ref:
                res = extract_dependency_token(item, max_depth - 1, visited)
                if res:
                    return res
        elif isinstance(ref, dict):
            for k in ("task_id", "id", "parent_task_id", "child_task_id"):
                if k in ref:
                    res = extract_dependency_token(ref[k], max_depth - 1, visited)
                    if res:
                        return res
        elif hasattr(ref, "__dict__"):
            for k in ("task_id", "id"):
                if hasattr(ref, k):
                    res = extract_dependency_token(
                        getattr(ref, k), max_depth - 1, visited
                    )
                    if res:
                        return res
    finally:
        visited.discard(id(ref))

    # Base case: Primitive that looks like an ID
    if isinstance(ref, str) and len(ref) > 5:
        return ref
    return None


def collect_record_aliases(
    record: Any,
    max_depth: Optional[int] = DEFAULT_RECURSION_DEPTH,
    include_metadata: bool = True,
) -> Set[str]:
    """Collect all possible identifier aliases from a record."""
    aliases: Set[str] = set()

    def _collect(item, d):
        if d <= 0:
            return
        if isinstance(item, dict):
            for k in ("task_id", "id", "child_task_id", "source_task_id"):
                if k in item:
                    aliases.add(canonicalize_identifier(item[k]))
            if include_metadata and "metadata" in item:
                _collect(item["metadata"], d - 1)
        elif hasattr(item, "task_id"):
            aliases.add(canonicalize_identifier(getattr(item, "task_id")))

    _collect(record, max_depth or 5)
    return {a for a in aliases if a}


def resolve_child_task_id(record: Any, fallback_step: Any) -> Any:
    """Extract the task identifier for a persisted subtask."""
    t = extract_dependency_token(record, max_depth=2)
    if t:
        return t
    return extract_dependency_token(fallback_step, max_depth=2)


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {}, set())
