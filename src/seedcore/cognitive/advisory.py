from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from ..models.advisory import (
    AdvisoryContractResponse,
    AdvisoryPlan,
    AmbiguityAssessment,
    ProposedRouting,
    RiskSummary,
)
from ..models.task_payload import TaskPayload


class CognitiveAdvisoryContractBuilder:
    """
    Core advisory contract logic for Cognitive layer.

    Service layers should call this builder to keep transport thin while
    preserving deterministic contract behavior.
    """

    @staticmethod
    def clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @classmethod
    def estimate_ambiguity(
        cls,
        request: TaskPayload,
        cognitive_result: Dict[str, Any],
    ) -> AmbiguityAssessment:
        params = request.params or {}
        desc = (request.description or "").strip()
        signals: List[str] = []
        score = 0.0

        if len(desc) < 20:
            score += 0.20
            signals.append("short_or_sparse_description")

        lowered = desc.lower()
        ambiguous_markers = {"this", "that", "it", "somewhere", "quickly", "asap"}
        if any(marker in lowered for marker in ambiguous_markers):
            score += 0.20
            signals.append("ambiguous_reference_tokens")

        if "?" in desc:
            score += 0.10
            signals.append("explicit_question_mark")

        multimodal = params.get("multimodal", {}) if isinstance(params, dict) else {}
        mm_conf = multimodal.get("confidence")
        if isinstance(mm_conf, (int, float)):
            if float(mm_conf) < 0.6:
                score += 0.35
                signals.append("low_multimodal_confidence")
            elif float(mm_conf) < 0.8:
                score += 0.15
                signals.append("mid_multimodal_confidence")

        cog_conf = cognitive_result.get("confidence_score")
        if isinstance(cog_conf, (int, float)) and float(cog_conf) < 0.6:
            score += 0.20
            signals.append("low_cognitive_confidence")

        score = cls.clamp01(score)
        return AmbiguityAssessment(
            score=round(score, 3),
            needs_clarification=score >= 0.45,
            signals=signals,
        )

    @classmethod
    def derive_risk(
        cls,
        request: TaskPayload,
        ambiguity: AmbiguityAssessment,
    ) -> tuple[float, str, List[str]]:
        params = request.params or {}
        risk = params.get("risk", {}) if isinstance(params, dict) else {}
        triggers: List[str] = []

        score = 0.0
        if isinstance(risk, dict):
            raw_score = risk.get("score")
            if isinstance(raw_score, (int, float)):
                score = max(score, float(raw_score))
            if bool(risk.get("is_high_stakes")):
                score = max(score, 0.75)
                triggers.append("high_stakes_flag")

        score = max(score, ambiguity.score * 0.75)
        score = cls.clamp01(score)

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

    @classmethod
    def build_contract(
        cls,
        request: TaskPayload,
        cognitive_result: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> AdvisoryContractResponse:
        params = request.params or {}
        cognitive = params.get("cognitive", {}) if isinstance(params, dict) else {}
        proto_plan = cognitive.get("proto_plan") if isinstance(cognitive, dict) else {}
        if not isinstance(proto_plan, dict):
            proto_plan = {}

        routing = params.get("routing", {}) if isinstance(params, dict) else {}
        routing_source = "task_payload"
        if not isinstance(routing, dict):
            routing = {}

        if not routing and isinstance(proto_plan.get("routing"), dict):
            routing = dict(proto_plan["routing"])
            routing_source = "pkg_proto_plan"

        proposed_routing = ProposedRouting(
            required_specialization=routing.get("required_specialization"),
            specialization=routing.get("specialization"),
            skills=(
                routing.get("skills")
                if isinstance(routing.get("skills"), dict)
                else {}
            ),
            tools=[t for t in (routing.get("tools") or []) if isinstance(t, str)],
            source=routing_source,
        )

        ambiguity = cls.estimate_ambiguity(request, cognitive_result)
        risk_score, risk_level, risk_triggers = cls.derive_risk(request, ambiguity)

        interpretation = {
            "task_type": request.type,
            "domain": request.domain,
            "description": request.description,
            "multimodal": (
                params.get("multimodal", {}) if isinstance(params, dict) else {}
            ),
            "normalized_intent_text": (
                (params.get("chat", {}) or {}).get("message")
                if isinstance(params, dict)
                else None
            )
            or request.description,
        }

        steps = []
        if isinstance(cognitive_result.get("solution_steps"), list):
            steps = cognitive_result["solution_steps"]
        elif isinstance(cognitive_result.get("steps"), list):
            steps = cognitive_result["steps"]

        has_plan = bool(steps) or bool(proto_plan.get("steps")) or bool(
            cognitive_result.get("nodes")
        )

        confidence = cognitive_result.get("confidence_score")
        if not isinstance(confidence, (int, float)):
            confidence = round(cls.clamp01(1.0 - ambiguity.score), 3)

        if risk_level in {"high", "critical"} or (
            ambiguity.needs_clarification and not has_plan
        ):
            recommended_action = (
                "quarantine" if risk_level == "critical" else "step_up_approval"
            )
            summary = RiskSummary(
                task_id=request.task_id,
                risk_score=risk_score,
                risk_level=risk_level,  # type: ignore[arg-type]
                triggers=risk_triggers,
                recommended_action=recommended_action,  # type: ignore[arg-type]
                ambiguity=ambiguity,
                structured_interpretation=interpretation,
            )
            return AdvisoryContractResponse(
                success=True,
                advisory=summary,
                metadata={
                    "contract": "risk_summary",
                    "source": "cognitive_service",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "stateless": True,
                    **(metadata or {}),
                },
            )

        summary_text = cognitive_result.get("summary")
        if not isinstance(summary_text, str) or not summary_text.strip():
            step_count = len(steps) if steps else len(proto_plan.get("steps") or [])
            summary_text = (
                f"Prepared proto-planning advisory with {step_count} proposed step(s)."
            )

        plan = AdvisoryPlan(
            task_id=request.task_id,
            summary=summary_text,
            confidence=cls.clamp01(float(confidence)),
            ambiguity=ambiguity,
            structured_interpretation=interpretation,
            proposed_routing=proposed_routing,
            proto_plan=proto_plan,
        )
        return AdvisoryContractResponse(
            success=True,
            advisory=plan,
            metadata={
                "contract": "advisory_plan",
                "source": "cognitive_service",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stateless": True,
                **(metadata or {}),
            },
        )

    @classmethod
    def build_execution_failure_contract(
        cls,
        request: TaskPayload,
        error: str | None,
    ) -> AdvisoryContractResponse:
        ambiguity = cls.estimate_ambiguity(request, {})
        fallback = RiskSummary(
            advisory_id=str(uuid4()),
            task_id=request.task_id,
            risk_score=max(0.75, round(ambiguity.score, 3)),
            risk_level="high",
            triggers=["cognitive_execution_failed"],
            recommended_action="step_up_approval",
            ambiguity=ambiguity,
            structured_interpretation={
                "task_type": request.type,
                "domain": request.domain,
                "description": request.description,
            },
        )
        return AdvisoryContractResponse(
            success=False,
            advisory=fallback,
            error=error,
            metadata={
                "contract": "risk_summary",
                "source": "cognitive_service_fallback",
                "stateless": True,
            },
        )
