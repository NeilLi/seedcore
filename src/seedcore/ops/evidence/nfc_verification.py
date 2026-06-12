from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


NfcDisposition = Literal["allow", "deny", "quarantine"]


class DynamicNfcPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    workflow_join_key: str
    nfc_uid_hash: str
    scan_counter: int = Field(ge=0)
    challenge_nonce: str
    challenge_response_hash: str
    cmac_ref: str
    tamper_state: str
    anchor_profile_ref: str

    @field_validator(
        "asset_ref",
        "workflow_join_key",
        "nfc_uid_hash",
        "challenge_nonce",
        "challenge_response_hash",
        "cmac_ref",
        "tamper_state",
        "anchor_profile_ref",
    )
    @classmethod
    def _non_empty_str(cls, value: str, info) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{info.field_name} must be non-empty")
        return normalized


class DynamicNfcEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    freshness_seconds: int = Field(ge=0)
    max_allowed_age_seconds: int = Field(ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    nfc_payload: DynamicNfcPayload

    @field_validator("evidence_refs")
    @classmethod
    def _non_empty_refs(cls, value: list[str]) -> list[str]:
        refs = [str(item).strip() for item in value if str(item).strip()]
        if not refs:
            raise ValueError("evidence_refs must include at least one evidence ref")
        return refs


class NfcVerificationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_asset_ref: str
    workflow_join_key: str
    issued_challenge_nonce: str
    registered_nfc_uid_hash: str
    expected_anchor_profile_ref: str
    highest_observed_scan_counter: int = Field(default=-1)
    mock_root_key: str
    kms_master_key_hex: str = Field(default="")
    revoked_keys: list[str] = Field(default_factory=list)
    simulate_kms_unavailable: bool = Field(default=False)

    @field_validator(
        "expected_asset_ref",
        "workflow_join_key",
        "issued_challenge_nonce",
        "registered_nfc_uid_hash",
        "expected_anchor_profile_ref",
        "mock_root_key",
    )
    @classmethod
    def _non_empty_str(cls, value: str, info) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"{info.field_name} must be non-empty")
        return normalized


class NfcVerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    disposition: NfcDisposition
    reason_code: str
    issues: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    freshness_seconds: int | None = None
    max_allowed_age_seconds: int | None = None
    observed_at: str | None = None
    nfc_uid_hash: str | None = None
    anchor_profile_ref: str | None = None
    scan_counter: int | None = None
    anchor_counter_key: str | None = None
    current_highest_scan_counter: int | None = None
    observed_counter_for_persistence: int | None = None
    shadow_nfc_verification: dict[str, Any] | None = None


