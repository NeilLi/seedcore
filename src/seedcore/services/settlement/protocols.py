from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Protocol

from seedcore.models.action_intent import TwinSnapshot
from seedcore.ops.evidence.verification import verify_evidence_bundle_result


@dataclass(frozen=True)
class SettlementContext:
    context: Mapping[str, Any]
    task_id: Optional[str]
    intent_id: Optional[str]
    relevant_twin_snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class SettlementVerification:
    verified: bool
    reason: str
    bundle_verification: Mapping[str, Any] = field(default_factory=dict)
    resolved_node_id: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified": bool(self.verified),
            "reason": str(self.reason),
            "bundle_verification": dict(self.bundle_verification or {}),
            "resolved_node_id": self.resolved_node_id,
            "details": dict(self.details or {}),
        }


class SettlementProtocol(Protocol):
    settlement_type: str

    async def verify(self, context: SettlementContext) -> SettlementVerification:
        ...

    def apply(self, snapshot: TwinSnapshot, verification: SettlementVerification) -> TwinSnapshot:
        ...

    def proof_package(
        self,
        context: SettlementContext,
        verification: SettlementVerification,
    ) -> Dict[str, Any]:
        ...


class SettlementRegistry:
    def __init__(self, protocols: Mapping[str, SettlementProtocol] | None = None) -> None:
        self._protocols: dict[str, SettlementProtocol] = {}
        for protocol in dict(protocols or {}).values():
            self.register(protocol)

    def register(self, protocol: SettlementProtocol) -> None:
        settlement_type = _normalize_settlement_type(protocol.settlement_type)
        if not settlement_type:
            raise ValueError("settlement protocol must define settlement_type")
        self._protocols[settlement_type] = protocol

    def resolve(self, settlement_type: str | None) -> SettlementProtocol:
        normalized = _normalize_settlement_type(settlement_type or "delivery")
        protocol = self._protocols.get(normalized)
        if protocol is None:
            raise KeyError(normalized)
        return protocol


class DeliverySettlement:
    settlement_type = "delivery"

    async def verify(self, context: SettlementContext) -> SettlementVerification:
        raw_context = context.context
        evidence_bundle = (
            raw_context.get("evidence_bundle")
            if isinstance(raw_context.get("evidence_bundle"), Mapping)
            else {}
        )
        bundle_verification = verify_evidence_bundle_result(evidence_bundle)
        if bundle_verification.get("verified") is not True:
            return SettlementVerification(
                verified=False,
                reason=str(
                    bundle_verification.get("error")
                    or "evidence_bundle_verification_failed"
                ),
                bundle_verification=bundle_verification,
            )

        verified, reason = _verify_settlement_node(raw_context)
        resolved_node_id = _resolve_settlement_node_id(raw_context)
        return SettlementVerification(
            verified=verified,
            reason=reason,
            bundle_verification=bundle_verification,
            resolved_node_id=resolved_node_id,
            details={
                "node_binding_verified": bool(verified),
                "expected_endpoint_id": _expected_endpoint_id(raw_context),
            },
        )

    def apply(self, snapshot: TwinSnapshot, verification: SettlementVerification) -> TwinSnapshot:
        return snapshot

    def proof_package(
        self,
        context: SettlementContext,
        verification: SettlementVerification,
    ) -> Dict[str, Any]:
        raw_context = context.context
        evidence_bundle = (
            raw_context.get("evidence_bundle")
            if isinstance(raw_context.get("evidence_bundle"), Mapping)
            else {}
        )
        return {
            "proof_version": "settlement.delivery.v1",
            "settlement_type": self.settlement_type,
            "verified": bool(verification.verified),
            "reason": verification.reason,
            "task_id": context.task_id,
            "intent_id": context.intent_id,
            "evidence_bundle_id": evidence_bundle.get("evidence_bundle_id"),
            "expected_endpoint_id": _expected_endpoint_id(raw_context),
            "resolved_node_id": verification.resolved_node_id,
            "requirements": {
                "evidence_bundle_verified": bool(
                    verification.bundle_verification.get("verified") is True
                ),
                "node_binding_verified": bool(
                    (verification.details or {}).get("node_binding_verified")
                ),
            },
            "evidence_refs": _collect_evidence_refs(evidence_bundle),
        }


