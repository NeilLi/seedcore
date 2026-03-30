from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.coordinator.dao import TransferApprovalEnvelopeDAO
from seedcore.database import get_async_pg_session


router = APIRouter(tags=["transfer-approvals"])
_DAO = TransferApprovalEnvelopeDAO()


class TransferApprovalCreateRequest(BaseModel):
    envelope: Dict[str, Any] = Field(default_factory=dict)


class TransferApprovalTransitionRequest(BaseModel):
    transition: Dict[str, Any] = Field(default_factory=dict)
    actor_ref: Optional[str] = None
    occurred_at: Optional[str] = None


@router.post("/transfer-approvals")
async def create_transfer_approval(
    payload: TransferApprovalCreateRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    try:
        record = await _DAO.create_or_update_envelope(session, envelope=payload.envelope)
        await session.commit()
        return record
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/transfer-approvals/{approval_envelope_id}")
async def fetch_transfer_approval(
    approval_envelope_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await _DAO.get_current_with_history(
        session,
        approval_envelope_id=approval_envelope_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"approval envelope '{approval_envelope_id}' not found")
    return record


@router.get("/transfer-approvals/{approval_envelope_id}/versions/{version}")
async def fetch_transfer_approval_version(
    approval_envelope_id: str,
    version: int,
    session: AsyncSession = Depends(get_async_pg_session),
):
    record = await _DAO.get_version(
        session,
        approval_envelope_id=approval_envelope_id,
        version=version,
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"approval envelope '{approval_envelope_id}' version '{version}' not found",
        )
    return record


@router.post("/transfer-approvals/{approval_envelope_id}/transitions")
async def apply_transfer_approval_transition(
    approval_envelope_id: str,
    payload: TransferApprovalTransitionRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    try:
        record = await _DAO.apply_transition(
            session,
            approval_envelope_id=approval_envelope_id,
            transition=payload.transition,
            actor_ref=payload.actor_ref,
            occurred_at=payload.occurred_at,
        )
        await session.commit()
        return record
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
