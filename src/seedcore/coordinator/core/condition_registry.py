"""
Condition Registry: in-memory lifecycle tracking for blocked plan conditions.

This is intentionally minimal and evolvable:
- Tracks pending/satisfied/expired condition steps per root task.
- Provides a wake-up payload for event-driven resumption.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ConditionRecord:
    task_id: str
    step_id: str
    condition: Dict[str, Any]
    resume_after: List[str]
    created_at: float
    timeout_at: Optional[float]
    status: str  # "pending" | "satisfied" | "expired"
    payload: Optional[Dict[str, Any]] = None


class ConditionRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_task: Dict[str, Dict[str, ConditionRecord]] = {}

    def register(
        self,
        *,
        task_id: str,
        step_id: str,
        condition: Dict[str, Any],
        resume_after: List[str],
        timeout_s: Optional[float] = None,
    ) -> None:
        now = time.time()
        timeout_at = (now + float(timeout_s)) if timeout_s else None
        record = ConditionRecord(
            task_id=task_id,
            step_id=step_id,
            condition=condition,
            resume_after=list(resume_after or []),
            created_at=now,
            timeout_at=timeout_at,
            status="pending",
        )
        with self._lock:
            self._by_task.setdefault(task_id, {})[step_id] = record

    def mark_satisfied(
        self,
        *,
        task_id: str,
        step_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[ConditionRecord]:
        with self._lock:
            record = self._by_task.get(task_id, {}).get(step_id)
            if not record:
                return None
            record.status = "satisfied"
            record.payload = payload
            return record

    def is_satisfied(self, task_id: str, step_id: str) -> bool:
        record = self._get(task_id, step_id)
        return bool(record and record.status == "satisfied")

    def pending_for_task(self, task_id: str) -> List[str]:
        with self._lock:
            records = list(self._by_task.get(task_id, {}).values())
        return [r.step_id for r in records if r.status == "pending"]

    def get_record(self, task_id: str, step_id: str) -> Optional[ConditionRecord]:
        return self._get(task_id, step_id)

    def _get(self, task_id: str, step_id: str) -> Optional[ConditionRecord]:
        with self._lock:
            record = self._by_task.get(task_id, {}).get(step_id)
        if record and record.timeout_at and time.time() > record.timeout_at:
            record.status = "expired"
        return record


# Default in-memory registry (safe for single-process deployments).
default_condition_registry = ConditionRegistry()
