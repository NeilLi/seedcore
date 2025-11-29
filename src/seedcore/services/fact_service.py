#!/usr/bin/env python3
"""
Fact Manager Service - Unified fact management with PKG integration.

This service provides a unified interface for fact management, combining the enhanced
Fact model with eventizer processing and PKG governance capabilities.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Sequence, Tuple, Union
from fastapi import HTTPException, Request  # type: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]

from sqlalchemy import select, delete, and_, or_, text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from ..models.fact import Fact
from .eventizer_service import EventizerService
from ..ops.eventizer.schemas.eventizer_models import (
    EventizerRequest,
    EventizerResponse,
    EventizerConfig,
    PKGEnv,
)

logger = logging.getLogger(__name__)


class FactManager:
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
        db_session: AsyncSession,
        eventizer_config: Optional[EventizerConfig] = None,
    ):
        """
        Initialize the FactManager.

        Args:
            db_session: Database session for fact operations
            eventizer_config: Optional eventizer configuration
        """
        self.db = db_session
        self.eventizer_config = eventizer_config or EventizerConfig()
        self._eventizer: Optional[EventizerService] = None
        self._initialized = False

    # -----------------
    # Internal helpers
    # -----------------

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

    async def _ensure_task_node(self, task_id: uuid.UUID) -> None:
        await self.db.execute(
            text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
            {"task_id": str(task_id)},
        )

    async def _ensure_fact_nodes(self, fact_ids: Sequence[uuid.UUID]) -> None:
        if not fact_ids:
            return
        await self.db.execute(
            text(
                "SELECT ensure_fact_node(fact_id) "
                "FROM unnest(CAST(:fact_ids AS uuid[])) AS fact_id"
            ),
            {"fact_ids": [str(fid) for fid in fact_ids]},
        )

    async def _record_task_produces_fact(
        self,
        task_id: Union[str, uuid.UUID],
        fact_id: Union[str, uuid.UUID],
    ) -> None:
        normalized_task_id = self._normalize_uuid(task_id)
        normalized_fact_id = self._normalize_uuid(fact_id)

        if not normalized_task_id or not normalized_fact_id:
            return

        await self._ensure_task_node(normalized_task_id)
        await self._ensure_fact_nodes([normalized_fact_id])

        await self.db.execute(
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

        await self._ensure_task_node(normalized_task_id)
        await self._ensure_fact_nodes(unique_fact_ids)

        await self.db.execute(
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
            logger.info("FactManager initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize FactManager: {e}")
            raise

    # -----------------
    # Basic Fact Operations
    # -----------------

    async def create_fact(
        self,
        text: str,
        tags: Optional[List[str]] = None,
        meta_data: Optional[Dict[str, Any]] = None,
        namespace: str = "default",
        created_by: str = "fact_manager",
        produced_by_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> Fact:
        """
        Create a basic fact.

        Args:
            text: Fact text content
            tags: Optional tags for the fact
            meta_data: Optional metadata
            namespace: Fact namespace
            created_by: Creator identifier

        Returns:
            Created Fact instance
        """
        fact = Fact(
            text=text,
            tags=tags or [],
            meta_data=meta_data or {},
            namespace=namespace,
            created_by=created_by,
        )

        self.db.add(fact)
        await self.db.flush()

        if produced_by_task_id:
            await self._record_task_produces_fact(produced_by_task_id, fact.id)

        await self.db.commit()
        await self.db.refresh(fact)

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
        query = select(Fact).where(Fact.id == fact_id)
        result = await self.db.execute(query)
        fact = result.scalar_one_or_none()

        if fact and reading_task_id:
            await self._record_task_reads_fact(reading_task_id, [fact.id])

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
        query = (
            select(Fact)
            .where(Fact.namespace == namespace)
            .order_by(Fact.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.db.execute(query)
        facts = result.scalars().all()

        if facts and reading_task_id:
            await self._record_task_reads_fact(
                reading_task_id, [fact.id for fact in facts]
            )

        return facts

    async def search_facts(
        self,
        text_query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        limit: int = 100,
        reading_task_id: Optional[Union[str, uuid.UUID]] = None,
    ) -> List[Fact]:
        """
        Search facts with various criteria.

        Args:
            text_query: Text to search for in fact content
            tags: Tags to filter by
            namespace: Namespace to filter by
            subject: Subject to filter by
            predicate: Predicate to filter by
            limit: Maximum number of facts to return

        Returns:
            List of matching Fact instances
        """
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

        query = query.order_by(Fact.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        facts = result.scalars().all()

        if facts and reading_task_id:
            await self._record_task_reads_fact(
                reading_task_id, [fact.id for fact in facts]
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
        self.db.add(fact)
        await self.db.flush()

        if produced_by_task_id:
            await self._record_task_produces_fact(produced_by_task_id, fact.id)

        await self.db.commit()
        await self.db.refresh(fact)

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

        self.db.add(fact)
        await self.db.flush()

        if produced_by_task_id:
            await self._record_task_produces_fact(produced_by_task_id, fact.id)

        await self.db.commit()
        await self.db.refresh(fact)

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

        result = await self.db.execute(query)
        facts = result.scalars().all()

        if facts and reading_task_id:
            await self._record_task_reads_fact(
                reading_task_id, [fact.id for fact in facts]
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
        now = datetime.now(timezone.utc)

        query = select(Fact).where(
            and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
        )

        if namespace:
            query = query.where(Fact.namespace == namespace)

        query = query.order_by(Fact.valid_to.desc()).limit(limit)

        result = await self.db.execute(query)
        facts = result.scalars().all()

        if facts and reading_task_id:
            await self._record_task_reads_fact(
                reading_task_id, [fact.id for fact in facts]
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
        now = datetime.now(timezone.utc)

        query = select(Fact).where(
            and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
        )

        if namespace:
            query = query.where(Fact.namespace == namespace)

        if dry_run:
            result = await self.db.execute(query)
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

        result = await self.db.execute(delete_query)
        await self.db.commit()

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
        query = select(Fact).where(Fact.validation_status.is_not(None))

        if snapshot_id:
            query = query.where(Fact.snapshot_id == snapshot_id)

        if rule_id:
            query = query.where(Fact.pkg_rule_id == rule_id)

        if namespace:
            query = query.where(Fact.namespace == namespace)

        query = query.order_by(Fact.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
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
        base_query = select(Fact)

        if namespace:
            base_query = base_query.where(Fact.namespace == namespace)

        # Total facts
        total_result = await self.db.execute(base_query)
        total_facts = len(total_result.scalars().all())

        # Temporal facts
        temporal_query = base_query.where(
            or_(Fact.valid_from.is_not(None), Fact.valid_to.is_not(None))
        )
        temporal_result = await self.db.execute(temporal_query)
        temporal_facts = len(temporal_result.scalars().all())

        # PKG governed facts
        pkg_query = base_query.where(Fact.validation_status.is_not(None))
        pkg_result = await self.db.execute(pkg_query)
        pkg_facts = len(pkg_result.scalars().all())

        # Expired facts
        now = datetime.now(timezone.utc)
        expired_query = base_query.where(
            and_(Fact.valid_to.is_not(None), Fact.valid_to <= now)
        )
        expired_result = await self.db.execute(expired_query)
        expired_facts = len(expired_result.scalars().all())

        # Namespaces
        namespaces_query = select(Fact.namespace).distinct()
        if namespace:
            namespaces_query = namespaces_query.where(Fact.namespace == namespace)
        namespaces_result = await self.db.execute(namespaces_query)
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
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = select(Fact).where(Fact.created_at >= cutoff_time)

        if namespace:
            query = query.where(Fact.namespace == namespace)

        query = query.order_by(Fact.created_at.desc()).limit(limit)

        result = await self.db.execute(query)
        facts = result.scalars().all()

        if facts and reading_task_id:
            await self._record_task_reads_fact(
                reading_task_id, [fact.id for fact in facts]
            )

        return facts


# -----------------
# Convenience Functions
# -----------------


async def create_fact_manager(
    db_session: AsyncSession,
    pkg_environment: PKGEnv = PKGEnv.PROD,
    enable_pkg_validation: bool = True,
) -> FactManager:
    """
    Create a FactManager instance with default configuration.

    Args:
        db_session: Database session
        pkg_environment: PKG environment (for eventizer config)
        enable_pkg_validation: Whether to enable PKG validation in eventizer

    Returns:
        Initialized FactManager instance

    Note:
        PKG validation is now handled by the global PKGManager, not by FactManager.
        This parameter only affects eventizer configuration.
    """
    eventizer_config = EventizerConfig(
        pkg_validation_enabled=enable_pkg_validation, pkg_environment=pkg_environment
    )

    fact_manager = FactManager(db_session=db_session, eventizer_config=eventizer_config)

    await fact_manager.initialize()
    return fact_manager


@serve.deployment(route_prefix=None)
class FactManagerService:
    """Ray Serve wrapper for FactManager."""

    def __init__(self) -> None:
        self.impl = None
        self._initialized = False

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "fact_manager"}

    async def initialize(self) -> None:
        """Initialize the underlying service."""
        if not self._initialized:
            # Note: FactManager requires a database session
            # This will be initialized when first used
            self._initialized = True
            logger.info("FactManager wrapper initialized")

    async def create_fact(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a basic fact."""
        try:
            if not self._initialized:
                await self.initialize()

            # For now, return a placeholder response
            # In a real implementation, this would use the FactManager
            return {
                "status": "created",
                "fact_id": "placeholder-id",
                "message": "Fact creation not yet implemented in wrapper",
            }

        except Exception as e:
            logger.error(f"Fact creation failed: {e}")
            raise HTTPException(
                status_code=500, detail=f"Fact creation failed: {str(e)}"
            )

    async def query_facts(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Query facts."""
        try:
            if not self._initialized:
                await self.initialize()

            # For now, return a placeholder response
            return {
                "status": "success",
                "facts": [],
                "count": 0,
                "message": "Fact querying not yet implemented in wrapper",
            }

        except Exception as e:
            logger.error(f"Fact query failed: {e}")
            raise HTTPException(status_code=500, detail=f"Fact query failed: {str(e)}")

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy",
            "service": "fact_manager",
            "initialized": self._initialized,
        }
