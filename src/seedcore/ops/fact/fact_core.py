import uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional

from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # pyright: ignore[reportMissingImports]

# Import your baseline database connector
from seedcore.database import get_async_pg_session_factory
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.ops.fact.fact_core")
logger = ensure_serve_logger("seedcore.ops.fact.fact_core", level="DEBUG")


class FactCore:
    """
    FactCore: High-performance repository for Facts, Lineage, and PKG Governance.

    This core bridges the gap between Python and the Migration SQL (011, 012, 016).
    It handles:
    - SPO (Subject-Predicate-Object) temporal facts (Mig 011, 016)
    - HGNN Lineage tracking (Mig 012)
    - PKG Policy integration (Mig 011, 016)
    - Optimized analytics via DB functions (Mig 016)
    
    Note: Migration 011 creates the facts table with all columns including
    tags, meta_data, and PKG fields. Migration 016 adds foreign keys and
    helper functions.
    """

    def __init__(
        self, session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    ):
        self.session_factory = session_factory or get_async_pg_session_factory()

    # -------------------------------------------------------------------------
    # 1. Lineage & HGNN Integration (Migration 012)
    # -------------------------------------------------------------------------

    async def record_lineage(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        fact_ids: List[uuid.UUID],
        relationship: str = "produces",
    ):
        """
        Records the relationship between a Task and Facts in the HGNN.
        Relies on Mig 012 tables: task_produces_fact / task_reads_fact.
        
        Uses batch operations for better performance when recording multiple facts.
        """
        if not fact_ids:
            return
            
        table = (
            "task_produces_fact" if relationship == "produces" else "task_reads_fact"
        )

        # Ensure Task exists in HGNN node map
        await session.execute(
            text("SELECT ensure_task_node(CAST(:tid AS uuid))"), 
            {"tid": str(task_id)}
        )

        # Ensure all Facts exist in HGNN node map (batch operation)
        await session.execute(
            text(
                "SELECT ensure_fact_node(fact_id) "
                "FROM unnest(CAST(:fact_ids AS uuid[])) AS fact_id"
            ),
            {"fact_ids": [str(fid) for fid in fact_ids]},
        )

        # Insert edges in batch
        await session.execute(
            text(f"""
                WITH payload AS (
                    SELECT CAST(:task_id AS uuid) AS task_id, 
                           unnest(CAST(:fact_ids AS uuid[])) AS fact_id
                )
                INSERT INTO {table} (task_id, fact_id)
                SELECT task_id, fact_id FROM payload
                ON CONFLICT (task_id, fact_id) DO NOTHING
            """),
            {
                "task_id": str(task_id),
                "fact_ids": [str(fid) for fid in fact_ids],
            },
        )

    # -------------------------------------------------------------------------
    # 2. Fact Creation & Governance (Migration 011 & 016)
    # -------------------------------------------------------------------------

    async def save_fact(
        self,
        text_content: str,
        namespace: str = "default",
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object_data: Optional[Dict] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        produced_by_task: Optional[uuid.UUID] = None,
        pkg_metadata: Optional[Dict] = None,
        created_by: str = "system",
        tags: Optional[List[str]] = None,
        meta_data: Optional[Dict] = None,
    ) -> uuid.UUID:
        """
        Creates a fact with full SPO and PKG support.
        
        Note: Migration 011 creates the facts table with all columns including
        tags and meta_data. Migration 016 sets valid_from = created_at for
        structured/PKG facts, but we set it explicitly here for new facts.
        """
        async with self.session_factory() as session:
            # Insert using the schema from Migration 011 (all columns defined there)
            # Use CAST for JSONB columns to ensure proper type handling
            sql = text("""
                INSERT INTO public.facts (
                    text, namespace, subject, predicate, object_data,
                    valid_from, valid_to, created_by,
                    snapshot_id, pkg_rule_id, pkg_provenance, validation_status,
                    tags, meta_data
                ) VALUES (
                    :txt, :ns, :sub, :pred, 
                    CASE WHEN :obj IS NULL THEN NULL ELSE CAST(:obj AS jsonb) END,
                    :v_from, :v_to, :by,
                    :snap, :rule, 
                    CASE WHEN :prov IS NULL THEN NULL ELSE CAST(:prov AS jsonb) END,
                    :v_status,
                    :tags, 
                    CASE WHEN :meta IS NULL THEN NULL ELSE CAST(:meta AS jsonb) END
                ) RETURNING id
            """)

            pkg = pkg_metadata or {}
            
            # Set valid_from for structured/PKG facts (consistent with migration 016 logic)
            # If not provided and it's a structured fact or PKG-governed, set to now()
            should_set_valid_from = (
                valid_from is None 
                and (subject is not None or pkg.get("rule_id") is not None)
            )
            
            params = {
                "txt": text_content,
                "ns": namespace,
                "sub": subject,
                "pred": predicate,
                # Pass dict directly - CAST in SQL will handle JSONB conversion
                "obj": object_data,
                "v_from": valid_from if valid_from is not None else (
                    datetime.now(timezone.utc) if should_set_valid_from else None
                ),
                "v_to": valid_to,
                "by": created_by,
                "snap": pkg.get("snapshot_id"),
                "rule": pkg.get("rule_id"),
                # Pass dict directly - CAST in SQL will handle JSONB conversion
                "prov": pkg.get("provenance"),
                "v_status": pkg.get("validation_status"),
                "tags": tags or [],
                "meta": meta_data,
            }

            result = await session.execute(sql, params)
            fact_id = result.scalar()

            # Record Lineage if task provided (Mig 012)
            if produced_by_task:
                await self.record_lineage(
                    session, produced_by_task, [fact_id], "produces"
                )

            await session.commit()
            return fact_id

    # -------------------------------------------------------------------------
    # 3. Optimized Queries (Migration 016 Functions & Views)
    # -------------------------------------------------------------------------

    async def fetch_active_facts(
        self, subject: str, namespace: str = "default"
    ) -> List[Dict]:
        """
        Uses the 'get_facts_by_subject' function from Migration 016.
        This handles temporal filtering (valid_from/to) automatically.
        """
        async with self.session_factory() as session:
            sql = text("SELECT * FROM get_facts_by_subject(:sub, :ns, false)")
            result = await session.execute(sql, {"sub": subject, "ns": namespace})
            return [dict(row._mapping) for row in result]

    async def get_cortex_stats(self, namespace: Optional[str] = None) -> Dict:
        """
        Uses the 'get_fact_statistics' function from Migration 016.
        Returns a high-level summary of total, temporal, and expired facts.
        """
        async with self.session_factory() as session:
            sql = text("SELECT * FROM get_fact_statistics(:ns)")
            result = await session.execute(sql, {"ns": namespace})
            row = result.fetchone()
            return dict(row._mapping) if row else {}

    # -------------------------------------------------------------------------
    # 4. Maintenance (Migration 016)
    # -------------------------------------------------------------------------

    async def purge_expired(self, namespace: Optional[str] = None) -> int:
        """
        Calls the 'cleanup_expired_facts' procedure from Migration 016.
        """
        async with self.session_factory() as session:
            sql = text("SELECT cleanup_expired_facts(:ns, false)")
            result = await session.execute(sql, {"ns": namespace})
            count = result.scalar()
            await session.commit()
            logger.info(
                f"Purged {count} expired facts from namespace: {namespace or 'ALL'}"
            )
            return count
