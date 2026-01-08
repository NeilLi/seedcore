#!/usr/bin/env python3
"""
Intent extractors: Extract routing intent from PKG proto_plan.

Architecture:
- PKG is the authoritative source of "Policy Intent" (The 'Why' and 'What').
- Coordinator is the authoritative source of "Execution Intent" (The 'How' and 'Where').
- This module bridges the two by interpreting PKG plans and synthesizing a
  RoutingIntent for the Organism/Router.
"""

from typing import Dict, Any, Optional
from seedcore.logging_setup import ensure_serve_logger
from .model import RoutingIntent, IntentSource, IntentConfidence

logger = ensure_serve_logger("seedcore.coordinator.core.intent.extractors")


class PKGPlanIntentExtractor:
    """
    Stateful-aware extractor for multi-replica Coordinator clusters.

    This class follows a 'Best Effort to Explicit' extraction hierarchy.
    """

    @staticmethod
    def extract(
        proto_plan: Dict[str, Any],
        ctx: Any,  # TaskContext
    ) -> Optional[RoutingIntent]:
        """
        Extract routing intent from PKG proto_plan across three logical phases.
        """
        if not proto_plan:
            return None

        # Phase 1: Explicit Top-Level Policy
        # Check: proto_plan.routing
        intent = PKGPlanIntentExtractor._from_top_level(proto_plan, ctx)
        if intent:
            return intent

        # Phase 2: Implicit Step-Level Policy
        # Check: proto_plan.steps[0].task.params.routing
        intent = PKGPlanIntentExtractor._from_first_step(proto_plan, ctx)
        if intent:
            return intent

        # Phase 3: Aggregated Intent
        # Scans all steps to find a consensus specialization
        return PKGPlanIntentExtractor._from_aggregation(proto_plan, ctx)

    @staticmethod
    def _from_top_level(
        proto_plan: Dict[str, Any], ctx: Any
    ) -> Optional[RoutingIntent]:
        routing = proto_plan.get("routing") or {}
        req_spec = routing.get("required_specialization")
        spec = routing.get("specialization")

        if req_spec or spec:
            return RoutingIntent(
                specialization=req_spec or spec,
                skills=routing.get("skills") or {},
                source=IntentSource.PKG_TOP_LEVEL,
                confidence=IntentConfidence.HIGH,
            )
        return None

    @staticmethod
    def _from_first_step(
        proto_plan: Dict[str, Any], ctx: Any
    ) -> Optional[RoutingIntent]:
        steps = proto_plan.get("steps") or proto_plan.get("solution_steps") or []
        if not steps or not isinstance(steps, list):
            return None

        first_step = steps[0]
        # Dig into the task params routing envelope
        step_task = first_step.get("task", first_step)
        if not isinstance(step_task, dict):
            return None

        routing = step_task.get("params", {}).get("routing", {})
        req_spec = routing.get("required_specialization")
        spec = routing.get("specialization")

        if req_spec or spec:
            return RoutingIntent(
                specialization=req_spec or spec,
                skills=routing.get("skills") or {},
                source=IntentSource.PKG_STEP_EMBEDDED,
                confidence=IntentConfidence.MEDIUM,
            )
        return None

    @staticmethod
    def _from_aggregation(
        proto_plan: Dict[str, Any], ctx: Any
    ) -> Optional[RoutingIntent]:
        steps = proto_plan.get("steps") or []
        found_spec = None
        merged_skills = {}

        for step in steps:
            task = step.get("task", step)
            if not isinstance(task, dict):
                continue

            r = task.get("params", {}).get("routing", {})
            # Required spec in any step forces that specialization for the whole plan
            if r.get("required_specialization"):
                found_spec = r["required_specialization"]
                break
            if r.get("specialization") and not found_spec:
                found_spec = r["specialization"]

            # Aggregate skills (max intensity wins)
            for s, val in r.get("skills", {}).items():
                merged_skills[s] = max(merged_skills.get(s, 0.0), float(val))

        if found_spec:
            return RoutingIntent(
                specialization=found_spec,
                skills=merged_skills,
                source=IntentSource.PKG_AGGREGATED,
                confidence=IntentConfidence.MEDIUM,
            )
        return None