class _UnsupportedSettlement:
    settlement_type = "unsupported"

    async def verify(self, context: SettlementContext) -> SettlementVerification:
        return SettlementVerification(
            verified=False,
            reason=f"{self.settlement_type}_settlement_not_implemented",
            details={"settlement_type": self.settlement_type},
        )

    def apply(self, snapshot: TwinSnapshot, verification: SettlementVerification) -> TwinSnapshot:
        return snapshot

    def proof_package(
        self,
        context: SettlementContext,
        verification: SettlementVerification,
    ) -> Dict[str, Any]:
        return {
            "proof_version": f"settlement.{self.settlement_type}.v1",
            "settlement_type": self.settlement_type,
            "verified": bool(verification.verified),
            "reason": verification.reason,
            "task_id": context.task_id,
            "intent_id": context.intent_id,
        }


class CustodyChangeSettlement(_UnsupportedSettlement):
    settlement_type = "custody_change"


class RollbackSettlement(_UnsupportedSettlement):
    settlement_type = "rollback"


class RemediationSettlement(_UnsupportedSettlement):
    settlement_type = "remediation"


def default_settlement_registry() -> SettlementRegistry:
    return SettlementRegistry(
        {
            "delivery": DeliverySettlement(),
            "custody_change": CustodyChangeSettlement(),
            "rollback": RollbackSettlement(),
            "remediation": RemediationSettlement(),
        }
    )


def _normalize_settlement_type(value: Any) -> str:
    return str(value or "").strip().lower()


def _expected_endpoint_id(context: Mapping[str, Any]) -> Optional[str]:
    execution_token = (
        context.get("execution_token")
        if isinstance(context.get("execution_token"), Mapping)
        else {}
    )
    constraints = (
        execution_token.get("constraints")
        if isinstance(execution_token.get("constraints"), Mapping)
        else {}
    )
    endpoint = constraints.get("endpoint_id")
    if endpoint is None:
        return None
    normalized = str(endpoint).strip()
    return normalized or None


def _verify_settlement_node(context: Mapping[str, Any]) -> tuple[bool, str]:
    expected_node_id = _expected_endpoint_id(context)
    resolved_node = _resolve_settlement_node_id(context)
    if not resolved_node:
        return False, "missing_node_id"
    if expected_node_id and str(expected_node_id) != str(resolved_node):
        return False, "node_id_mismatch_expected_endpoint"
    return True, "ok"


def _resolve_settlement_node_id(context: Mapping[str, Any]) -> Optional[str]:
    evidence_bundle = (
        context.get("evidence_bundle")
        if isinstance(context.get("evidence_bundle"), Mapping)
        else {}
    )
    evidence_inputs = (
        evidence_bundle.get("evidence_inputs")
        if isinstance(evidence_bundle.get("evidence_inputs"), Mapping)
        else {}
    )
    execution_summary = (
        evidence_inputs.get("execution_summary")
        if isinstance(evidence_inputs.get("execution_summary"), Mapping)
        else {}
    )
    for candidate in (
        evidence_bundle.get("node_id"),
        execution_summary.get("node_id"),
        (
            evidence_bundle.get("execution_receipt", {}).get("node_id")
            if isinstance(evidence_bundle.get("execution_receipt"), Mapping)
            else None
        ),
    ):
        if candidate is None:
            continue
        node_id = str(candidate).strip()
        if node_id:
            return node_id
    return None


def _collect_evidence_refs(evidence_bundle: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    bundle_id = evidence_bundle.get("evidence_bundle_id")
    if isinstance(bundle_id, str) and bundle_id.strip():
        refs.append(bundle_id.strip())
    evidence_inputs = (
        evidence_bundle.get("evidence_inputs")
        if isinstance(evidence_bundle.get("evidence_inputs"), Mapping)
        else {}
    )
    transition_receipts = (
        evidence_inputs.get("transition_receipts")
        if isinstance(evidence_inputs.get("transition_receipts"), list)
        else []
    )
    for item in transition_receipts:
        if not isinstance(item, Mapping):
            continue
        receipt_id = item.get("transition_receipt_id")
        if isinstance(receipt_id, str) and receipt_id.strip():
            refs.append(receipt_id.strip())
    return sorted(set(refs))
