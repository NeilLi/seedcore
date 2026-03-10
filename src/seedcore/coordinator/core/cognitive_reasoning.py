from __future__ import annotations

from typing import Any, Dict, Optional

from seedcore.models.task_payload import TaskPayload

from .intent import IntentConfidence, IntentSource, RoutingIntent


class CoordinatorCognitiveReasoner:
    """AI-first coordinator helpers backed by cognitive advisory contracts."""

    @staticmethod
    def extract_advisory_payload(task: TaskPayload | Dict[str, Any]) -> Dict[str, Any]:
        params = task.params if isinstance(task, TaskPayload) else (task.get("params") or {})
        if not isinstance(params, dict):
            return {}

        cognitive = params.get("cognitive") or {}
        if not isinstance(cognitive, dict):
            return {}

        advisory = cognitive.get("advisory_contract") or {}
        return advisory if isinstance(advisory, dict) else {}

    @staticmethod
    def extract_advisory_metadata(task: TaskPayload | Dict[str, Any]) -> Dict[str, Any]:
        params = task.params if isinstance(task, TaskPayload) else (task.get("params") or {})
        if not isinstance(params, dict):
            return {}

        cognitive = params.get("cognitive") or {}
        if not isinstance(cognitive, dict):
            return {}

        metadata = cognitive.get("advisory_metadata") or {}
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def merge_advisory_into_task(
        cls,
        task_payload: Dict[str, Any],
        advisory_response: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(task_payload or {})
        params = dict(merged.get("params") or {})
        cognitive = dict(params.get("cognitive") or {})
        routing = dict(params.get("routing") or {})
        advisory = advisory_response.get("advisory")
        metadata = advisory_response.get("metadata")

        if not isinstance(advisory, dict):
            return merged

        cognitive["advisory_contract"] = advisory
        if isinstance(metadata, dict) and metadata:
            cognitive["advisory_metadata"] = metadata

        if advisory.get("kind") == "risk_summary":
            recommended_action = advisory.get("recommended_action")
            if recommended_action in {"step_up_approval", "quarantine"}:
                cognitive["force_deep_reasoning"] = True

        proposed_routing = advisory.get("proposed_routing") or {}
        if isinstance(proposed_routing, dict):
            if not routing.get("required_specialization") and not routing.get("specialization"):
                advisory_spec = (
                    proposed_routing.get("specialization")
                    or proposed_routing.get("required_specialization")
                )
                if isinstance(advisory_spec, str) and advisory_spec.strip():
                    routing["specialization"] = advisory_spec.strip()

            if not routing.get("skills") and isinstance(proposed_routing.get("skills"), dict):
                routing["skills"] = proposed_routing.get("skills") or {}

            if not routing.get("tools") and isinstance(proposed_routing.get("tools"), list):
                routing["tools"] = proposed_routing.get("tools") or []

        params["cognitive"] = cognitive
        if routing:
            params["routing"] = routing
        merged["params"] = params
        return merged

    @classmethod
    def derive_decision_hints(
        cls,
        task: TaskPayload | Dict[str, Any],
    ) -> Dict[str, bool]:
        advisory = cls.extract_advisory_payload(task)
        if not advisory:
            return {
                "requires_planning": False,
                "has_conditional_logic": False,
                "has_multiple_actions": False,
                "force_cognitive": False,
            }

        ambiguity = advisory.get("ambiguity") or {}
        ambiguity_needs_clarification = bool(
            isinstance(ambiguity, dict) and ambiguity.get("needs_clarification")
        )

        proto_plan = advisory.get("proto_plan") or {}
        steps = proto_plan.get("steps") if isinstance(proto_plan, dict) else None
        step_count = len(steps) if isinstance(steps, list) else 0

        interpretation = advisory.get("structured_interpretation") or {}
        has_conditional_logic = bool(
            isinstance(interpretation, dict)
            and interpretation.get("has_conditional_logic") is True
        )
        has_multiple_actions = bool(
            isinstance(interpretation, dict)
            and interpretation.get("has_multiple_actions") is True
        )

        kind = advisory.get("kind")
        recommended_action = advisory.get("recommended_action")
        risk_level = advisory.get("risk_level")

        force_cognitive = False
        if kind == "risk_summary" and (
            recommended_action in {"step_up_approval", "quarantine"}
            or risk_level in {"high", "critical"}
        ):
            force_cognitive = True

        requires_planning = step_count > 1 or force_cognitive
        if ambiguity_needs_clarification and step_count > 0:
            requires_planning = True

        return {
            "requires_planning": requires_planning,
            "has_conditional_logic": has_conditional_logic,
            "has_multiple_actions": has_multiple_actions,
            "force_cognitive": force_cognitive,
        }

    @classmethod
    def derive_policy_signal_overrides(
        cls,
        task: TaskPayload | Dict[str, Any],
    ) -> Dict[str, Any]:
        advisory = cls.extract_advisory_payload(task)
        if not advisory:
            return {}

        ambiguity = advisory.get("ambiguity") or {}
        ambiguity_score = (
            float(ambiguity.get("score"))
            if isinstance(ambiguity, dict)
            and isinstance(ambiguity.get("score"), (int, float))
            else 0.0
        )
        risk_score = (
            float(advisory.get("risk_score"))
            if isinstance(advisory.get("risk_score"), (int, float))
            else 0.0
        )

        interpretation = advisory.get("structured_interpretation") or {}
        if not isinstance(interpretation, dict):
            interpretation = {}

        proto_plan = advisory.get("proto_plan") or {}
        proto_steps = proto_plan.get("steps") if isinstance(proto_plan, dict) else []
        step_count = interpretation.get("step_count")
        if not isinstance(step_count, int):
            step_count = len(proto_steps) if isinstance(proto_steps, list) else 0

        has_conditional_logic = bool(interpretation.get("has_conditional_logic"))
        has_multiple_actions = bool(interpretation.get("has_multiple_actions")) or step_count > 1

        decision_hints = cls.derive_decision_hints(task)

        return {
            "advisory_available": True,
            "ambiguity_score": max(0.0, min(1.0, ambiguity_score)),
            "risk_score": max(0.0, min(1.0, risk_score)),
            "step_count": max(0, int(step_count)),
            "has_conditional_logic": has_conditional_logic,
            "has_multiple_actions": has_multiple_actions,
            "requires_planning": decision_hints["requires_planning"],
            "force_cognitive": decision_hints["force_cognitive"],
            "kind": advisory.get("kind"),
            "recommended_action": advisory.get("recommended_action"),
            "risk_level": advisory.get("risk_level"),
        }

    @classmethod
    def derive_drift_score(
        cls,
        task: TaskPayload | Dict[str, Any],
    ) -> Optional[float]:
        policy = cls.derive_policy_signal_overrides(task)
        if not policy:
            return None

        drift = max(
            float(policy.get("ambiguity_score") or 0.0),
            float(policy.get("risk_score") or 0.0),
        )
        if policy.get("requires_planning"):
            drift = max(drift, 0.55)
        if policy.get("has_multiple_actions"):
            drift = max(drift, 0.65)
        if policy.get("has_conditional_logic"):
            drift = max(drift, 0.75)
        if policy.get("force_cognitive"):
            drift = max(drift, 0.8)

        return round(max(0.0, min(1.0, drift)), 3)

    @classmethod
    def advisory_to_routing_intent(
        cls,
        task: TaskPayload | Dict[str, Any],
    ) -> Optional[RoutingIntent]:
        advisory = cls.extract_advisory_payload(task)
        if not advisory:
            return None

        proposed_routing = advisory.get("proposed_routing") or {}
        if not isinstance(proposed_routing, dict):
            return None

        specialization = (
            proposed_routing.get("specialization")
            or proposed_routing.get("required_specialization")
        )
        if not isinstance(specialization, str) or not specialization.strip():
            return None

        confidence_score = advisory.get("confidence")
        if isinstance(confidence_score, (int, float)):
            if float(confidence_score) >= 0.75:
                confidence = IntentConfidence.HIGH
            elif float(confidence_score) >= 0.40:
                confidence = IntentConfidence.MEDIUM
            else:
                confidence = IntentConfidence.LOW
        else:
            confidence = IntentConfidence.MEDIUM

        metadata = {
            "advisory_id": advisory.get("advisory_id"),
            "advisory_source": proposed_routing.get("source"),
            "stateless": advisory.get("stateless", True),
        }

        return RoutingIntent(
            specialization=specialization.strip(),
            skills=(
                proposed_routing.get("skills")
                if isinstance(proposed_routing.get("skills"), dict)
                else {}
            ),
            source=IntentSource.COGNITIVE_ADVISORY,
            confidence=confidence,
            metadata={k: v for k, v in metadata.items() if v is not None},
        )
