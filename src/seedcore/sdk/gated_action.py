from __future__ import annotations

import contextlib
from dataclasses import dataclass
import threading
from typing import Any, Callable, Dict, List, Optional

from seedcore.adapters.rct_agent_action_gateway_reference_adapter import (
    build_rct_agent_action_evaluate_request_v1,
)

# Global default plus thread-local overrides for test and agent isolation.
_evaluator: Optional[Callable[[Dict[str, Any]], Any]] = None
_evaluator_lock = threading.Lock()
_evaluator_local = threading.local()

_executor: Optional[Callable[[Dict[str, Any]], Any]] = None
_executor_lock = threading.Lock()
_executor_local = threading.local()

SUPPORTED_POLICY = "strict_custody"
SUPPORTED_EVIDENCE_LABELS = frozenset({"origin_scan", "delivery_scan", "signed_edge_telemetry"})
SUPPORTED_FAIL_MODES = frozenset({"deny", "quarantine", "escalate"})
SUPPORTED_MODES = frozenset({"shadow", "enforce"})


class GatedActionEvaluatorNotConfigured(Exception):
    """Exception raised when a decorated gated action is called but no evaluator has been configured.

    This ensures that gated actions strictly fail closed rather than executing silently
    or relying on permissive defaults.
    """
    pass


class GatedActionEvaluationError(Exception):
    """Raised when the configured evaluator fails or returns an invalid response."""
    pass


@dataclass
class GovernedResult:
    """The structured governed result representing the SeedCore preflight decision boundary.

    In preflight/shadow mode, this object is returned directly to the caller,
    completely bypassing the wrapped business logic.
    """
    request_id: str
    decision: str
    reason_code: str
    replay_ref: Optional[str]
    audit_id: Optional[str]
    execution_token_id: Optional[str] = None
    evidence_bundle_id: Optional[str] = None
    verification_status: str = "incomplete"
    execution_result: Any = None


def set_evaluator(eval_fn: Callable[[Dict[str, Any]], Any]) -> None:
    """Register the global gateway evaluator function.

    Example:
        set_evaluator(lambda payload: client.post("/api/v1/agent-actions/evaluate", json=payload))
    """
    global _evaluator
    with _evaluator_lock:
        _evaluator = eval_fn


def set_executor(exec_fn: Callable[[Dict[str, Any]], Any]) -> None:
    """Register the global gateway executor function.

    Example:
        set_executor(lambda payload: client.post("/api/v1/agent-actions/execute", json=payload))
    """
    global _executor
    with _executor_lock:
        _executor = exec_fn


def reset_evaluator() -> None:
    """Reset and clear any configured evaluator and executor.

    Ensures clean environment state and fail-closed posture between test executions.
    """
    global _evaluator, _executor
    with _evaluator_lock:
        _evaluator = None
    with _executor_lock:
        _executor = None
    if hasattr(_evaluator_local, "evaluator"):
        delattr(_evaluator_local, "evaluator")
    if hasattr(_executor_local, "executor"):
        delattr(_executor_local, "executor")


@contextlib.contextmanager
def using_evaluator(eval_fn: Callable[[Dict[str, Any]], Any], exec_fn: Optional[Callable[[Dict[str, Any]], Any]] = None):
    """Thread-local context manager to inject an evaluator and optional executor function temporarily.

    Guarantees clean test isolation and prevents state leakage between unit tests.
    """
    sentinel = object()
    old_evaluator = getattr(_evaluator_local, "evaluator", sentinel)
    old_executor = getattr(_executor_local, "executor", sentinel)
    _evaluator_local.evaluator = eval_fn
    if exec_fn is not None:
        _executor_local.executor = exec_fn
    try:
        yield
    finally:
        if old_evaluator is sentinel:
            if hasattr(_evaluator_local, "evaluator"):
                delattr(_evaluator_local, "evaluator")
        else:
            _evaluator_local.evaluator = old_evaluator

        if old_executor is sentinel:
            if hasattr(_executor_local, "executor"):
                delattr(_executor_local, "executor")
        else:
            _executor_local.executor = old_executor


def _configured_evaluator() -> Optional[Callable[[Dict[str, Any]], Any]]:
    local_evaluator = getattr(_evaluator_local, "evaluator", None)
    if local_evaluator is not None:
        return local_evaluator
    with _evaluator_lock:
        return _evaluator


def _configured_executor() -> Optional[Callable[[Dict[str, Any]], Any]]:
    local_executor = getattr(_executor_local, "executor", None)
    if local_executor is not None:
        return local_executor
    with _executor_lock:
        return _executor


