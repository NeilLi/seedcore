from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.api.external_authority import (
    CreatorProfileUpsertRequest,
    OwnerPolicyUpsertRequest,
    OwnerContextPreflightRequest,
    DIDRegistrationRequest,
    DIDUpdateRequest,
    DelegationGrantRequest,
    DelegationRevokeRequest,
    SignedIntentSubmissionRequest,
    TrustPreferencesUpsertRequest,
    build_owner_twin_snapshot,
    get_creator_profile,
    get_delegation,
    get_did_document,
    get_owner_policy,
    get_trust_preferences,
    grant_delegation,
    patch_did_document,
    revoke_delegation,
    upsert_creator_profile,
    upsert_did_document,
    upsert_owner_policy,
    upsert_trust_preferences,
    verify_signed_intent_submission,
)
from seedcore.coordinator.core.governance import build_governance_context
from seedcore.database import get_async_pg_session
from seedcore.ops.evidence.owner_context import owner_context_hash as build_owner_context_hash


router = APIRouter(tags=["identity"])


def _provenance_rank(level: str | None) -> int:
    normalized = str(level or "").strip().lower()
    order = {"none": 0, "basic": 1, "verified": 2, "certified": 3}
    return int(order.get(normalized, 0))


@router.post("/identities/dids")
async def register_did(
    payload: DIDRegistrationRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await upsert_did_document(session, payload)
    return record.model_dump(mode="json")


@router.patch("/identities/dids/{did}")
async def update_did(
    did: str,
    patch: DIDUpdateRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await patch_did_document(session, did, patch)
    if record is None:
        raise HTTPException(status_code=404, detail=f"DID '{did}' not found")
    return record.model_dump(mode="json")


@router.get("/identities/dids/{did}")
async def fetch_did(
    did: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await get_did_document(session, did)
    if record is None:
        raise HTTPException(status_code=404, detail=f"DID '{did}' not found")
    return record.model_dump(mode="json")


@router.post("/delegations")
async def create_delegation(
    payload: DelegationGrantRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    owner = await get_did_document(session, payload.owner_id)
    assistant = await get_did_document(session, payload.assistant_id)
    if owner is None:
        raise HTTPException(status_code=404, detail=f"Owner DID '{payload.owner_id}' not found")
    if assistant is None:
        raise HTTPException(status_code=404, detail=f"Assistant DID '{payload.assistant_id}' not found")
    record = await grant_delegation(session, payload)
    return record.model_dump(mode="json")


@router.post("/delegations/{delegation_id}/revoke")
async def revoke_delegation_endpoint(
    delegation_id: str,
    payload: DelegationRevokeRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await revoke_delegation(session, delegation_id, reason=payload.reason)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Delegation '{delegation_id}' not found")
    return record.model_dump(mode="json")


@router.get("/delegations/{delegation_id}")
async def fetch_delegation(
    delegation_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await get_delegation(session, delegation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Delegation '{delegation_id}' not found")
    return record.model_dump(mode="json")


@router.post("/intents/submit-signed")
async def submit_signed_intent(
    payload: SignedIntentSubmissionRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    verified, error, did_document = await verify_signed_intent_submission(session, payload)
    if not verified:
        raise HTTPException(status_code=400, detail=f"Signed intent rejected: {error}")

    relevant_twin_snapshot: dict[str, object] = {}
    if payload.owner_id:
        owner_twin = await build_owner_twin_snapshot(session, payload.owner_id)
        relevant_twin_snapshot["owner"] = owner_twin.model_dump(mode="json")

    context = build_governance_context(
        payload.action_intent,
        relevant_twin_snapshot=relevant_twin_snapshot or None,
    )
    context["external_submission"] = {
        "verified": True,
        "signer_did": did_document.did if did_document is not None else payload.signer_did,
        "signing_scheme": payload.signing_scheme,
        "key_ref": payload.key_ref or (did_document.verification_method.key_ref if did_document else None),
        "nonce": payload.nonce,
        "signed_at": payload.signed_at,
        "owner_id": payload.owner_id,
    }
    return context


@router.post("/creator-profiles")
async def upsert_creator_profile_endpoint(
    payload: CreatorProfileUpsertRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await upsert_creator_profile(session, payload)
    return record.model_dump(mode="json")


@router.get("/creator-profiles/{owner_id}")
async def fetch_creator_profile(
    owner_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await get_creator_profile(session, owner_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Creator profile for owner '{owner_id}' not found")
    return record.model_dump(mode="json")


@router.post("/trust-preferences")
async def upsert_trust_preferences_endpoint(
    payload: TrustPreferencesUpsertRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await upsert_trust_preferences(session, payload)
    return record.model_dump(mode="json")


@router.get("/trust-preferences/{owner_id}")
async def fetch_trust_preferences(
    owner_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await get_trust_preferences(session, owner_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Trust preferences for owner '{owner_id}' not found")
    return record.model_dump(mode="json")


@router.post("/owner-policies")
async def upsert_owner_policy_endpoint(
    payload: OwnerPolicyUpsertRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await upsert_owner_policy(session, payload)
    return record.model_dump(mode="json")


@router.get("/owner-policies/{owner_id}")
async def fetch_owner_policy(
    owner_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await get_owner_policy(session, owner_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Owner policy for owner '{owner_id}' not found")
    return record.model_dump(mode="json")


@router.post("/owner-context/preflight")
async def owner_context_preflight(
    payload: OwnerContextPreflightRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    owner_id = str(payload.owner_id or "").strip()
    if not owner_id:
        raise HTTPException(status_code=422, detail="owner_id is required")
    assistant_id = str(payload.assistant_id or "").strip() or None
    delegation_id = str(payload.delegation_id or "").strip() or None
    merchant_ref = str(payload.merchant_ref or "").strip() or None
    observed_provenance_level = str(payload.observed_provenance_level or "").strip() or None
    declared_value_usd = payload.declared_value_usd
    risk_score = payload.risk_score

    required_modalities = [
        str(item).strip() for item in payload.required_modalities if str(item).strip()
    ]
    available_modalities = [
        str(item).strip() for item in payload.available_modalities if str(item).strip()
    ]

    warnings: list[str] = []
    owner_identity = await get_did_document(session, owner_id)
    if owner_identity is None:
        warnings.append("owner_identity_unavailable")
    creator_profile = await get_creator_profile(session, owner_id)
    if creator_profile is None:
        warnings.append("creator_profile_unavailable")
    trust_preferences_record = await get_trust_preferences(session, owner_id)
    if trust_preferences_record is None:
        warnings.append("trust_preferences_unavailable")
    trust_preferences = trust_preferences_record.model_dump(mode="json") if trust_preferences_record else {}

    signer_did = owner_identity.did if owner_identity is not None else owner_id
    signer_key_ref = (
        owner_identity.verification_method.key_ref
        if owner_identity is not None and owner_identity.verification_method is not None
        else None
    )
    owner_context_ref = {
        "owner_id": owner_id,
        "creator_profile_ref": (
            {
                "owner_id": owner_id,
                "version": creator_profile.version,
                "updated_at": creator_profile.updated_at,
                "updated_by": creator_profile.updated_by,
                "source_namespace": "identity",
                "source_predicate": "creator_profile",
                "signer_did": signer_did,
                "signer_key_ref": signer_key_ref,
            }
            if creator_profile is not None
            else None
        ),
        "trust_preferences_ref": (
            {
                "owner_id": owner_id,
                "trust_version": trust_preferences_record.trust_version,
                "updated_at": trust_preferences_record.updated_at,
                "updated_by": trust_preferences_record.updated_by,
                "source_namespace": "identity",
                "source_predicate": "trust_preferences",
                "signer_did": signer_did,
                "signer_key_ref": signer_key_ref,
            }
            if trust_preferences_record is not None
            else None
        ),
    }
    owner_context_hash = build_owner_context_hash(owner_context_ref)

    delegation_check: dict[str, Any] = {
        "checked": bool(delegation_id),
        "delegation_id": delegation_id,
        "valid": None,
        "issues": [],
    }
    if delegation_id:
        delegation = await get_delegation(session, delegation_id)
        if delegation is None:
            delegation_check["issues"].append("delegation_not_found")
            delegation_check["valid"] = False
        else:
            delegation_payload = delegation.model_dump(mode="json")
            delegation_check["record"] = delegation_payload
            status = str(delegation_payload.get("status") or "").strip().upper()
            delegation_owner = str(delegation_payload.get("owner_id") or "").strip()
            delegation_assistant = str(delegation_payload.get("assistant_id") or "").strip()
            if status != "ACTIVE":
                delegation_check["issues"].append("delegation_not_active")
            if delegation_owner and delegation_owner != owner_id:
                delegation_check["issues"].append("delegation_owner_mismatch")
            if assistant_id and delegation_assistant and delegation_assistant != assistant_id:
                delegation_check["issues"].append("delegation_assistant_mismatch")
            delegation_check["valid"] = len(delegation_check["issues"]) == 0

    trust_gap_codes: list[str] = []
    reason_codes: list[str] = []

    def _add_gap(code: str, reason_code: str) -> None:
        if code not in trust_gap_codes:
            trust_gap_codes.append(code)
        if reason_code not in reason_codes:
            reason_codes.append(reason_code)

    if isinstance(trust_preferences.get("max_risk_score"), (int, float)) and isinstance(risk_score, (int, float)):
        if float(risk_score) > float(trust_preferences["max_risk_score"]):
            _add_gap("owner_trust_risk_escalation", "owner_trust_risk_threshold_exceeded")

    if isinstance(trust_preferences.get("high_value_step_up_threshold_usd"), (int, float)) and isinstance(
        declared_value_usd, (int, float)
    ):
        if float(declared_value_usd) >= float(trust_preferences["high_value_step_up_threshold_usd"]):
            _add_gap("owner_trust_high_value_step_up", "owner_trust_high_value_threshold_exceeded")

    allowlist = (
        [str(item).strip() for item in trust_preferences.get("merchant_allowlist", []) if str(item).strip()]
        if isinstance(trust_preferences.get("merchant_allowlist"), list)
        else []
    )
    if merchant_ref and allowlist and merchant_ref not in set(allowlist):
        _add_gap("owner_trust_merchant_violation", "owner_trust_merchant_not_allowlisted")

    required_level = str(trust_preferences.get("required_provenance_level") or "").strip().lower()
    if required_level:
        observed_level = str(observed_provenance_level or "").strip().lower()
        if not observed_level:
            _add_gap("owner_trust_provenance_violation", "owner_trust_provenance_missing")
        elif _provenance_rank(observed_level) < _provenance_rank(required_level):
            _add_gap("owner_trust_provenance_violation", "owner_trust_provenance_insufficient_level")

    policy_required_modalities = (
        [str(item).strip() for item in trust_preferences.get("required_evidence_modalities", []) if str(item).strip()]
        if isinstance(trust_preferences.get("required_evidence_modalities"), list)
        else []
    )
    combined_required = sorted(set(policy_required_modalities + required_modalities))
    available = sorted(set(available_modalities))
    missing_modalities = sorted(set(combined_required) - set(available)) if combined_required else []
    if missing_modalities:
        _add_gap("owner_trust_modality_violation", "owner_trust_modalities_missing")

    return {
        "ok": not trust_gap_codes and (delegation_check["valid"] is not False),
        "owner_id": owner_id,
        "assistant_id": assistant_id,
        "owner_context_hash": owner_context_hash,
        "owner_context_ref": owner_context_ref,
        "delegation_check": delegation_check,
        "predicted_policy_signals": {
            "trust_gap_codes": trust_gap_codes,
            "reason_codes": reason_codes,
            "missing_modalities": missing_modalities,
        },
        "inputs": {
            "merchant_ref": merchant_ref,
            "declared_value_usd": declared_value_usd,
            "observed_provenance_level": observed_provenance_level,
            "risk_score": risk_score,
            "required_modalities": required_modalities,
            "available_modalities": available_modalities,
        },
        "warnings": warnings,
    }
