from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from seedcore.ops.evidence.nfc_verification import verify_dynamic_nfc_evidence


PROVENANCE_CLASSES = Literal[
    "PLAYER_EXCLUSIVE",
    "PROTOTYPE_SAMPLE",
    "LIMITED_RETAIL_RUN",
    "SIGNED_PAIR",
    "GENERAL_COLLECTIBLE",
]

AUTHENTICATION_STATUS = Literal["pending", "approved", "rejected", "expired", "quarantined"]
CUSTODY_STATE = Literal[
    "REGISTRATION_PENDING",
    "AUTHENTICATED_REGISTERED",
    "VAULTED_SECURE",
    "PENDING_TRADE_AUTHORITY",
    "IN_TRANSIT_BONDED",
    "DELIVERED_OPERATOR_CUSTODY",
]
RISK_STATE = Literal[
    "CLEAR",
    "PENDING_TELEMETRY",
    "QUARANTINED_ANOMALY",
    "ISOLATED_SECURITY_EVENT",
    "LEGAL_LOCK",
    "DISPUTED",
]

RARE_SHOE_FIXTURE_NFC_ROOT_KEY = "seedcore-rare-shoe-fixture-nfc-root-v1"


RARE_SHOE_ALLOWED_PUBLIC_PROOF_KEYS = frozenset(
    {
        "asset_id",
        "product_ref",
        "provenance_class",
        "authentication_verdict",
        "condition_grade_summary",
        "current_custody_state",
        "current_risk_state",
        "public_proof_hash",
        "forensic_video_proof_ref",
        "forensic_video_hash",
        "replay_reference",
        "verification_url",
    }
)

RARE_SHOE_FORBIDDEN_PUBLIC_PROOF_KEYS = frozenset(
    {
        "raw_telemetry_refs",
        "raw_nfc_uid",
        "challenge_nonce",
        "challenge_response_hash",
        "cmac_ref",
        "microscopic_image_hashes",
        "signer_key_ref",
        "approval_envelope",
        "device_attestation",
        "operator_reason_trace",
    }
)