def _normalize_evaluator_response(raw_response: Any) -> Dict[str, Any]:
    if isinstance(raw_response, dict):
        return raw_response
    if hasattr(raw_response, "model_dump"):
        data = raw_response.model_dump(mode="json")
        if isinstance(data, dict):
            return data
    if hasattr(raw_response, "dict"):
        data = raw_response.dict()
        if isinstance(data, dict):
            return data
    if hasattr(raw_response, "json"):
        status_code = getattr(raw_response, "status_code", 200)
        if isinstance(status_code, int) and status_code >= 400:
            raise GatedActionEvaluationError(f"Evaluator returned HTTP {status_code}")
        data = raw_response.json()
        if isinstance(data, dict):
            return data
    raise TypeError("Evaluator must return a dictionary, Pydantic model, or JSON HTTP response.")


def gated_action(
    policy: str = "strict_custody",
    evidence_required: Optional[List[str]] = None,
    fail_mode: str = "quarantine",
    mode: str = "shadow",
):
    """Lightweight developer-experience (DX) decorator to protect actions with SeedCore.

    It validates that critical security policies, telemetry evidence requirements,
    and delegation parameters are satisfied before admitting execution, returning
    a GovernedResult and never running inner business logic in preflight mode.

    Supports:
        - policy="strict_custody"
        - evidence_required=["origin_scan", "delivery_scan", "signed_edge_telemetry"]
        - fail_modes: "deny", "quarantine", "escalate"
        - modes: "shadow", "enforce"
    """
    if policy != SUPPORTED_POLICY:
        raise ValueError(f"Unsupported gated action policy: {policy}")
    if fail_mode not in SUPPORTED_FAIL_MODES:
        raise ValueError(f"Unsupported gated action fail_mode: {fail_mode}")
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported gated action mode: {mode}")
    required_evidence = list(evidence_required or ["origin_scan", "delivery_scan", "signed_edge_telemetry"])
    unsupported_evidence = sorted(set(required_evidence) - SUPPORTED_EVIDENCE_LABELS)
    if unsupported_evidence:
        raise ValueError(f"Unsupported gated action evidence labels: {', '.join(unsupported_evidence)}")

    def decorator(func: Callable[..., Any]) -> Callable[..., GovernedResult]:
        def wrapper(*args, **kwargs) -> GovernedResult:
            # MVP preflight intentionally never calls the wrapped business logic.
            # 1. Locate the intent dictionary passed as the first positional arg or kwarg
            intent: Optional[Dict[str, Any]] = None
            if args:
                intent = args[0]
            elif "intent" in kwargs:
                intent = kwargs["intent"]

            if not isinstance(intent, dict):
                raise ValueError(
                    "Gated action expects a dictionary of 'intent' as the first positional argument "
                    "or keyword argument (e.g. transfer_asset(intent_dict))."
                )

            request_id = intent.get("request_id", "unknown-request-id")

            # 2. SDK-side telemetry evidence validation (Preflight Safety Check)
            # Check if all required evidence labels are present in telemetry.evidence_refs
            telemetry = intent.get("telemetry") if isinstance(intent.get("telemetry"), dict) else {}
            telemetry_refs = telemetry.get("evidence_refs", [])
            if not isinstance(telemetry_refs, list):
                telemetry_refs = []
            missing_evidence = [
                label for label in required_evidence if label not in telemetry_refs
            ]

            if missing_evidence:
                # Bypass evaluation path entirely and immediately return configured fail_mode
                return GovernedResult(
                    request_id=request_id,
                    decision=fail_mode,
                    reason_code="missing_required_evidence",
                    replay_ref=f"replay://workflow/request_id/{request_id}",
                    audit_id=None,
                    execution_token_id=None,
                    evidence_bundle_id=None,
                    verification_status="incomplete",
                )

            # 3. Fail-closed evaluator registration check
            eval_fn = _configured_evaluator()
            if eval_fn is None:
                raise GatedActionEvaluatorNotConfigured(
                    "Gated action evaluator not configured. Use set_evaluator() or "
                    "using_evaluator() to register an evaluator before calling gated actions."
                )

            # 4. Formulate the gateway evaluation payload using the existing RCT reference adapter
            try:
                # Extract and map required payload arguments from intent
                idempotency_key = intent["idempotency_key"]
                requested_at = intent["requested_at"]
                policy_snapshot_ref = intent.get("policy_snapshot_ref")
                principal = intent["principal"]
                workflow_valid_until = intent["workflow_valid_until"]
                asset_base = intent["asset_base"]
                approval_envelope_id = intent["approval_envelope_id"]
                approval_expected_envelope_version = intent.get("approval_expected_envelope_version")
                authority_scope_base = intent["authority_scope_base"]
                telemetry = intent["telemetry"]
                security_contract = intent["security_contract"]
                shopify_sandbox_transaction = intent["shopify_sandbox_transaction"]

                # Set no_execute options flag based on mode
                options_dict = dict(intent.get("options") or {})
                if mode == "shadow":
                    options_dict["no_execute"] = True
                elif mode == "enforce":
                    options_dict["no_execute"] = False

            except KeyError as e:
                # Missing delegation, principal, or asset mappings fails closed with ValueError
                raise ValueError(f"Missing required intent parameter: {e}")

            gateway_payload = build_rct_agent_action_evaluate_request_v1(
                request_id=request_id,
                idempotency_key=idempotency_key,
                requested_at=requested_at,
                policy_snapshot_ref=policy_snapshot_ref,
                principal=principal,
                workflow_valid_until=workflow_valid_until,
                asset_base=asset_base,
                approval_envelope_id=approval_envelope_id,
                approval_expected_envelope_version=approval_expected_envelope_version,
                authority_scope_base=authority_scope_base,
                telemetry=telemetry,
                security_contract=security_contract,
                shopify_sandbox_transaction=shopify_sandbox_transaction,
                options=options_dict,
            )

            # 5. Invoke the registered gateway evaluator
            raw_response = eval_fn(gateway_payload)
            evaluate_response = _normalize_evaluator_response(raw_response)

            # 6. Parse results and construct type-safe GovernedResult
            decision_view = evaluate_response.get("decision") or {}
            decision = decision_view.get("disposition") or "deny"
            reason_code = decision_view.get("reason_code") or "policy_denied"

            forensic_linkage = evaluate_response.get("forensic_linkage") or {}
            governed_receipt = evaluate_response.get("governed_receipt") or {}

            # Safe audit_id capture
            audit_id = governed_receipt.get("audit_id") or forensic_linkage.get("audit_id")

            # Determine optimal replay reference (preflight preference: forensic_linkage -> replay_lookup -> request_id)
            replay_ref = None
            if forensic_linkage.get("replay_ref"):
                replay_ref = forensic_linkage.get("replay_ref")
            elif evaluate_response.get("replay_lookup", {}).get("preferred_key"):
                pref_key = evaluate_response["replay_lookup"]["preferred_key"]
                replay_ref = f"replay://workflow/{pref_key}"
            else:
                replay_ref = f"replay://workflow/request_id/{request_id}"

            evidence_bundle_id = (
                forensic_linkage.get("forensic_block_id") or governed_receipt.get("forensic_block_id")
            )

            # Mapping decision to verification status
            if decision == "allow":
                verification_status = "passed"
            elif decision == "quarantine":
                verification_status = "incomplete"
            else:
                verification_status = "failed"

            # Parse execution_token_id if present
            execution_token = evaluate_response.get("execution_token") or {}
            execution_token_id = (
                execution_token.get("token_id")
                if isinstance(execution_token, dict)
                else getattr(execution_token, "token_id", None)
            )

            # 7. Execute wrapped business logic and close execution (Enforce mode only)
            execution_result = None
            if mode == "enforce":
                if decision == "allow":
                    if not execution_token_id:
                        raise GatedActionEvaluationError(
                            "Enforce mode requires an ExecutionToken before running business logic."
                        )
                    exec_fn = _configured_executor()
                    if exec_fn is None:
                        raise GatedActionEvaluationError(
                            "Enforce mode requires an executor to close governed execution."
                        )
                    execution_result = func(*args, **kwargs)
                    try:
                        exec_fn(gateway_payload)
                    except Exception as e:
                        raise GatedActionEvaluationError(f"Post-execution closure failed: {e}") from e
                else:
                    # Retain fail-closed posture: return without executing the inner business function.
                    pass

            return GovernedResult(
                request_id=request_id,
                decision=decision,
                reason_code=reason_code,
                replay_ref=replay_ref,
                audit_id=audit_id,
                execution_token_id=execution_token_id,
                evidence_bundle_id=evidence_bundle_id,
                verification_status=verification_status,
                execution_result=execution_result,
            )

        return wrapper

    return decorator
