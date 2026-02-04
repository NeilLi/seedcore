#!/usr/bin/env python3
"""
Intent enrichers: Augment and synthesize routing intent.

This module provides the "Coordinator's Reflex" logic. It can:
1. Synthesize a baseline intent from perception (Eventizer tags/domain).
2. Refine existing PKG intent using semantic history (v_unified_cortex_memory).
3. Map perceived service requirements to agent specializations.
"""

from dataclasses import replace
from typing import Dict, Any, Optional, List
from seedcore.logging_setup import ensure_serve_logger
from seedcore.agents.roles import Specialization
from .model import RoutingIntent, IntentSource, IntentConfidence

logger = ensure_serve_logger("seedcore.coordinator.core.intent.enrichers")

class IntentEnricher:
    """
    Enriches routing intent with perception-based baselines and memory patterns.
    """

    # Mapping perceived 'required_service' attributes to canonical Specializations
    # Note: Removed specializations (HVAC_CONTROLLER, LIGHTING_CONTROLLER, etc.) are now
    # dynamically registered from pkg_subtask_types. Fallback to GENERALIST for unmapped services.
    SERVICE_MAP = {
        "guest_request": Specialization.USER_LIAISON,
        "graph_query": Specialization.GENERALIST,
        # Legacy service mappings fallback to GENERALIST (will be dynamically resolved from pkg_subtask_types)
        "hvac_service": Specialization.GENERALIST,
        "lighting_service": Specialization.GENERALIST,
        "security_service": Specialization.GENERALIST,
        "maintenance_service": Specialization.GENERALIST,
        "robot_service": Specialization.GENERALIST,
    }

    @staticmethod
    def synthesize_baseline(ctx: Any) -> RoutingIntent:
        """
        Generates a baseline intent from Eventizer perception.
        Ensures the Coordinator is 'Never Blind' if PKG provides no hints.
        """
        # 1. Try mapping from Eventizer attributes (System 1)
        service_hint = ctx.attributes.get("required_service")
        spec = IntentEnricher.SERVICE_MAP.get(service_hint)

        # 2. Fallback to Domain/Type heuristics
        if not spec:
            if ctx.domain == "device":
                spec = Specialization.DEVICE_ORCHESTRATOR
            elif ctx.task_type == "chat":
                spec = Specialization.USER_LIAISON
            else:
                # Default fallback - specific specializations will be dynamically resolved from pkg_subtask_types
                spec = Specialization.GENERALIST

        return RoutingIntent(
            specialization=spec.value,
            skills=ctx.attributes.get("required_skills") or {},
            source=IntentSource.COORDINATOR_BASELINE,
            confidence=IntentConfidence.MEDIUM
        )

    @staticmethod
    def enrich(
        intent: RoutingIntent,
        ctx: Any,  # TaskContext
        semantic_context: Optional[List[Dict[str, Any]]] = None,
    ) -> RoutingIntent:
        """
        Refines intent using historical patterns from Unified Memory.
        """
        if not semantic_context:
            return intent

        # HARD CONSTRAINT: If caller provided required_specialization in TaskPayload routing inbox,
        # memory must NEVER override it. (docs/references/task-payload-capabilities.md §5.2)
        try:
            hard_required_spec = (
                getattr(ctx, "params", {}) or {}
            ).get("routing", {}).get("required_specialization")
        except Exception:
            hard_required_spec = None
        if hard_required_spec:
            # We allow confidence boosts when memory matches, but never specialization changes.
            top_memory = semantic_context[0] if semantic_context else None
            historical_spec = (
                top_memory.get("metadata", {}).get("intended_specialization")
                if isinstance(top_memory, dict)
                else None
            )
            if historical_spec and historical_spec == hard_required_spec:
                return replace(intent, confidence=IntentConfidence.HIGH)
            return intent

        # 1. Check for 'Specialization Drift' in memory
        # If history shows a high similarity hit with a different specialization,
        # we suggest an override or adjust confidence.
        top_memory = semantic_context[0] if semantic_context else None
        
        if top_memory and top_memory.get("similarity", 0) > 0.95:
            # High confidence historical match
            historical_spec = top_memory.get("metadata", {}).get("intended_specialization")
            
            if historical_spec:
                if historical_spec != intent.specialization:
                    logger.info(
                        f"[IntentEnricher] Detected historical spec override: "
                        f"{intent.specialization} -> {historical_spec} (sim: {top_memory['similarity']:.2f})"
                    )
                    # Update both specialization and confidence for different spec
                    intent = replace(
                        intent,
                        confidence=IntentConfidence.HIGH,
                        specialization=historical_spec
                    )
                else:
                    # Same specialization but high similarity - boost confidence
                    intent = replace(
                        intent,
                        confidence=IntentConfidence.HIGH
                    )

        return intent