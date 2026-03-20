from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.database import get_async_pg_session
from seedcore.services.custody_graph_service import CustodyGraphService


router = APIRouter(tags=["custody"])
custody_graph_service = CustodyGraphService()


class DisputeCreateRequest(BaseModel):
    title: str
    summary: Optional[str] = None
    opened_by: Optional[str] = None
    references: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DisputeEventRequest(BaseModel):
    actor_id: Optional[str] = None
    note: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[str] = None


class DisputeResolveRequest(BaseModel):
    status: str
    resolved_by: Optional[str] = None
    resolution: Optional[str] = None


@router.get("/custody/assets/{asset_id}/lineage")
async def get_asset_lineage(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_pg_session),
):
    return await custody_graph_service.get_asset_lineage(session, asset_id=asset_id, limit=limit)


@router.get("/custody/assets/{asset_id}/transitions")
async def get_asset_transitions(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_pg_session),
):
    return {
        "asset_id": asset_id,
        "transitions": await custody_graph_service.get_asset_transitions(session, asset_id=asset_id, limit=limit),
    }


@router.get("/custody/assets/{asset_id}/graph")
async def get_asset_graph(
    asset_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_pg_session),
):
    return await custody_graph_service.get_asset_graph(session, asset_id=asset_id, limit=limit)


@router.get("/custody/query")
async def query_custody(
    asset_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    task_id: Optional[str] = None,
    token_id: Optional[str] = None,
    zone: Optional[str] = None,
    actor_agent_id: Optional[str] = None,
    endpoint_id: Optional[str] = None,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    dispute_status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_pg_session),
):
    return await custody_graph_service.query(
        session,
        asset_id=asset_id,
        intent_id=intent_id,
        task_id=task_id,
        token_id=token_id,
        zone=zone,
        actor_agent_id=actor_agent_id,
        endpoint_id=endpoint_id,
        from_time=custody_graph_service.parse_datetime(from_time),
        to_time=custody_graph_service.parse_datetime(to_time),
        dispute_status=dispute_status,
        limit=limit,
    )


@router.get("/custody/disputes")
async def list_disputes(
    status: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_pg_session),
):
    return {
        "disputes": await custody_graph_service.list_disputes(session, status=status, asset_id=asset_id, limit=limit),
    }


@router.get("/custody/disputes/{dispute_id}")
async def get_dispute(
    dispute_id: str,
    session: AsyncSession = Depends(get_async_pg_session),
):
    dispute = await custody_graph_service.get_dispute(session, dispute_id=dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail=f"Dispute '{dispute_id}' not found")
    return dispute


@router.post("/custody/disputes")
async def create_dispute(
    payload: DisputeCreateRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    try:
        async with session.begin():
            dispute = await custody_graph_service.open_dispute(
                session,
                title=payload.title,
                summary=payload.summary,
                opened_by=payload.opened_by,
                references=payload.references,
                metadata=payload.metadata,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dispute


@router.post("/custody/disputes/{dispute_id}/events")
async def append_dispute_event(
    dispute_id: str,
    payload: DisputeEventRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    try:
        async with session.begin():
            event = await custody_graph_service.append_dispute_event(
                session,
                dispute_id=dispute_id,
                actor_id=payload.actor_id,
                note=payload.note,
                payload=payload.payload,
                status=payload.status,
            )
    except ValueError as exc:
        if "Unknown dispute_id" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return event


@router.post("/custody/disputes/{dispute_id}/resolve")
async def resolve_dispute(
    dispute_id: str,
    payload: DisputeResolveRequest,
    session: AsyncSession = Depends(get_async_pg_session),
):
    try:
        async with session.begin():
            dispute = await custody_graph_service.resolve_dispute(
                session,
                dispute_id=dispute_id,
                status=payload.status,
                resolved_by=payload.resolved_by,
                resolution=payload.resolution,
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if dispute is None:
        raise HTTPException(status_code=404, detail=f"Dispute '{dispute_id}' not found")
    return dispute
