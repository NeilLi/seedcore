from __future__ import annotations

from dataclasses import asdict, is_dataclass
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from seedcore.models.governed_mutation import GovernedMutationContract
from seedcore.ops.evidence.policy import canonical_json, sha256_hex
from seedcore.services.mutation_receipt_service import mutation_receipt_service


class GovernedMutationError(ValueError):
    def __init__(self, code: str, message: Optional[str] = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class GovernedMutationResult:
    mutation_result: Any
    payload_hash: str
    mutation_receipt: Optional[Dict[str, Any]]
    audit_result: Optional[Dict[str, Any]]


def _normalize_value_for_receipt(value: Any) -> Any:
    """
    Convert mutation outputs into a deterministic JSON-safe shape for hashing.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_value_for_receipt(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value_for_receipt(item) for item in value]
    if isinstance(value, set):
        normalized = [_normalize_value_for_receipt(item) for item in value]
        return sorted(normalized, key=lambda item: canonical_json(item))
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json")  # type: ignore[attr-defined]
        except Exception:
            dumped = value.model_dump()  # type: ignore[attr-defined]
        return _normalize_value_for_receipt(dumped)
    if is_dataclass(value):
        return _normalize_value_for_receipt(asdict(value))
    return {"type": value.__class__.__name__}


class GovernedMutationWrapper:
    async def execute(
        self,
        *,
        entrypoint_id: str,
        contract: GovernedMutationContract,
        payload_for_hash: Mapping[str, Any],
        mutation_operation: Callable[[], Awaitable[Any]],
        receipt_kind: str,
        actor_ref: Optional[str],
        target_ref: Optional[str],
        intent_id: Optional[str],
        token_id: Optional[str],
        policy_receipt_id: Optional[str] = None,
        snapshot_id: Optional[int] = None,
        rbac_check: Optional[Callable[[], Awaitable[None]]] = None,
        execution_token_check: Optional[Callable[[], None]] = None,
        policy_receipt_check: Optional[Callable[[], None]] = None,
        snapshot_binding_check: Optional[Callable[[], None]] = None,
        load_previous_receipt_chain: Optional[
            Callable[[], Awaitable[tuple[Optional[str], Optional[int]]]]
        ] = None,
        append_audit_record: Optional[
            Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]
        ] = None,
        evidence_bundle_base: Optional[Mapping[str, Any]] = None,
    ) -> GovernedMutationResult:
        if contract.is_mutating() and rbac_check is not None:
            try:
                await rbac_check()
            except GovernedMutationError:
                raise
            except Exception as exc:
                raise GovernedMutationError(
                    "rbac_denied", f"RBAC check failed for {entrypoint_id}: {exc}"
                ) from exc

        if contract.requires_execution_token:
            if execution_token_check is None:
                raise GovernedMutationError("missing_execution_token_validator")
            execution_token_check()

        if contract.requires_policy_receipt:
            if policy_receipt_check is None:
                raise GovernedMutationError("missing_policy_receipt_validator")
            policy_receipt_check()

        if contract.snapshot_binding_required:
            if snapshot_binding_check is not None:
                snapshot_binding_check()
            elif snapshot_id is None:
                raise GovernedMutationError("missing_snapshot_binding")

        payload_hash = sha256_hex(canonical_json(dict(payload_for_hash or {})))

        previous_receipt_hash: Optional[str] = None
        previous_receipt_counter: Optional[int] = None
        if contract.requires_signed_receipt:
            if load_previous_receipt_chain is None:
                raise GovernedMutationError("missing_receipt_chain_loader")
            previous_receipt_hash, previous_receipt_counter = (
                await load_previous_receipt_chain()
            )

        mutation_result = await mutation_operation()

        mutation_receipt: Optional[Dict[str, Any]] = None
        if contract.requires_signed_receipt:
            if not intent_id:
                raise GovernedMutationError("missing_intent_id")
            if not token_id:
                raise GovernedMutationError("missing_token_id")
            normalized_result = _normalize_value_for_receipt(mutation_result)
            result_hash = sha256_hex(canonical_json({"result": normalized_result}))
            mutation_receipt = mutation_receipt_service.build_signed_receipt(
                receipt_kind=receipt_kind,
                intent_id=str(intent_id),
                token_id=str(token_id),
                actor_ref=actor_ref,
                target_ref=target_ref,
                mutation_payload={
                    "request_payload_hash": payload_hash,
                    "result_hash": result_hash,
                    "result_type": mutation_result.__class__.__name__,
                },
                snapshot_id=snapshot_id,
                policy_receipt_id=policy_receipt_id,
                previous_receipt_hash=previous_receipt_hash,
                previous_receipt_counter=previous_receipt_counter,
            )
            verification = mutation_receipt_service.verify_signed_receipt(mutation_receipt)
            if not bool(verification.get("verified")):
                raise GovernedMutationError(
                    "invalid_mutation_receipt",
                    str(verification.get("error") or "mutation receipt verification failed"),
                )

        audit_result: Optional[Dict[str, Any]] = None
        if append_audit_record is not None:
            evidence_bundle = dict(evidence_bundle_base or {})
            evidence_bundle["governed_payload_hash"] = payload_hash
            if mutation_receipt is not None:
                evidence_bundle["mutation_receipt"] = mutation_receipt
            audit_result = await append_audit_record(evidence_bundle)

        return GovernedMutationResult(
            mutation_result=mutation_result,
            payload_hash=payload_hash,
            mutation_receipt=mutation_receipt,
            audit_result=audit_result,
        )


governed_mutation_wrapper = GovernedMutationWrapper()
