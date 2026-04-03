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

    async def get_active_governed_facts(
        self,
        snapshot_id: int,
        namespace: Optional[str] = None,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        limit: int = 100,
        governed_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get active facts for policy evaluation.
        
        Returns facts that are:
        - Currently valid (within temporal validity window)
        - Scoped to the specified snapshot
        - Optionally filtered to PKG-governed facts only (if governed_only=True)
        
        Args:
            snapshot_id: PKG snapshot ID to filter facts
            namespace: Optional namespace filter (defaults to 'default')
            subject: Optional subject filter for subject-specific hydration
            predicate: Optional predicate filter
            limit: Maximum number of facts to return
            governed_only: If True, only return PKG-governed facts. If False (default), return all active facts.
        
        Returns:
            List of fact dictionaries with SPO triple structure
        """
        return await self.cortex.get_active_governed_facts(
            snapshot_id=snapshot_id,
            namespace=namespace,
            subject=subject,
            predicate=predicate,
            limit=limit,
            governed_only=governed_only
        )

    async def promote_task_to_knowledge_graph(
        self,
        task_id: str,
        actor: str,
        preserve_multimodal: bool = True
    ) -> Dict[str, Any]:
        """
        Promotes a task from Tier 1 (Multimodal Event Memory) to Tier 2/3 (Knowledge Graph).
        
        This bridges the gap between short-term working perception and long-term structured knowledge.
        
        Args:
            task_id: UUID string of the task to promote
            actor: Actor identifier (e.g., 'admin', 'mother') for audit trail
            preserve_multimodal: If True, keeps the original multimodal embedding (default: True)
        
        Returns:
            Dictionary with ok, msg, new_node_id, task_id
        """
        return await self.cortex.promote_task_to_knowledge_graph(
            task_id=task_id,
            actor=actor,
            preserve_multimodal=preserve_multimodal
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

    async def get_snapshot_by_id(self, snapshot_id: int) -> Optional[PKGSnapshotData]:
        """Get a specific snapshot by its numeric ID."""
        return await self.snapshots.get_snapshot_by_id(snapshot_id)

    async def activate_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        """Activate snapshot for its env lane."""
        return await self.snapshots.activate_snapshot(snapshot_id)

    async def get_subtask_types(self, snapshot_id: int) -> List[Dict[str, Any]]:
        """
        Return the "DNA registry" of subtask types for a given snapshot.

        This is the canonical read-path for `pkg_subtask_types` and is intended to
        power dynamic capability discovery / executor binding at runtime.
        """
        return await self.snapshots.list_subtask_types(snapshot_id)
    
    async def get_merged_capability(
        self,
        guest_id: Optional[str] = None,
        persona_name: Optional[str] = None,
        base_capability_name: Optional[str] = None,
        snapshot_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get merged capability: guest overlay (if exists) merged with system base.
        
        This is the primary method used by Router/Coordinator to resolve capabilities.
        Resolution order:
        1. Check guest_capabilities for active guest overlay (if guest_id provided)
        2. If found, merge custom_params with base_subtask_type_id defaults
        3. If no guest overlay, fall back to system pkg_subtask_types
        
        Args:
            guest_id: Optional guest UUID (if None, only checks system layer)
            persona_name: Optional persona name filter
            base_capability_name: Optional base capability name (e.g., "reachy_actuator")
            snapshot_id: Optional snapshot ID (defaults to active snapshot)
            
        Returns:
            Dict with merged capability params, or None if not found
        """
        return await self.snapshots.get_merged_capability(
            guest_id=guest_id,
            persona_name=persona_name,
            base_capability_name=base_capability_name,
            snapshot_id=snapshot_id,
        )
    
    async def get_active_artifact(self, env: str = "prod") -> Optional[Dict[str, Any]]:
        """Get active artifact information using the view."""
        return await self.snapshots.get_active_artifact(env)

    async def store_snapshot_artifact(
        self,
        *,
        snapshot_id: int,
        artifact_type: str,
        artifact_bytes: bytes,
        sha256: str,
        created_by: str = "system",
    ) -> None:
        await self.snapshots.store_snapshot_artifact(
            snapshot_id=snapshot_id,
            artifact_type=artifact_type,
            artifact_bytes=artifact_bytes,
            sha256=sha256,
            created_by=created_by,
        )

    async def store_snapshot_artifact_json(
        self,
        *,
        snapshot_id: int,
        artifact_type: str,
        payload: Dict[str, Any],
        created_by: str = "system",
    ) -> Dict[str, Any]:
        return await self.snapshots.store_snapshot_artifact_json(
            snapshot_id=snapshot_id,
            artifact_type=artifact_type,
            payload=payload,
            created_by=created_by,
        )

    async def list_snapshot_artifacts(self, snapshot_id: int) -> List[Dict[str, Any]]:
        return await self.snapshots.list_snapshot_artifacts(snapshot_id)

    async def get_snapshot_artifact_payload(
        self,
        *,
        snapshot_id: int,
        artifact_type: str,
    ) -> Optional[Dict[str, Any]]:
        return await self.snapshots.get_snapshot_artifact_payload(
            snapshot_id=snapshot_id,
            artifact_type=artifact_type,
        )

    async def get_snapshot_manifest(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        return await self.snapshots.get_snapshot_manifest(snapshot_id)

    async def upsert_snapshot_manifest(
        self,
        *,
        snapshot_id: int,
        workflow_type: str = "restricted_custody_transfer",
        decision_contract_version: Optional[str] = None,
        request_schema_version: Optional[str] = None,
        evidence_contract_version: Optional[str] = None,
        reason_code_taxonomy_version: Optional[str] = None,
        trust_gap_taxonomy_version: Optional[str] = None,
        obligation_taxonomy_version: Optional[str] = None,
        consistency_contract_version: Optional[str] = None,
        safety_profile: Optional[str] = None,
        requires_signed_bundle: bool = False,
        requires_compiled_decision_graph: bool = False,
        requires_authority_state_binding: bool = False,
        activation_requirements: Optional[Dict[str, Any]] = None,
        manifest_json: Optional[Dict[str, Any]] = None,
        manifest_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.snapshots.upsert_snapshot_manifest(
            snapshot_id=snapshot_id,
            workflow_type=workflow_type,
            decision_contract_version=decision_contract_version,
            request_schema_version=request_schema_version,
            evidence_contract_version=evidence_contract_version,
            reason_code_taxonomy_version=reason_code_taxonomy_version,
            trust_gap_taxonomy_version=trust_gap_taxonomy_version,
            obligation_taxonomy_version=obligation_taxonomy_version,
            consistency_contract_version=consistency_contract_version,
            safety_profile=safety_profile,
            requires_signed_bundle=requires_signed_bundle,
            requires_compiled_decision_graph=requires_compiled_decision_graph,
            requires_authority_state_binding=requires_authority_state_binding,
            activation_requirements=activation_requirements,
            manifest_json=manifest_json,
            manifest_hash=manifest_hash,
        )

    async def get_taxonomy_bundle(self, snapshot_id: int) -> Dict[str, List[Dict[str, Any]]]:
        return await self.snapshots.get_taxonomy_bundle(snapshot_id=snapshot_id)
    
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

    async def upsert_deployment(
        self,
        *,
        snapshot_id: int,
        target: str,
        region: str = "global",
        percent: int = 100,
        is_active: bool = True,
        activated_by: str = "system",
    ) -> Dict[str, Any]:
        """Upsert an active deployment lane."""
        return await self.deployments.upsert_deployment(
            snapshot_id=snapshot_id,
            target=target,
            region=region,
            percent=percent,
            is_active=is_active,
            activated_by=activated_by,
        )

    async def get_effective_deployment(
        self,
        *,
        target: str,
        region: str = "global",
    ) -> Optional[Dict[str, Any]]:
        """Resolve effective deployment lane (region-specific first, then global)."""
        return await self.deployments.get_effective_deployment(target=target, region=region)

    async def resolve_desired_snapshot_for_device(
        self,
        *,
        device_type: str,
        region: str = "global",
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve desired policy snapshot for an edge device.

        Priority:
        1. `pkg_deployments` lane `edge:<device_type>` (region first, then global)
        2. active snapshot fallback.
        """
        target = f"edge:{str(device_type).strip().lower()}"
        deployment = await self.get_effective_deployment(target=target, region=region)
        if deployment:
            return {
                "snapshot_id": deployment.get("snapshot_id"),
                "snapshot_version": deployment.get("snapshot_version"),
                "target": deployment.get("target"),
                "region": deployment.get("region"),
                "percent": deployment.get("percent"),
                "source": "deployment_lane",
            }

        active = await self.get_active_snapshot()
        if active is None:
            return None
        return {
            "snapshot_id": active.id,
            "snapshot_version": active.version,
            "target": target,
            "region": region,
            "percent": 100,
            "source": "active_snapshot_fallback",
        }
    
    # =========================
    # Validation (delegate to DAO)
    # =========================
    
    async def get_validation_fixtures(
        self,
        snapshot_id: int
    ) -> List[Dict[str, Any]]:
        """Get validation fixtures for a snapshot."""
        return await self.validation.get_validation_fixtures(snapshot_id)

    async def get_validation_fixture_by_id(
        self,
        fixture_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Get a single validation fixture by ID."""
        return await self.validation.get_validation_fixture_by_id(fixture_id)
    
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
