from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from ...models.advisory import (
    AdvisoryContractResponse,
    AmbiguityAssessment,
    RiskSummary,
)
from ...models.cognitive import CognitiveType, DecisionKind


class CoordinatorAdvisoryCore:
    """Core advisory helpers for coordinator-level stateless reasoning flow."""

    @staticmethod
    def extract_eventizer_tags(eventizer_data: Dict[str, Any]) -> list[str]:
        event_tags = eventizer_data.get("event_tags") or {}
        tags: list[str] = []
        if isinstance(event_tags, dict):
            for key in ("hard_tags", "soft_tags", "semantic_tags"):
                values = event_tags.get(key)
                if isinstance(values, list):
                    tags.extend([str(v) for v in values if v is not None])
        return sorted(set(tags))

    @staticmethod
    def clean_numeric_signals(signals: Dict[str, Any]) -> Dict[str, float]:
        cleaned: Dict[str, float] = {}
        for key, value in (signals or {}).items():
            if isinstance(value, bool):
                cleaned[key] = 1.0 if value else 0.0
            elif isinstance(value, (int, float)):
                cleaned[key] = float(value)
        return cleaned

    @staticmethod
    def estimate_ambiguity(
        task_dict: Dict[str, Any],
        eventizer_data: Dict[str, Any],
    ) -> AmbiguityAssessment:
        description = str(task_dict.get("description") or "").strip()
        reasons: list[str] = []
        score = 0.0

        if len(description) < 20:
            score += 0.2
            reasons.append("short_or_sparse_description")
        if "?" in description:
            score += 0.1
            reasons.append("explicit_question")

        lowered = description.lower()
        if any(tok in lowered for tok in ("this", "that", "it", "somewhere", "asap")):
            score += 0.2
            reasons.append("ambiguous_reference_tokens")

        confidence = (
            (eventizer_data.get("confidence") or {})
            if isinstance(eventizer_data, dict)
            else {}
        )
        overall_conf = confidence.get("overall_confidence")
        if isinstance(overall_conf, (int, float)):
            if float(overall_conf) < 0.6:
                score += 0.35
                reasons.append("low_eventizer_confidence")
            elif float(overall_conf) < 0.8:
                score += 0.15
                reasons.append("mid_eventizer_confidence")

        score = max(0.0, min(1.0, score))
        return AmbiguityAssessment(
            score=round(score, 3),
            needs_clarification=score >= 0.45,
            signals=reasons,
        )

    @staticmethod
    def risk_profile(
        task_dict: Dict[str, Any],
        ambiguity: AmbiguityAssessment,
    ) -> tuple[float, str, list[str]]:
        params = task_dict.get("params", {}) if isinstance(task_dict, dict) else {}
        risk = params.get("risk", {}) if isinstance(params, dict) else {}
        score = 0.0
        triggers: list[str] = []

        if isinstance(risk, dict):
            if isinstance(risk.get("score"), (int, float)):
                score = max(score, float(risk["score"]))
            if bool(risk.get("is_high_stakes")):
                score = max(score, 0.75)
                triggers.append("high_stakes_flag")

        score = max(score, ambiguity.score * 0.75)
        score = max(0.0, min(1.0, score))

        if score >= 0.9:
            level = "critical"
        elif score >= 0.7:
            level = "high"
        elif score >= 0.4:
            level = "medium"
        else:
            level = "low"

        if ambiguity.needs_clarification:
            triggers.append("ambiguity_requires_clarification")

        return round(score, 3), level, triggers

    @staticmethod
    def build_cognitive_advisory_payload(
        task_payload: Dict[str, Any],
        proto_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        advisory_payload = dict(task_payload)
        advisory_params = dict(advisory_payload.get("params") or {})
        advisory_cognitive = dict(advisory_params.get("cognitive") or {})
        interaction = (
            advisory_params.get("interaction")
            if isinstance(advisory_params.get("interaction"), dict)
            else {}
        )
        assigned_agent_id = (
            interaction.get("assigned_agent_id") if isinstance(interaction, dict) else None
        )

        advisory_cognitive["agent_id"] = (
            advisory_cognitive.get("agent_id")
            or assigned_agent_id
            or "coordinator_service"
        )
        advisory_cognitive["cog_type"] = advisory_cognitive.get(
            "cog_type", CognitiveType.TASK_PLANNING.value
        )
        advisory_cognitive["decision_kind"] = advisory_cognitive.get(
            "decision_kind", DecisionKind.COGNITIVE.value
        )
        advisory_cognitive["disable_memory_write"] = True
        advisory_cognitive["advisory_mode"] = True
        advisory_cognitive["proto_plan"] = proto_plan
        advisory_params["cognitive"] = advisory_cognitive
        advisory_payload["params"] = advisory_params
        return advisory_payload

    @staticmethod
    def build_coordinator_response(
        cognitive_res: Dict[str, Any],
        task_id: str,
        eventizer_data: Dict[str, Any],
        proto_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        advisory_obj = cognitive_res.get("advisory") or {}
        if isinstance(advisory_obj, dict):
            interpretation = advisory_obj.setdefault("structured_interpretation", {})
            interpretation.setdefault("eventizer", eventizer_data)

            if isinstance(advisory_obj.get("proto_plan"), dict):
                advisory_obj["proto_plan"] = advisory_obj.get("proto_plan") or proto_plan
            elif proto_plan:
                advisory_obj["proto_plan"] = proto_plan

            proposed_routing = advisory_obj.setdefault("proposed_routing", {})
            if isinstance(proposed_routing, dict):
                if not proposed_routing.get("required_specialization"):
                    pkg_routing = (
                        proto_plan.get("routing")
                        if isinstance(proto_plan.get("routing"), dict)
                        else {}
                    )
                    if pkg_routing:
                        proposed_routing.setdefault(
                            "required_specialization",
                            pkg_routing.get("required_specialization"),
                        )
                        proposed_routing.setdefault(
                            "specialization", pkg_routing.get("specialization")
                        )
                        if isinstance(pkg_routing.get("skills"), dict):
                            proposed_routing.setdefault("skills", pkg_routing.get("skills"))
                        if isinstance(pkg_routing.get("tools"), list):
                            proposed_routing.setdefault("tools", pkg_routing.get("tools"))
                        proposed_routing.setdefault("source", "pkg_proto_plan")

        return {
            "success": bool(cognitive_res.get("success", True)),
            "advisory": advisory_obj,
            "error": cognitive_res.get("error"),
            "metadata": {
                **(cognitive_res.get("metadata") or {}),
                "task_id": task_id,
                "source": "coordinator_advisory",
                "stateless": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }

    @classmethod
    def build_fallback_contract(
        cls,
        task_dict: Dict[str, Any],
        error: str,
    ) -> AdvisoryContractResponse:
        fallback_task_id = task_dict.get("task_id") or task_dict.get("id") or "unknown"
        ambiguity = cls.estimate_ambiguity(task_dict, {})
        risk_score, risk_level, triggers = cls.risk_profile(task_dict, ambiguity)
        fallback = RiskSummary(
            task_id=str(fallback_task_id),
            risk_score=max(0.75, risk_score),
            risk_level=(
                "high" if risk_level in {"low", "medium"} else risk_level
            ),  # type: ignore[arg-type]
            triggers=list(set(triggers + ["advisory_generation_failed"])),
            recommended_action="step_up_approval",
            ambiguity=ambiguity,
            structured_interpretation={
                "task_type": task_dict.get("type"),
                "domain": task_dict.get("domain"),
                "description": task_dict.get("description"),
            },
        )
        return AdvisoryContractResponse(
            success=False,
            advisory=fallback,
            error=error,
            metadata={
                "source": "coordinator_advisory_fallback",
                "stateless": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
