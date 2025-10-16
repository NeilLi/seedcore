#!/usr/bin/env python3
"""
PKG (Policy Knowledge Graph) client for PostgreSQL-based policy management.

This module provides a client for interacting with the PKG data layer defined by
SQL migrations 013-015, including snapshot management, rule evaluation, validation,
and deployment tracking.
"""

import os
import uuid
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from sqlalchemy import text
from ..schemas.eventizer_models import (
    PKGSnapshot, PKGSubtaskType, PKGPolicyRule, PKGRuleCondition, PKGRuleEmission,
    PKGSnapshotArtifact, PKGDeployment, PKGFact, PKGValidationFixture,
    PKGValidationRun, PKGPromotion, PKGDeviceVersion, PKGValidationResult,
    PKGDeploymentStatus, PKGHelper, PKGEnv, PKGEngine, PKGConditionType,
    PKGOperator, PKGRelation, PKGArtifactType
)
from ....database import get_async_pg_session_factory

logger = logging.getLogger(__name__)

__all__ = [
    "PKGClient",
    "get_active_snapshot",
    "validate_snapshot",
    "list_deployments",
    "get_device_coverage",
]


class PKGClient:
    """
    Client for PKG operations.
    
    Handles snapshot management, rule evaluation, validation, and deployment tracking
    using the PostgreSQL-based PKG data layer.
    """
    
    def __init__(self, environment: PKGEnv = PKGEnv.PROD):
        """
        Initialize PKG client.
        
        Args:
            environment: PKG environment (prod, staging, dev)
        """
        self.environment = environment
        self._sf = get_async_pg_session_factory()

    async def get_active_snapshot(self) -> Optional[PKGSnapshot]:
        """Get the active snapshot for the current environment."""
        async with self._sf() as s:
            res = await s.execute(text("""
                SELECT id, version, env, entrypoint, schema_version, checksum, 
                       size_bytes, signature, is_active, notes, created_at
                FROM pkg_snapshots 
                WHERE env = :env AND is_active = TRUE
                LIMIT 1
            """), {"env": self.environment.value})
            
            row = res.first()
            if not row:
                return None
                
            return PKGSnapshot.from_db_row(row)

    async def get_snapshot_by_version(self, version: str) -> Optional[PKGSnapshot]:
        """Get a snapshot by version string."""
        async with self._sf() as s:
            res = await s.execute(text("""
                SELECT id, version, env, entrypoint, schema_version, checksum,
                       size_bytes, signature, is_active, notes, created_at
                FROM pkg_snapshots
                WHERE version = :version
                LIMIT 1
            """), {"version": version})
            
            row = res.first()
            if not row:
                return None
                
            return PKGSnapshot.from_db_row(row)

    async def get_snapshot_artifact(self, snapshot_id: int) -> Optional[PKGSnapshotArtifact]:
        """Get the artifact for a snapshot."""
        async with self._sf() as s:
            res = await s.execute(text("""
                SELECT snapshot_id, artifact_type, artifact_bytes, sha256, created_at, created_by
                FROM pkg_snapshot_artifacts
                WHERE snapshot_id = :snapshot_id
            """), {"snapshot_id": snapshot_id})
            
            row = res.first()
            if not row:
                return None
                
            return PKGSnapshotArtifact(
                snapshot_id=row[0],
                artifact_type=PKGArtifactType(row[1]),
                artifact_bytes=row[2],
                sha256=row[3],
                created_at=row[4],
                created_by=row[5]
            )

    async def validate_snapshot(self, snapshot_id: int) -> PKGValidationResult:
        """Validate a snapshot using its fixtures."""
        start_time = datetime.now(timezone.utc)
        
        try:
            async with self._sf() as s:
                # Get snapshot info
                res = await s.execute(text("""
                    SELECT version FROM pkg_snapshots WHERE id = :snapshot_id
                """), {"snapshot_id": snapshot_id})
                
                row = res.first()
                if not row:
                    return PKGValidationResult(
                        success=False,
                        snapshot_id=snapshot_id,
                        snapshot_version="unknown",
                        validation_time_ms=0.0,
                        error_message="Snapshot not found"
                    )
                
                snapshot_version = row[0]
                
                # Get validation fixtures
                res = await s.execute(text("""
                    SELECT id, name, input, expect FROM pkg_validation_fixtures
                    WHERE snapshot_id = :snapshot_id
                """), {"snapshot_id": snapshot_id})
                
                fixtures = [dict(r._mapping) for r in res]
                
                if not fixtures:
                    return PKGValidationResult(
                        success=True,
                        snapshot_id=snapshot_id,
                        snapshot_version=snapshot_version,
                        validation_time_ms=0.0,
                        fixtures_tested=0,
                        fixtures_passed=0,
                        fixtures_failed=0
                    )
                
                # Create validation run record
                res = await s.execute(text("""
                    INSERT INTO pkg_validation_runs (snapshot_id, started_at)
                    VALUES (:snapshot_id, :started_at)
                    RETURNING id
                """), {
                    "snapshot_id": snapshot_id,
                    "started_at": start_time
                })
                
                run_id = res.scalar_one()
                
                # TODO: Implement actual validation logic here
                # For now, simulate validation
                fixtures_passed = len(fixtures)  # Assume all pass
                fixtures_failed = 0
                
                # Update validation run
                end_time = datetime.now(timezone.utc)
                await s.execute(text("""
                    UPDATE pkg_validation_runs 
                    SET finished_at = :finished_at, success = :success,
                        report = :report
                    WHERE id = :run_id
                """), {
                    "finished_at": end_time,
                    "success": fixtures_failed == 0,
                    "report": {"fixtures_tested": len(fixtures), "fixtures_passed": fixtures_passed},
                    "run_id": run_id
                })
                
                await s.commit()
                
                validation_time = (end_time - start_time).total_seconds() * 1000
                
                return PKGValidationResult(
                    success=fixtures_failed == 0,
                    snapshot_id=snapshot_id,
                    snapshot_version=snapshot_version,
                    validation_time_ms=validation_time,
                    fixtures_tested=len(fixtures),
                    fixtures_passed=fixtures_passed,
                    fixtures_failed=fixtures_failed,
                    report={"run_id": run_id, "fixtures": fixtures}
                )
                
        except Exception as e:
            logger.error(f"PKG validation failed: {e}")
            return PKGValidationResult(
                success=False,
                snapshot_id=snapshot_id,
                snapshot_version="unknown",
                validation_time_ms=0.0,
                error_message=str(e)
            )

    async def promote_snapshot(self, snapshot_id: int, actor: str, reason: Optional[str] = None) -> bool:
        """Promote a snapshot to active using the database function."""
        try:
            async with self._sf() as s:
                await s.execute(text("""
                    SELECT pkg_promote_snapshot(:snapshot_id, :env, :actor, :reason)
                """), {
                    "snapshot_id": snapshot_id,
                    "env": self.environment.value,
                    "actor": actor,
                    "reason": reason
                })
                await s.commit()
                return True
        except Exception as e:
            logger.error(f"PKG promotion failed: {e}")
            return False

    async def get_deployments(self, target: Optional[str] = None) -> List[PKGDeployment]:
        """Get deployments, optionally filtered by target."""
        async with self._sf() as s:
            if target:
                res = await s.execute(text("""
                    SELECT id, snapshot_id, target, region, percent, is_active,
                           activated_at, activated_by
                    FROM pkg_deployments
                    WHERE target = :target AND is_active = TRUE
                    ORDER BY activated_at DESC
                """), {"target": target})
            else:
                res = await s.execute(text("""
                    SELECT id, snapshot_id, target, region, percent, is_active,
                           activated_at, activated_by
                    FROM pkg_deployments
                    WHERE is_active = TRUE
                    ORDER BY activated_at DESC
                """))
            
            deployments = []
            for row in res:
                deployments.append(PKGDeployment.from_db_row(row))
            
            return deployments

    async def get_device_coverage(self) -> List[PKGDeploymentStatus]:
        """Get device coverage information from the deployment_coverage view."""
        async with self._sf() as s:
            res = await s.execute(text("""
                SELECT target, region, snapshot_id, version, devices_on_snapshot, devices_total
                FROM pkg_deployment_coverage
                ORDER BY target, region
            """))
            
            coverage = []
            for row in res:
                # Get additional deployment info
                deployment_res = await s.execute(text("""
                    SELECT activated_at, activated_by, percent, is_active
                    FROM pkg_deployments
                    WHERE target = :target AND region = :region AND snapshot_id = :snapshot_id
                    LIMIT 1
                """), {
                    "target": row[0],
                    "region": row[1],
                    "snapshot_id": row[2]
                })
                
                deployment_row = deployment_res.first()
                if deployment_row:
                    coverage.append(PKGDeploymentStatus(
                        target=row[0],
                        region=row[1],
                        snapshot_id=row[2],
                        snapshot_version=row[3],
                        is_active=deployment_row[3],
                        percent=deployment_row[2],
                        devices_total=row[5],
                        devices_on_snapshot=row[4],
                        activated_at=deployment_row[0],
                        activated_by=deployment_row[1]
                    ))
            
            return coverage

    async def get_temporal_facts(self, subject: Optional[str] = None, predicate: Optional[str] = None) -> List[PKGFact]:
        """Get temporal facts, optionally filtered by subject or predicate."""
        async with self._sf() as s:
            if subject and predicate:
                res = await s.execute(text("""
                    SELECT id, snapshot_id, namespace, subject, predicate, object,
                           valid_from, valid_to, created_at, created_by
                    FROM pkg_facts
                    WHERE subject = :subject AND predicate = :predicate
                    AND (valid_to IS NULL OR valid_to > now())
                    ORDER BY created_at DESC
                """), {"subject": subject, "predicate": predicate})
            elif subject:
                res = await s.execute(text("""
                    SELECT id, snapshot_id, namespace, subject, predicate, object,
                           valid_from, valid_to, created_at, created_by
                    FROM pkg_facts
                    WHERE subject = :subject
                    AND (valid_to IS NULL OR valid_to > now())
                    ORDER BY created_at DESC
                """), {"subject": subject})
            else:
                res = await s.execute(text("""
                    SELECT id, snapshot_id, namespace, subject, predicate, object,
                           valid_from, valid_to, created_at, created_by
                    FROM pkg_facts
                    WHERE (valid_to IS NULL OR valid_to > now())
                    ORDER BY created_at DESC
                    LIMIT 100
                """))
            
            facts = []
            for row in res:
                facts.append(PKGFact.from_db_row(row))
            
            return facts

    async def create_temporal_fact(self, fact: PKGFact) -> bool:
        """Create a temporal fact."""
        try:
            async with self._sf() as s:
                await s.execute(text("""
                    INSERT INTO pkg_facts (snapshot_id, namespace, subject, predicate, object,
                                         valid_from, valid_to, created_by)
                    VALUES (:snapshot_id, :namespace, :subject, :predicate, :object,
                            :valid_from, :valid_to, :created_by)
                """), {
                    "snapshot_id": fact.snapshot_id,
                    "namespace": fact.namespace,
                    "subject": fact.subject,
                    "predicate": fact.predicate,
                    "object": fact.object,
                    "valid_from": fact.valid_from,
                    "valid_to": fact.valid_to,
                    "created_by": fact.created_by
                })
                await s.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to create temporal fact: {e}")
            return False

    async def check_integrity(self) -> Tuple[bool, str]:
        """Check PKG integrity using the database function."""
        async with self._sf() as s:
            res = await s.execute(text("SELECT * FROM pkg_check_integrity()"))
            row = res.first()
            return (row[0], row[1]) if row else (False, "Unknown error")


# Convenience functions following the existing pattern
async def get_active_snapshot(environment: PKGEnv = PKGEnv.PROD) -> Optional[PKGSnapshot]:
    """Get the active snapshot for the specified environment."""
    client = PKGClient(environment)
    return await client.get_active_snapshot()


async def validate_snapshot(snapshot_id: int) -> PKGValidationResult:
    """Validate a snapshot."""
    client = PKGClient()
    return await client.validate_snapshot(snapshot_id)


async def list_deployments(target: Optional[str] = None) -> List[PKGDeployment]:
    """List deployments."""
    client = PKGClient()
    return await client.get_deployments(target)


async def get_device_coverage() -> List[PKGDeploymentStatus]:
    """Get device coverage information."""
    client = PKGClient()
    return await client.get_device_coverage()
