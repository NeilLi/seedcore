# src/seedcore/api/routers/control_router.py (Optimized)
# Copyright 2024 SeedCore Contributors
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

# --- ADDED: Import DB session and the new Fact model ---
from ...database import get_async_pg_session
from ...models.fact import Fact

router = APIRouter(tags=["control"])

# --- Models can be simplified or removed if they match the DB model ---
class FactCreate(BaseModel):
    text: str = Field(..., description="Human or system supplied fact text")
    tags: List[str] = Field(default_factory=list)
    meta_data: Dict[str, Any] = Field(default_factory=dict)

class FactPatch(BaseModel):
    text: Optional[str] = None
    tags: Optional[List[str]] = None
    meta_data: Optional[Dict[str, Any]] = None

# ========== FACTS ==========
@router.get("/facts", response_model=Dict[str, Any])
async def list_facts(
    q: Optional[str] = Query(None, description="Substring match against text/metadata"),
    tag: Optional[str] = Query(None, description="Filter by a single tag"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_pg_session)
):
    query = select(Fact)
    if q:
        # Use ILIKE for case-insensitive search and cast meta_data to text
        query = query.where(or_(
            Fact.text.ilike(f"%{q}%"),
            Fact.meta_data.astext.ilike(f"%{q}%")
        ))
    if tag:
        # Use ANY for array contains operation
        query = query.where(Fact.tags.any(tag))

    # Get total count before applying limit/offset for pagination
    count_query = select(func.count()).select_from(query.alias())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Apply ordering, offset, and limit for the final result
    final_query = query.order_by(Fact.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(final_query)
    facts = result.scalars().all()
    
    return {"total": total, "items": [fact.to_dict() for fact in facts]}

@router.get("/facts/{fact_id}", response_model=Dict[str, Any])
async def get_fact(fact_id: uuid.UUID, session: AsyncSession = Depends(get_async_pg_session)):
    fact = await session.get(Fact, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
    return fact.to_dict()

@router.post("/facts", response_model=Dict[str, Any])
async def create_fact(payload: FactCreate, session: AsyncSession = Depends(get_async_pg_session)):
    new_fact = Fact(
        text=payload.text,
        tags=payload.tags,
        meta_data=payload.meta_data
    )
    session.add(new_fact)
    await session.commit()
    await session.refresh(new_fact)
    return new_fact.to_dict()

@router.patch("/facts/{fact_id}", response_model=Dict[str, Any])
async def patch_fact(fact_id: uuid.UUID, patch: FactPatch, session: AsyncSession = Depends(get_async_pg_session)):
    fact = await session.get(Fact, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
    
    update_data = patch.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fact, key, value)
        
    await session.commit()
    await session.refresh(fact)
    return fact.to_dict()

@router.delete("/facts/{fact_id}", response_model=Dict[str, Any])
async def delete_fact(fact_id: uuid.UUID, session: AsyncSession = Depends(get_async_pg_session)):
    fact = await session.get(Fact, fact_id)
    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
    
    await session.delete(fact)
    await session.commit()
    return {"deleted": str(fact_id)}

# ========== LEGACY TASKS (Removed) ==========
# The legacy task implementation has been fully replaced by the more robust
# database-backed tasks_router.py from the previous step.
# It is recommended to remove this conditional block entirely to avoid confusion
# and rely on the new, scalable task router.