def verify_dynamic_nfc_evidence(
    evidence: Mapping[str, Any] | DynamicNfcEvidence,
    context: Mapping[str, Any] | NfcVerificationContext,
    *,
    clock: Callable[[], datetime] | None = None,
) -> NfcVerificationResult:
    try:
        model = evidence if isinstance(evidence, DynamicNfcEvidence) else DynamicNfcEvidence.model_validate(dict(evidence))
        ctx = context if isinstance(context, NfcVerificationContext) else NfcVerificationContext.model_validate(dict(context))
    except Exception:
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="nfc_payload_incomplete",
            issues=["nfc_payload_incomplete"],
        )

    payload = model.nfc_payload
    common = {
        "evidence_refs": list(model.evidence_refs),
        "freshness_seconds": _effective_freshness_seconds(model, clock=clock),
        "max_allowed_age_seconds": model.max_allowed_age_seconds,
        "observed_at": _isoformat_utc(model.observed_at),
        "nfc_uid_hash": payload.nfc_uid_hash,
        "anchor_profile_ref": payload.anchor_profile_ref,
        "scan_counter": payload.scan_counter,
        "anchor_counter_key": anchor_counter_key(
            nfc_uid_hash=payload.nfc_uid_hash,
            anchor_profile_ref=payload.anchor_profile_ref,
        ),
        "current_highest_scan_counter": ctx.highest_observed_scan_counter,
        "observed_counter_for_persistence": payload.scan_counter,
    }

    payload_is_simulator = "fixture" in payload.anchor_profile_ref or payload.anchor_profile_ref == "profile:nxp-ntag424-dna-fixture-v1"
    expected_is_trusted = "trusted" in ctx.expected_anchor_profile_ref or ctx.expected_anchor_profile_ref.startswith("profile:ntag424-prod")
    expected_is_shadow = ctx.expected_anchor_profile_ref == "ntag424_sun_shadow"
    expected_is_ntag = "ntag424" in ctx.expected_anchor_profile_ref and "fixture" not in ctx.expected_anchor_profile_ref

    if payload.asset_ref != ctx.expected_asset_ref:
        return _result(
            verified=False,
            disposition="deny",
            reason_code="nfc_asset_anchor_mismatch",
            issues=["nfc_asset_anchor_mismatch"],
            **common,
        )
    if payload.workflow_join_key != ctx.workflow_join_key:
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="nfc_workflow_binding_mismatch",
            issues=["nfc_workflow_binding_mismatch"],
            **common,
        )
    if common["freshness_seconds"] is not None and common["freshness_seconds"] > model.max_allowed_age_seconds:
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="nfc_scan_too_stale",
            issues=["nfc_scan_too_stale"],
            **common,
        )

    # 1. Simulator evidence in trusted profile -> fail-closed/quarantine
    if expected_is_trusted and payload_is_simulator:
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="simulator_in_trusted_profile",
            issues=["simulator_in_trusted_profile"],
            **common,
        )

    # 2. Match nfc_uid_hash and anchor_profile_ref (skip profile ref check if shadow)
    profile_mismatch = (
        payload.anchor_profile_ref != ctx.expected_anchor_profile_ref
        and not expected_is_shadow
    )
    if payload.nfc_uid_hash != ctx.registered_nfc_uid_hash or profile_mismatch:
        return _result(
            verified=False,
            disposition="deny",
            reason_code="nfc_asset_anchor_mismatch",
            issues=["nfc_asset_anchor_mismatch"],
            **common,
        )
    if payload.challenge_nonce != ctx.issued_challenge_nonce:
        return _result(
            verified=False,
            disposition="deny",
            reason_code="dynamic_nfc_proof_invalid",
            issues=["dynamic_nfc_proof_invalid"],
            **common,
        )
    if payload.scan_counter <= ctx.highest_observed_scan_counter:
        return _result(
            verified=False,
            disposition="deny",
            reason_code="dynamic_nfc_proof_invalid",
            issues=["dynamic_nfc_proof_invalid"],
            **common,
        )

    # 2. Cryptographic verification
    shadow_nfc_verification = None

    if expected_is_ntag and not expected_is_shadow:
        # AUTHORITATIVE Ntag424 SUN CMAC verifier
        from seedcore.ops.evidence.nfc_kms import NfcKmsClient, NfcKeyRevokedError, NfcKmsUnavailableError
        from seedcore.ops.evidence.nfc_crypto import Ntag424SunCmacVerifier

        kms_client = NfcKmsClient(
            master_key_hex=ctx.kms_master_key_hex,
            revoked_keys=ctx.revoked_keys,
            simulate_unavailable=ctx.simulate_kms_unavailable,
        )
        try:
            derived_key = kms_client.get_tag_derived_key_material(
                nfc_uid_hash=payload.nfc_uid_hash,
                cmac_ref=payload.cmac_ref,
            )
            verifier = Ntag424SunCmacVerifier()
            verified_ok = verifier.verify(payload, derived_key)
            if not verified_ok:
                return _result(
                    verified=False,
                    disposition="deny",
                    reason_code="dynamic_nfc_proof_invalid",
                    issues=["dynamic_nfc_proof_invalid"],
                    **common,
                )
        except NfcKeyRevokedError as exc:
            return _result(
                verified=False,
                disposition="deny",
                reason_code="nfc_key_revoked",
                issues=[f"nfc_key_revoked: {exc}"],
                **common,
            )
        except NfcKmsUnavailableError as exc:
            return _result(
                verified=False,
                disposition="quarantine",
                reason_code="nfc_kms_unavailable",
                issues=[f"nfc_kms_unavailable: {exc}"],
                **common,
            )
    else:
        # Fixture / simulated HMAC verifier
        from seedcore.ops.evidence.nfc_crypto import FixtureDynamicNfcVerifier
        verifier = FixtureDynamicNfcVerifier()
        verified_ok = verifier.verify(payload, ctx.mock_root_key.encode("utf-8"))
        if not verified_ok:
            return _result(
                verified=False,
                disposition="deny",
                reason_code="dynamic_nfc_proof_invalid",
                issues=["dynamic_nfc_proof_invalid"],
                **common,
            )

        # In parallel, perform shadow verification if configured
        if expected_is_shadow:
            from seedcore.ops.evidence.nfc_kms import NfcKmsClient, NfcKeyRevokedError, NfcKmsUnavailableError
            from seedcore.ops.evidence.nfc_crypto import Ntag424SunCmacVerifier

            kms_client = NfcKmsClient(
                master_key_hex=ctx.kms_master_key_hex,
                revoked_keys=ctx.revoked_keys,
                simulate_unavailable=ctx.simulate_kms_unavailable,
            )
            try:
                derived_key = kms_client.get_tag_derived_key_material(
                    nfc_uid_hash=payload.nfc_uid_hash,
                    cmac_ref=payload.cmac_ref,
                )
                sv_verifier = Ntag424SunCmacVerifier()
                shadow_ok = sv_verifier.verify(payload, derived_key)
                shadow_nfc_verification = {
                    "verified": shadow_ok,
                    "disposition": "allow" if shadow_ok else "deny",
                    "reason_code": "rct_nfc_scan_verified" if shadow_ok else "dynamic_nfc_proof_invalid",
                    "issues": [] if shadow_ok else ["dynamic_nfc_proof_invalid"],
                }
            except NfcKeyRevokedError as exc:
                shadow_nfc_verification = {
                    "verified": False,
                    "disposition": "deny",
                    "reason_code": "nfc_key_revoked",
                    "issues": [str(exc)],
                }
            except NfcKmsUnavailableError as exc:
                shadow_nfc_verification = {
                    "verified": False,
                    "disposition": "quarantine",
                    "reason_code": "nfc_kms_unavailable",
                    "issues": [str(exc)],
                }

    common["shadow_nfc_verification"] = shadow_nfc_verification

    if payload.tamper_state != "clear":
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="hardware_tamper_detected",
            issues=["hardware_tamper_detected"],
            **common,
        )

    return _result(
        verified=True,
        disposition="allow",
        reason_code="rct_nfc_scan_verified",
        issues=[],
        **common,
    )


