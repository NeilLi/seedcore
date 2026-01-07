#!/usr/bin/env python3
"""
PKG (Policy Knowledge Graph) client for PostgreSQL.

Updated v2.5: Unified Facade with Cortex Memory Integration.
This client now composes the PKGCortexDAO to bridge vectors into policy evaluation.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from .dao import (
    PKGSnapshotsDAO,
    PKGDeploymentsDAO,
    PKGValidationDAO,
    PKGPromotionsDAO,
    PKGDevicesDAO,
    PKGCortexDAO,         # NEW: Added Cortex DAO
    PKGSnapshotData,
    check_pkg_integrity,
)
from ...database import get_async_pg_session_factory 

logger = logging.getLogger(__name__)

__all__ = ["PKGClient", "PKGSnapshotData"]


class PKGClient:
    """
    Unified facade client for PKG operations.
    
    Delegates specialized operations to:
    - self.snapshots: Policy versions and rules
    - self.cortex: Semantic context and Unified Memory queries [NEW]
    - self.deployments: Rollout management
    - self.validation: Policy testing
    - self.promotions: Audit and governance
    - self.devices: Edge telemetry
    """
    
    def __init__(self, session_factory: Optional[callable] = None):
        """
        Initialize PKG client facade.
        """
        self._sf = session_factory or get_async_pg_session_factory()
        
        # Compose specialized DAOs
        self.snapshots = PKGSnapshotsDAO(self._sf)
        self.cortex = PKGCortexDAO(self._sf)       # NEW: Cortex Integration
        self.deployments = PKGDeploymentsDAO(self._sf)
        self.validation = PKGValidationDAO(self._sf)
        self.promotions = PKGPromotionsDAO(self._sf)
        self.devices = PKGDevicesDAO(self._sf)
    
    # =========================
    # Cortex / Unified Memory [NEW]
    # =========================

    async def get_semantic_context(
        self, 
        embedding: List[float], 
        limit: int = 5,
        min_similarity: float = 0.8,
        exclude_task_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves cross-tier semantic context from Unified Memory.
        Used to 'hydrate' the PKG evaluation context with historical facts.

        Args:
            embedding: 1024d embedding vector for similarity search
            limit: Maximum number of results to return
            min_similarity: Minimum similarity threshold (0.0-1.0)
            exclude_task_id: Optional task ID to exclude from results (prevents self-retrieval)
        """
        return await self.cortex.get_semantic_context(
            embedding=embedding,
            limit=limit,
            min_similarity=min_similarity,
            exclude_task_id=exclude_task_id
        )

    # =========================
    # Snapshots (delegate to DAO)
    # =========================

    async def get_active_snapshot(self) -> Optional[PKGSnapshotData]:
        """Get the currently active snapshot from the database."""
        return await self.snapshots.get_active_snapshot()

    async def get_snapshot_by_version(self, version: str) -> Optional[PKGSnapshotData]:
        """Get a specific snapshot by its version string."""
        return await self.snapshots.get_snapshot_by_version(version)
    
    async def get_active_artifact(self, env: str = "prod") -> Optional[Dict[str, Any]]:
        """Get active artifact information using the view."""
        return await self.snapshots.get_active_artifact(env)
    
    # =========================
    # Deployments (delegate to DAO)
    # =========================
    
    async def get_deployments(
        self,
        snapshot_id: Optional[int] = None,
        target: Optional[str] = None,
        region: Optional[str] = None,
        active_only: bool = True
    ) -> List[Dict[str, Any]]:
        """Get deployment configurations for canary/targeted rollouts."""
        return await self.deployments.get_deployments(
            snapshot_id=snapshot_id,
            target=target,
            region=region,
            active_only=active_only
        )
        
    async def get_deployment_coverage(
        self,
        target: Optional[str] = None,
        region: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get deployment coverage statistics from the view."""
        return await self.deployments.get_deployment_coverage(target=target, region=region)
    
    # =========================
    # Validation (delegate to DAO)
    # =========================
    
    async def get_validation_fixtures(
        self,
        snapshot_id: int
    ) -> List[Dict[str, Any]]:
        """Get validation fixtures for a snapshot."""
        return await self.validation.get_validation_fixtures(snapshot_id)
    
    async def create_validation_run(
        self,
        snapshot_id: int,
        started_at: Optional[datetime] = None
    ) -> int:
        """Create a new validation run record."""
        return await self.validation.create_validation_run(snapshot_id, started_at)
    
    async def finish_validation_run(
        self,
        run_id: int,
        success: bool,
        report: Optional[Dict[str, Any]] = None
    ) -> None:
        """Mark a validation run as finished with results."""
        return await self.validation.finish_validation_run(run_id, success, report)

    async def get_validation_runs(
        self, 
        snapshot_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get validation run history."""
        return await self.validation.get_validation_runs(snapshot_id=snapshot_id, limit=limit)
    
    # =========================
    # Promotions (delegate to DAO)
    # =========================
    
    async def get_promotions(
        self,
        snapshot_id: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get promotion/rollback audit history."""
        return await self.promotions.get_promotions(snapshot_id=snapshot_id, limit=limit)
    
    async def create_promotion(
        self,
        snapshot_id: int,
        actor: str,
        action: str = "promote",
        reason: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
        success: bool = True
    ) -> int:
        """Create a promotion/rollback audit record."""
        return await self.promotions.create_promotion(
            snapshot_id=snapshot_id,
            actor=actor,
            action=action,
            reason=reason,
            metrics=metrics,
            success=success
        )
    
    # =========================
    # Devices (delegate to DAO)
    # =========================
    
    async def get_device_versions(
        self,
        device_type: Optional[str] = None,
        region: Optional[str] = None,
        snapshot_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get device version heartbeat records (edge telemetry)."""
        return await self.devices.get_device_versions(
            device_type=device_type,
            region=region,
            snapshot_id=snapshot_id
        )
    
    async def update_device_heartbeat(
        self,
        device_id: str,
        device_type: str,
        snapshot_id: Optional[int] = None,
        version: Optional[str] = None,
        region: str = "global"
    ) -> None:
        """Update device heartbeat (upsert device version record)."""
        return await self.devices.update_device_heartbeat(
            device_id=device_id,
            device_type=device_type,
            snapshot_id=snapshot_id,
            version=version,
            region=region
        )
    
    # =========================
    # Helper Methods
    # =========================
    
    async def check_integrity(self) -> Dict[str, Any]:
        """Run integrity check function to validate PKG data consistency."""
        return await check_pkg_integrity(self._sf)