"""
Plan persistence & dependency registration (core.plan)

Framework-free, testable helpers for:
- Persisting HGNN plan subtasks to a repository
- Registering dependency edges (root → child, and inter-subtask)

Notes
-----
- No imports from service or façade modules.
- Repository methods are injected and may be sync or async; we use a local
  `_maybe_call` shim to support both.
- Robust to a variety of record/step shapes (dicts or objects) and alias keys.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, Iterable
import asyncio

from .utils import extract_dependency_token, canonicalize_identifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Small utility
# ---------------------------------------------------------------------------
async def _maybe_call(fn, *args, **kwargs):
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def persist_and_register_dependencies(
    *,
    plan: List[Dict[str, Any]],
    repo: Any,
    task: Any,
    root_db_id: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Insert plan subtasks and register dependency edges.

    Parameters
    ----------
    plan : list[dict]
        List of plan steps (each may include `task`, `depends_on`, `organ_id`, etc.)
    repo : Any
        Graph task repository. Expected methods:
          - insert_subtasks(root_task_id, plan) -> list[record]
          - add_dependency(parent_id, child_id) -> None
    task : Any
        Root task object or dict. Must provide an identifier via `id` attribute
        or key. Only used for logging and for `insert_subtasks` root reference.
    root_db_id : Optional[Any]
        Persisted DB id for the root task. If provided, we create parent edges
        from root to each inserted subtask.

    Returns
    -------
    list[dict]
        Repository-returned subtask records (or empty list on failure).
    """
    if not plan:
        return []

    if repo is None or not hasattr(repo, "insert_subtasks"):
        logger.debug("GraphTaskRepository missing or unusable; skipping subtask persistence")
        return []

    root_task_id = _read_task_id(task)

    try:
        inserted = await _maybe_call(repo.insert_subtasks, root_task_id, plan)
    except Exception as exc:
        logger.warning("[Coordinator] insert_subtasks failed for task %s: %s", root_task_id or "unknown", exc)
        return []

    # Root → child edges
    if root_db_id is not None and hasattr(repo, "add_dependency"):
        try:
            for idx, record in enumerate(inserted or []):
                fallback_step = plan[idx] if idx < len(plan) else None
                child_value = resolve_child_task_id(record, fallback_step)
                if child_value is None:
                    continue
                try:
                    await _maybe_call(repo.add_dependency, root_db_id, child_value)
                except Exception as exc:
                    logger.error("[Coordinator] Failed to add root dependency %s -> %s: %s", root_db_id, child_value, exc)
        except Exception as exc:  # pragma: no cover (defensive)
            logger.error("[Coordinator] Failed to register root dependency edges for %s: %s", root_task_id or "unknown", exc)

    # Inter-subtask edges
    try:
        await register_task_dependencies(plan=plan, inserted_subtasks=inserted, repo=repo)
    except Exception as exc:  # pragma: no cover (defensive)
        logger.error("[Coordinator] Failed to register task dependencies for %s: %s", root_task_id or "unknown", exc)

    return inserted or []


async def register_task_dependencies(
    *,
    plan: List[Dict[str, Any]],
    inserted_subtasks: Any,
    repo: Any,
) -> None:
    """Record dependency edges (parent → child) based on `depends_on` fields.

    This builds an alias map so that indices, UUIDs, and step ids can all be
    resolved to the canonical persisted child id.
    """
    if repo is None or not hasattr(repo, "add_dependency"):
        return

    plan_steps = list(plan or [])
    inserted = list(inserted_subtasks or [])
    if not plan_steps or not inserted:
        return

    alias_to_child: Dict[str, Any] = {}
    index_to_child: Dict[int, Any] = {}
    known_child_keys: Set[str] = set()

    # Phase 1: alias map from inserted records (+ step fallbacks)
    for idx, record in enumerate(inserted):
        fallback_step = plan_steps[idx] if idx < len(plan_steps) else None
        child_value = resolve_child_task_id(record, fallback_step)
        if child_value is None:
            continue

        child_key = canonicalize_identifier(child_value)
        if not child_key:
            continue

        index_to_child[idx] = child_value
        known_child_keys.add(child_key)
        alias_to_child[child_key] = child_value

        for alias in collect_record_aliases(record):
            alias_to_child[alias] = child_value
        if fallback_step is not None:
            for alias in collect_step_aliases(fallback_step):
                alias_to_child[alias] = child_value

    if not index_to_child:
        logger.debug("No subtask identifiers resolved; skipping dependency registration")
        return

    invalid_refs: Set[str] = set()
    edges_added: Set[Tuple[str, str]] = set()

    # Phase 2: edges from `depends_on`
    for idx, step in enumerate(plan_steps):
        dependencies = step.get("depends_on") if isinstance(step, dict) else getattr(step, "depends_on", None)
        if not dependencies:
            continue

        # Child resolution for current step
        child_value = index_to_child.get(idx)
        if child_value is None:
            for alias in collect_step_aliases(step):
                child_value = alias_to_child.get(alias)
                if child_value is not None:
                    break
        if child_value is None:
            logger.warning("[Coordinator] Skipping dependency recording for step %d: missing child task ID", idx)
            continue

        child_key = canonicalize_identifier(child_value)

        for dep_entry in iter_dependency_entries(dependencies):
            dep_token = extract_dependency_token(dep_entry)
            if dep_token is None:
                dep_repr = repr(dep_entry)
                if dep_repr not in invalid_refs:
                    logger.warning("[Coordinator] Ignoring invalid dependency reference %s for child %s", dep_repr, child_key)
                    invalid_refs.add(dep_repr)
                continue

            parent_value = None
            # 1) by numeric index
            if isinstance(dep_token, int):
                parent_value = index_to_child.get(dep_token)
            # 2) by canonical alias / id
            if parent_value is None:
                parent_key = canonicalize_identifier(dep_token)
                parent_value = alias_to_child.get(parent_key)
                # 3) handle integer-like strings
                if parent_value is None and parent_key.isdigit():
                    parent_value = index_to_child.get(int(parent_key))

            if parent_value is None:
                dep_key = canonicalize_identifier(dep_token)
                if dep_key not in invalid_refs:
                    logger.warning("[Coordinator] Dependency reference %r for child %s does not match any known subtask", dep_entry, child_key)
                    invalid_refs.add(dep_key)
                continue

            parent_key = canonicalize_identifier(parent_value)
            if parent_key not in known_child_keys:
                if parent_key not in invalid_refs:
                    logger.warning("[Coordinator] Dependency parent %s for child %s is unknown; skipping", parent_key, child_key)
                    invalid_refs.add(parent_key)
                continue

            if parent_key == child_key:
                logger.warning("[Coordinator] Skipping self-dependency for task %s", child_key)
                continue

            edge_key = (parent_key, child_key)
            if edge_key in edges_added:
                continue

            try:
                await _maybe_call(repo.add_dependency, parent_value, child_value)
            except Exception as exc:  # pragma: no cover
                logger.error("[Coordinator] Failed to add dependency %s -> %s: %s", parent_key, child_key, exc)
            else:
                edges_added.add(edge_key)


