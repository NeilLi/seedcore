# src/seedcore/api/routers/control_router.py (Optimized)
# Copyright 2024 SeedCore Contributors
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, String

# --- ADDED: Import DB session and the new Fact model ---
from ...database import get_async_pg_session
from ...models.fact import Fact

router = APIRouter(tags=["control"])

# --- NEW: Short-UUID Resolution Helper ---
async def _resolve_fact_id(session: AsyncSession, fact_id_or_prefix: str) -> uuid.UUID:
    """Resolve a fact ID from either a full UUID or a short prefix."""
    try:
        # Try to parse as full UUID first
        return uuid.UUID(fact_id_or_prefix)
    except ValueError:
        # Treat as prefix - find facts that start with this prefix
        print(f"🔍 Resolving short fact ID: '{fact_id_or_prefix}'")
        query = select(Fact.id).where(
            Fact.id.cast(String).like(f"{fact_id_or_prefix}%")
        ).limit(2)
        
        result = await session.execute(query)
        rows = result.all()
        
        if len(rows) == 1:
            resolved_id = rows[0][0]
            print(f"✅ Resolved '{fact_id_or_prefix}' to full UUID: {resolved_id}")
            return resolved_id
        elif len(rows) > 1:
            print(f"⚠️  Ambiguous short ID '{fact_id_or_prefix}' - {len(rows)} facts match")
            raise HTTPException(
                status_code=409, 
                detail=f"Ambiguous short ID '{fact_id_or_prefix}' - multiple facts match"
            )
        else:
            print(f"❌ No facts found with prefix '{fact_id_or_prefix}'")
            raise HTTPException(
                status_code=404, 
                detail=f"Fact not found with ID prefix '{fact_id_or_prefix}'"
            )

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
    try:
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
        
        # Convert facts to dictionaries manually to avoid lazy loading issues
        fact_items = []
        for fact in facts:
            fact_items.append({
                "id": str(fact.id),
                "text": fact.text,
                "tags": fact.tags,
                "meta_data": fact.meta_data,
                "created_at": fact.created_at.isoformat() if fact.created_at else None,
                "updated_at": fact.updated_at.isoformat() if fact.updated_at else None
            })
        
        return {"total": total, "items": fact_items}
        
    except Exception as e:
        # Check if it's a table doesn't exist error
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            print(f"⚠️  Facts table doesn't exist yet. Please run database initialization first.")
            print(f"   Error: {e}")
            return {
                "total": 0,
                "items": [],
                "error": "Facts table not initialized. Please run database initialization first.",
                "details": str(e)
            }
        else:
            # Re-raise other errors
            print(f"❌ Error in list_facts: {e}")
            raise

@router.get("/facts/{fact_id}", response_model=Dict[str, Any])
async def get_fact(fact_id: str, session: AsyncSession = Depends(get_async_pg_session)):
    try:
        # Use short-ID resolution to handle both full UUIDs and prefixes
        resolved_id = await _resolve_fact_id(session, fact_id)
        fact = await session.get(Fact, resolved_id)
        if not fact:
            raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
        
        # Return the fact data - timestamps should be loaded since we're querying by ID
        return {
            "id": str(fact.id),
            "text": fact.text,
            "tags": fact.tags,
            "meta_data": fact.meta_data,
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
            "updated_at": fact.updated_at.isoformat() if fact.updated_at else None
        }
    except Exception as e:
        # Check if it's a table doesn't exist error
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            print(f"⚠️  Facts table doesn't exist yet. Please run database initialization first.")
            print(f"   Error: {e}")
            raise HTTPException(
                status_code=503, 
                detail="Facts table not initialized. Please run database initialization first."
            )
        else:
            # Re-raise other errors
            print(f"❌ Error in get_fact: {e}")
            raise

