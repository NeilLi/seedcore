"""
Summary generator for Coordinator routing decisions.

Synthesizes Perception (Eventizer), Memory (Cortex), and Policy (PKG) signals
into a human-readable narrative explaining routing decisions.

This provides a "Cognitive Audit Trail" that explains why the system made
a specific choice, enabling:
- Auditability: Clear explanation in unified memory
- Trust: Human operators can understand system reasoning
- Learning: Feed summaries back into knowledge graph for pattern learning
"""

from typing import Dict, Any, Optional

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models.cognitive import DecisionKind
from .model import IntentInsight, RoutingIntent, IntentConfidence

logger = ensure_serve_logger("seedcore.coordinator.core.intent.summary")


class SummaryGenerator:
    """
    Synthesizes a human-readable narrative explaining the Coordinator's 
    routing and planning decisions.
    
    This generator taps into the metadata collected throughout the perception
    and reasoning pipeline to provide a "Cognitive Audit Trail" that explains
    **why** the system made a specific choice.
    
    Architecture:
    - Perception (Eventizer): Tags, confidence, signals (x1..x6)
    - Memory (Cortex): Historical grounding, semantic context
    - Policy (PKG): Rules matched, routing hints, proto_plan structure
    """
    
    @staticmethod
    def generate(
        ctx: Any,  # TaskContext - avoiding circular import
        proto_plan: Dict[str, Any],
        intent: RoutingIntent,
        decision_kind: str,
        raw_drift: Optional[float] = None,
        drift_state: Optional[Any] = None,
    ) -> IntentInsight:
        """
        Generate intent insight explaining routing decision.
        
        Args:
            ctx: TaskContext with Eventizer signals and perception data
            proto_plan: PKG-generated proto_plan with policy decisions
            intent: Extracted RoutingIntent
            decision_kind: DecisionKind value ('fast' or 'cognitive')
            raw_drift: Raw drift score from OCPS
            drift_state: OCPS drift state (for escalation details)
        
        Returns:
            IntentInsight with synthesized narrative and metadata
        """
        # 1. Perception Logic (Eventizer)
        perception_trace = SummaryGenerator._build_perception_trace(ctx)
        
        # 2. Memory Logic (Cortex/Unified Memory)
        memory_trace, memory_count = SummaryGenerator._build_memory_trace(proto_plan)
        
        # 3. Policy Logic (PKG)
        policy_trace, policy_rules = SummaryGenerator._build_policy_trace(proto_plan, intent)
        
        # 4. Escalation Logic (OCPS)
        is_escalated = decision_kind == DecisionKind.COGNITIVE.value
        escalation_trace = SummaryGenerator._build_escalation_trace(
            is_escalated, raw_drift, drift_state
        )
        
        # 5. Synthesize Narrative
        path_desc = (
            "Escalated to System 2 (Cognitive)" if is_escalated 
            else "Processed via System 1 (Reflex)"
        )
        
        narrative_parts = [
            path_desc,
            perception_trace,
            policy_trace,
        ]
        
        if memory_trace:
            narrative_parts.append(memory_trace)
        
        if escalation_trace:
            narrative_parts.append(escalation_trace)
        
        # Add routing decision
        specialization = intent.specialization or "Generalist"
        narrative_parts.append(f"Routed to {specialization} specialization.")
        
        narrative = " ".join(narrative_parts)
        
        # 6. Determine Primary Driver
        primary_driver = SummaryGenerator._determine_primary_driver(
            intent, memory_count, len(policy_rules), ctx
        )
        
        # 7. Calculate Confidence Score
        confidence_score = SummaryGenerator._calculate_confidence_score(
            intent, memory_count, is_escalated
        )
        
        # 8. Extract Perception Signals
        perception_signals = SummaryGenerator._extract_perception_signals(ctx)
        
        return IntentInsight(
            summary=narrative,
            primary_driver=primary_driver,
            confidence_score=confidence_score,
            grounding_hits=memory_count,
            is_escalated=is_escalated,
            perception_signals=perception_signals,
            policy_rules=policy_rules,
            memory_context=memory_count,
        )
    
    @staticmethod
    def _build_perception_trace(ctx: Any) -> str:
        """Build perception trace from Eventizer data."""
        tags = list(ctx.tags) if ctx.tags else []
        
        # Format tags nicely
        if tags:
            tags_str = ", ".join(sorted(tags)[:5])  # Limit to 5 tags
            if len(tags) > 5:
                tags_str += f" (+{len(tags) - 5} more)"
        else:
            tags_str = "general"
        
        # Get confidence
        confidence_val = ctx.confidence.get("overall_confidence", 0.0) if ctx.confidence else 0.0
        if isinstance(confidence_val, (int, float)):
            confidence_pct = f"{confidence_val:.1%}" if confidence_val < 1.0 else f"{confidence_val * 100:.1f}%"
        else:
            confidence_pct = "unknown"
        
        # Check for multimodal context
        multimodal_hint = ""
        if ctx.params and isinstance(ctx.params, dict):
            multimodal = ctx.params.get("multimodal", {})
            if multimodal and isinstance(multimodal, dict):
                source = multimodal.get("source", "")
                if source == "voice":
                    multimodal_hint = " (voice command)"
                elif source == "vision":
                    multimodal_hint = " (vision detection)"
        
        return f"Detected {tags_str} intent{multimodal_hint} with {confidence_pct} confidence."
    
    @staticmethod
    def _build_memory_trace(proto_plan: Dict[str, Any]) -> tuple:
        """Build memory trace from proto_plan semantic context."""
        # Check for semantic context in proto_plan
        # This could be in various places depending on PKG implementation
        memory_count = 0
        
        # Check for semantic_context field
        if "semantic_context" in proto_plan:
            context_items = proto_plan["semantic_context"]
            if isinstance(context_items, list):
                memory_count = len(context_items)
        
        # Check for memory_hits or similar fields
        if "memory_hits" in proto_plan:
            memory_count = max(memory_count, proto_plan.get("memory_hits", 0))
        
        # Check metadata for memory references
        meta = proto_plan.get("metadata", {})
        if isinstance(meta, dict):
            memory_count = max(
                memory_count,
                meta.get("semantic_context_count", 0),
                meta.get("memory_hits", 0),
            )
        
        if memory_count > 0:
            return f"Grounded by {memory_count} historical incident(s).", memory_count
        
        return "", 0
    
    @staticmethod
    def _build_policy_trace(
        proto_plan: Dict[str, Any], intent: RoutingIntent
    ) -> tuple:
        """Build policy trace from PKG proto_plan."""
        rules_matched = []
        
        # Extract rules from proto_plan
        if "rules" in proto_plan:
            rules = proto_plan["rules"]
            if isinstance(rules, list):
                for rule in rules:
                    if isinstance(rule, dict):
                        rule_name = rule.get("rule_name") or rule.get("name")
                        if rule_name:
                            rules_matched.append(str(rule_name))
        
        # Check metadata for rules
        meta = proto_plan.get("metadata", {})
        if isinstance(meta, dict):
            meta_rules = meta.get("rules_matched", [])
            if isinstance(meta_rules, list):
                rules_matched.extend([str(r) for r in meta_rules if r])
        
        # Deduplicate
        rules_matched = list(dict.fromkeys(rules_matched))  # Preserves order
        
        if rules_matched:
            rules_str = ", ".join(rules_matched[:3])  # Limit to 3 rules
            if len(rules_matched) > 3:
                rules_str += f" (+{len(rules_matched) - 3} more)"
            return f"Policy applied: {rules_str}.", rules_matched
        
        # Fallback: Use intent source to infer policy
        if intent.is_explicit():
            return "Policy applied: PKG routing hints.", []
        
        return "Used default routing policy.", []
    
    @staticmethod
    def _build_escalation_trace(
        is_escalated: bool,
        raw_drift: Optional[float],
        drift_state: Optional[Any],
    ) -> str:
        """Build escalation trace from OCPS data."""
        if not is_escalated:
            return ""
        
        parts = []
        
        if raw_drift is not None:
            parts.append(f"high semantic drift (x2={raw_drift:.2f})")
        
        if drift_state:
            severity = getattr(drift_state, "severity", None)
            if severity:
                parts.append(f"severity={severity}")
            
            cusum_score = getattr(drift_state, "score", None)
            if cusum_score is not None:
                parts.append(f"CUSUM={cusum_score:.2f}")
        
        if parts:
            return f"Escalation triggered by: {', '.join(parts)}."
        
        return "Escalated to System 2 (Cognitive)."
    
    @staticmethod
    def _determine_primary_driver(
        intent: RoutingIntent,
        memory_count: int,
        policy_rules_count: int,
        ctx: Any,
    ) -> str:
        """Determine the primary driver of the routing decision."""
        # Priority: Policy > Memory > Perception
        
        if intent.is_explicit() or policy_rules_count > 0:
            return "policy"
        
        if memory_count > 0:
            return "memory"
        
        # Check if perception signals are strong
        if ctx.signals:
            x2_drift = ctx.signals.get("x2_semantic_drift", 0.0) or ctx.signals.get("x2_ocps_drift", 0.0)
            if x2_drift and float(x2_drift) > 0.5:
                return "perception"
        
        return "policy"  # Default to policy
    
    @staticmethod
    def _calculate_confidence_score(
        intent: RoutingIntent,
        memory_count: int,
        is_escalated: bool,
    ) -> float:
        """Calculate overall confidence score."""
        # Base confidence from intent source
        base_confidence = {
            IntentConfidence.HIGH: 0.9,
            IntentConfidence.MEDIUM: 0.7,
            IntentConfidence.LOW: 0.5,
            IntentConfidence.MINIMAL: 0.3,
        }.get(intent.confidence, 0.5)
        
        # Boost confidence if grounded by memory
        if memory_count > 0:
            memory_boost = min(0.1, memory_count * 0.02)  # Max 0.1 boost
            base_confidence = min(1.0, base_confidence + memory_boost)
        
        # Slight reduction if escalated (uncertainty)
        if is_escalated:
            base_confidence = max(0.3, base_confidence - 0.1)
        
        return round(base_confidence, 2)
    
    @staticmethod
    def _extract_perception_signals(ctx: Any) -> Dict[str, float]:
        """Extract perception signals (x1..x6) from TaskContext."""
        signals = {}
        
        if ctx.signals and isinstance(ctx.signals, dict):
            # Extract x1..x6 signals
            signal_names = [
                "x1_cache_novelty",
                "x2_semantic_drift",
                "x3_multimodal_anomaly",
                "x4_graph_context_drift",
                "x5_logic_uncertainty",
                "x6_cost_risk",
            ]
            
            # Also check legacy names
            legacy_map = {
                "x2_ocps_drift": "x2_semantic_drift",
                "x3_ood_novelty": "x3_multimodal_anomaly",
                "x4_graph_novelty": "x4_graph_context_drift",
                "x5_dep_uncertainty": "x5_logic_uncertainty",
            }
            
            for name in signal_names:
                value = ctx.signals.get(name)
                if value is not None:
                    try:
                        signals[name] = float(value)
                    except (ValueError, TypeError):
                        pass
            
            # Check legacy names
            for legacy_name, canonical_name in legacy_map.items():
                if canonical_name not in signals:
                    value = ctx.signals.get(legacy_name)
                    if value is not None:
                        try:
                            signals[canonical_name] = float(value)
                        except (ValueError, TypeError):
                            pass
        
        return signals
