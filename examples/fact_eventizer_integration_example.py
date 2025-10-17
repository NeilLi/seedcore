#!/usr/bin/env python3
"""
Fact-Eventizer Integration Example

This script demonstrates how to use the enhanced Fact model with PKG integration
and eventizer processing for policy-driven fact management.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from src.seedcore.services.fact_manager import FactManager, create_fact_manager
from src.seedcore.ops.eventizer.schemas.eventizer_models import PKGEnv
from src.seedcore.database import get_async_pg_session_factory

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Demonstrate fact-eventizer integration capabilities."""
    
    # Get database session
    session_factory = get_async_pg_session_factory()
    
    async with session_factory() as db_session:
        # Create fact manager with PKG integration
        fact_manager = await create_fact_manager(
            db_session=db_session,
            pkg_environment=PKGEnv.DEV,  # Use DEV for testing
            enable_pkg_validation=True
        )
        
        logger.info("=== Fact-Eventizer Integration Demo ===")
        
        # 1. Basic fact creation (backward compatible)
        logger.info("\n1. Creating basic fact...")
        basic_fact = await fact_manager.create_fact(
            text="Room 101 temperature is 72°F",
            tags=["temperature", "room"],
            meta_data={"room_id": "101", "temperature": 72},
            namespace="hotel_ops"
        )
        logger.info(f"Created basic fact: {basic_fact.id}")
        
        # 2. Eventizer-processed fact creation
        logger.info("\n2. Creating fact from eventizer processing...")
        eventizer_texts = [
            "Emergency alert: Fire detected in building A",
            "VIP guest John Doe requests room upgrade to suite",
            "HVAC system showing high temperature in zone 3",
            "Security breach detected at main entrance",
            "Maintenance required for elevator in lobby"
        ]
        
        processed_facts = []
        for text in eventizer_texts:
            try:
                fact, response = await fact_manager.create_from_text(
                    text=text,
                    domain="hotel_ops",
                    process_with_pkg=True
                )
                processed_facts.append((fact, response))
                logger.info(f"Processed: {text[:50]}... -> Fact {fact.id}")
                logger.info(f"  Event types: {[tag.value for tag in response.event_tags.event_types]}")
                logger.info(f"  Confidence: {response.confidence.overall_confidence:.2f}")
                if response.pkg_hint:
                    logger.info(f"  PKG subtasks: {len(response.pkg_hint.subtasks)}")
            except Exception as e:
                logger.error(f"Failed to process '{text}': {e}")
        
        # 3. Temporal fact creation
        logger.info("\n3. Creating temporal facts...")
        temporal_facts = []
        
        # Guest temporary access
        guest_access = await fact_manager.create_temporal_fact(
            subject="guest:john_doe",
            predicate="hasTemporaryAccess",
            object_data={"service": "lounge", "level": "premium"},
            text="John Doe has premium lounge access for 24 hours",
            valid_from=datetime.now(timezone.utc),
            valid_to=datetime.now(timezone.utc) + timedelta(hours=24),
            namespace="hotel_ops"
        )
        temporal_facts.append(guest_access)
        logger.info(f"Created temporal fact: {guest_access.id}")
        logger.info(f"  Validity: {guest_access.valid_from} to {guest_access.valid_to}")
        
        # Maintenance window
        maintenance = await fact_manager.create_temporal_fact(
            subject="system:elevator_lobby",
            predicate="requiresMaintenance",
            object_data={"type": "routine", "estimated_duration": "2 hours"},
            text="Lobby elevator scheduled for routine maintenance",
            valid_from=datetime.now(timezone.utc) + timedelta(hours=2),
            valid_to=datetime.now(timezone.utc) + timedelta(hours=4),
            namespace="hotel_ops"
        )
        temporal_facts.append(maintenance)
        logger.info(f"Created maintenance fact: {maintenance.id}")
        
        # 4. Query examples
        logger.info("\n4. Querying facts...")
        
        # Get facts by namespace
        hotel_facts = await fact_manager.get_facts_by_namespace("hotel_ops", limit=10)
        logger.info(f"Found {len(hotel_facts)} facts in hotel_ops namespace")
        
        # Search facts by text
        search_results = await fact_manager.search_facts(
            text_query="emergency",
            namespace="hotel_ops"
        )
        logger.info(f"Found {len(search_results)} facts containing 'emergency'")
        
        # Get active temporal facts for a subject
        if temporal_facts:
            subject = temporal_facts[0].subject
            active_facts = await fact_manager.get_active_facts(subject, "hotel_ops")
            logger.info(f"Found {len(active_facts)} active temporal facts for {subject}")
        
        # 5. PKG governance queries
        logger.info("\n5. PKG governance queries...")
        
        pkg_facts = await fact_manager.get_pkg_governed_facts(
            namespace="hotel_ops",
            limit=10
        )
        logger.info(f"Found {len(pkg_facts)} PKG-governed facts")
        
        for fact in pkg_facts[:3]:  # Show first 3
            logger.info(f"  PKG fact: {fact.subject} {fact.predicate} - Status: {fact.validation_status}")
        
        # 6. Statistics and analytics
        logger.info("\n6. Fact statistics...")
        
        stats = await fact_manager.get_fact_statistics("hotel_ops")
        logger.info("Fact Statistics:")
        logger.info(f"  Total facts: {stats['total_facts']}")
        logger.info(f"  Temporal facts: {stats['temporal_facts']}")
        logger.info(f"  PKG governed facts: {stats['pkg_governed_facts']}")
        logger.info(f"  Expired facts: {stats['expired_facts']}")
        logger.info(f"  Active temporal facts: {stats['active_temporal_facts']}")
        logger.info(f"  Namespaces: {stats['namespaces']}")
        
        # 7. Recent activity
        logger.info("\n7. Recent activity...")
        
        recent_facts = await fact_manager.get_recent_activity(
            hours=1,
            namespace="hotel_ops",
            limit=5
        )
        logger.info(f"Found {len(recent_facts)} facts created in the last hour")
        
        for fact in recent_facts:
            logger.info(f"  Recent: {fact.text[:50]}... ({fact.created_at})")
        
        # 8. Cleanup expired facts (dry run)
        logger.info("\n8. Cleanup expired facts (dry run)...")
        
        expired_count = await fact_manager.cleanup_expired_facts(
            namespace="hotel_ops",
            dry_run=True
        )
        logger.info(f"Found {expired_count} expired facts (dry run)")
        
        # 9. Batch processing
        logger.info("\n9. Batch processing multiple texts...")
        
        batch_texts = [
            "Room service request for room 205",
            "Housekeeping completed for suite 301",
            "Guest complaint about noise from room 102",
            "Spa appointment confirmed for guest Smith"
        ]
        
        batch_results = await fact_manager.process_multiple_texts(
            texts=batch_texts,
            domain="hotel_ops",
            process_with_pkg=True
        )
        
        logger.info(f"Batch processed {len(batch_results)} texts successfully")
        
        # 10. Validation examples
        logger.info("\n10. PKG validation...")
        
        if processed_facts:
            sample_fact = processed_facts[0][0]  # Get first processed fact
            is_valid = await fact_manager.validate_with_pkg(sample_fact)
            logger.info(f"PKG validation for fact {sample_fact.id}: {'PASSED' if is_valid else 'FAILED'}")
        
        logger.info("\n=== Demo completed successfully! ===")
        
        # Summary
        logger.info("\n=== Summary ===")
        logger.info(f"Created {len(processed_facts)} eventizer-processed facts")
        logger.info(f"Created {len(temporal_facts)} temporal facts")
        logger.info(f"Total facts in hotel_ops namespace: {stats['total_facts']}")
        logger.info(f"PKG-governed facts: {stats['pkg_governed_facts']}")
        logger.info(f"Active temporal facts: {stats['active_temporal_facts']}")