@router.post("/facts", response_model=Dict[str, Any])
async def create_fact(payload: FactCreate, session: AsyncSession = Depends(get_async_pg_session)):
    try:
        new_fact = Fact(
            text=payload.text,
            tags=payload.tags,
            meta_data=payload.meta_data
        )
        session.add(new_fact)
        await session.commit()
        
        # Get the fact with fresh data from database to avoid lazy loading issues
        # Use a new query to get the complete fact data
        result = await session.execute(select(Fact).where(Fact.id == new_fact.id))
        fresh_fact = result.scalar_one()
        
        # Return the fact data using the fresh fact object
        return {
            "id": str(fresh_fact.id),
            "text": fresh_fact.text,
            "tags": fresh_fact.tags,
            "meta_data": fresh_fact.meta_data,
            "created_at": fresh_fact.created_at.isoformat() if fresh_fact.created_at else None,
            "updated_at": fresh_fact.updated_at.isoformat() if fresh_fact.updated_at else None
        }
    except Exception as e:
        # Check if it's a table doesn't exist error
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            print(f"⚠️  Facts table doesn't exist yet. Please run database initialization first.")
            print(f"   Error: {e}")
            raise HTTPException(
                status_code=503, 
                detail="Facts table not initialized. Please run database initialization first."
            )
        else:
            # Re-raise other errors
            print(f"❌ Error in create_fact: {e}")
            raise

@router.patch("/facts/{fact_id}", response_model=Dict[str, Any])
async def patch_fact(fact_id: str, patch: FactPatch, session: AsyncSession = Depends(get_async_pg_session)):
    try:
        # Use short-ID resolution to handle both full UUIDs and prefixes
        resolved_id = await _resolve_fact_id(session, fact_id)
        fact = await session.get(Fact, resolved_id)
        if not fact:
            raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
        
        update_data = patch.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(fact, key, value)
            
        await session.commit()
        
        # Get the fact with fresh data from database to avoid lazy loading issues
        # Use a new query to get the complete fact data
        result = await session.execute(select(Fact).where(Fact.id == resolved_id))
        fresh_fact = result.scalar_one()
        
        # Return the fact data using the fresh fact object
        return {
            "id": str(fresh_fact.id),
            "text": fresh_fact.text,
            "tags": fresh_fact.tags,
            "meta_data": fresh_fact.meta_data,
            "created_at": fresh_fact.created_at.isoformat() if fresh_fact.created_at else None,
            "updated_at": fresh_fact.updated_at.isoformat() if fresh_fact.updated_at else None
        }
    except Exception as e:
        # Check if it's a table doesn't exist error
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            print(f"⚠️  Facts table doesn't exist yet. Please run database initialization first.")
            print(f"   Error: {e}")
            raise HTTPException(
                status_code=503, 
                detail="Facts table not initialized. Please run database initialization first."
            )
        else:
            # Re-raise other errors
            print(f"❌ Error in patch_fact: {e}")
            raise

@router.delete("/facts/{fact_id}", response_model=Dict[str, Any])
async def delete_fact(fact_id: str, session: AsyncSession = Depends(get_async_pg_session)):
    try:
        # Use short-ID resolution to handle both full UUIDs and prefixes
        resolved_id = await _resolve_fact_id(session, fact_id)
        fact = await session.get(Fact, resolved_id)
        if not fact:
            raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found")
        
        await session.delete(fact)
        await session.commit()
        return {"deleted": str(resolved_id)}
    except Exception as e:
        # Check if it's a table doesn't exist error
        if "relation" in str(e).lower() and "does not exist" in str(e).lower():
            print(f"⚠️  Facts table doesn't exist yet. Please run database initialization first.")
            print(f"   Error: {e}")
            raise HTTPException(
                status_code=503, 
                detail="Facts table not initialized. Please run database initialization first."
            )
        else:
            # Re-raise other errors
            print(f"❌ Error in delete_fact: {e}")
            raise

# ========== LEGACY TASKS (Removed) ==========
# The legacy task implementation has been fully replaced by the more robust
# database-backed tasks_router.py from the previous step.
# It is recommended to remove this conditional block entirely to avoid confusion
# and rely on the new, scalable task router.