def verify_dynamic_nfc_evidence_with_counter_ledger(
    evidence: Mapping[str, Any] | DynamicNfcEvidence,
    context: Mapping[str, Any] | NfcVerificationContext,
    *,
    counter_ledger: Any,
    clock: Callable[[], datetime] | None = None,
) -> NfcVerificationResult:
    from seedcore.ops.evidence.nfc_counter_ledger import CounterStoreError

    try:
        model = evidence if isinstance(evidence, DynamicNfcEvidence) else DynamicNfcEvidence.model_validate(dict(evidence))
        ctx = context if isinstance(context, NfcVerificationContext) else NfcVerificationContext.model_validate(dict(context))
    except Exception:
        return _result(
            verified=False,
            disposition="quarantine",
            reason_code="nfc_payload_incomplete",
            issues=["nfc_payload_incomplete"],
        )

    payload = model.nfc_payload
    try:
        highest_observed = counter_ledger.get_highest_counter(
            nfc_uid_hash=payload.nfc_uid_hash,
            anchor_profile_ref=payload.anchor_profile_ref,
        )
    except CounterStoreError as exc:
        return _counter_store_unavailable_result(exc)

    result = verify_dynamic_nfc_evidence(
        model,
        ctx.model_copy(update={"highest_observed_scan_counter": highest_observed}),
        clock=clock,
    )
    if result.disposition != "allow":
        return result

    try:
        admission = counter_ledger.admit_counter(
            nfc_uid_hash=payload.nfc_uid_hash,
            anchor_profile_ref=payload.anchor_profile_ref,
            scan_counter=payload.scan_counter,
            workflow_join_key=payload.workflow_join_key,
            observed_at=model.observed_at,
        )
    except CounterStoreError as exc:
        return _counter_store_unavailable_result(exc, base=result)

    if not admission.admitted:
        return result.model_copy(
            update={
                "verified": False,
                "disposition": "deny",
                "reason_code": "dynamic_nfc_proof_invalid",
                "issues": ["dynamic_nfc_proof_invalid"],
                "current_highest_scan_counter": admission.current_highest,
            }
        )
    return result.model_copy(update={"current_highest_scan_counter": highest_observed})


def anchor_counter_key(*, nfc_uid_hash: str, anchor_profile_ref: str) -> str:
    return f"{str(nfc_uid_hash).strip()}|{str(anchor_profile_ref).strip()}"


def expected_fixture_challenge_response_hash(
    *,
    mock_root_key: str,
    nfc_uid_hash: str,
    anchor_profile_ref: str,
    cmac_ref: str,
    asset_ref: str,
    workflow_join_key: str,
    challenge_nonce: str,
    scan_counter: int,
) -> str:
    tag_material = f"{nfc_uid_hash}|{anchor_profile_ref}|{cmac_ref}"
    tag_key = hmac.new(
        str(mock_root_key).encode("utf-8"),
        tag_material.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    response_material = f"{asset_ref}|{workflow_join_key}|{challenge_nonce}|{scan_counter}"
    return "sha256:" + hmac.new(tag_key, response_material.encode("utf-8"), hashlib.sha256).hexdigest()


def _effective_freshness_seconds(
    evidence: DynamicNfcEvidence,
    *,
    clock: Callable[[], datetime] | None,
) -> int:
    observed = _ensure_utc(evidence.observed_at)
    stated = int(evidence.freshness_seconds)
    if clock is None:
        return stated
    now = _ensure_utc(clock())
    observed_age = max(0, int((now - observed).total_seconds()))
    return max(stated, observed_age)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")


def _result(
    *,
    verified: bool,
    disposition: NfcDisposition,
    reason_code: str,
    issues: list[str],
    **kwargs: Any,
) -> NfcVerificationResult:
    return NfcVerificationResult(
        verified=verified,
        disposition=disposition,
        reason_code=reason_code,
        issues=issues,
        **kwargs,
    )


def _counter_store_unavailable_result(
    exc: Exception,
    *,
    base: NfcVerificationResult | None = None,
) -> NfcVerificationResult:
    update = {
        "verified": False,
        "disposition": "quarantine",
        "reason_code": "counter_store_unavailable",
        "issues": [f"counter_store_unavailable: {exc}"],
    }
    if base is not None:
        return base.model_copy(update=update)
    return _result(
        verified=False,
        disposition="quarantine",
        reason_code="counter_store_unavailable",
        issues=update["issues"],
    )
