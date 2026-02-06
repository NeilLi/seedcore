"""
Plan Executor: converts pure planner DAG into executable TaskPayloads.

Responsibilities:
- Consume a routing-free plan (explicit DAG or implicit steps)
- Resolve routing/tooling hints (via provided resolver)
- Materialize executable TaskPayloads
- Execute respecting dependencies + conditions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models.task_payload import TaskPayload
from seedcore.coordinator.core.intent import RoutingIntent
from seedcore.coordinator.core.condition_registry import (
    ConditionRegistry,
    default_condition_registry,
)

logger = ensure_serve_logger("seedcore.coordinator.core.plan_executor", level="DEBUG")


class StepState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class ExecutionStep:
    id: str
    raw: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    state: StepState = StepState.PENDING
    result: Optional[Any] = None


class PlanExecutionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"
    PARTIAL = "partial"


RoutingResolver = Callable[
    [ExecutionStep, TaskPayload, Optional[RoutingIntent]],
    Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]],
]

ConditionEvaluator = Callable[[ExecutionStep, TaskPayload], bool]

BuildStepPayloadFn = Callable[
    [TaskPayload, Dict[str, Any], int, Optional[str], Optional[RoutingIntent]],
    Tuple[Dict[str, Any], str],
]


class PlanExecutor:
    def __init__(
        self,
        *,
        organism_execute: Callable[[str, dict[str, Any], float, str], Any],
        build_step_payload: Optional[BuildStepPayloadFn] = None,
        routing_resolver: Optional[RoutingResolver] = None,
        condition_evaluator: Optional[ConditionEvaluator] = None,
        condition_registry: Optional[ConditionRegistry] = None,
        logger_override=None,
    ) -> None:
        self.organism_execute = organism_execute
        self.build_step_payload = build_step_payload
        self.routing_resolver = routing_resolver
        self.condition_evaluator = condition_evaluator
        self.condition_registry = condition_registry or default_condition_registry
        self.logger = logger_override or logger

    def normalize_plan(
        self, plan: Dict[str, Any] | List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize explicit or implicit DAG to implicit steps with depends_on.
        """
        if isinstance(plan, dict) and "nodes" in plan:
            nodes = plan.get("nodes") or []
            edges = plan.get("edges") or []
            deps: Dict[str, List[str]] = {}
            for edge in edges:
                if (
                    isinstance(edge, (list, tuple))
                    and len(edge) == 2
                    and isinstance(edge[0], str)
                    and isinstance(edge[1], str)
                ):
                    deps.setdefault(edge[1], []).append(edge[0])
            normalized: List[Dict[str, Any]] = []
            for node in nodes:
                if not isinstance(node, dict) or "id" not in node:
                    continue
                step_id = str(node["id"])
                normalized.append(
                    {
                        "id": step_id,
                        "type": node.get("type") or "action",
                        "depends_on": deps.get(step_id, []),
                    }
                )
            return normalized

        if isinstance(plan, list):
            normalized_steps: List[Dict[str, Any]] = []
            for idx, step in enumerate(plan):
                if not isinstance(step, dict):
                    continue
                step_id = step.get("id") or f"step_{idx}"
                depends_on = step.get("depends_on", [])
                if depends_on is None:
                    depends_on = []
                if not isinstance(depends_on, list):
                    depends_on = [depends_on]
                normalized_steps.append(
                    {
                        "id": str(step_id),
                        "type": step.get("type") or "action",
                        "depends_on": depends_on,
                    }
                )
            return normalized_steps

        return []

    def _build_execution_graph(
        self, plan: Dict[str, Any] | List[Dict[str, Any]]
    ) -> Tuple[Dict[str, ExecutionStep], List[Tuple[str, str]]]:
        steps: Dict[str, ExecutionStep] = {}
        edges: List[Tuple[str, str]] = []

        if isinstance(plan, dict) and "nodes" in plan:
            for node in plan.get("nodes") or []:
                if not isinstance(node, dict) or "id" not in node:
                    continue
                step_id = str(node["id"])
                steps[step_id] = ExecutionStep(
                    id=step_id,
                    raw=node,
                    depends_on=[],
                )
            for edge in plan.get("edges") or []:
                if (
                    isinstance(edge, (list, tuple))
                    and len(edge) == 2
                    and isinstance(edge[0], str)
                    and isinstance(edge[1], str)
                ):
                    edges.append((edge[0], edge[1]))

        elif isinstance(plan, list):
            for idx, step in enumerate(plan):
                if not isinstance(step, dict):
                    continue
                step_id = str(step.get("id") or f"step_{idx}")
                depends_on = step.get("depends_on", [])
                if depends_on is None:
                    depends_on = []
                if not isinstance(depends_on, list):
                    depends_on = [depends_on]
                steps[step_id] = ExecutionStep(
                    id=step_id,
                    raw=step,
                    depends_on=[str(d) for d in depends_on],
                )
            edges = [(d, s.id) for s in steps.values() for d in s.depends_on]

        # Attach dependencies for explicit DAG
        if edges and steps:
            for from_id, to_id in edges:
                if to_id in steps:
                    steps[to_id].depends_on.append(from_id)

        return steps, edges

    def _is_condition_step(self, step: ExecutionStep) -> bool:
        step_type = str(step.raw.get("type") or "").lower()
        return step_type in {"condition", "event", "wait"}

    def _update_readiness(self, steps: Dict[str, ExecutionStep]) -> None:
        for step in steps.values():
            if step.state != StepState.PENDING:
                continue
            if all(
                steps[dep].state == StepState.DONE
                for dep in step.depends_on
                if dep in steps
            ):
                step.state = StepState.READY

    def _deps_satisfied(self, step: ExecutionStep, steps: Dict[str, ExecutionStep]) -> bool:
        return all(
            steps[dep].state == StepState.DONE
            for dep in step.depends_on
            if dep in steps
        )

    def _resolve_routing(
        self,
        step: ExecutionStep,
        parent_task: TaskPayload,
        routing_intent: Optional[RoutingIntent],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
        if self.routing_resolver:
            return self.routing_resolver(step, parent_task, routing_intent)
        if routing_intent:
            return routing_intent.to_routing_params(), [], routing_intent.organ_hint
        return {}, [], None

    def _materialize_task(
        self,
        step: ExecutionStep,
        parent_task: TaskPayload,
        idx: int,
        cid: Optional[str],
        routing_intent: Optional[RoutingIntent],
    ) -> Tuple[Dict[str, Any], str]:
        routing, tool_calls, organ_hint = self._resolve_routing(
            step, parent_task, routing_intent
        )
        step_payload = {
            "id": step.id,
            "type": step.raw.get("type") or "action",
            "params": {
                "routing": routing,
                "tool_calls": tool_calls,
            },
        }

        if self.build_step_payload:
            built, hint = self.build_step_payload(
                parent_task,
                step_payload,
                idx,
                cid,
                routing_intent,
            )
            if organ_hint:
                hint = organ_hint
            return built, hint

        return step_payload, organ_hint or "organism"

    async def execute_plan(
        self,
        *,
        plan: Dict[str, Any] | List[Dict[str, Any]],
        parent_task: TaskPayload,
        timeout_s: float,
        cid: str,
        routing_intent: Optional[RoutingIntent] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], PlanExecutionStatus]:
        # Hard entry log to confirm PlanExecutor invocation and plan shape
        plan_kind = "dict" if isinstance(plan, dict) else "list" if isinstance(plan, list) else type(plan).__name__
        plan_nodes = (
            len(plan.get("nodes") or []) if isinstance(plan, dict) else len(plan) if isinstance(plan, list) else 0
        )
        plan_edges = len(plan.get("edges") or []) if isinstance(plan, dict) else 0
        self.logger.info(
            "[PlanExecutor] execute_plan: task_id=%s plan_kind=%s nodes=%s edges=%s timeout_s=%.2f",
            parent_task.task_id,
            plan_kind,
            plan_nodes,
            plan_edges,
            float(timeout_s),
        )
        steps, _edges = self._build_execution_graph(plan)
        normalized_steps = self.normalize_plan(plan)
        if not steps:
            self.logger.warning(
                "[PlanExecutor] Empty plan: no steps to execute (task_id=%s)",
                parent_task.task_id,
            )
            return [], normalized_steps, PlanExecutionStatus.COMPLETED

        step_ids = list(steps.keys())
        results: List[Dict[str, Any]] = []

        while True:
            self._update_readiness(steps)

            runnable = [s for s in step_ids if steps[s].state == StepState.READY]
            if not runnable:
                # No runnable steps
                pending_conditions = [
                    s
                    for s in steps.values()
                    if self._is_condition_step(s)
                    and s.state in (StepState.PENDING, StepState.READY)
                    and self._deps_satisfied(s, steps)
                ]
                if pending_conditions:
                    # If condition steps exist but are not satisfied, block
                    for step in pending_conditions:
                        # Register condition lifecycle (pauses, not failure)
                        condition_payload = (
                            step.raw.get("condition")
                            if isinstance(step.raw, dict)
                            else None
                        ) or {}
                        self.condition_registry.register(
                            task_id=parent_task.task_id,
                            step_id=step.id,
                            condition=condition_payload,
                            resume_after=[
                                s.id
                                for s in steps.values()
                                if step.id in s.depends_on
                            ],
                            timeout_s=float(timeout_s) if timeout_s else None,
                        )
                        step.state = StepState.BLOCKED
                        self.logger.info(
                            "[PlanExecutor] Step blocked (condition_unsatisfied): id=%s type=%s deps=%s",
                            step.id,
                            step.raw.get("type"),
                            step.depends_on,
                        )
                    results.append(
                        {
                            "step": None,
                            "success": True,
                            "result": {
                                "status": "waiting",
                                "error": "condition_unsatisfied",
                                "blocked": [s.id for s in pending_conditions],
                            },
                        }
                    )
                    return results, normalized_steps, PlanExecutionStatus.WAITING
                else:
                    # dependency deadlock
                    missing = {
                        s.id: [d for d in s.depends_on if steps[d].state != StepState.DONE]
                        for s in steps.values()
                        if s.state not in (StepState.DONE, StepState.FAILED)
                    }
                    self.logger.error(
                        "[PlanExecutor] Dependency deadlock: missing=%s",
                        missing,
                    )
                    results.append(
                        {
                            "step": None,
                            "success": False,
                            "result": {
                                "error": "dependency_deadlock",
                                "missing": missing,
                            },
                        }
                    )
                return results, normalized_steps, PlanExecutionStatus.FAILED

            # deterministic: pick first runnable id
            step_id = runnable[0]
            step = steps[step_id]
            self.logger.info(
                "[PlanExecutor] Step ready: id=%s type=%s deps=%s",
                step.id,
                step.raw.get("type"),
                step.depends_on,
            )

            # Handle condition steps (no organism call)
            if self._is_condition_step(step):
                # If already satisfied (event-driven resumption), proceed
                if self.condition_registry.is_satisfied(parent_task.task_id, step.id):
                    step.state = StepState.DONE
                    results.append(
                        {
                            "step": step_id,
                            "success": True,
                            "result": {"condition": "satisfied"},
                        }
                    )
                    continue
                if self.condition_evaluator and self.condition_evaluator(step, parent_task):
                    step.state = StepState.DONE
                    results.append(
                        {
                            "step": step_id,
                            "success": True,
                            "result": {"condition": "satisfied"},
                        }
                    )
                    continue

                # No evaluator or condition not satisfied: block to avoid infinite loop
                condition_payload = (
                    step.raw.get("condition") if isinstance(step.raw, dict) else None
                ) or {}
                self.condition_registry.register(
                    task_id=parent_task.task_id,
                    step_id=step.id,
                    condition=condition_payload,
                    resume_after=[
                        s.id for s in steps.values() if step.id in s.depends_on
                    ],
                    timeout_s=float(timeout_s) if timeout_s else None,
                )
                step.state = StepState.BLOCKED
                self.logger.info(
                    "[PlanExecutor] Step blocked (condition_unsatisfied): id=%s type=%s deps=%s",
                    step.id,
                    step.raw.get("type"),
                    step.depends_on,
                )
                results.append(
                    {
                        "step": step_id,
                        "success": True,
                        "result": {
                            "status": "waiting",
                            "error": "condition_unsatisfied",
                            "blocked": step_id,
                        },
                    }
                )
                return results, normalized_steps, PlanExecutionStatus.WAITING

            step.state = StepState.RUNNING
            step_payload, organ_hint = self._materialize_task(
                step, parent_task, step_ids.index(step_id), cid, routing_intent
            )
            # Child task materialization checks
            if not isinstance(step_payload, dict):
                self.logger.error(
                    "[PlanExecutor] Child task payload is not a dict (step_id=%s, type=%s)",
                    step.id,
                    step.raw.get("type"),
                )
            else:
                if "type" not in step_payload:
                    self.logger.warning(
                        "[PlanExecutor] Child task missing type (step_id=%s)",
                        step.id,
                    )
                if "params" not in step_payload:
                    self.logger.warning(
                        "[PlanExecutor] Child task missing params (step_id=%s)",
                        step.id,
                    )
            self.logger.info(
                "[PlanExecutor] Dispatching child task: step_id=%s organ_hint=%s task_id=%s",
                step.id,
                organ_hint or "organism",
                step_payload.get("task_id") if isinstance(step_payload, dict) else None,
            )

            step_res = await self.organism_execute(
                organ_hint or "organism",
                step_payload,
                timeout_s,
                cid,
            )

            ok = bool(step_res.get("success"))
            self.logger.info(
                "[PlanExecutor] Step result: step_id=%s success=%s",
                step.id,
                ok,
            )
            results.append({"step": step_id, "success": ok, "result": step_res})
            step.state = StepState.DONE if ok else StepState.FAILED

            if not ok:
                return results, normalized_steps, PlanExecutionStatus.FAILED

            if all(s.state == StepState.DONE for s in steps.values()):
                return results, normalized_steps, PlanExecutionStatus.COMPLETED

        # Fallback (should not reach here)
        return results, normalized_steps, PlanExecutionStatus.PARTIAL
