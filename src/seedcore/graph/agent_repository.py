"""Repository helpers for agent and organ registry persistence and graph relationships.

This repository is stateless and centralizes CRUD helpers for agents and organs.
It expects an ``AsyncSession`` to be injected into its methods.

The caller is responsible for session lifecycle and transaction management
(e.g., ``async with session.begin()``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional, Dict, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
            return epoch

        # If missing, create one implicitly
        new_epoch = str(uuid.uuid4())
        await session.execute(
            text("SELECT set_current_epoch(:epoch::uuid)"),
            {"epoch": new_epoch}
        )
        return new_epoch

    async def set_current_cluster_epoch(self, session: AsyncSession, epoch: str) -> None:
        """Rotate/set the current epoch."""
        await session.execute(
            text("SELECT set_current_cluster_epoch(:epoch::uuid)"),
            {"epoch": str(epoch)}
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
        q = """
        SELECT register_instance(
            :instance_id::uuid, :logical_id, :cluster_epoch::uuid,
            :actor_name, :serve_route, :node_id,
            :ip_address::inet, :pid::int
        )
        """
        params = {
            "instance_id": instance_id,
            "logical_id": logical_id,
            "cluster_epoch": cluster_epoch,
            "actor_name": actor_name,
            "serve_route": serve_route,
            "node_id": node_id,
            "ip_address": ip_address,
            "pid": pid,
        }
        await session.execute(text(q), params)

    async def set_instance_status(
        self, session: AsyncSession, instance_id: str, status: str
    ) -> None:
        """Set the status for a runtime instance (starting/alive/draining/dead)."""
        await session.execute(
            text("SELECT set_instance_status(:instance_id::uuid, :status::InstanceStatus)"),
            {"instance_id": instance_id, "status": status}
        )

    async def beat(self, session: AsyncSession, instance_id: str) -> None:
        """Update last_heartbeat for the given instance."""
        await session.execute(
            text("SELECT beat(:instance_id::uuid)"),
            {"instance_id": instance_id}
        )

    async def expire_stale_instances(
        self, session: AsyncSession, timeout_seconds: int = 15
    ) -> int:
        """Mark stale instances as dead; returns number of rows affected."""
        result = await session.execute(
            text("SELECT expire_stale_instances(:timeout)"),
            {"timeout": timeout_seconds}
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
        await session.execute(
            text("""
                INSERT INTO organ_registry (organ_id, kind, props)
                VALUES (:organ_id, :kind, COALESCE(:props, '{}'::jsonb))
                ON CONFLICT (organ_id) DO UPDATE
                SET kind = COALESCE(EXCLUDED.kind, organ_registry.kind),
                    props = COALESCE(EXCLUDED.props, organ_registry.props)
            """),
            {"organ_id": organ_id, "kind": kind, "props": props},
        )
        await session.execute(
            text("SELECT ensure_organ_node(:organ_id)"),
            {"organ_id": organ_id}
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
        await session.execute(
            text("""
                INSERT INTO agent_registry (agent_id, display_name, props)
                VALUES (:agent_id, :display_name, COALESCE(:props, '{}'::jsonb))
                ON CONFLICT (agent_id) DO UPDATE
                SET display_name = COALESCE(EXCLUDED.display_name, agent_registry.display_name),
                    props = COALESCE(EXCLUDED.props, agent_registry.props)
            """),
            {"agent_id": agent_id, "display_name": display_name, "props": props},
        )
        await session.execute(
            text("SELECT ensure_agent_node(:agent_id)"),
            {"agent_id": agent_id}
        )

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
            text("INSERT INTO agent_registry (agent_id) VALUES (:agent_id) ON CONFLICT DO NOTHING"),
            {"agent_id": agent_id},
        )
        await session.execute(
            text("INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"),
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
            text("INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"),
            {"organ_id": organ_id},
        )
        # Ensure skill exists
        await session.execute(
            text("INSERT INTO skill (skill_name) VALUES (:skill_name) ON CONFLICT DO NOTHING"),
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
            text("INSERT INTO organ_registry (organ_id) VALUES (:organ_id) ON CONFLICT DO NOTHING"),
            {"organ_id": organ_id},
        )
        # Ensure service exists
        await session.execute(
            text("INSERT INTO service (service_name) VALUES (:service_name) ON CONFLICT DO NOTHING"),
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