# ---------------------------------------------------------------------------
# Helpers for aliases and token extraction
# ---------------------------------------------------------------------------

def iter_dependency_entries(dependencies: Any) -> Iterable[Any]:
    """Depth-first iteration over dependency entries that may be nested."""
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
    """Extract the canonical subtask identifier from repository record or step."""
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


def collect_record_aliases(record: Any) -> Set[str]:
    """Collect alias keys from a repository record into canonical strings."""
    aliases: Set[str] = set()

    if isinstance(record, dict):
        aliases.update(collect_aliases_from_mapping(record))
        maybe_task = record.get("task")
        if isinstance(maybe_task, dict):
            aliases.update(collect_aliases_from_mapping(maybe_task))
        maybe_meta = record.get("metadata")
        if isinstance(maybe_meta, dict):
            aliases.update(collect_aliases_from_mapping(maybe_meta))
    else:
        aliases.update(collect_aliases_from_object(record))

    return aliases


def collect_step_aliases(step: Any) -> Set[str]:
    """Collect alias keys from a plan step into canonical strings."""
    aliases: Set[str] = set()

    if isinstance(step, dict):
        aliases.update(collect_aliases_from_mapping(step))
        maybe_task = step.get("task")
        if isinstance(maybe_task, dict):
            aliases.update(collect_aliases_from_mapping(maybe_task))
        maybe_meta = step.get("metadata")
        if isinstance(maybe_meta, dict):
            aliases.update(collect_aliases_from_mapping(maybe_meta))
    else:
        aliases.update(collect_aliases_from_object(step))

    return aliases


def collect_aliases_from_mapping(mapping: Dict[str, Any]) -> Set[str]:
    """Collect aliases from a mapping/dict recursively."""
    aliases: Set[str] = set()
    alias_keys = {"task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id"}

    for key in alias_keys:
        if key in mapping:
            token = extract_dependency_token(mapping[key])
            if token is not None:
                aliases.add(canonicalize_identifier(token))

    for value in mapping.values():
        if isinstance(value, dict):
            aliases.update(collect_aliases_from_mapping(value))

    return aliases


def collect_aliases_from_object(obj: Any) -> Set[str]:
    """Collect aliases from an object; also inspects `task`/`metadata` dict attrs."""
    aliases: Set[str] = set()
    alias_keys = ("task_id", "id", "step_id", "original_task_id", "child_task_id", "source_task_id", "parent_task_id")

    for key in alias_keys:
        if hasattr(obj, key):
            token = extract_dependency_token(getattr(obj, key))
            if token is not None:
                aliases.add(canonicalize_identifier(token))

    for attr in ("task", "metadata"):
        if hasattr(obj, attr):
            value = getattr(obj, attr)
            if isinstance(value, dict):
                aliases.update(collect_aliases_from_mapping(value))

    return aliases


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _read_task_id(task: Any) -> Optional[str]:
    """Best-effort extraction of the root task id (attribute or mapping)."""
    if task is None:
        return None
    if isinstance(task, dict):
        return task.get("id") or task.get("task_id")
    for attr in ("id", "task_id"):
        if hasattr(task, attr):
            try:
                val = getattr(task, attr)
                if val:
                    return str(val)
            except Exception:
                pass
    return None
