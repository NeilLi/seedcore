"""Repository helpers for agent and organ registry persistence and graph relationships.

This repository is stateless and centralizes CRUD helpers for agents and organs.
It expects an ``AsyncSession`` to be injected into its methods.

The caller is responsible for session lifecycle and transaction management
(e.g., ``async with session.begin()``).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional, Dict, Any

from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


class AgentGraphRepository:
    """Repository for managing agent and organ registry persistence and relationships.

    This stateless repository handles:
    - Creating/updating agent and organ registry entries
    - Linking agents to organs (agent_member_of_organ)
    - Querying organs by skill or service capabilities
    - Ensuring graph node consistency via ensure_*_node functions
    - Runtime registry management
    """

    # ---------------------------------------------------------------------
    # Runtime registry: epoch and instance lifecycle
    # ---------------------------------------------------------------------
    async def get_current_cluster_epoch(self, session: AsyncSession) -> str:
        """Return the current cluster epoch (UUID as string) or create one if missing."""
        result = await session.execute(
            text("SELECT current_epoch::text FROM cluster_metadata WHERE id=1")
        )
        epoch = result.scalar_one_or_none()
        if epoch:
            return str(epoch)

        # If missing, create one implicitly
        new_epoch = str(uuid.uuid4())
        await session.execute(
            text("SELECT set_current_epoch(:epoch)"), {"epoch": uuid.UUID(new_epoch)}
        )
        return new_epoch

    async def set_current_cluster_epoch(
        self, session: AsyncSession, epoch: str
    ) -> None:
        """Rotate/set the current epoch."""
        await session.execute(
            text("SELECT set_current_epoch(:epoch)"), {"epoch": uuid.UUID(str(epoch))}
        )

    async def register_instance(
        self,
        session: AsyncSession,
        *,
        instance_id: str,
        logical_id: str,
        cluster_epoch: str,
        actor_name: Optional[str] = None,
        serve_route: Optional[str] = None,
        node_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> None:
        """Register or update a runtime instance record (sets status=starting)."""
        # Convert string UUIDs to UUID objects for PostgreSQL
        # and convert IP address string for INET type
        import uuid as uuid_module

        q = """
        SELECT register_instance(
            :instance_id, :logical_id, :cluster_epoch,
            :actor_name, :serve_route, :node_id,
            :ip_address, :pid
        )
        """
        params = {
            "instance_id": uuid_module.UUID(instance_id),
            "logical_id": logical_id,
            "cluster_epoch": uuid_module.UUID(cluster_epoch),
            "actor_name": actor_name,
            "serve_route": serve_route,
            "node_id": node_id,
            "ip_address": ip_address,  # PostgreSQL will accept string for INET type
            "pid": pid,
        }
        await session.execute(text(q), params)

    async def set_instance_status(
        self, session: AsyncSession, instance_id: str, status: str
    ) -> None:
        """Set the status for a runtime instance (starting/alive/draining/dead)."""
        import uuid as uuid_module

        await session.execute(
            text("SELECT set_instance_status(:instance_id, :status)"),
            {"instance_id": uuid_module.UUID(instance_id), "status": status},
        )

    async def beat(self, session: AsyncSession, instance_id: str) -> None:
        """Update last_heartbeat for the given instance."""
        import uuid as uuid_module

        await session.execute(
            text("SELECT beat(:instance_id)"),
            {"instance_id": uuid_module.UUID(instance_id)},
        )

    async def expire_stale_instances(
        self, session: AsyncSession, timeout_seconds: int = 15
    ) -> int:
        """Mark stale instances as dead; returns number of rows affected."""
        result = await session.execute(
            text("SELECT expire_stale_instances(:timeout)"),
            {"timeout": timeout_seconds},
        )
        return result.scalar_one_or_none() or 0

    async def expire_old_epoch_instances(self, session: AsyncSession) -> int:
        """Mark instances from previous epochs as dead; returns affected count."""
        result = await session.execute(text("SELECT expire_old_epoch_instances()"))
        return result.scalar_one_or_none() or 0

    async def ensure_organ(
        self,
        session: AsyncSession,
        organ_id: str,
        *,
        kind: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Ensure an organ exists in the registry and graph node map.

        Args:
            session: The AsyncSession to use.
            organ_id: Unique identifier for the organ.
            kind: Type/kind of organ (e.g., 'utility', 'actuator', 'retriever').
            props: Additional properties as JSONB.
        """
        # Convert props dict to JSON string for asyncpg JSONB compatibility
        props_json = json.dumps(props) if props else None
        
        await session.execute(
            text("""
                INSERT INTO organ_registry (organ_id, kind, props)
                VALUES (:organ_id, :kind, COALESCE(CAST(:props AS jsonb), '{}'::jsonb))
                ON CONFLICT (organ_id) DO UPDATE
                SET kind = COALESCE(EXCLUDED.kind, organ_registry.kind),
                    props = COALESCE(EXCLUDED.props, organ_registry.props)
            """),
            {"organ_id": organ_id, "kind": kind, "props": props_json},
        )
        await session.execute(
            text("SELECT ensure_organ_node(:organ_id)"), {"organ_id": organ_id}
        )

    async def ensure_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        display_name: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Ensure an agent exists in the registry and graph node map.

        Args:
            session: The AsyncSession to use.
            agent_id: Unique identifier for the agent.
            display_name: Human-readable name for the agent.
            props: Additional properties as JSONB.
        """
        # Convert props dict to JSON string for asyncpg JSONB compatibility
        props_json = json.dumps(props) if props else None
        
        await session.execute(
            text("""
                INSERT INTO agent_registry (agent_id, display_name, props, status)
                VALUES (:agent_id, :display_name, COALESCE(CAST(:props AS jsonb), '{}'::jsonb), 'offline')
                ON CONFLICT (agent_id) DO UPDATE
                SET display_name = COALESCE(EXCLUDED.display_name, agent_registry.display_name),
                    props = COALESCE(EXCLUDED.props, agent_registry.props)
            """),
            {"agent_id": agent_id, "display_name": display_name, "props": props_json},
        )
        await session.execute(
            text("SELECT ensure_agent_node(:agent_id)"), {"agent_id": agent_id}
        )

    async def update_agent_heartbeat(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> None:
        """Update agent heartbeat (status='online', last_seen_at=now).

        Creates agent entry if it doesn't exist (upsert pattern).

        Args:
            session: The AsyncSession to use.
            agent_id: Unique identifier for the agent.
        """
        await session.execute(
            text("""
                INSERT INTO agent_registry (agent_id, status, last_seen_at)
                VALUES (:agent_id, 'online', CURRENT_TIMESTAMP)
                ON CONFLICT (agent_id) DO UPDATE
                SET status = 'online',
                    last_seen_at = CURRENT_TIMESTAMP
            """),
            {"agent_id": agent_id},
        )

    async def update_organ_heartbeat(
        self,
        session: AsyncSession,
        organ_id: str,
    ) -> None:
        """Update organ heartbeat (status='active', last_seen_at=now).

        Creates organ entry if it doesn't exist (upsert pattern).

        Args:
            session: The AsyncSession to use.
            organ_id: Unique identifier for the organ.
        """
        await session.execute(
            text("""
                INSERT INTO organ_registry (organ_id, status, last_seen_at)
                VALUES (:organ_id, 'active', CURRENT_TIMESTAMP)
                ON CONFLICT (organ_id) DO UPDATE
                SET status = 'active',
                    last_seen_at = CURRENT_TIMESTAMP
            """),
            {"organ_id": organ_id},
        )

    async def prune_stale_agents(
        self,
        session: AsyncSession,
        *,
        heartbeat_timeout_minutes: int = 5,
        cleanup_timeout_hours: int = 1,
        keep_static_agents: Optional[list[str]] = None,
    ) -> Dict[str, int]:
        """Prune stale agents (mark offline, optionally delete old ones).

        Args:
            session: The AsyncSession to use.
            heartbeat_timeout_minutes: Minutes without heartbeat before marking offline.
            cleanup_timeout_hours: Hours offline before deletion (0 = never delete).
            keep_static_agents: List of agent IDs to never delete (e.g., core agents).

        Returns:
            Dict with counts: {'marked_offline': int, 'deleted': int}
        """
        keep_static_agents = keep_static_agents or []
        
        # Mark agents as offline if no heartbeat for timeout period
        result_offline = await session.execute(
            text("""
                UPDATE agent_registry
                SET status = 'offline'
                WHERE status = 'online'
                  AND last_seen_at < (CURRENT_TIMESTAMP - INTERVAL ':timeout minutes')
                RETURNING agent_id
            """),
            {"timeout": heartbeat_timeout_minutes},
        )
        marked_offline = len(result_offline.fetchall())

        deleted = 0
        if cleanup_timeout_hours > 0:
            # Build exclusion list for static agents
            if keep_static_agents:
                exclusion_clause = "AND agent_id != ALL(:keep_agents)"
                params = {
                    "timeout": cleanup_timeout_hours,
                    "keep_agents": keep_static_agents,
                }
            else:
                exclusion_clause = ""
                params = {"timeout": cleanup_timeout_hours}

            result_delete = await session.execute(
                text(f"""
                    DELETE FROM agent_registry
                    WHERE status = 'offline'
                      AND last_seen_at < (CURRENT_TIMESTAMP - INTERVAL ':timeout hours')
                      {exclusion_clause}
                    RETURNING agent_id
                """),
                params,
            )
            deleted = len(result_delete.fetchall())

        return {"marked_offline": marked_offline, "deleted": deleted}

    async def prune_stale_organs(
        self,
        session: AsyncSession,
        *,
        heartbeat_timeout_minutes: int = 5,
    ) -> int:
        """Mark stale organs as inactive.

        Args:
            session: The AsyncSession to use.
            heartbeat_timeout_minutes: Minutes without heartbeat before marking inactive.

        Returns:
            Number of organs marked inactive.
        """
        result = await session.execute(
            text("""
                UPDATE organ_registry
                SET status = 'inactive'
                WHERE status = 'active'
                  AND last_seen_at < (CURRENT_TIMESTAMP - INTERVAL ':timeout minutes')
                RETURNING organ_id
            """),
            {"timeout": heartbeat_timeout_minutes},
        )
        return len(result.fetchall())

    async def link_agent_to_organ(
        self, session: AsyncSession, agent_id: str, organ_id: str
    ) -> None:
        """Link an agent to an organ in the agent_member_of_organ relationship.

        Args:
            session: The AsyncSession to use.
            agent_id: Agent identifier.
            organ_id: Organ identifier.
        """
        # Ensure endpoints exist first (idempotent)
        await session.execute(
            text(
                "INSERT INTO agent_registry (agent_id) VALUES (:agent_id) ON CONFLICT DO NOTHING"
            ),
            {"agent_id": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"
            ),
            {"organ_id": organ_id},
        )
        # Create the relationship
        await session.execute(
            text("""
                INSERT INTO agent_member_of_organ (agent_id, organ_id)
                VALUES (:agent_id, :organ_id)
                ON CONFLICT DO NOTHING
            """),
            {"agent_id": agent_id, "organ_id": organ_id},
        )

    async def find_organ_by_skill(
        self, session: AsyncSession, skill_name: str
    ) -> Optional[str]:
        """Find an organ that provides a specific skill.

        Args:
            session: The AsyncSession to use.
            skill_name: Name of the skill to search for.

        Returns:
            Organ ID if found, None otherwise.
        """
        result = await session.execute(
            text("""
                SELECT ps.organ_id
                FROM organ_provides_skill ps
                JOIN organ_registry o ON o.organ_id = ps.organ_id
                WHERE ps.skill_name = :skill_name
                ORDER BY ps.created_at DESC
                LIMIT 1
            """),
            {"skill_name": skill_name},
        )
        return result.scalar_one_or_none()

    async def find_organ_by_service(
        self, session: AsyncSession, service_name: str
    ) -> Optional[str]:
        """Find an organ that uses a specific service.

        Args:
            session: The AsyncSession to use.
            service_name: Name of the service to search for.

        Returns:
            Organ ID if found, None otherwise.
        """
        result = await session.execute(
            text("""
                SELECT us.organ_id
                FROM organ_uses_service us
                JOIN organ_registry o ON o.organ_id = us.organ_id
                WHERE us.service_name = :service_name
                ORDER BY us.created_at DESC
                LIMIT 1
            """),
            {"service_name": service_name},
        )
        return result.scalar_one_or_none()

    async def add_organ_skill(
        self, session: AsyncSession, organ_id: str, skill_name: str
    ) -> None:
        """Add a skill capability to an organ.

        Args:
            session: The AsyncSession to use.
            organ_id: Organ identifier.
            skill_name: Skill name to add.
        """
        # Ensure organ exists
        await session.execute(
            text(
                "INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"
            ),
            {"organ_id": organ_id},
        )
        # Ensure skill exists
        await session.execute(
            text(
                "INSERT INTO skill (skill_name) VALUES (:skill_name) ON CONFLICT DO NOTHING"
            ),
            {"skill_name": skill_name},
        )
        # Create the relationship
        await session.execute(
            text("""
                INSERT INTO organ_provides_skill (organ_id, skill_name)
                VALUES (:organ_id, :skill_name)
                ON CONFLICT DO NOTHING
            """),
            {"organ_id": organ_id, "skill_name": skill_name},
        )

    async def add_organ_service(
        self, session: AsyncSession, organ_id: str, service_name: str
    ) -> None:
        """Add a service usage to an organ.

        Args:
            session: The AsyncSession to use.
            organ_id: Organ identifier.
            service_name: Service name to add.
        """
        # Ensure organ exists
        await session.execute(
            text(
                "INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"
            ),
            {"organ_id": organ_id},
        )
        # Ensure service exists
        await session.execute(
            text(
                "INSERT INTO service (service_name) VALUES (:service_name) ON CONFLICT DO NOTHING"
            ),
            {"service_name": service_name},
        )
        # Create the relationship
        await session.execute(
            text("""
                INSERT INTO organ_uses_service (organ_id, service_name)
                VALUES (:organ_id, :service_name)
                ON CONFLICT DO NOTHING
            """),
            {"organ_id": organ_id, "service_name": service_name},
        )

    async def upsert_agent_collab_bond(
        self,
        session: AsyncSession,
        *,
        src_agent: str,
        dst_agent: str,
        weight: float = 0.5,
        bond_kind: str = "functional",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create or update a collaboration bond between two agents.

        Symmetry is enforced at the overlay level: we store both (src,dst) and (dst,src)
        so that queries remain simple. The energy layer can still treat this as undirected.
        """
        meta = meta or {}

        # Ensure both endpoints exist
        await session.execute(
            text(
                "INSERT INTO agent_registry (agent_id) VALUES (:aid) "
                "ON CONFLICT DO NOTHING"
            ),
            {"aid": src_agent},
        )
        await session.execute(
            text(
                "INSERT INTO agent_registry (agent_id) VALUES (:aid) "
                "ON CONFLICT DO NOTHING"
            ),
            {"aid": dst_agent},
        )

        # Convert meta dict to JSON string for asyncpg JSONB compatibility
        meta_json = json.dumps(meta) if meta else None
        
        q = """
        INSERT INTO agent_collab_agent (src_agent, dst_agent, weight, bond_kind, meta)
        VALUES (:src, :dst, :weight, :bond_kind, COALESCE(CAST(:meta AS jsonb), '{}'::jsonb))
        ON CONFLICT (src_agent, dst_agent) DO UPDATE
        SET weight    = EXCLUDED.weight,
            bond_kind = EXCLUDED.bond_kind,
            meta      = COALESCE(EXCLUDED.meta, agent_collab_agent.meta)
        """

        params = {
            "src": src_agent,
            "dst": dst_agent,
            "weight": float(weight),
            "bond_kind": bond_kind,
            "meta": meta_json,
        }

        # Upsert both directions to keep the table effectively undirected
        await session.execute(text(q), params)
        await session.execute(
            text(q),
            {
                **params,
                "src": dst_agent,
                "dst": src_agent,
            },
        )

    async def get_agent_collab_neighbors(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        min_weight: float = 0.0,
        bond_kinds: Optional[list[str]] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Return neighbors of an agent in the virtual overlay.

        Each result is:
        {
          "agent_id": <neighbor_id>,
          "weight": <float>,
          "bond_kind": <str>,
          "meta": <dict>
        }
        """
        filters = ["c.src_agent = :agent_id", "c.weight >= :min_weight"]
        params: Dict[str, Any] = {
            "agent_id": agent_id,
            "min_weight": float(min_weight),
        }

        if bond_kinds:
            filters.append("c.bond_kind = ANY(:bond_kinds)")
            params["bond_kinds"] = bond_kinds

        where_clause = " AND ".join(filters)
        limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""

        q = f"""
        SELECT c.dst_agent, c.weight, c.bond_kind, c.meta
          FROM agent_collab_agent c
         WHERE {where_clause}
         ORDER BY c.weight DESC
         {limit_clause}
        """

        result = await session.execute(text(q), params)
        rows = result.fetchall()
        return [
            {
                "agent_id": r.dst_agent,
                "weight": float(r.weight),
                "bond_kind": r.bond_kind,
                "meta": r.meta or {},
            }
            for r in rows
        ]

    async def load_agent_overlay_matrix(
        self,
        session: AsyncSession,
        *,
        organ_ids: Optional[list[str]] = None,
        min_weight: float = 0.0,
    ) -> tuple[list[str], "list[list[float]]"]:
        """Build a dense adjacency/weight matrix W for agents in the given organ scope.

        Returns:
            (agent_ids, W) where:
              - agent_ids[i] is the agent at index i
              - W[i][j] is the weight from agent i to agent j
        """
        # 1) Determine the agent set (scope)
        if organ_ids:
            q_agents = """
            SELECT DISTINCT amo.agent_id
              FROM agent_member_of_organ amo
              JOIN organ_registry o ON o.organ_id = amo.organ_id
             WHERE amo.organ_id = ANY(:organ_ids)
             ORDER BY amo.agent_id
            """
            result = await session.execute(text(q_agents), {"organ_ids": organ_ids})
        else:
            q_agents = """
            SELECT DISTINCT a.agent_id
              FROM agent_registry a
             ORDER BY a.agent_id
            """
            result = await session.execute(text(q_agents))

        agent_ids = [row.agent_id for row in result.fetchall()]
        n = len(agent_ids)
        if n == 0:
            return [], []

        # index mapping
        index_of = {aid: idx for idx, aid in enumerate(agent_ids)}

        # 2) Initialize W with a small self-loop
        W = [[0.1 if i == j else 0.0 for j in range(n)] for i in range(n)]

        # 3) Load bonds within this scope
        q_bonds = """
        SELECT src_agent, dst_agent, weight
          FROM agent_collab_agent
         WHERE weight >= :min_weight
           AND src_agent = ANY(:agent_ids)
           AND dst_agent = ANY(:agent_ids)
        """
        result = await session.execute(
            text(q_bonds), {"min_weight": float(min_weight), "agent_ids": agent_ids}
        )
        for row in result.fetchall():
            i = index_of[row.src_agent]
            j = index_of[row.dst_agent]
            if i == j:
                continue
            w = float(row.weight)
            # symmetric assignment, in case DB lacks both directions
            W[i][j] = w
            W[j][i] = w

        return agent_ids, W