async def demonstrate_fact_model_methods():
    """Demonstrate enhanced Fact model methods."""
    
    logger.info("\n=== Enhanced Fact Model Methods Demo ===")
    
    # Create a sample fact using class methods
    from src.seedcore.models.fact import Fact
    
    # 1. Create temporal fact using class method
    temporal_fact = Fact.create_temporal(
        subject="guest:jane_smith",
        predicate="hasSpecialDiet",
        object_data={"diet_type": "vegetarian", "allergies": ["nuts", "dairy"]},
        text="Jane Smith has vegetarian diet with nut and dairy allergies",
        valid_from=datetime.now(timezone.utc),
        valid_to=datetime.now(timezone.utc) + timedelta(days=7)
    )
    
    logger.info(f"Created temporal fact: {temporal_fact}")
    logger.info(f"  Is temporal: {temporal_fact.is_temporal()}")
    logger.info(f"  Is valid: {temporal_fact.is_valid()}")
    logger.info(f"  Validity status: {temporal_fact.get_validity_status()}")
    
    # 2. Create fact from eventizer data
    eventizer_fact = Fact.create_from_eventizer(
        processed_text="Emergency situation in lobby area",
        event_types=["emergency", "security"],
        attributes={
            "target_organ": "security_organ",
            "required_service": "emergency_service",
            "priority": 10
        },
        pkg_hint={
            "subtasks": [{"name": "emergency_response", "priority": "critical"}],
            "applied_snapshot": "v1.2.3"
        },
        domain="hotel_ops"
    )
    
    logger.info(f"Created eventizer fact: {eventizer_fact}")
    
    # 3. Convert to PKG fact format
    pkg_fact_data = temporal_fact.to_pkg_fact()
    logger.info(f"PKG fact data: {pkg_fact_data}")
    
    # 4. Add PKG governance
    temporal_fact.add_pkg_governance(
        rule_id="guest_diet_rule_v1",
        provenance={"rule_version": "1.0", "evaluation_time": datetime.now(timezone.utc).isoformat()},
        validation_status="pkg_validated"
    )
    
    logger.info(f"Added PKG governance: {temporal_fact.validation_status}")
    
    # 5. Create fact from PKG data
    pkg_derived_fact = Fact.from_pkg_fact(
        pkg_fact_data,
        text="Custom text override"
    )
    
    logger.info(f"Created from PKG data: {pkg_derived_fact}")


if __name__ == "__main__":
    # Run the main demo
    asyncio.run(main())
    
    # Run the model methods demo
    asyncio.run(demonstrate_fact_model_methods())
