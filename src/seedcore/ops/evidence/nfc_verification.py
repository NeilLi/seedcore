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
    if payload.nfc_uid_hash != ctx.registered_nfc_uid_hash or payload.anchor_profile_ref != ctx.expected_anchor_profile_ref:
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
    if payload.challenge_response_hash != expected_fixture_challenge_response_hash(
        mock_root_key=ctx.mock_root_key,
        nfc_uid_hash=payload.nfc_uid_hash,
        anchor_profile_ref=payload.anchor_profile_ref,
        cmac_ref=payload.cmac_ref,
        asset_ref=payload.asset_ref,
        workflow_join_key=payload.workflow_join_key,
        challenge_nonce=payload.challenge_nonce,
        scan_counter=payload.scan_counter,
    ):
        return _result(
            verified=False,
            disposition="deny",
            reason_code="dynamic_nfc_proof_invalid",
            issues=["dynamic_nfc_proof_invalid"],
            **common,
        )
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
