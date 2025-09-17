"""Repository for agent and organ registry persistence and graph relationships."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class AgentGraphRepository:
    """Repository for managing agent and organ registry persistence and relationships.
    
    This repository handles:
    - Creating/updating agent and organ registry entries
    - Linking agents to organs (agent_member_of_organ)
    - Querying organs by skill or service capabilities
    - Ensuring graph node consistency via ensure_*_node functions
    - Runtime registry management with connection pooling
    """

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None

    async def _pool_lazy(self) -> asyncpg.Pool:
        """Lazy initialization of connection pool."""
        if self._pool is None:
            # Use database.py to construct the DSN from individual POSTGRES_* variables
            from ..database import PG_DSN
            dsn = PG_DSN
            self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
        return self._pool

    # ---------------------------------------------------------------------
    # Runtime registry: epoch and instance lifecycle
    # ---------------------------------------------------------------------
    async def get_current_cluster_epoch(self) -> str:
        """Return the current cluster epoch (UUID as string) or create one if missing."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            row = await con.fetchrow("SELECT current_epoch::text FROM cluster_metadata WHERE id=1")
            if row:
                return row[0]
            # If missing, create one implicitly (rare in prod)
            import uuid
            new_epoch = str(uuid.uuid4())
            await con.execute("SELECT set_current_epoch($1::uuid)", new_epoch)
            return new_epoch

    async def set_current_cluster_epoch(self, epoch: str) -> None:
        """Rotate/set the current epoch under advisory lock."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            await con.execute("SELECT set_current_epoch($1::uuid)", str(epoch))

    async def register_instance(
        self,
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
        pool = await self._pool_lazy()
        q = """
        SELECT register_instance($1::uuid,$2,$3::uuid,$4,$5,$6,$7::inet,$8::int)
        """
        args = (
            instance_id, logical_id, cluster_epoch,
            actor_name, serve_route, node_id,
            ip_address, pid,
        )
        async with pool.acquire() as con:
            await con.execute(q, *args)

    async def set_instance_status(self, instance_id: str, status: str) -> None:
        """Set the status for a runtime instance (starting/alive/draining/dead)."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            await con.execute("SELECT set_instance_status($1::uuid, $2::InstanceStatus)", instance_id, status)

    async def beat(self, instance_id: str) -> None:
        """Update last_heartbeat for the given instance."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            await con.execute("SELECT beat($1::uuid)", instance_id)

    async def expire_stale_instances(self, timeout_seconds: int = 15) -> int:
        """Mark stale instances as dead; returns number of rows affected."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            row = await con.fetchrow("SELECT expire_stale_instances($1)", timeout_seconds)
            return row[0] if row else 0

    async def expire_old_epoch_instances(self) -> int:
        """Mark instances from previous epochs as dead; returns affected count."""
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            row = await con.fetchrow("SELECT expire_old_epoch_instances()")
            return row[0] if row else 0

    async def ensure_organ(self, organ_id: str, *, kind: Optional[str] = None, props: Optional[dict] = None) -> None:
        """Ensure an organ exists in the registry and graph node map.
        
        Args:
            organ_id: Unique identifier for the organ
            kind: Type/kind of organ (e.g., 'utility', 'actuator', 'retriever')
            props: Additional properties as JSONB
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            await con.execute("""
                INSERT INTO organ_registry (organ_id, kind, props)
                VALUES ($1, $2, COALESCE($3, '{}'::jsonb))
                ON CONFLICT (organ_id) DO UPDATE
                SET kind = COALESCE(EXCLUDED.kind, organ_registry.kind),
                    props = COALESCE(EXCLUDED.props, organ_registry.props)
            """, organ_id, kind, props)
            await con.execute("SELECT ensure_organ_node($1)", organ_id)

    async def ensure_agent(self, agent_id: str, *, display_name: Optional[str] = None, props: Optional[dict] = None) -> None:
        """Ensure an agent exists in the registry and graph node map.
        
        Args:
            agent_id: Unique identifier for the agent
            display_name: Human-readable name for the agent
            props: Additional properties as JSONB
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            await con.execute("""
                INSERT INTO agent_registry (agent_id, display_name, props)
                VALUES ($1, $2, COALESCE($3, '{}'::jsonb))
                ON CONFLICT (agent_id) DO UPDATE
                SET display_name = COALESCE(EXCLUDED.display_name, agent_registry.display_name),
                    props = COALESCE(EXCLUDED.props, agent_registry.props)
            """, agent_id, display_name, props)
            await con.execute("SELECT ensure_agent_node($1)", agent_id)

    async def link_agent_to_organ(self, agent_id: str, organ_id: str) -> None:
        """Link an agent to an organ in the agent_member_of_organ relationship.
        
        Args:
            agent_id: Agent identifier
            organ_id: Organ identifier
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            # Ensure endpoints exist first (idempotent)
            await con.execute("INSERT INTO agent_registry (agent_id) VALUES ($1) ON CONFLICT DO NOTHING", agent_id)
            await con.execute("INSERT INTO organ_registry (organ_id) VALUES ($1) ON CONFLICT DO NOTHING", organ_id)
            # Create the relationship
            await con.execute("""
                INSERT INTO agent_member_of_organ (agent_id, organ_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, agent_id, organ_id)

    async def find_organ_by_skill(self, skill_name: str) -> Optional[str]:
        """Find an organ that provides a specific skill.
        
        Args:
            skill_name: Name of the skill to search for
            
        Returns:
            Organ ID if found, None otherwise
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            row = await con.fetchrow("""
                SELECT ps.organ_id
                FROM organ_provides_skill ps
                JOIN organ_registry o ON o.organ_id = ps.organ_id
                WHERE ps.skill_name = $1
                ORDER BY ps.created_at DESC
                LIMIT 1
            """, skill_name)
            return row[0] if row else None

    async def find_organ_by_service(self, service_name: str) -> Optional[str]:
        """Find an organ that uses a specific service.
        
        Args:
            service_name: Name of the service to search for
            
        Returns:
            Organ ID if found, None otherwise
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            row = await con.fetchrow("""
                SELECT us.organ_id
                FROM organ_uses_service us
                JOIN organ_registry o ON o.organ_id = us.organ_id
                WHERE us.service_name = $1
                ORDER BY us.created_at DESC
                LIMIT 1
            """, service_name)
            return row[0] if row else None

    async def add_organ_skill(self, organ_id: str, skill_name: str) -> None:
        """Add a skill capability to an organ.
        
        Args:
            organ_id: Organ identifier
            skill_name: Skill name to add
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            # Ensure organ exists
            await con.execute("INSERT INTO organ_registry (organ_id) VALUES ($1) ON CONFLICT DO NOTHING", organ_id)
            # Ensure skill exists
            await con.execute("INSERT INTO skill (skill_name) VALUES ($1) ON CONFLICT DO NOTHING", skill_name)
            # Create the relationship
            await con.execute("""
                INSERT INTO organ_provides_skill (organ_id, skill_name)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, organ_id, skill_name)

    async def add_organ_service(self, organ_id: str, service_name: str) -> None:
        """Add a service usage to an organ.
        
        Args:
            organ_id: Organ identifier
            service_name: Service name to add
        """
        pool = await self._pool_lazy()
        async with pool.acquire() as con:
            # Ensure organ exists
            await con.execute("INSERT INTO organ_registry (organ_id) VALUES ($1) ON CONFLICT DO NOTHING", organ_id)
            # Ensure service exists
            await con.execute("INSERT INTO service (service_name) VALUES ($1) ON CONFLICT DO NOTHING", service_name)
            # Create the relationship
            await con.execute("""
                INSERT INTO organ_uses_service (organ_id, service_name)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, organ_id, service_name)
