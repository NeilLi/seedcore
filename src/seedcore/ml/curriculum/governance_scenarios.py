from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class GovernanceScenario:
    """Shadow-only synthetic ActionIntent probe for governance drills."""

    name: str
    intent: Dict[str, Any]
    expected_disposition: str
    expected_reason_code: str
    expected_no_execute: bool = True
    shadow_only: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


class GovernanceScenarioGenerator:
    """Generate bounded RCT governance probes without granting authority."""

    def __init__(self, base_intent: Dict[str, Any]) -> None:
        self._base_intent = deepcopy(base_intent)

    def generate(self) -> List[GovernanceScenario]:
        return [
            self.stale_telemetry(),
            self.out_of_bounds_scope(),
            self.missing_required_evidence(),
        ]

    def stale_telemetry(self) -> GovernanceScenario:
        intent = self._clone("stale-telemetry")
        intent["telemetry"]["observed_at"] = "2026-05-21T09:45:00Z"
        intent["telemetry"]["freshness_seconds"] = 900
        intent["telemetry"]["max_allowed_age_seconds"] = 300
        return GovernanceScenario(
            name="stale_telemetry_preflight",
            intent=intent,
            expected_disposition="quarantine",
            expected_reason_code="stale_context",
            metadata={"probe": "telemetry_freshness"},
        )

    def out_of_bounds_scope(self) -> GovernanceScenario:
        intent = self._clone("out-of-bounds")
        intent["telemetry"]["current_zone"] = "loading_dock_unapproved"
        intent["telemetry"]["current_coordinate_ref"] = "gazebo://warehouse/loading-dock/Z9"
        return GovernanceScenario(
            name="out_of_bounds_preflight",
            intent=intent,
            expected_disposition="deny",
            expected_reason_code="out_of_bounds_scope",
            metadata={"probe": "scope_coordinate_mismatch"},
        )

    def missing_required_evidence(self) -> GovernanceScenario:
        intent = self._clone("missing-evidence")
        intent["telemetry"]["evidence_refs"] = ["origin_scan", "delivery_scan"]
        return GovernanceScenario(
            name="missing_required_evidence",
            intent=intent,
            expected_disposition="quarantine",
            expected_reason_code="missing_required_evidence",
            metadata={"probe": "sdk_local_evidence_contract"},
        )

    def _clone(self, suffix: str) -> Dict[str, Any]:
        intent = deepcopy(self._base_intent)
        intent["request_id"] = f"{intent['request_id']}-{suffix}"
        intent["idempotency_key"] = f"{intent['idempotency_key']}-{suffix}"
        options = dict(intent.get("options") or {})
        options["scenario_lane"] = "shadow"
        intent["options"] = options
        return intent
