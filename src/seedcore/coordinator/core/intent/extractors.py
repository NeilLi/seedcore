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

        # Only use first step routing if ALL steps have routing AND all have specialization
        # If there are multiple steps and any step (other than first) has required_specialization, 
        # let aggregation handle it (required_specialization takes precedence)
        # Otherwise, we should aggregate (handled by _from_aggregation)
        if req_spec or spec:
            # Single step: always use PKG_STEP_EMBEDDED regardless of required_specialization
            if len(steps) == 1:
                return RoutingIntent(
                    specialization=req_spec or spec,
                    skills=routing.get("skills") or {},
                    source=IntentSource.PKG_STEP_EMBEDDED,
                    confidence=IntentConfidence.MEDIUM,
                )
            
            # Multiple steps: check if ANY step (including first) has required_specialization
            # If so, let aggregation handle it to ensure required_specialization takes precedence
            has_required_spec_anywhere = False
            for step in steps:
                task = step.get("task", step)
                if not isinstance(task, dict):
                    continue
                step_routing = task.get("params", {}).get("routing", {})
                if step_routing.get("required_specialization"):
                    has_required_spec_anywhere = True
                    break
            
            if has_required_spec_anywhere:
                # Let aggregation handle required_specialization prioritization
                return None
            
            # Check if all steps have routing with specialization (not required_specialization)
            all_steps_have_specialization = True
            for step in steps:
                task = step.get("task", step)
                if not isinstance(task, dict):
                    all_steps_have_specialization = False
                    break
                step_routing = task.get("params", {}).get("routing", {})
                if not step_routing:
                    all_steps_have_specialization = False
                    break
                # Check if this step has specialization (required_specialization already handled above)
                if not step_routing.get("specialization"):
                    all_steps_have_specialization = False
                    break

            if all_steps_have_specialization:
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
        steps = proto_plan.get("steps") or proto_plan.get("solution_steps") or []
        found_spec = None
        merged_skills = {}
        found_required_spec = None

        for step in steps:
            task = step.get("task", step)
            if not isinstance(task, dict):
                continue

            r = task.get("params", {}).get("routing", {})
            if not r:
                continue

            # Aggregate skills (max intensity wins) - do this for all steps
            for s, val in r.get("skills", {}).items():
                merged_skills[s] = max(merged_skills.get(s, 0.0), float(val))

            # Required spec in any step forces that specialization for the whole plan
            # If we find required_specialization, it takes precedence and we ignore regular specialization
            if r.get("required_specialization"):
                found_required_spec = r["required_specialization"]
                # Clear found_spec since required_specialization takes precedence
                found_spec = None
                # Don't break - continue to aggregate skills from remaining steps
            elif r.get("specialization") and not found_required_spec and not found_spec:
                # Only set found_spec if we haven't found a required_specialization yet
                found_spec = r["specialization"]

        # Use required_specialization if found, otherwise use first specialization found
        final_spec = found_required_spec or found_spec
        if final_spec:
            return RoutingIntent(
                specialization=final_spec,
                skills=merged_skills,
                source=IntentSource.PKG_AGGREGATED,
                confidence=IntentConfidence.MEDIUM,
            )
        return None
