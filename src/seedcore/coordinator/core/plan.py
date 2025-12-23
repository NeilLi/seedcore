"""
Plan persistence & dependency registration (coordinator.core.plan)

Framework-free, testable helpers for:
- Persisting planner/HGNN/PKG subtasks to a repository
- Registering dependency edges:
    - root -> child
    - parent_subtask -> child_subtask

Design goals
------------
- No imports from service or façade modules.
- Repository methods are injected and may be sync or async.
- Robust to a variety of record/step shapes (dicts or objects) and alias keys.
- Defensive against mismatched ordering between `plan` and `inserted_subtasks`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from ..utils import (
    extract_dependency_token,
    canonicalize_identifier,
    iter_dependency_entries,
    resolve_child_task_id,
    collect_record_aliases,
    collect_step_aliases,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small async utility
# ---------------------------------------------------------------------------


async def _maybe_call(fn, *args, **kwargs):
    """Call sync/async repo functions uniformly."""
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res


async def _try_call_variants(fn, variants: List[tuple]) -> Any:
    """
    Try multiple (args, kwargs) call variants until one works.
    Only falls back on TypeError (signature mismatch).
    """
    last_exc: Optional[Exception] = None
    for args, kwargs in variants:
        try:
            return await _maybe_call(fn, *args, **kwargs)
        except TypeError as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc
    raise TypeError("No call variants provided")


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
    """
    Insert plan subtasks and register dependency edges.

    Expected repo methods (best effort; signature tolerant):
      - insert_subtasks(...)
      - add_dependency(parent_id, child_id)

    `root_db_id`:
      If provided, root->child edges should use DB PK ids (preferred).
      If repo only understands string ids, we fall back gracefully.
    """
    if not plan:
        return []

    if repo is None or not hasattr(repo, "insert_subtasks"):
        logger.debug(
            "GraphTaskRepository missing/unusable; skipping subtask persistence"
        )
        return []

    root_task_id = _read_task_id(task)

    # --- Insert subtasks (signature-tolerant) ---
    try:
        insert_fn = repo.insert_subtasks

        # Try most-likely variants:
        # 1) insert_subtasks(root_db_id, plan)
        # 2) insert_subtasks(root_task_id, plan)
        # 3) insert_subtasks(root_task_id=root_task_id, plan=plan)
        # 4) insert_subtasks(root_db_id=root_db_id, root_task_id=root_task_id, plan=plan)
        variants: List[tuple] = []
        if root_db_id is not None:
            variants.append(((root_db_id, plan), {}))
        variants.append(((root_task_id, plan), {}))
        variants.append(((), {"root_task_id": root_task_id, "plan": plan}))
        if root_db_id is not None:
            variants.append(
                (
                    (),
                    {
                        "root_db_id": root_db_id,
                        "root_task_id": root_task_id,
                        "plan": plan,
                    },
                )
            )

        inserted = await _try_call_variants(insert_fn, variants)

    except Exception as exc:
        logger.warning(
            "[Coordinator] insert_subtasks failed (task=%s): %s",
            root_task_id or "unknown",
            exc,
            exc_info=True,
        )
        return []

    inserted_list = list(inserted or [])
    if not inserted_list:
        return []

    # --- Root → child edges ---
    if root_db_id is not None and hasattr(repo, "add_dependency"):
        await _add_root_dependencies(
            repo=repo,
            root_db_id=root_db_id,
            plan=plan,
            inserted_subtasks=inserted_list,
            root_task_id=root_task_id,
        )

    # --- Inter-subtask edges ---
    try:
        await register_task_dependencies(
            plan=plan, inserted_subtasks=inserted_list, repo=repo
        )
    except Exception as exc:  # defensive
        logger.error(
            "[Coordinator] Failed to register inter-subtask dependencies (task=%s): %s",
            root_task_id or "unknown",
            exc,
            exc_info=True,
        )

    return inserted_list


async def register_task_dependencies(
    *,
    plan: List[Dict[str, Any]],
    inserted_subtasks: Any,
    repo: Any,
) -> None:
    """
    Record dependency edges (parent → child) based on each step's `depends_on`.

    Dependency references may be:
    - numeric index (0-based)
    - step/task ids (strings)
    - objects/dicts with id-like fields (handled by extract_dependency_token)

    The function builds an alias map to resolve diverse references to canonical persisted ids.
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

    # warn-once keys
    warned_invalid: Set[str] = set()
    warned_missing_child: Set[int] = set()

    # -----------------------------------------------------------------------
    # Phase 1: Build alias map from inserted records + step fallbacks
    # -----------------------------------------------------------------------
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

        # Map canonical id
        alias_to_child[child_key] = child_value

        # Map record aliases
        for alias in collect_record_aliases(record):
            if alias:
                alias_to_child[alias] = child_value

        # Map step aliases
        if fallback_step is not None:
            for alias in collect_step_aliases(fallback_step):
                if alias:
                    alias_to_child[alias] = child_value

    if not index_to_child:
        logger.debug(
            "No subtask identifiers resolved; skipping dependency registration"
        )
        return

    edges_added: Set[Tuple[str, str]] = set()

    # -----------------------------------------------------------------------
    # Phase 2: Add edges based on depends_on
    # -----------------------------------------------------------------------
    for idx, step in enumerate(plan_steps):
        dependencies = (
            step.get("depends_on")
            if isinstance(step, dict)
            else getattr(step, "depends_on", None)
        )
        if not dependencies:
            continue

        # Resolve current child
        child_value = index_to_child.get(idx)
        if child_value is None:
            # fallback: alias-based lookup from step aliases
            for alias in collect_step_aliases(step):
                child_value = alias_to_child.get(alias)
                if child_value is not None:
                    break

        if child_value is None:
            if idx not in warned_missing_child:
                logger.warning(
                    "[Coordinator] Skipping dependency recording for step %d: missing child task id",
                    idx,
                )
                warned_missing_child.add(idx)
            continue

        child_key = canonicalize_identifier(child_value)
        if not child_key:
            continue

        for dep_entry in iter_dependency_entries(dependencies):
            dep_token = extract_dependency_token(dep_entry)
            if dep_token is None:
                dep_repr = f"invalid:{repr(dep_entry)}"
                if dep_repr not in warned_invalid:
                    logger.warning(
                        "[Coordinator] Ignoring invalid dependency reference %s for child %s",
                        repr(dep_entry),
                        child_key,
                    )
                    warned_invalid.add(dep_repr)
                continue

            parent_value = _resolve_parent_value(
                dep_token=dep_token,
                index_to_child=index_to_child,
                alias_to_child=alias_to_child,
            )

            if parent_value is None:
                dep_key = (
                    f"missing:{canonicalize_identifier(dep_token) or repr(dep_token)}"
                )
                if dep_key not in warned_invalid:
                    logger.warning(
                        "[Coordinator] Dependency reference %r for child %s does not match any known subtask",
                        dep_entry,
                        child_key,
                    )
                    warned_invalid.add(dep_key)
                continue

            parent_key = canonicalize_identifier(parent_value)
            if not parent_key:
                continue

            # Ensure parent is one of known subtasks
            if parent_key not in known_child_keys:
                unk_key = f"unknown_parent:{parent_key}"
                if unk_key not in warned_invalid:
                    logger.warning(
                        "[Coordinator] Dependency parent %s for child %s is unknown; skipping",
                        parent_key,
                        child_key,
                    )
                    warned_invalid.add(unk_key)
                continue

            if parent_key == child_key:
                logger.warning(
                    "[Coordinator] Skipping self-dependency for task %s", child_key
                )
                continue

            edge_key = (parent_key, child_key)
            if edge_key in edges_added:
                continue

            try:
                await _maybe_call(repo.add_dependency, parent_value, child_value)
            except Exception as exc:
                logger.error(
                    "[Coordinator] Failed to add dependency %s -> %s: %s",
                    parent_key,
                    child_key,
                    exc,
                    exc_info=True,
                )
            else:
                edges_added.add(edge_key)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _add_root_dependencies(
    *,
    repo: Any,
    root_db_id: Any,
    plan: List[Dict[str, Any]],
    inserted_subtasks: List[Any],
    root_task_id: Optional[str],
) -> None:
    """
    Root -> child edges. Uses `root_db_id` as parent.

    If repo expects string ids, this will still work if child ids are strings.
    If child ids are DB ids, this matches DB PK graph semantics.
    """
    if not hasattr(repo, "add_dependency"):
        return

    for idx, record in enumerate(inserted_subtasks):
        fallback_step = plan[idx] if idx < len(plan) else None
        child_value = resolve_child_task_id(record, fallback_step)
        if child_value is None:
            continue
        try:
            await _maybe_call(repo.add_dependency, root_db_id, child_value)
        except Exception as exc:
            logger.error(
                "[Coordinator] Failed to add root dependency %s -> %s (task=%s): %s",
                root_db_id,
                child_value,
                root_task_id or "unknown",
                exc,
                exc_info=True,
            )


def _resolve_parent_value(
    *,
    dep_token: Any,
    index_to_child: Dict[int, Any],
    alias_to_child: Dict[str, Any],
) -> Optional[Any]:
    """
    Resolve a dependency token into a persisted subtask id.
    Supports:
      - int index
      - id-like string
      - int-like string "0"
    """
    # 1) direct numeric index
    if isinstance(dep_token, int):
        return index_to_child.get(dep_token)

    # 2) canonical id / alias
    parent_key = canonicalize_identifier(dep_token)
    if parent_key:
        hit = alias_to_child.get(parent_key)
        if hit is not None:
            return hit

        # 3) integer-like strings
        if parent_key.isdigit():
            try:
                return index_to_child.get(int(parent_key))
            except Exception:
                return None

    return None


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
