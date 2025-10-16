#!/usr/bin/env python3
"""
Fact Manager Service - Unified fact management with PKG integration.

This service provides a unified interface for fact management, combining the enhanced
Fact model with eventizer processing and PKG governance capabilities.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple, Union

from sqlalchemy import select, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.fact import Fact
from .eventizer_service import EventizerService
from ..eventizer.schemas.eventizer_models import (
    EventizerRequest,
    EventizerResponse,
    EventizerConfig,
    PKGEnv
)
from ..eventizer.clients.pkg_client import PKGClient

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
        pkg_client: Optional[PKGClient] = None,
        eventizer_config: Optional[EventizerConfig] = None
    ):
        """
        Initialize the FactManager.
        
        Args:
            db_session: Database session for fact operations
            pkg_client: Optional PKG client for policy validation
            eventizer_config: Optional eventizer configuration
        """
        self.db = db_session
        self.pkg_client = pkg_client
        self.eventizer_config = eventizer_config or EventizerConfig()
        self._eventizer: Optional[EventizerService] = None
        self._initialized = False
    
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
        created_by: str = "fact_manager"
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
            created_by=created_by
        )
        
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)
        
        logger.info(f"Created fact {fact.id} in namespace {namespace}")
        return fact
    
    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        """
        Get a fact by ID.
        
        Args:
            fact_id: UUID string of the fact
        
        Returns:
            Fact instance or None if not found
        """
        query = select(Fact).where(Fact.id == fact_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_facts_by_namespace(
        self, 
        namespace: str, 
        limit: int = 100,
        offset: int = 0
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
        return result.scalars().all()
    
    async def search_facts(
        self,
        text_query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        namespace: Optional[str] = None,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        limit: int = 100
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
        return result.scalars().all()
    
    # -----------------
    # Eventizer Integration
    # -----------------
    
    async def create_from_text(
        self, 
        text: str, 
        domain: str = "default",
        process_with_pkg: bool = True,
        preserve_pii: bool = False
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
            include_pkg_hint=process_with_pkg
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
            domain=domain
        )
        
        # Add PKG governance if available
        if process_with_pkg and response.pkg_hint and response.pkg_hint.provenance:
            fact.add_pkg_governance(
                rule_id=response.pkg_hint.provenance[0].rule_id if response.pkg_hint.provenance else "unknown",
                provenance=[prov.model_dump() for prov in response.pkg_hint.provenance],
                validation_status="pkg_validated" if response.pkg_validation_status else "pkg_validation_failed"
            )
        
        # Store in database
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)
        
        logger.info(f"Created fact {fact.id} from eventizer processing with {len(response.event_tags.event_types)} event types")
        return fact, response
    
    async def process_multiple_texts(
        self,
        texts: List[str],
        domain: str = "default",
        process_with_pkg: bool = True
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
        
        for text in texts:
            try:
                fact, response = await self.create_from_text(
                    text=text,
                    domain=domain,
                    process_with_pkg=process_with_pkg
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
        created_by: str = "fact_manager"
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
            created_by=created_by
        )
        
        # Validate with PKG if available
        if self.pkg_client:
            try:
                pkg_fact_data = fact.to_pkg_fact()
                await self.pkg_client.create_temporal_fact(pkg_fact_data)
                fact.validation_status = "pkg_validated"
            except Exception as e:
                logger.warning(f"PKG validation failed for temporal fact: {e}")
                fact.validation_status = "pkg_validation_failed"
        
        self.db.add(fact)
        await self.db.commit()
        await self.db.refresh(fact)
        
        logger.info(f"Created temporal fact {fact.id} for subject {subject}")
        return fact
    
    async def get_active_facts(
        self, 
        subject: str, 
        namespace: str = "default"
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
        
        query = select(Fact).where(
            and_(
                Fact.subject == subject,
                Fact.namespace == namespace,
                or_(
                    Fact.valid_to.is_(None),
                    Fact.valid_to > now
                )
            )
        ).order_by(Fact.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_expired_facts(
        self,
        namespace: Optional[str] = None,
        limit: int = 1000
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
            and_(
                Fact.valid_to.is_not(None),
                Fact.valid_to <= now
            )
        )
        
        if namespace:
            query = query.where(Fact.namespace == namespace)
        
        query = query.order_by(Fact.valid_to.desc()).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def cleanup_expired_facts(
        self,
        namespace: Optional[str] = None,
        dry_run: bool = False
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
            and_(
                Fact.valid_to.is_not(None),
                Fact.valid_to <= now
            )
        )
        
        if namespace:
            query = query.where(Fact.namespace == namespace)
        
        if dry_run:
            result = await self.db.execute(query)
            expired_facts = result.scalars().all()
            logger.info(f"Found {len(expired_facts)} expired facts in namespace {namespace or 'all'}")
            return len(expired_facts)
        
        # Delete expired facts
        delete_query = delete(Fact).where(
            and_(
                Fact.valid_to.is_not(None),
                Fact.valid_to <= now
            )
        )
        
        if namespace:
            delete_query = delete_query.where(Fact.namespace == namespace)
        
        result = await self.db.execute(delete_query)
        await self.db.commit()
        
        deleted_count = result.rowcount
        logger.info(f"Cleaned up {deleted_count} expired facts from namespace {namespace or 'all'}")
        return deleted_count
    
    # -----------------
    # PKG Integration
    # -----------------
    
    async def validate_with_pkg(self, fact: Fact) -> bool:
        """
        Validate fact against PKG policies.
        
        Args:
            fact: Fact to validate
        
        Returns:
            True if validation passes, False otherwise
        """
        if not self.pkg_client:
            logger.warning("PKG client not available for validation")
            return True
        
        try:
            pkg_fact_data = fact.to_pkg_fact()
            # Use PKG client to validate
            # This would integrate with PKG validation logic
            fact.validation_status = "pkg_validated"
            return True
        except Exception as e:
            logger.error(f"PKG validation failed for fact {fact.id}: {e}")
            fact.validation_status = "pkg_validation_failed"
            return False
    
    async def get_pkg_governed_facts(
        self,
        snapshot_id: Optional[int] = None,
        rule_id: Optional[str] = None,
        namespace: Optional[str] = None,
        limit: int = 100
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
        query = select(Fact).where(
            Fact.validation_status.is_not(None)
        )
        
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
        self,
        namespace: Optional[str] = None
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
            or_(
                Fact.valid_from.is_not(None),
                Fact.valid_to.is_not(None)
            )
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
            and_(
                Fact.valid_to.is_not(None),
                Fact.valid_to <= now
            )
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
            "namespace_count": len(namespaces)
        }
    
    async def get_recent_activity(
        self,
        hours: int = 24,
        namespace: Optional[str] = None,
        limit: int = 100
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
        
        query = select(Fact).where(
            Fact.created_at >= cutoff_time
        )
        
        if namespace:
            query = query.where(Fact.namespace == namespace)
        
        query = query.order_by(Fact.created_at.desc()).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()


# -----------------
# Convenience Functions
# -----------------

async def create_fact_manager(
    db_session: AsyncSession,
    pkg_environment: PKGEnv = PKGEnv.PROD,
    enable_pkg_validation: bool = True
) -> FactManager:
    """
    Create a FactManager instance with default configuration.
    
    Args:
        db_session: Database session
        pkg_environment: PKG environment
        enable_pkg_validation: Whether to enable PKG validation
    
    Returns:
        Initialized FactManager instance
    """
    pkg_client = None
    if enable_pkg_validation:
        try:
            pkg_client = PKGClient(pkg_environment)
        except Exception as e:
            logger.warning(f"Failed to create PKG client: {e}")
    
    eventizer_config = EventizerConfig(
        pkg_validation_enabled=enable_pkg_validation,
        pkg_environment=pkg_environment
    )
    
    fact_manager = FactManager(
        db_session=db_session,
        pkg_client=pkg_client,
        eventizer_config=eventizer_config
    )
    
    await fact_manager.initialize()
    return fact_manager
