from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from seedcore.api.routers.agent_actions_router import evaluate_agent_action
from seedcore.models.agent_action_gateway import AgentActionEvaluateRequest


router = APIRouter(tags=["policy-assistant"])


class ScenarioPackScenario(BaseModel):
    scenario_id: str
    label: str
    request: AgentActionEvaluateRequest


class ScenarioPackEvaluateRequest(BaseModel):
    owner_id: str
    policy_version: str
    scenarios: list[ScenarioPackScenario] = Field(default_factory=list)


@router.post("/policy-assistant/scenario-pack/evaluate")
async def evaluate_scenario_pack(payload: ScenarioPackEvaluateRequest) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    allowed = 0
    denied = 0
    escalated = 0
    errors = 0

    for scenario in payload.scenarios:
        try:
            scenario_request = scenario.request.model_copy(
                update={
                    "options": scenario.request.options.model_copy(update={"no_execute": True}),
                }
            )
            response = await evaluate_agent_action(
                payload_body=scenario_request.model_dump(mode="json"),
                debug=False,
                no_execute=True,
            )
        except HTTPException as exc:
            errors += 1
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "label": scenario.label,
                    "decision": "ERROR",
                    "reason_code": (
                        str(detail.get("error_code") or "").strip() if isinstance(detail, dict) else ""
                    )
                    or "scenario_evaluation_failed",
                    "trust_gaps": [],
                    "required_approvals": [],
                    "obligations": [],
                    "governed_receipt_ref": None,
                    "error": {
                        "status_code": exc.status_code,
                        "detail": detail,
                    },
                }
            )
            continue
        except Exception as exc:
            errors += 1
            results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "label": scenario.label,
                    "decision": "ERROR",
                    "reason_code": "scenario_evaluation_failed",
                    "trust_gaps": [],
                    "required_approvals": [],
                    "obligations": [],
                    "governed_receipt_ref": None,
                    "error": {
                        "status_code": None,
                        "detail": {"message": str(exc)},
                    },
                }
            )
            continue

        disposition = str(response.decision.disposition or "").strip().lower()
        if disposition == "allow":
            allowed += 1
        elif disposition == "escalate":
            escalated += 1
        else:
            denied += 1

        governed_receipt_ref = None
        if response.governed_receipt:
            governed_receipt_ref = str(
                response.governed_receipt.get("policy_receipt_id")
                or response.governed_receipt.get("audit_id")
                or ""
            ).strip() or None

        results.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.label,
                "decision": str(response.decision.disposition or "").upper(),
                "reason_code": response.decision.reason_code,
                "trust_gaps": [str(item).strip() for item in response.trust_gaps if str(item).strip()],
                "required_approvals": [str(item).strip() for item in response.required_approvals if str(item).strip()],
                "obligations": [item if isinstance(item, dict) else {"value": str(item)} for item in response.obligations],
                "governed_receipt_ref": governed_receipt_ref,
            }
        )

    return {
        "owner_id": payload.owner_id,
        "policy_version": payload.policy_version,
        "summary": {
            "total": len(payload.scenarios),
            "allowed": allowed,
            "denied": denied,
            "escalated": escalated,
            "errors": errors,
        },
        "results": results,
    }
