#!/usr/bin/env python3
"""
Fact Manager Service - Unified fact management with PKG integration.

This service provides a unified interface for fact management, combining the enhanced
Fact model with eventizer processing and PKG governance capabilities.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Sequence, Tuple, Union, AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from sqlalchemy import select, delete, and_, or_, text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # pyright: ignore[reportMissingImports]

from ..models.fact import Fact
from .eventizer_service import EventizerService
from seedcore.models.eventizer import (
    EventizerRequest,
    EventizerResponse,
    EventizerConfig,
)
from seedcore.database import get_async_pg_session_factory

# Logging
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.fact_service.driver")
logger = ensure_serve_logger("seedcore.fact_service", level="DEBUG")


# --- 1. Shared Pydantic Models ---
class FactCreate(BaseModel):
    content: str = Field(..., min_length=1, description="Raw fact content")
    source: str = Field(default="user", description="Source of the fact")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FactQuery(BaseModel):
    query_text: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)


class FactResponse(BaseModel):
    id: str
    status: str
    message: str

class FactManagerImpl:
    """
    Unified fact management with PKG integration.

    This class provides a comprehensive interface for fact management, including:
    - Traditional fact creation and retrieval
    - Eventizer-based text processing and fact creation
    - PKG-governed temporal facts
    - Policy validation and provenance tracking
    - Automatic cleanup of expired facts
    """

    def __init__(
        self,
        db_session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        eventizer_config: Optional[EventizerConfig] = None,
    ):
        """
        Initialize the FactManagerImpl.

        Args:
            db_session_factory: Database session factory for fact operations.
                               If None, uses get_async_pg_session_factory() from database.py
            eventizer_config: Optional eventizer configuration
        """
        # Use provided factory or get default from database.py
        self.db_session_factory = db_session_factory or get_async_pg_session_factory()
        self.eventizer_config = eventizer_config or EventizerConfig()
        self._eventizer: Optional[EventizerService] = None
        self._initialized = False

    # -----------------
    # Internal helpers
    # -----------------

    @asynccontextmanager
    async def _get_db_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session from the factory."""
        async with self.db_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @staticmethod
    def _normalize_uuid(value: Optional[Union[str, uuid.UUID]]) -> Optional[uuid.UUID]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid UUID provided for task/fact relationship: %s", value
            )
            return None

    async def _ensure_task_node(self, db: AsyncSession, task_id: uuid.UUID) -> None:
        await db.execute(
            text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
            {"task_id": str(task_id)},
        )

    async def _ensure_fact_nodes(self, db: AsyncSession, fact_ids: Sequence[uuid.UUID]) -> None:
        if not fact_ids:
            return
        await db.execute(
            text(
                "SELECT ensure_fact_node(fact_id) "
                "FROM unnest(CAST(:fact_ids AS uuid[])) AS fact_id"
            ),
            {"fact_ids": [str(fid) for fid in fact_ids]},
        )

    async def _record_task_produces_fact(
        self,
        db: AsyncSession,
        task_id: Union[str, uuid.UUID],
        fact_id: Union[str, uuid.UUID],
    ) -> None:
        normalized_task_id = self._normalize_uuid(task_id)
        normalized_fact_id = self._normalize_uuid(fact_id)

        if not normalized_task_id or not normalized_fact_id:
            return

        await self._ensure_task_node(db, normalized_task_id)
        await self._ensure_fact_nodes(db, [normalized_fact_id])

        await db.execute(
            text(
                "INSERT INTO task_produces_fact(task_id, fact_id) "
                "VALUES (CAST(:task_id AS uuid), CAST(:fact_id AS uuid)) "
                "ON CONFLICT (task_id, fact_id) DO NOTHING"
            ),
            {
                "task_id": str(normalized_task_id),
                "fact_id": str(normalized_fact_id),
            },
        )

    async def _record_task_reads_fact(
        self,
        db: AsyncSession,
        task_id: Union[str, uuid.UUID],
        fact_ids: Sequence[Union[str, uuid.UUID]],
    ) -> None:
        normalized_task_id = self._normalize_uuid(task_id)
        normalized_fact_ids = [
            normalized
            for normalized in (self._normalize_uuid(fid) for fid in fact_ids)
            if normalized is not None
        ]

        if not normalized_task_id or not normalized_fact_ids:
            return

        # Deduplicate to avoid unnecessary work and conflicts
        unique_fact_ids = list(dict.fromkeys(normalized_fact_ids))

        await self._ensure_task_node(db, normalized_task_id)
        await self._ensure_fact_nodes(db, unique_fact_ids)

        await db.execute(
            text(
                "WITH payload AS ("
                "    SELECT CAST(:task_id AS uuid) AS task_id, unnest(CAST(:fact_ids AS uuid[])) AS fact_id"
                ")"
                "INSERT INTO task_reads_fact(task_id, fact_id) "
                "SELECT task_id, fact_id FROM payload "
                "ON CONFLICT (task_id, fact_id) DO NOTHING"
            ),
            {
                "task_id": str(normalized_task_id),
                "fact_ids": [str(fid) for fid in unique_fact_ids],
            },
        )

    async def initialize(self) -> None:
        """Initialize the eventizer service."""
        if self._initialized:
            return

        try:
            # Initialize eventizer service
            self._eventizer = EventizerService(config=self.eventizer_config)
            await self._eventizer.initialize()

            self._initialized = True
            logger.info("FactManagerImpl initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize FactManagerImpl: {e}")
            raise

    # -----------------
    # Basic Fact Operations
    # -----------------

    async def create_fact(
        self,
        fact_data: Union[FactCreate, Dict[str, Any], str],
        tags: Optional[List[str]] = None,
        namespace: str = "default",
        created_by: Optional[str] = None,
        produced_by_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Fact:
        """
        Create a basic fact.

        Args:
            fact_data: FactCreate model, dict, or text string (for backward compatibility)
            tags: Optional tags for the fact (merged with metadata tags if present)
            namespace: Fact namespace
            created_by: Creator identifier (overrides fact_data.source if provided)
            produced_by_task_id: Optional task ID that produced this fact

        Returns:
            Created Fact instance
        """
        async with self._get_db_session() as db:
            # Normalize input to FactCreate model
            if isinstance(fact_data, str):
                # Backward compatibility: treat string as content
                fact_create = FactCreate(content=fact_data)
            elif isinstance(fact_data, dict):
                fact_create = FactCreate(**fact_data)
            elif isinstance(fact_data, FactCreate):
                fact_create = fact_data
            else:
                raise ValueError(f"Invalid fact_data type: {type(fact_data)}")

            # Extract metadata and merge with tags
            meta_data = fact_create.metadata.copy() if fact_create.metadata else {}
            
            # Merge tags from metadata if present
            if tags is None:
                tags = meta_data.pop("tags", [])
            elif "tags" in meta_data:
                # Merge tags from metadata with provided tags
                tags = list(set(tags + meta_data.pop("tags", [])))

            # Use source from FactCreate or provided created_by
            creator = created_by if created_by is not None else fact_create.source

            fact = Fact(
                text=fact_create.content,
                tags=tags or [],
                meta_data=meta_data,
                namespace=namespace,
                created_by=creator,
            )

            db.add(fact)
            await db.flush()

            if produced_by_task_id:
                await self._record_task_produces_fact(db, produced_by_task_id, fact.id)

            await db.commit()
            await db.refresh(fact)

            logger.info(f"Created fact {fact.id} in namespace {namespace}")
            return fact

    async def get_fact(
        self,
        fact_id: str,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Optional[Fact]:
        """
        Get a fact by ID.

        Args:
            fact_id: UUID string of the fact

        Returns:
            Fact instance or None if not found
        """
        async with self._get_db_session() as db:
            query = select(Fact).where(Fact.id == fact_id)
            result = await db.execute(query)
            fact = result.scalar_one_or_none()

            if fact and reading_task_id:
                await self._record_task_reads_fact(db, reading_task_id, [fact.id])

            return fact

    async def get_facts_by_namespace(
        self,
        namespace: str,
        limit: int = 100,
        offset: int = 0,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Get facts by namespace.

        Args:
            namespace: Namespace to query
            limit: Maximum number of facts to return
            offset: Number of facts to skip

        Returns:
            List of Fact instances
        """
        async with self._get_db_session() as db:
            query = (
                select(Fact)
                .where(Fact.namespace == namespace)
                .order_by(Fact.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            result = await db.execute(query)
            facts = result.scalars().all()

            if facts and reading_task_id:
                await self._record_task_reads_fact(
                    db, reading_task_id, [fact.id for fact in facts]
                )

            return facts

    async def search_fact(
        self,
        query_data: Optional[Union[FactQuery, Dict[str, Any], str]] = None,
        tags: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        limit: Optional[int] = None,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Search facts with various criteria.

        Args:
            query_data: FactQuery model, dict, or query string (for backward compatibility)
            tags: Tags to filter by
            namespace: Namespace to filter by
            subject: Subject to filter by
            predicate: Predicate to filter by
            limit: Maximum number of facts to return (overrides FactQuery.limit if provided)
            reading_task_id: Optional task ID that read these facts

        Returns:
            List of matching Fact instances
        """
        async with self._get_db_session() as db:
            # Normalize input to FactQuery model
            if query_data is None:
                fact_query = FactQuery()
            elif isinstance(query_data, str):
                # Backward compatibility: treat string as query_text
                fact_query = FactQuery(query_text=query_data)
            elif isinstance(query_data, dict):
                fact_query = FactQuery(**query_data)
            elif isinstance(query_data, FactQuery):
                fact_query = query_data
            else:
                raise ValueError(f"Invalid query_data type: {type(query_data)}")

            # Use limit from FactQuery unless explicitly overridden
            search_limit = limit if limit is not None else fact_query.limit
            text_query = fact_query.query_text

            query = select(Fact)
            conditions = []

            if text_query:
                conditions.append(Fact.text.ilike(f"%{text_query}%"))

            if tags:
                for tag in tags:
                    conditions.append(Fact.tags.contains([tag]))

            if namespace:
                conditions.append(Fact.namespace == namespace)

            if subject:
                conditions.append(Fact.subject == subject)

            if predicate:
                conditions.append(Fact.predicate == predicate)

            if conditions:
                query = query.where(and_(*conditions))

            query = query.order_by(Fact.created_at.desc()).limit(search_limit)

            result = await db.execute(query)
            facts = result.scalars().all()

            if facts and reading_task_id:
                await self._record_task_reads_fact(
                    db, reading_task_id, [fact.id for fact in facts]
                )

            return facts

    # -----------------
    # Eventizer Integration
    # -----------------

    async def create_from_text(
        self,
        text: str,
        domain: str = "default",
        process_with_pkg: bool = True,
        preserve_pii: bool = False,
        produced_by_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Tuple[Fact, EventizerResponse]:
        """
        Create fact from text with eventizer processing.

        Args:
            text: Input text to process
            domain: Processing domain
            process_with_pkg: Whether to enable PKG processing
            preserve_pii: Whether to preserve PII in output

        Returns:
            Tuple of (created Fact, EventizerResponse)
        """
        if not self._initialized:
            await self.initialize()

        # Configure eventizer request
        request = EventizerRequest(
            text=text,
            domain=domain,
            preserve_pii=preserve_pii,
            include_pkg_hint=process_with_pkg,
        )

        # Process through eventizer
        response = await self._eventizer.process_text(request)

        # Create fact from response
        fact = Fact.create_from_eventizer(
            processed_text=response.processed_text,
            event_types=[tag.value for tag in response.event_tags.event_types],
            attributes=response.attributes.model_dump(),
            pkg_hint=response.pkg_hint.model_dump() if response.pkg_hint else None,
            snapshot_id=response.pkg_snapshot_id,
            domain=domain,
        )

        # Add PKG governance if available
        if process_with_pkg and response.pkg_hint and response.pkg_hint.provenance:
            fact.add_pkg_governance(
                rule_id=response.pkg_hint.provenance[0].rule_id
                if response.pkg_hint.provenance
                else "unknown",
                provenance=[prov.model_dump() for prov in response.pkg_hint.provenance],
                validation_status="pkg_validated"
                if response.pkg_validation_status
                else "pkg_validation_failed",
            )

        # Store in database
        async with self._get_db_session() as db:
            db.add(fact)
            await db.flush()

            if produced_by_task_id:
                await self._record_task_produces_fact(db, produced_by_task_id, fact.id)

            await db.commit()
            await db.refresh(fact)

            logger.info(
                f"Created fact {fact.id} from eventizer processing with {len(response.event_tags.event_types)} event types"
            )
            return fact, response

    async def process_multiple_texts(
        self,
        texts: List[str],
        domain: str = "default",
        process_with_pkg: bool = True,
        produced_by_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Tuple[Fact, EventizerResponse]]:
        """
        Process multiple texts and create facts.

        Args:
            texts: List of texts to process
            domain: Processing domain
            process_with_pkg: Whether to enable PKG processing

        Returns:
            List of (Fact, EventizerResponse) tuples
        """
        results = []

        for text in texts:  # noqa: F402
            try:
                fact, response = await self.create_from_text(
                    text=text,
                    domain=domain,
                    process_with_pkg=process_with_pkg,
                    produced_by_task_id=produced_by_task_id,
                )
                results.append((fact, response))
            except Exception as e:
                logger.error(f"Failed to process text '{text[:50]}...': {e}")
                # Continue processing other texts

        return results

    # -----------------
    # Temporal Facts
    # -----------------

    async def create_temporal_fact(
        self,
        subject: str,
        predicate: str,
        object_data: dict,
        text: Optional[str] = None,
        valid_from: Optional[datetime] = None,
        valid_to: Optional[datetime] = None,
        namespace: str = "default",
        created_by: str = "fact_manager",
        produced_by_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Fact:
        """
        Create a temporal fact with explicit validity window.

        Args:
            subject: Fact subject (e.g., 'guest:john_doe')
            predicate: Fact predicate (e.g., 'hasTemporaryAccess')
            object_data: Fact object data
            text: Optional text description
            valid_from: Validity start time (defaults to now)
            valid_to: Validity end time (None = indefinite)
            namespace: Fact namespace
            created_by: Creator identifier

        Returns:
            Created temporal Fact instance
        """
        async with self._get_db_session() as db:
            fact = Fact.create_temporal(
                subject=subject,
                predicate=predicate,
                object_data=object_data,
                text=text,
                valid_from=valid_from,
                valid_to=valid_to,
                namespace=namespace,
                created_by=created_by,
            )

            # PKG validation is now handled upstream by the coordinator
            # This method just creates the temporal fact

            db.add(fact)
            await db.flush()

            if produced_by_task_id:
                await self._record_task_produces_fact(db, produced_by_task_id, fact.id)

            await db.commit()
            await db.refresh(fact)

            logger.info(f"Created temporal fact {fact.id} for subject {subject}")
            return fact

    async def get_active_facts(
        self,
        subject: str,
        namespace: str = "default",
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Get non-expired temporal facts for a subject.

        Args:
            subject: Subject to query
            namespace: Namespace to filter by

        Returns:
            List of active temporal facts
        """
        async with self._get_db_session() as db:
            now = datetime.now(timezone.utc)

            query = (
                select(Fact)
                .where(
                    and_(
                        Fact.subject == subject,
                        Fact.namespace == namespace,
                        or_(Fact.valid_to.is_(None), Fact.valid_to > now),
                    )
                )
                .order_by(Fact.created_at.desc())
            )

            result = await db.execute(query)
            facts = result.scalars().all()

            if facts and reading_task_id:
                await self._record_task_reads_fact(
                    db, reading_task_id, [fact.id for fact in facts]
                )

            return facts

    async def get_expired_facts(
        self,
        namespace: Optional[str] = None,
        limit: int = 1000,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Get expired temporal facts.

        Args:
            namespace: Optional namespace to filter by
            limit: Maximum number of facts to return

        Returns:
            List of expired temporal facts
        """
        async with self._get_db_session() as db:
            now = datetime.now(timezone.utc)

            query = select(Fact).where(
                and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
            )

            if namespace:
                query = query.where(Fact.namespace == namespace)

            query = query.order_by(Fact.valid_to.desc()).limit(limit)

            result = await db.execute(query)
            facts = result.scalars().all()

            if facts and reading_task_id:
                await self._record_task_reads_fact(
                    db, reading_task_id, [fact.id for fact in facts]
                )

            return facts

    async def cleanup_expired_facts(
        self, namespace: Optional[str] = None, dry_run: bool = False
    ) -> int:
        """
        Remove expired temporal facts.

        Args:
            namespace: Optional namespace to filter by
            dry_run: If True, only count expired facts without deleting

        Returns:
            Number of expired facts processed
        """
        async with self._get_db_session() as db:
            now = datetime.now(timezone.utc)

            query = select(Fact).where(
                and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
            )

            if namespace:
                query = query.where(Fact.namespace == namespace)

            if dry_run:
                result = await db.execute(query)
                expired_facts = result.scalars().all()
                logger.info(
                    f"Found {len(expired_facts)} expired facts in namespace {namespace or 'all'}"
                )
                return len(expired_facts)

            # Delete expired facts
            delete_query = delete(Fact).where(
                and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
            )

            if namespace:
                delete_query = delete_query.where(Fact.namespace == namespace)

            result = await db.execute(delete_query)
            await db.commit()

            deleted_count = result.rowcount
            logger.info(
                f"Cleaned up {deleted_count} expired facts from namespace {namespace or 'all'}"
            )
            return deleted_count

    # -----------------
    # PKG Integration
    # -----------------

    # validate_with_pkg method removed - PKG validation is now handled upstream by the coordinator
    # Facts should receive PKG governance data from the coordinator after evaluation

    async def get_pkg_governed_facts(
        self,
        snapshot_id: Optional[int] = None,
        rule_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 100,
    ) -> List[Fact]:
        """
        Get facts governed by PKG policies.

        Args:
            snapshot_id: PKG snapshot ID to filter by
            rule_id: PKG rule ID to filter by
            namespace: Namespace to filter by
            limit: Maximum number of facts to return

        Returns:
            List of PKG-governed facts
        """
        async with self._get_db_session() as db:
            query = select(Fact).where(Fact.validation_status.is_not(None))

            if snapshot_id:
                query = query.where(Fact.snapshot_id == snapshot_id)

            if rule_id:
                query = query.where(Fact.pkg_rule_id == rule_id)

            if namespace:
                query = query.where(Fact.namespace == namespace)

            query = query.order_by(Fact.created_at.desc()).limit(limit)

            result = await db.execute(query)
            return result.scalars().all()

    # -----------------
    # Analytics and Reporting
    # -----------------

    async def get_fact_statistics(
        self, namespace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get statistics about facts.

        Args:
            namespace: Optional namespace to filter by

        Returns:
            Dictionary with fact statistics
        """
        async with self._get_db_session() as db:
            base_query = select(Fact)

            if namespace:
                base_query = base_query.where(Fact.namespace == namespace)

            # Total facts
            total_result = await db.execute(base_query)
            total_facts = len(total_result.scalars().all())

            # Temporal facts
            temporal_query = base_query.where(
                or_(Fact.valid_from.is_not(None), Fact.valid_to.is_not(None))
            )
            temporal_result = await db.execute(temporal_query)
            temporal_facts = len(temporal_result.scalars().all())

            # PKG governed facts
            pkg_query = base_query.where(Fact.validation_status.is_not(None))
            pkg_result = await db.execute(pkg_query)
            pkg_facts = len(pkg_result.scalars().all())

            # Expired facts
            now = datetime.now(timezone.utc)
            expired_query = base_query.where(
                and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
            )
            expired_result = await db.execute(expired_query)
            expired_facts = len(expired_result.scalars().all())

            # Namespaces
            namespaces_query = select(Fact.namespace).distinct()
            if namespace:
                namespaces_query = namespaces_query.where(Fact.namespace == namespace)
            namespaces_result = await db.execute(namespaces_query)
            namespaces = [ns[0] for ns in namespaces_result.fetchall()]

            return {
                "total_facts": total_facts,
                "temporal_facts": temporal_facts,
                "pkg_governed_facts": pkg_facts,
                "expired_facts": expired_facts,
                "active_facts": temporal_facts - expired_facts,
                "namespaces": namespaces,
                "namespace_count": len(namespaces),
            }

    async def get_recent_activity(
        self,
        hours: int = 24,
        namespace: Optional[str] = None,
        limit: int = 100,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Get recent fact creation activity.

        Args:
            hours: Number of hours to look back
            namespace: Optional namespace to filter by
            limit: Maximum number of facts to return

        Returns:
            List of recently created facts
        """
        async with self._get_db_session() as db:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            query = select(Fact).where(Fact.created_at >= cutoff_time)

            if namespace:
                query = query.where(Fact.namespace == namespace)

            query = query.order_by(Fact.created_at.desc()).limit(limit)

            result = await db.execute(query)
            facts = result.scalars().all()

            if facts and reading_task_id:
                await self._record_task_reads_fact(
                    db, reading_task_id, [fact.id for fact in facts]
                )

            return facts


# --- 2. Define the FastAPI app (Ingress) ---
app = FastAPI(docs_url=None, redoc_url=None)  # Disable docs - only accessed via RPC


@serve.deployment(
    name="FactManagerService", num_replicas=1, ray_actor_options={"num_cpus": 0.1}
)
@serve.ingress(app)
class FactManagerService:
    """
    Hybrid Service: Accepts Pydantic models via HTTP and Dicts via RPC.
    """

    def __init__(self, db_config: Dict[str, Any] = None):
        try:
            logger.info("Initializing FactManagerImpl backend...")
            # Initialize your actual logic implementation here
            self.impl = self._init_fact_manager(db_config)
            self._ready = True
            logger.info("✅ FactManagerService initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize FactManagerImpl: {e}")
            self._ready = False
            raise e

    def _init_fact_manager(self, config: Dict[str, Any]) -> FactManagerImpl:
        """
        Initialize FactManagerImpl with database session factory from database.py.
        
        Args:
            config: Optional configuration dict (currently unused, session factory
                   is obtained from database.py)
        
        Returns:
            Initialized FactManagerImpl instance
        """
        # Use get_async_pg_session_factory() from database.py
        # This creates a session factory using the centralized database configuration
        return FactManagerImpl(db_session_factory=None)  # None triggers default from database.py

    # --- 3. Hybrid Handlers (RPC + HTTP) ---

    @app.post("/fact/create", response_model=FactResponse)
    async def create_fact(self, payload: Union[FactCreate, Dict[str, Any]]):
        """
        Handles fact creation.
        Auto-detects if input is a Dict (from RPC) or Model (from HTTP).
        """
        try:
            # 1. Normalization: Ensure we have a Pydantic Model
            # This allows OpsGateway to pass raw Dicts safely
            if isinstance(payload, dict):
                fact_data = FactCreate(**payload)
            else:
                fact_data = payload

            logger.info(
                f"📝 Processing fact from {fact_data.source}: {fact_data.content[:20]}..."
            )

            # 2. Call Implementation
            fact = await self.impl.create_fact(fact_data)

            return {
                "id": str(fact.id),
                "status": "created",
                "message": "Fact successfully stored via Manager",
            }

        except Exception as e:
            logger.error(f"Fact creation failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/fact/query")
    async def query_fact(self, payload: Union[FactQuery, Dict[str, Any]]):
        """
        Query facts. Handles Dict (RPC) or Model (HTTP).
        """
        try:
            # 1. Normalization
            if isinstance(payload, dict):
                query_data = FactQuery(**payload)
            else:
                query_data = payload

            logger.debug(f"🔍 Querying facts: {query_data.query_text}")
            results = await self.impl.search_fact(query_data)

            return {
                "results": results,
                "count": len(results),
                "filter": query_data.query_text,
                "processed_by": "FactManagerService",
            }

        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # --- 4. Health & Management ---

    @app.get("/fact/health")
    async def health_check(self):
        """Standard health check."""
        if not getattr(self, "_ready", False):
            raise HTTPException(status_code=503, detail="Service not initialized")
        return {"status": "healthy", "service": "FactManagerService"}


# Deployment Binding
fact_app = FactManagerService.bind()
