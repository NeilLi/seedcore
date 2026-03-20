from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.api.external_authority import (
    DIDRegistrationRequest,
    DIDUpdateRequest,
    DelegationGrantRequest,
    DelegationRevokeRequest,
    SignedIntentSubmissionRequest,
    build_owner_twin_snapshot,
    get_delegation,
    get_did_document,
    grant_delegation,
    patch_did_document,
    revoke_delegation,
    upsert_did_document,
    verify_signed_intent_submission,
)
from seedcore.coordinator.core.governance import build_governance_context
from seedcore.database import get_async_pg_session


router = APIRouter(tags=["identity"])


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
