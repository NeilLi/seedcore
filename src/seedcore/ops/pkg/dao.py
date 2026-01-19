#!/usr/bin/env python3
"""
PKG (Policy Knowledge Graph) Data Access Objects (DAOs).

This module provides modular DAOs for different PKG subsystems:
- PKGSnapshotsDAO: Versioned policy snapshots, rules, conditions, emissions
- PKGDeploymentsDAO: Canary deployments and targeted rollouts
- PKGValidationDAO: Test fixtures and validation runs
- PKGPromotionsDAO: Promotion/rollback audit trail
- PKGDevicesDAO: Edge device telemetry and version tracking

Each DAO is focused on a single domain responsibility, improving modularity,
testability, and maintainability.
"""

import logging
import inspect
from typing import Optional, List, Dict, Any, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from ...database import get_async_pg_session_factory

logger = logging.getLogger(__name__)


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _row_mapping(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None

    mapping = getattr(row, "_mapping", None)
    if mapping is None:
        try:
            return dict(row)
        except TypeError:
            return None

    mapping = await _maybe_await(mapping)

    if isinstance(mapping, Mapping):
        return dict(mapping)

    try:
        return dict(mapping)
    except TypeError:
        return None


__all__ = [
    "PKGSnapshotsDAO",
    "PKGDeploymentsDAO",
    "PKGValidationDAO",
    "PKGPromotionsDAO",
    "PKGDevicesDAO",
]


@dataclass(frozen=True)
class PKGSnapshotData:
    """
    An internal, self-contained representation of a snapshot.

    This object holds all data needed by the PKGManager and PKGEvaluator,
    resolving the 'engine' type based on the loaded data.
    """

    id: int
    version: str
    engine: str  # 'wasm' or 'native', derived by the client
    wasm_artifact: Optional[bytes]
    checksum: Optional[str]
    rules: List[Dict[str, Any]]  # For the 'native' engine [cite: 93]


# =========================
# Snapshots DAO
# =========================


class PKGSnapshotsDAO:
    """
    DAO for PKG policy snapshots, rules, conditions, and emissions.

    Handles versioned policy governance - the core of the PKG system.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        """
        Initialize snapshots DAO.

        Args:
            session_factory: An async session factory. If None, uses the
                             project's default.
        """
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_active_snapshot(self) -> Optional[PKGSnapshotData]:
        """
        Get the currently active snapshot from the database.

        This queries the pkg_snapshots table for the is_active=TRUE row
        and builds the complete PKGSnapshotData object.
        """
        sql = text("""
            SELECT s.id, s.version, s.checksum, s.notes
            FROM pkg_snapshots s
            WHERE s.is_active = TRUE
            LIMIT 1
        """)

        async with self._sf() as session:
            res = await session.execute(sql)
            snapshot_row = await _maybe_await(res.first())
            snapshot_mapping = await _row_mapping(snapshot_row)

            if not snapshot_mapping:
                logger.warning("No active PKG snapshot found in database.")
                return None

            return await self._build_snapshot_data(snapshot_mapping, session)

    async def get_snapshot_by_version(self, version: str) -> Optional[PKGSnapshotData]:
        """
        Get a specific snapshot by its version string.

        This is used by the PKGManager for hot-swapping.
        """
        sql = text("""
            SELECT s.id, s.version, s.checksum, s.notes
            FROM pkg_snapshots s
            WHERE s.version = :version
            LIMIT 1
        """)

        async with self._sf() as session:
            res = await session.execute(sql, {"version": version})
            snapshot_row = await _maybe_await(res.first())
            snapshot_mapping = await _row_mapping(snapshot_row)

            if not snapshot_mapping:
                logger.error(f"Snapshot version '{version}' not found in database.")
                return None

            return await self._build_snapshot_data(snapshot_mapping, session)

    async def _build_snapshot_data(
        self, snapshot_row: Dict[str, Any], session: AsyncSession
    ) -> PKGSnapshotData:
        """
        Private helper to assemble the full snapshot data object.

        This method resolves the engine type and fetches native rules
        with conditions and emissions if the snapshot is not a WASM snapshot.

        Optimized with parallel fetching for conditions and emissions.
        """
        import time

        start = time.perf_counter()

        snapshot_id = snapshot_row["id"]

        # Fetch WASM artifact from pkg_snapshot_artifacts if it exists
        artifact_sql = text("""
            SELECT artifact_bytes, artifact_type
            FROM pkg_snapshot_artifacts
            WHERE snapshot_id = :snapshot_id
            LIMIT 1
        """)
        artifact_res = await session.execute(artifact_sql, {"snapshot_id": snapshot_id})
        artifact_row = await _maybe_await(artifact_res.first())
        artifact_dict = await _row_mapping(artifact_row)

        wasm_artifact: Optional[bytes] = None
        if artifact_dict:
            # Only use if it's a WASM artifact
            if artifact_dict.get("artifact_type") == "wasm_pack":
                wasm_artifact = artifact_dict.get("artifact_bytes")

        engine: str
        rules_list: List[Dict[str, Any]] = []

        if wasm_artifact:
            # This is a WASM snapshot
            engine = "wasm"
            logger.info(
                f"Building 'wasm' snapshot {snapshot_row['version']} (id={snapshot_id})"
            )
        else:
            # This is a Native snapshot
            engine = "native"
            logger.info(
                f"Building 'native' snapshot {snapshot_row['version']} (id={snapshot_id})"
            )

            # Optimized: Use a single query with LEFT JOINs to fetch all rules data
            # This avoids N+1 queries for conditions and emissions
            rules_sql = text("""
                SELECT 
                    r.id AS rule_id,
                    r.rule_name,
                    r.priority,
                    r.rule_source,
                    r.compiled_rule,
                    r.engine,
                    r.rule_hash,
                    r.metadata,
                    r.disabled,
                    c.condition_type,
                    c.condition_key,
                    c.operator,
                    c.value AS condition_value,
                    c.position AS condition_position,
                    e.relationship_type,
                    e.params AS emission_params,
                    e.position AS emission_position,
                    st.id AS subtask_type_id,
                    st.name AS subtask_name,
                    st.default_params AS subtask_default_params
                FROM pkg_policy_rules r
                LEFT JOIN pkg_rule_conditions c ON c.rule_id = r.id
                LEFT JOIN pkg_rule_emissions e ON e.rule_id = r.id
                LEFT JOIN pkg_subtask_types st ON st.id = e.subtask_type_id
                WHERE r.snapshot_id = :snapshot_id AND r.disabled = FALSE
                ORDER BY r.priority DESC, r.rule_name, c.position, e.position
            """)
            rules_res = await session.execute(rules_sql, {"snapshot_id": snapshot_id})

            # Post-process: group conditions and emissions by rule
            rules_dict: Dict[str, Dict[str, Any]] = {}

            for row in rules_res:
                row_dict = dict(row._mapping)
                rule_id = str(row_dict["rule_id"])

                # Initialize rule if not seen
                if rule_id not in rules_dict:
                    rules_dict[rule_id] = {
                        "id": row_dict["rule_id"],
                        "rule_name": row_dict["rule_name"],
                        "priority": row_dict["priority"],
                        "rule_source": row_dict["rule_source"],
                        "compiled_rule": row_dict["compiled_rule"],
                        "engine": row_dict["engine"],
                        "rule_hash": row_dict["rule_hash"],
                        "metadata": row_dict["metadata"],
                        "conditions": [],
                        "emissions": [],
                    }

                # Add condition if present
                if row_dict.get("condition_type"):
                    rules_dict[rule_id]["conditions"].append(
                        {
                            "condition_type": row_dict["condition_type"],
                            "condition_key": row_dict["condition_key"],
                            "operator": row_dict["operator"],
                            "value": row_dict["condition_value"],
                            "position": row_dict["condition_position"] or 0,
                        }
                    )

                # Add emission if present
                if row_dict.get("subtask_name"):
                    rules_dict[rule_id]["emissions"].append(
                        {
                            "subtask_type": row_dict["subtask_name"],
                            "subtask_type_id": str(row_dict["subtask_type_id"]),
                            "subtask_name": row_dict["subtask_name"],
                            "params": row_dict["emission_params"]
                            or row_dict["subtask_default_params"]
                            or {},
                            "relationship_type": row_dict["relationship_type"],
                            "position": row_dict["emission_position"] or 0,
                        }
                    )

            # Convert to list and deduplicate emissions/conditions
            for rule_dict in rules_dict.values():
                # Remove duplicates from conditions (in case of join multiplication)
                seen_conditions = set()
                unique_conditions = []
                for cond in rule_dict["conditions"]:
                    cond_key = (
                        cond["condition_key"],
                        cond["operator"],
                        cond.get("value"),
                    )
                    if cond_key not in seen_conditions:
                        seen_conditions.add(cond_key)
                        unique_conditions.append(cond)
                rule_dict["conditions"] = unique_conditions

                # Remove duplicates from emissions
                seen_emissions = set()
                unique_emissions = []
                for em in rule_dict["emissions"]:
                    em_key = (em["subtask_type_id"], em["position"])
                    if em_key not in seen_emissions:
                        seen_emissions.add(em_key)
                        unique_emissions.append(em)
                rule_dict["emissions"] = unique_emissions

            rules_list = list(rules_dict.values())

            elapsed = time.perf_counter() - start
            logger.info(
                f"Built native snapshot {snapshot_row['version']} with {len(rules_list)} rules in {elapsed:.3f}s"
            )

        return PKGSnapshotData(
            id=snapshot_id,
            version=snapshot_row["version"],
            engine=engine,
            wasm_artifact=wasm_artifact,
            checksum=snapshot_row["checksum"],
            rules=rules_list,
        )

    async def get_active_artifact(self, env: str = "prod") -> Optional[Dict[str, Any]]:
        """
        Get active artifact information using the view.

        Args:
            env: Environment (prod, staging, dev)

        Returns:
            Dictionary with artifact details or None
        """
        sql = text("""
            SELECT * FROM pkg_active_artifact
            WHERE env = :env
            LIMIT 1
        """)

        async with self._sf() as session:
            res = await session.execute(sql, {"env": env})
            row = await _maybe_await(res.first())
            mapping = await _row_mapping(row)
            return mapping if mapping is not None else None


# =========================
# Deployments DAO
# =========================


class PKGDeploymentsDAO:
    """
    DAO for PKG deployment management (canary deployments, targeted rollouts).

    Handles rollout metadata for router/edge classes.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        """Initialize deployments DAO."""
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_deployments(
        self,
        snapshot_id: Optional[int] = None,
        target: Optional[str] = None,
        region: Optional[str] = None,
        active_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get deployment configurations for canary/targeted rollouts.

        Args:
            snapshot_id: Filter by snapshot ID
            target: Filter by target (e.g., 'router', 'edge:door')
            region: Filter by region
            active_only: Only return active deployments

        Returns:
            List of deployment dictionaries
        """
        conditions = []
        params = {}

        if snapshot_id:
            conditions.append("snapshot_id = :snapshot_id")
            params["snapshot_id"] = snapshot_id

        if target:
            conditions.append("target = :target")
            params["target"] = target

        if region:
            conditions.append("region = :region")
            params["region"] = region

        if active_only:
            conditions.append("is_active = TRUE")

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = text(f"""
            SELECT d.*, s.version AS snapshot_version
            FROM pkg_deployments d
            JOIN pkg_snapshots s ON s.id = d.snapshot_id
            {where_clause}
            ORDER BY d.activated_at DESC
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]

    async def get_deployment_coverage(
        self, target: Optional[str] = None, region: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get deployment coverage statistics from the view.

        Shows how many devices are running the intended snapshot vs total devices.

        Args:
            target: Filter by target
            region: Filter by region

        Returns:
            List of coverage dictionaries with devices_on_snapshot and devices_total
        """
        conditions = []
        params = {}

        if target:
            conditions.append("d.target = :target")
            params["target"] = target

        if region:
            conditions.append("d.region = :region")
            params["region"] = region

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = text(f"""
            SELECT * FROM pkg_deployment_coverage d
            {where_clause}
            ORDER BY d.target, d.region
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]


# =========================
# Validation DAO
# =========================


class PKGValidationDAO:
    """
    DAO for PKG validation framework (test fixtures, validation runs).

    Handles policy correctness validation and test execution tracking.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        """Initialize validation DAO."""
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_validation_fixtures(self, snapshot_id: int) -> List[Dict[str, Any]]:
        """
        Get validation fixtures for a snapshot.

        Args:
            snapshot_id: Snapshot ID to get fixtures for

        Returns:
            List of fixture dictionaries with input and expected outputs
        """
        sql = text("""
            SELECT id, name, input, expect, created_at
            FROM pkg_validation_fixtures
            WHERE snapshot_id = :snapshot_id
            ORDER BY name
        """)

        async with self._sf() as session:
            res = await session.execute(sql, {"snapshot_id": snapshot_id})
            return [dict(r._mapping) for r in res]

    async def create_validation_run(
        self, snapshot_id: int, started_at: Optional[datetime] = None
    ) -> int:
        """
        Create a new validation run record.

        Args:
            snapshot_id: Snapshot ID being validated
            started_at: Optional start time (defaults to now)

        Returns:
            Validation run ID
        """
        sql = text("""
            INSERT INTO pkg_validation_runs (snapshot_id, started_at)
            VALUES (:snapshot_id, COALESCE(:started_at, now()))
            RETURNING id
        """)

        async with self._sf() as session:
            async with session.begin():  # Explicit transaction
                res = await session.execute(
                    sql, {"snapshot_id": snapshot_id, "started_at": started_at}
                )
                run_id = await _maybe_await(res.scalar())
                return run_id

    async def finish_validation_run(
        self, run_id: int, success: bool, report: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Mark a validation run as finished with results.

        Args:
            run_id: Validation run ID
            success: Whether validation succeeded
            report: Optional JSON report with detailed results
        """
        sql = text("""
            UPDATE pkg_validation_runs
            SET finished_at = now(), success = :success, report = :report
            WHERE id = :run_id
        """)

        async with self._sf() as session:
            async with session.begin():  # Explicit transaction
                await session.execute(
                    sql, {"run_id": run_id, "success": success, "report": report}
                )

    async def get_validation_runs(
        self, snapshot_id: Optional[int] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get validation run history.

        Args:
            snapshot_id: Filter by snapshot ID
            limit: Maximum number of runs to return

        Returns:
            List of validation run dictionaries
        """
        conditions = []
        params = {"limit": limit}

        if snapshot_id:
            conditions.append("snapshot_id = :snapshot_id")
            params["snapshot_id"] = snapshot_id

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = text(f"""
            SELECT * FROM pkg_validation_runs
            {where_clause}
            ORDER BY started_at DESC
            LIMIT :limit
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]


# =========================
# Promotions DAO
# =========================


class PKGPromotionsDAO:
    """
    DAO for PKG promotion/rollback audit trail.

    Handles promotion history and audit records.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        """Initialize promotions DAO."""
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_promotions(
        self, snapshot_id: Optional[int] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get promotion/rollback audit history.

        Args:
            snapshot_id: Filter by snapshot ID
            limit: Maximum number of records to return

        Returns:
            List of promotion dictionaries with actor, action, reason, metrics
        """
        conditions = []
        params = {"limit": limit}

        if snapshot_id:
            conditions.append("snapshot_id = :snapshot_id")
            params["snapshot_id"] = snapshot_id

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = text(f"""
            SELECT p.*, s.version AS snapshot_version
            FROM pkg_promotions p
            JOIN pkg_snapshots s ON s.id = p.snapshot_id
            {where_clause}
            ORDER BY p.created_at DESC
            LIMIT :limit
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]

    async def create_promotion(
        self,
        snapshot_id: int,
        actor: str,
        action: str = "promote",
        reason: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
        success: bool = True,
    ) -> int:
        """
        Create a promotion/rollback audit record.

        Args:
            snapshot_id: Snapshot ID being promoted/rolled back
            actor: Who performed the action
            action: 'promote' or 'rollback'
            reason: Optional reason for the action
            metrics: Optional metrics (e.g., eval p95, validation summary)
            success: Whether the promotion succeeded

        Returns:
            Promotion record ID
        """
        # Get current active snapshot for from_version
        from_version = None
        async with self._sf() as session:
            async with session.begin():  # Explicit transaction
                current_sql = text("""
                    SELECT version FROM pkg_snapshots
                    WHERE is_active = TRUE
                    LIMIT 1
                """)
                current_res = await session.execute(current_sql)
                current_row = await _maybe_await(current_res.first())
                current_mapping = await _row_mapping(current_row)
                if current_mapping:
                    from_version = current_mapping.get("version") or next(
                        iter(current_mapping.values())
                    )

                # Get to_version
                to_sql = text(
                    "SELECT version FROM pkg_snapshots WHERE id = :snapshot_id"
                )
                to_res = await session.execute(to_sql, {"snapshot_id": snapshot_id})
                to_row = await _maybe_await(to_res.first())
                to_mapping = await _row_mapping(to_row)
                if not to_mapping:
                    raise ValueError(f"Snapshot {snapshot_id} not found")
                to_version = to_mapping.get("version") or next(
                    iter(to_mapping.values())
                )

                # Insert promotion record
                sql = text("""
                    INSERT INTO pkg_promotions 
                        (snapshot_id, from_version, to_version, actor, action, reason, metrics, success)
                    VALUES 
                        (:snapshot_id, :from_version, :to_version, :actor, :action, :reason, :metrics, :success)
                    RETURNING id
                """)
                res = await session.execute(
                    sql,
                    {
                        "snapshot_id": snapshot_id,
                        "from_version": from_version,
                        "to_version": to_version,
                        "actor": actor,
                        "action": action,
                        "reason": reason,
                        "metrics": metrics,
                        "success": success,
                    },
                )
                promo_id = await _maybe_await(res.scalar())
                return promo_id


# =========================
# Devices DAO
# =========================


class PKGDevicesDAO:
    """
    DAO for PKG device coverage (edge telemetry, version tracking).

    Handles device heartbeat and version tracking for distributed deployments.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        """Initialize devices DAO."""
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_device_versions(
        self,
        device_type: Optional[str] = None,
        region: Optional[str] = None,
        snapshot_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get device version heartbeat records (edge telemetry).

        Args:
            device_type: Filter by device type (e.g., 'door', 'robot')
            region: Filter by region
            snapshot_id: Filter by snapshot ID

        Returns:
            List of device version dictionaries
        """
        conditions = []
        params = {}

        if device_type:
            conditions.append("device_type = :device_type")
            params["device_type"] = device_type

        if region:
            conditions.append("region = :region")
            params["region"] = region

        if snapshot_id:
            conditions.append("snapshot_id = :snapshot_id")
            params["snapshot_id"] = snapshot_id

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        sql = text(f"""
            SELECT dv.*, s.version AS snapshot_version
            FROM pkg_device_versions dv
            LEFT JOIN pkg_snapshots s ON s.id = dv.snapshot_id
            {where_clause}
            ORDER BY dv.last_seen DESC
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]

    async def update_device_heartbeat(
        self,
        device_id: str,
        device_type: str,
        snapshot_id: Optional[int] = None,
        version: Optional[str] = None,
        region: str = "global",
    ) -> None:
        """
        Update device heartbeat (upsert device version record).

        Args:
            device_id: Device identifier (e.g., 'door:D-1510')
            device_type: Device type (e.g., 'door', 'robot')
            snapshot_id: Current snapshot ID running on device
            version: Optional version string
            region: Device region
        """
        sql = text("""
            INSERT INTO pkg_device_versions 
                (device_id, device_type, region, snapshot_id, version, last_seen)
            VALUES 
                (:device_id, :device_type, :region, :snapshot_id, :version, now())
            ON CONFLICT (device_id) 
            DO UPDATE SET
                device_type = EXCLUDED.device_type,
                region = EXCLUDED.region,
                snapshot_id = EXCLUDED.snapshot_id,
                version = EXCLUDED.version,
                last_seen = now()
        """)

        async with self._sf() as session:
            async with session.begin():  # Explicit transaction
                await session.execute(
                    sql,
                    {
                        "device_id": device_id,
                        "device_type": device_type,
                        "region": region,
                        "snapshot_id": snapshot_id,
                        "version": version,
                    },
                )
                logger.debug(f"Updated device heartbeat for {device_id}")


class PKGCortexDAO:
    """
    DAO for bridging Unified Memory (Vectors) into the PKG evaluation context.

    This allows the PKG to 'remember' historical tasks and 'ground'
    decisions based on the current state of the Knowledge Graph.
    """

    def __init__(self, session_factory: Optional[callable] = None):
        self._sf = session_factory or get_async_pg_session_factory()

    async def get_semantic_context(
        self, 
        embedding: List[float], 
        limit: int = 5, 
        min_similarity: float = 0.8,
        exclude_task_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Queries the Unified Cortex View for cross-tier context.

        This fetches:
        - Tier 1: Recent similar tasks (Working Memory)
        - Tier 2/3: Relevant Knowledge Graph nodes (Rules/World Context)

        Args:
            embedding: 1024d embedding vector for similarity search
            limit: Maximum number of results to return
            min_similarity: Minimum similarity threshold (0.0-1.0)
            exclude_task_id: Optional task ID to exclude from results (prevents self-retrieval)

        Note:
            The exclude_task_id parameter prevents the "Identity Match" problem where
            the current task returns itself as the #1 match. This is critical because
            the embedding is persisted before PKG evaluation, making the current task
            immediately queryable via v_unified_cortex_memory.
        """
        import json

        vec_str = json.dumps(embedding)

        # Build WHERE clause conditionally to exclude current task if provided
        where_conditions = ["1 - (vector <=> CAST(:vec AS vector)) >= :min_sim"]
        params = {"vec": vec_str, "limit": limit, "min_sim": min_similarity}

        if exclude_task_id:
            # Exclude the current task to prevent self-retrieval
            # The view's id field is TEXT (cast from UUID or BIGINT), so we compare as TEXT
            where_conditions.append("id != :exclude_task_id")
            params["exclude_task_id"] = str(exclude_task_id)

        where_clause = " WHERE " + " AND ".join(where_conditions)

        # Query the Unified View created in Migration 017
        sql = text(f"""
            SELECT 
                id, 
                category, 
                content, 
                memory_tier, 
                metadata,
                1 - (vector <=> CAST(:vec AS vector)) as similarity
            FROM v_unified_cortex_memory
            {where_clause}
            ORDER BY vector <=> CAST(:vec AS vector)
            LIMIT :limit
        """)

        async with self._sf() as session:
            res = await session.execute(sql, params)
            return [dict(r._mapping) for r in res]

    async def promote_task_to_knowledge_graph(
        self,
        task_id: str,
        actor: str,
        preserve_multimodal: bool = True
    ) -> Dict[str, Any]:
        """
        Promotes a task from Tier 1 (Multimodal Event Memory) to Tier 2/3 (Knowledge Graph).
        
        This bridges the gap between short-term working perception and long-term structured knowledge.
        The promotion process follows a "Read-Transform-Write" pattern:
        
        1. **Read**: Fetch the task and its multimodal embeddings
        2. **Transform**: Ensure graph_node_map entry exists (creates BIGINT node_id)
        3. **Embed**: Copy the 1024d multimodal vector to `graph_embeddings_1024` with label 'task.primary'
        4. **Register**: Task now appears in `v_unified_cortex_memory` under Tier 2/3 (knowledge_base)
        
        Args:
            task_id: UUID string of the task to promote
            actor: Actor identifier (e.g., 'admin', 'mother') for audit trail
            preserve_multimodal: If True, keeps the original multimodal embedding (default: True)
                               If False, removes it after promotion (not recommended)
        
        Returns:
            Dictionary with:
            - ok: bool - Success/failure status
            - msg: str - Human-readable message
            - new_node_id: Optional[int] - The BIGINT node_id from graph_node_map
            - task_id: str - The original task UUID
        """
        import uuid
        import json
        import time
        
        try:
            # Validate task_id format
            try:
                task_uuid = uuid.UUID(task_id)
            except ValueError:
                return {
                    "ok": False,
                    "msg": f"Invalid task_id format: {task_id}",
                    "new_node_id": None,
                    "task_id": task_id
                }
            
            async with self._sf() as session:
                async with session.begin():  # Transaction
                    # 1. Fetch task and verify it exists
                    task_sql = text("""
                        SELECT 
                            t.id,
                            t.type,
                            t.description,
                            t.params,
                            t.status,
                            t.created_at
                        FROM tasks t
                        WHERE t.id = CAST(:task_id AS uuid)
                    """)
                    
                    task_result = await session.execute(task_sql, {"task_id": str(task_uuid)})
                    task_row = task_result.mappings().first()
                    
                    if not task_row:
                        return {
                            "ok": False,
                            "msg": f"Task {task_id} not found in tasks table",
                            "new_node_id": None,
                            "task_id": task_id
                        }
                    
                    # 2. Ensure graph_node_map entry exists (creates BIGINT node_id)
                    ensure_node_sql = text("SELECT ensure_task_node(CAST(:task_id AS uuid)) AS node_id")
                    node_result = await session.execute(ensure_node_sql, {"task_id": str(task_uuid)})
                    node_id = node_result.scalar_one()
                    
                    if not node_id:
                        return {
                            "ok": False,
                            "msg": f"Failed to create graph_node_map entry for task {task_id}",
                            "new_node_id": None,
                            "task_id": task_id
                        }
                    
                    # 3. Fetch source metadata first (for inclusion in props)
                    metadata_sql = text("""
                        SELECT source_modality, model_version
                        FROM task_multimodal_embeddings
                        WHERE task_id = CAST(:task_id AS uuid)
                        LIMIT 1
                    """)
                    metadata_result = await session.execute(metadata_sql, {"task_id": str(task_uuid)})
                    metadata_row = metadata_result.mappings().first()
                    
                    if not metadata_row:
                        return {
                            "ok": False,
                            "msg": f"Task {task_id} has no multimodal embedding in task_multimodal_embeddings",
                            "new_node_id": None,
                            "task_id": task_id
                        }
                    
                    source_modality = metadata_row.get("source_modality", "unknown")
                    model_version = metadata_row.get("model_version", "unknown")
                    
                    # 4. Copy embedding from task_multimodal_embeddings to graph_embeddings_1024
                    # Use SQL to directly copy the vector (more efficient than Python conversion)
                    # Store promotion metadata in props JSONB
                    props_json = json.dumps({
                        "promoted_from": "multimodal",
                        "source_modality": source_modality,
                        "model_version": model_version,
                        "promoted_by": actor,
                        "promoted_at": time.time(),
                        "memory_label": "approved_seed"
                    })
                    
                    # Direct SQL copy: select from task_multimodal_embeddings and insert into graph_embeddings_1024
                    # This handles vector type conversion automatically
                    copy_embedding_sql = text("""
                        INSERT INTO graph_embeddings_1024 (
                            node_id, 
                            label, 
                            emb, 
                            model,
                            props
                        )
                        SELECT 
                            :node_id,
                            'task.primary',
                            tme.emb,
                            tme.model_version,
                            CAST(:props AS jsonb)
                        FROM task_multimodal_embeddings tme
                        WHERE tme.task_id = CAST(:task_id AS uuid)
                        LIMIT 1
                        ON CONFLICT (node_id, label)
                        DO UPDATE SET
                            emb = EXCLUDED.emb,
                            model = EXCLUDED.model,
                            props = EXCLUDED.props,
                            updated_at = NOW()
                    """)
                    
                    result = await session.execute(
                        copy_embedding_sql,
                        {
                            "node_id": node_id,
                            "task_id": str(task_uuid),
                            "props": props_json
                        }
                    )
                    
                    # Verify embedding was copied
                    rows_affected = result.rowcount
                    if rows_affected == 0:
                        return {
                            "ok": False,
                            "msg": f"Failed to copy embedding for task {task_id}",
                            "new_node_id": None,
                            "task_id": task_id
                        }
                    
                    # 5. Optional: Remove multimodal embedding if preserve_multimodal=False
                    # (Not recommended - multimodal embeddings are useful for fast perception queries)
                    if not preserve_multimodal:
                        delete_multimodal_sql = text("""
                            DELETE FROM task_multimodal_embeddings
                            WHERE task_id = CAST(:task_id AS uuid)
                        """)
                        await session.execute(delete_multimodal_sql, {"task_id": str(task_uuid)})
                        logger.info(f"Removed multimodal embedding for task {task_id} after promotion")
                    
                    # Transaction commits automatically via context manager
                    logger.info(
                        f"Successfully promoted task {task_id} to Knowledge Graph "
                        f"(node_id={node_id}, actor={actor}, modality={source_modality}, model={model_version})"
                    )
                    
                    return {
                        "ok": True,
                        "msg": f"Seed successfully promoted to Knowledge Graph (node_id={node_id})",
                        "new_node_id": node_id,
                        "task_id": task_id,
                        "preserved_multimodal": preserve_multimodal
                    }
                    
        except Exception as e:
            logger.error(f"Failed to promote task {task_id}: {e}", exc_info=True)
            return {
                "ok": False,
                "msg": f"Promotion failed: {str(e)}",
                "new_node_id": None,
                "task_id": task_id,
                "error": str(e),
                "error_type": type(e).__name__
            }


# =========================
# Integrity Helper
# =========================


async def check_pkg_integrity(
    session_factory: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Run integrity check function to validate PKG data consistency.

    Args:
        session_factory: Optional session factory

    Returns:
        Dictionary with 'ok' boolean and 'msg' string
    """
    sf = session_factory or get_async_pg_session_factory()
    sql = text("SELECT * FROM pkg_check_integrity()")

    async with sf() as session:
        res = await session.execute(sql)
        row = await _maybe_await(res.first())
        mapping = await _row_mapping(row)
        return (
            mapping
            if mapping is not None
            else {"ok": False, "msg": "Integrity check failed"}
        )
