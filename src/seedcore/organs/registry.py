# seedcore/organs/registry.py

from __future__ import annotations

import logging
from typing import Dict, List, Optional

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

    def __init__(self, repo: AgentGraphRepository):
        self.repo = repo
        self.topology = TopologyManager(repo)

        # === Dynamic runtime registry maps ===
        self.organs: Dict[str, Dict[str, any]] = {}        # organ_id -> organ metadata
        self.organ_handles: Dict[str, any] = {}            # organ_id -> Organ Ray actor handle

        self.agent_to_organ: Dict[str, str] = {}           # agent_id -> organ_id
        self.agent_specialization: Dict[str, str] = {}     # agent_id -> specialization (string)
        self.specialization_to_agents: Dict[str, List[str]] = {}  # specialization -> [agent_ids]

    # ------------------------------------------------------------------
    # ORGAN REGISTRATION
    # ------------------------------------------------------------------
    def record_organ(self, organ_id: str, organ_handle: any):
        """Register organ metadata + Ray actor handle."""
        self.organs[organ_id] = {"organ_id": organ_id}
        self.organ_handles[organ_id] = organ_handle
        logger.info(f"[OrganismRegistry] Registered organ {organ_id}")

    # ------------------------------------------------------------------
    # AGENT REGISTRATION (via Organ actor)
    # ------------------------------------------------------------------
    async def register_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        organ_id: str,
        specialization: str,
    ) -> None:
        """
        Called when OrganActor.create_agent() succeeds.

        This method updates Tier-1 registry and DB (agent_member_of_organ).
        """

        logger.info(
            f"[OrganismRegistry] Register agent {agent_id} under organ {organ_id} "
            f"spec={specialization}"
        )

        # 1) Update Tier-1 in-memory registry
        self.agent_to_organ[agent_id] = organ_id
        self.agent_specialization[agent_id] = specialization.lower()

        # Maintain reverse mapping (spec → agent list)
        self.specialization_to_agents.setdefault(specialization.lower(), []).append(agent_id)

        # 2) Update DB registry
        await self.repo.ensure_agent(session, agent_id)
        await self.repo.ensure_organ(session, organ_id)
        await self.repo.link_agent_to_organ(session, agent_id, organ_id)

    # ------------------------------------------------------------------
    # SPECIALIZATION → AGENT MAP (for topology)
    # ------------------------------------------------------------------
    def get_spec_to_agent_ids(self) -> Dict[str, List[str]]:
        return self.specialization_to_agents

    # ------------------------------------------------------------------
    # AGENT MIGRATION (dynamic)
    # ------------------------------------------------------------------
    async def migrate_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        new_organ_id: str,
    ) -> None:
        """
        Tier-1 migration:
            • updates DB membership
            • updates in-memory registry
        """

        if agent_id not in self.agent_to_organ:
            raise RuntimeError(f"Cannot migrate unknown agent {agent_id}")

        old_organ = self.agent_to_organ[agent_id]
        spec = self.agent_specialization.get(agent_id, "generalist")

        logger.info(
            f"[OrganismRegistry] 🔄 Migrating agent {agent_id} "
            f"{spec} from {old_organ} → {new_organ_id}"
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
