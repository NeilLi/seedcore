# seedcore/organs/registry.py

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from seedcore.graph.agent_repository import AgentGraphRepository
from seedcore.organs.topology_manager import TopologyManager

logger = logging.getLogger(__name__)


class OrganRegistry:
    """
    Tier-1 Dynamic Registry for the Organism.

    This is the authoritative registry for:
      • organs (their organ actors & metadata)
      • agents (their organ, specialization, ray handle, metadata)
      • dynamic topology updates (via TopologyManager)
      • agent migrations between organs
      • specialization → agent mapping (for YAML topology seeding)

    The Organ actors themselves are Tier-2 — they only contain
    local agent handles and metadata. The registry is Tier-1.
    """

    def __init__(
        self, 
        repo: AgentGraphRepository,
        session_factory: Optional[Callable[[], Any]] = None,
    ):
        self.repo = repo
        self.topology = TopologyManager(repo)
        self._session_factory = session_factory  # Optional session factory for DB writes

        # === Dynamic runtime registry maps ===
        self.organs: Dict[str, Dict[str, any]] = {}        # organ_id -> organ metadata
        self.organ_handles: Dict[str, any] = {}            # organ_id -> Organ Ray actor handle

        self.agent_to_organ: Dict[str, str] = {}           # agent_id -> organ_id
        self.agent_specialization: Dict[str, str] = {}     # agent_id -> specialization (string)
        self.specialization_to_agents: Dict[str, List[str]] = {}  # specialization -> [agent_ids]

    # ------------------------------------------------------------------
    # ORGAN REGISTRATION
    # ------------------------------------------------------------------
    async def record_organ(
        self, 
        organ_id: str, 
        organ_handle: any,
        session: Optional[AsyncSession] = None,
        *,
        kind: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
    ):
        """
        Register organ metadata + Ray actor handle.
        
        Also persists to database if session is provided or session_factory is available.
        
        Args:
            organ_id: Organ identifier
            organ_handle: Ray actor handle for the organ
            session: Optional database session (if None, will create one if session_factory available)
            kind: Optional organ kind/type
            props: Optional organ properties as JSONB
        """
        # Update in-memory registry
        self.organs[organ_id] = {"organ_id": organ_id, "kind": kind, "props": props}
        self.organ_handles[organ_id] = organ_handle
        
        # Persist to database if possible
        if session:
            # Use provided session
            await self.repo.ensure_organ(session, organ_id, kind=kind, props=props)
            logger.info(f"[OrganismRegistry] Registered organ {organ_id} (persisted to DB)")
        elif self._session_factory:
            # Create session from factory
            try:
                async with self._session_factory() as db_session:
                    async with db_session.begin():
                        await self.repo.ensure_organ(db_session, organ_id, kind=kind, props=props)
                    logger.info(f"[OrganismRegistry] Registered organ {organ_id} (persisted to DB)")
            except Exception as e:
                logger.warning(f"[OrganismRegistry] Failed to persist organ {organ_id} to DB: {e}")
                logger.info(f"[OrganismRegistry] Registered organ {organ_id} (in-memory only)")
        else:
            logger.info(f"[OrganismRegistry] Registered organ {organ_id} (in-memory only, no DB session)")

    # ------------------------------------------------------------------
    # AGENT REGISTRATION (via Organ actor)
    # ------------------------------------------------------------------
    async def register_agent(
        self,
        session: Optional[AsyncSession],
        *,
        agent_id: str,
        organ_id: str,
        specialization: str,
        display_name: Optional[str] = None,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Called when OrganActor.create_agent() succeeds.

        This method updates Tier-1 registry and DB (agent_member_of_organ).
        
        Supports both static Specialization enum values and DynamicSpecialization values.
        Specializations are normalized to lowercase for consistent lookup.
        
        Args:
            session: Optional database session. If None, will create one if session_factory available.
            agent_id: Agent identifier
            organ_id: Organ identifier
            specialization: Specialization string (will be normalized)
            display_name: Optional display name for the agent
            props: Optional agent properties as JSONB
        """

        # Normalize specialization to lowercase for consistency
        # This ensures compatibility with both static (USER_LIAISON -> user_liaison)
        # and dynamic (custom_agent_v2 -> custom_agent_v2) specializations
        spec_normalized = str(specialization).strip().lower()

        logger.info(
            f"[OrganismRegistry] Register agent {agent_id} under organ {organ_id} "
            f"spec={spec_normalized}"
        )

        # Handle agent re-registration (e.g., if specialization changed)
        # Remove from old specialization mapping if agent was previously registered
        if agent_id in self.agent_specialization:
            old_spec = self.agent_specialization[agent_id]
            if old_spec != spec_normalized:
                # Remove from old specialization's agent list
                if old_spec in self.specialization_to_agents:
                    if agent_id in self.specialization_to_agents[old_spec]:
                        self.specialization_to_agents[old_spec].remove(agent_id)
                    # Clean up empty lists
                    if not self.specialization_to_agents[old_spec]:
                        del self.specialization_to_agents[old_spec]
                logger.debug(
                    f"[OrganismRegistry] Agent {agent_id} specialization changed: "
                    f"{old_spec} → {spec_normalized}"
                )

        # 1) Update Tier-1 in-memory registry
        self.agent_to_organ[agent_id] = organ_id
        self.agent_specialization[agent_id] = spec_normalized

        # Maintain reverse mapping (spec → agent list)
        # Avoid duplicates if agent is re-registered with same specialization
        if spec_normalized not in self.specialization_to_agents:
            self.specialization_to_agents[spec_normalized] = []
        if agent_id not in self.specialization_to_agents[spec_normalized]:
            self.specialization_to_agents[spec_normalized].append(agent_id)

        # 2) Update DB registry (if session available or can create one)
        if session:
            # Use provided session
            await self.repo.ensure_agent(session, agent_id, display_name=display_name, props=props)
            await self.repo.ensure_organ(session, organ_id)
            await self.repo.link_agent_to_organ(session, agent_id, organ_id)
            logger.debug(f"[OrganismRegistry] Agent {agent_id} persisted to DB")
        else:
            # Try to create a session (either from factory or on-demand)
            session_factory = self._session_factory
            if not session_factory:
                # Create session factory on-demand (for Organ actors that don't have one)
                try:
                    from seedcore.database import get_async_pg_session_factory
                    session_factory = get_async_pg_session_factory()
                except Exception as e:
                    logger.debug(f"[OrganismRegistry] Could not create session factory: {e}")
                    session_factory = None
            
            if session_factory:
                # Create session from factory
                try:
                    async with session_factory() as db_session:
                        async with db_session.begin():
                            await self.repo.ensure_agent(db_session, agent_id, display_name=display_name, props=props)
                            await self.repo.ensure_organ(db_session, organ_id)
                            await self.repo.link_agent_to_organ(db_session, agent_id, organ_id)
                        logger.debug(f"[OrganismRegistry] Agent {agent_id} persisted to DB")
                except Exception as e:
                    logger.warning(f"[OrganismRegistry] Failed to persist agent {agent_id} to DB: {e}")
                    logger.debug(f"[OrganismRegistry] Agent {agent_id} registered in-memory only")
            else:
                logger.debug(f"[OrganismRegistry] Agent {agent_id} registered in-memory only (no DB session)")

    # ------------------------------------------------------------------
    # SPECIALIZATION → AGENT MAP (for topology)
    # ------------------------------------------------------------------
    def get_spec_to_agent_ids(self) -> Dict[str, List[str]]:
        """
        Get the specialization → agent IDs mapping.
        
        This is used by TopologyManager to apply YAML topology bonds.
        Returns a copy to prevent external modification.
        
        Returns:
            Dict mapping normalized specialization (lowercase) -> list of agent IDs
        """
        # Return a copy to prevent external modification
        return {spec: list(agent_ids) for spec, agent_ids in self.specialization_to_agents.items()}
    
    def get_agents_by_specialization(self, specialization: str) -> List[str]:
        """
        Get all agent IDs with a given specialization.
        
        Supports both static and dynamic specializations by normalizing input.
        
        Args:
            specialization: Specialization string (will be normalized to lowercase)
            
        Returns:
            List of agent IDs with this specialization
        """
        spec_normalized = str(specialization).strip().lower()
        return list(self.specialization_to_agents.get(spec_normalized, []))

    # ------------------------------------------------------------------
    # AGENT MIGRATION (dynamic)
    # ------------------------------------------------------------------
    async def migrate_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        new_organ_id: str,
        new_specialization: Optional[str] = None,
    ) -> None:
        """
        Tier-1 migration:
            • updates DB membership
            • updates in-memory registry
            • optionally updates specialization (if agent's specialization changed)
        
        Args:
            agent_id: Agent to migrate
            new_organ_id: Target organ ID
            new_specialization: Optional new specialization (if agent's specialization changed)
        """

        if agent_id not in self.agent_to_organ:
            raise RuntimeError(f"Cannot migrate unknown agent {agent_id}")

        old_organ = self.agent_to_organ[agent_id]
        old_spec = self.agent_specialization.get(agent_id, "generalist")
        
        # Handle specialization change if provided
        if new_specialization:
            new_spec_normalized = str(new_specialization).strip().lower()
            if new_spec_normalized != old_spec:
                # Update specialization mapping
                if old_spec in self.specialization_to_agents:
                    if agent_id in self.specialization_to_agents[old_spec]:
                        self.specialization_to_agents[old_spec].remove(agent_id)
                    if not self.specialization_to_agents[old_spec]:
                        del self.specialization_to_agents[old_spec]
                
                # Add to new specialization
                if new_spec_normalized not in self.specialization_to_agents:
                    self.specialization_to_agents[new_spec_normalized] = []
                if agent_id not in self.specialization_to_agents[new_spec_normalized]:
                    self.specialization_to_agents[new_spec_normalized].append(agent_id)
                
                self.agent_specialization[agent_id] = new_spec_normalized
                logger.info(
                    f"[OrganismRegistry] 🔄 Migrating agent {agent_id} "
                    f"{old_spec} → {new_spec_normalized} from {old_organ} → {new_organ_id}"
                )
            else:
                logger.info(
                    f"[OrganismRegistry] 🔄 Migrating agent {agent_id} "
                    f"{old_spec} from {old_organ} → {new_organ_id}"
                )
        else:
            logger.info(
                f"[OrganismRegistry] 🔄 Migrating agent {agent_id} "
                f"{old_spec} from {old_organ} → {new_organ_id}"
            )

        # 1. Update DB membership
        await self.repo.ensure_organ(session, new_organ_id)
        await self.repo.link_agent_to_organ(session, agent_id, new_organ_id)

        # 2. Update tier-1 registry
        self.agent_to_organ[agent_id] = new_organ_id

    # ------------------------------------------------------------------
    #  TOPOLOGY (this connects to TopologyManager)
    # ------------------------------------------------------------------

    async def apply_yaml_topology(self, session: AsyncSession, topology_cfg: dict):
        """
        Tier-1 call at organism boot.
        Applies genetic topology using TopologyManager.
        """
        spec_map = self.get_spec_to_agent_ids()
        await self.topology.apply_yaml_topology(session, topology_cfg, spec_map)
        logger.info("Applied YAML topology to organism virtual bond graph.")

    async def update_bond(
        self,
        session: AsyncSession,
        agent_a: str,
        agent_b: str,
        weight: float,
        bond_kind: str = "dynamic",
        meta: Optional[dict] = None,
    ):
        """
        Tier-1 dynamic update — called by Coordinator, Learning Organ, etc.
        """
        await self.topology.update_bond(
            session,
            agent_a,
            agent_b,
            weight=weight,
            bond_kind=bond_kind,
            meta=meta,
        )

    async def get_neighbors(
        self, session: AsyncSession, agent_id: str, min_weight=0.1
    ):
        """
        Tier-1 read API for RoutingDirectory.
        """
        return await self.topology.get_neighbors(
            session, agent_id, min_weight=min_weight
        )

    async def get_wpair(self, session: AsyncSession):
        """
        For CognitiveCore / StateService graph hydration.
        """
        return await self.topology.get_wpair_matrix(session)