def _required_str(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


def build_rare_shoe_workflow_join_key(
    *,
    asset_id: str,
    product_ref: str,
    quote_ref: str,
    order_ref: str,
    policy_snapshot_ref: str,
    valid_from: str,
    valid_until: str,
) -> str:
    authority_window = f"{valid_from.strip()}/{valid_until.strip()}"
    material = "|".join(
        [
            _required_str(asset_id, field_name="asset_id"),
            _required_str(product_ref, field_name="product_ref"),
            _required_str(quote_ref, field_name="quote_ref"),
            _required_str(order_ref, field_name="order_ref"),
            _required_str(policy_snapshot_ref, field_name="policy_snapshot_ref"),
            authority_window,
        ]
    )
    return "wf:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class RareShoeConditionGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grade: float = Field(ge=0, le=10)
    grader_ref: str
    graded_at: datetime
    restoration_flags: List[str] = Field(default_factory=list)

    @field_validator("grader_ref")
    @classmethod
    def _validate_required_str(cls, value: str) -> str:
        return _required_str(value, field_name="grader_ref")


class RareShoeHardwareAnchorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_profile_ref: str
    anchor_kind: Literal["dynamic_nfc", "rfid", "puf_backed", "fixture_dynamic_nfc"]
    tamper_state: Literal["clear", "tamper_detected", "unknown"]
    puf_attestation_ref: Optional[str] = None

    @field_validator("anchor_profile_ref")
    @classmethod
    def _validate_required_str(cls, value: str) -> str:
        return _required_str(value, field_name="anchor_profile_ref")


class CollectibleShoeRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_did: Optional[str] = None
    product_ref: str
    seller_ref: str
    brand_identifier: str
    style_code: str
    sku_serial_hash: str
    nfc_uid_hash: str
    hardware_anchor_profile: RareShoeHardwareAnchorProfile
    physical_fingerprint_refs: List[str] = Field(default_factory=list)
    provenance_class: PROVENANCE_CLASSES
    athlete_provenance_refs: List[str] = Field(default_factory=list)
    condition_grade: RareShoeConditionGrade
    authentication_status: AUTHENTICATION_STATUS
    authentication_payload_ref: str
    custody_state: CUSTODY_STATE
    risk_state: RISK_STATE
    policy_snapshot_ref: str
    registration_decision_ref: str
    workflow_join_key: Optional[str] = None

    @field_validator(
        "asset_id",
        "product_ref",
        "seller_ref",
        "brand_identifier",
        "style_code",
        "sku_serial_hash",
        "nfc_uid_hash",
        "authentication_payload_ref",
        "policy_snapshot_ref",
        "registration_decision_ref",
    )
    @classmethod
    def _validate_required_str(cls, value: str, info) -> str:
        return _required_str(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _require_transferable_registration(self) -> "CollectibleShoeRegistration":
        if self.custody_state != "REGISTRATION_PENDING" and self.authentication_status != "approved":
            raise ValueError("non-pending rare-shoe registrations require approved authentication evidence")
        if self.risk_state == "CLEAR" and self.hardware_anchor_profile.tamper_state != "clear":
            raise ValueError("clear risk state requires a clear hardware anchor tamper state")
        return self


class RareShoeBoundedCustodyAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_id: str
    asset_id: str
    workflow_join_key: str
    product_ref: str
    quote_ref: str
    order_ref: str
    policy_snapshot_ref: str
    authorized_actor_ref: str
    authorized_device_refs: List[str]
    valid_from: datetime
    valid_until: datetime
    from_zone: str
    to_zone: str
    max_delayed_submission_seconds: int = Field(default=300, ge=0)

    @field_validator(
        "authority_id",
        "asset_id",
        "workflow_join_key",
        "product_ref",
        "quote_ref",
        "order_ref",
        "policy_snapshot_ref",
        "authorized_actor_ref",
        "from_zone",
        "to_zone",
    )
    @classmethod
    def _validate_required_str(cls, value: str, info) -> str:
        return _required_str(value, field_name=info.field_name)

    @model_validator(mode="after")
    def _validate_window(self) -> "RareShoeBoundedCustodyAuthority":
        if self.valid_until <= self.valid_from:
            raise ValueError("authority valid_until must be after valid_from")
        if not self.authorized_device_refs:
            raise ValueError("authority requires at least one authorized device")
        return self


class RareShoeEdgeTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telemetry_id: str
    asset_id: str
    workflow_join_key: str
    authorized_device_ref: str
    edge_node_ref: str
    observed_at: datetime
    submitted_at: datetime
    nonce: str
    scan_kind: Literal["origin_scan", "delivery_scan"]
    zone_ref: str
    nfc_uid_hash: str
    scan_counter: int = Field(ge=0)
    challenge_nonce: str
    challenge_response_hash: str
    expected_challenge_response_hash: str
    cmac_ref: str
    expected_cmac_ref: str
    tamper_state: Literal["clear", "tamper_detected", "unknown"]
    anchor_profile_ref: str
    payload_sha256: str
    signer_key_ref: str
    signature_b64: str

    @field_validator(
        "telemetry_id",
        "asset_id",
        "workflow_join_key",
        "authorized_device_ref",
        "edge_node_ref",
        "nonce",
        "zone_ref",
        "nfc_uid_hash",
        "challenge_nonce",
        "challenge_response_hash",
        "expected_challenge_response_hash",
        "cmac_ref",
        "expected_cmac_ref",
        "anchor_profile_ref",
        "payload_sha256",
        "signer_key_ref",
        "signature_b64",
    )
    @classmethod
    def _validate_required_str(cls, value: str, info) -> str:
        return _required_str(value, field_name=info.field_name)


def validate_rare_shoe_public_proof_projection(public_proof: Mapping[str, Any]) -> Dict[str, Any]:
    keys = set(public_proof.keys())
    forbidden = sorted(keys & RARE_SHOE_FORBIDDEN_PUBLIC_PROOF_KEYS)
    unexpected = sorted(keys - RARE_SHOE_ALLOWED_PUBLIC_PROOF_KEYS)
    if forbidden or unexpected:
        return {
            "status": "review_required",
            "reason_code": "PUBLIC_PROOF_REDACTION_REQUIRED",
            "forbidden_keys": forbidden,
            "unexpected_keys": unexpected,
        }
    return {
        "status": "publishable",
        "reason_code": "PUBLIC_PROOF_SAFE",
        "forbidden_keys": [],
        "unexpected_keys": [],
    }


def evaluate_rare_shoe_edge_telemetry(
    *,
    telemetry: RareShoeEdgeTelemetry,
    authority: RareShoeBoundedCustodyAuthority,
    registration: CollectibleShoeRegistration,
    previous_scan_counter: int | None = None,
) -> Dict[str, Any]:
    issues: List[str] = []
    asset_mismatch = telemetry.asset_id != authority.asset_id or telemetry.asset_id != registration.asset_id
    if asset_mismatch:
        issues.append("CROSS_ASSET_REPLAY")
    if telemetry.authorized_device_ref not in authority.authorized_device_refs:
        issues.append("UNAUTHORIZED_EDGE_DEVICE")
    if telemetry.cmac_ref != telemetry.expected_cmac_ref:
        issues.append("DYNAMIC_NFC_PROOF_INVALID")

    nfc_result = verify_dynamic_nfc_evidence(
        {
            "observed_at": telemetry.observed_at,
            "freshness_seconds": max(0, int(telemetry.submitted_at.timestamp() - telemetry.observed_at.timestamp())),
            "max_allowed_age_seconds": authority.max_delayed_submission_seconds,
            "evidence_refs": [telemetry.telemetry_id],
            "nfc_payload": {
                "asset_ref": telemetry.asset_id,
                "workflow_join_key": telemetry.workflow_join_key,
                "nfc_uid_hash": telemetry.nfc_uid_hash,
                "scan_counter": telemetry.scan_counter,
                "challenge_nonce": telemetry.challenge_nonce,
                "challenge_response_hash": telemetry.challenge_response_hash,
                "cmac_ref": telemetry.cmac_ref,
                "tamper_state": telemetry.tamper_state,
                "anchor_profile_ref": telemetry.anchor_profile_ref,
            },
        },
        {
            "expected_asset_ref": registration.asset_id,
            "workflow_join_key": authority.workflow_join_key,
            "issued_challenge_nonce": telemetry.challenge_nonce,
            "registered_nfc_uid_hash": registration.nfc_uid_hash,
            "expected_anchor_profile_ref": registration.hardware_anchor_profile.anchor_profile_ref,
            "highest_observed_scan_counter": previous_scan_counter if previous_scan_counter is not None else -1,
            "mock_root_key": RARE_SHOE_FIXTURE_NFC_ROOT_KEY,
        },
    )
    nfc_issue = _legacy_rare_shoe_nfc_issue(nfc_result.reason_code)
    if nfc_issue is not None and not (asset_mismatch and nfc_issue == "HARDWARE_ANCHOR_MISMATCH"):
        issues.append(nfc_issue)

    if not (authority.valid_from <= telemetry.observed_at <= authority.valid_until):
        issues.append("TELEMETRY_OBSERVED_OUTSIDE_AUTHORITY_WINDOW")
    max_submitted_at = telemetry.observed_at.timestamp() + authority.max_delayed_submission_seconds
    if telemetry.submitted_at.timestamp() > max_submitted_at:
        issues.append("DELAYED_TELEMETRY_SUBMISSION_EXPIRED")

    verified = not issues
    return {
        "verified": verified,
        "disposition": "allow" if verified else "quarantine",
        "reason_code": "rare_shoe_edge_telemetry_verified" if verified else issues[0],
        "issues": issues,
        "nfc_verification": nfc_result.model_dump(mode="json"),
        "nfc_reason_code": nfc_result.reason_code,
    }


def _legacy_rare_shoe_nfc_issue(reason_code: str) -> Optional[str]:
    if reason_code == "rct_nfc_scan_verified":
        return None
    if reason_code == "nfc_asset_anchor_mismatch":
        return "HARDWARE_ANCHOR_MISMATCH"
    if reason_code == "nfc_workflow_binding_mismatch":
        return "WORKFLOW_JOIN_KEY_MISMATCH"
    if reason_code == "nfc_scan_too_stale":
        return "DELAYED_TELEMETRY_SUBMISSION_EXPIRED"
    if reason_code == "hardware_tamper_detected":
        return "HARDWARE_ANCHOR_TAMPER"
    if reason_code == "nfc_payload_incomplete":
        return "DYNAMIC_NFC_PROOF_INVALID"
    return "DYNAMIC_NFC_PROOF_INVALID"


def evaluate_rare_shoe_replay_bundle(bundle: Mapping[str, Any]) -> Dict[str, Any]:
    registration = CollectibleShoeRegistration.model_validate(bundle.get("registration"))
    authority = RareShoeBoundedCustodyAuthority.model_validate(bundle.get("bounded_custody_authority"))
    gateway_decision = bundle.get("gateway_decision") if isinstance(bundle.get("gateway_decision"), Mapping) else {}
    telemetry_items = [
        RareShoeEdgeTelemetry.model_validate(item)
        for item in bundle.get("edge_telemetry", [])
        if isinstance(item, Mapping)
    ]

    issues: List[str] = []
    if registration.authentication_status != "approved":
        issues.append("AUTHENTICATION_NOT_APPROVED")
    if gateway_decision.get("disposition") != "allow":
        issues.append(str(gateway_decision.get("reason_code") or "GATEWAY_DECISION_NOT_ALLOW"))
    if registration.asset_id != authority.asset_id:
        issues.append("CROSS_ASSET_REPLAY")
    if registration.workflow_join_key and registration.workflow_join_key != authority.workflow_join_key:
        issues.append("WORKFLOW_JOIN_KEY_MISMATCH")
    if len(telemetry_items) < 2:
        issues.append("CUSTODY_TELEMETRY_INCOMPLETE")

    previous_counter: int | None = None
    for telemetry in telemetry_items:
        result = evaluate_rare_shoe_edge_telemetry(
            telemetry=telemetry,
            authority=authority,
            registration=registration,
            previous_scan_counter=previous_counter,
        )
        issues.extend(result["issues"])
        previous_counter = telemetry.scan_counter

    public_result = validate_rare_shoe_public_proof_projection(
        bundle.get("public_proof_projection") if isinstance(bundle.get("public_proof_projection"), Mapping) else {}
    )
    if public_result["status"] != "publishable":
        issues.append(public_result["reason_code"])

    verified = not issues
    return {
        "verified": verified,
        "disposition": "allow" if verified else "quarantine",
        "reason_code": "rare_shoe_replay_verified" if verified else issues[0],
        "issues": issues,
        "public_proof": public_result,
        "workflow_join_key": authority.workflow_join_key,
        "asset_id": authority.asset_id,
        "product_ref": authority.product_ref,
        "quote_ref": authority.quote_ref,
        "order_ref": authority.order_ref,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
