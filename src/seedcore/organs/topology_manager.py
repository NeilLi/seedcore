"""
TopologyManager (Tier-1, OrganismCore)

Responsible for maintaining the Virtual Network Overlay of the organism.
This includes agent-to-agent collaboration bonds, topology seeding from YAML,
dynamic updates, and hydration into W_pair matrices for energy-based routing.

This module does NOT perform routing decisions. Those belong to the
RoutingDirectory (Tier-0). The topology manager keeps the structural &
functional connectivity model of the organism.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from seedcore.graph.agent_repository import AgentGraphRepository

logger = logging.getLogger(__name__)


class TopologyManager:
    """
    Maintains and evolves the organism's functional connectivity (virtual network overlay).

    Responsibilities:
      • Apply YAML topology (initial "genetic" wiring)
      • Manage runtime bond updates (plasticity)
      • Ensure invariants: symmetry, max_degree, min/max weight
      • Hydrate adjacency matrices (W_pair) for StateService / CognitiveCore
      • Provide read-only topology queries for RoutingDirectory
    """

    # Optional invariants
    DEFAULT_MAX_DEGREE = 8
    DEFAULT_MIN_WEIGHT = 0.05
    DEFAULT_MAX_WEIGHT = 1.0

    def __init__(self, repo: AgentGraphRepository):
        self.repo = repo

    # ---------------------------------------------------------------------
    # 1. APPLY GENETIC (YAML) TOPOLOGY
    # ---------------------------------------------------------------------
    async def apply_yaml_topology(
        self,
        session: AsyncSession,
        topology_cfg: Dict[str, Any],
        spec_to_agent_ids: Dict[str, List[str]],
    ) -> None:
        """
        Writes YAML-defined virtual bonds into agent_collab_agent.

        YAML Format:
            strong_pairs:
              - agents: ["A", "B"]
                weight: 0.9
                description: "...text..."
            cross_organ_bonds: [...]
        """
        if not topology_cfg:
            logger.info("No topology section found in organism YAML.")
            return

        groups = (
            topology_cfg.get("strong_pairs", [])
            + topology_cfg.get("cross_organ_bonds", [])
            + topology_cfg.get("learned_bonds", [])
        )

        for bond in groups:
            try:
                spec_a, spec_b = [s.upper() for s in bond["agents"]]
                weight = float(bond.get("weight", 0.5))
                bond_kind = bond.get("bond_kind") or "topology"
                meta = {
                    "description": bond.get("description", ""),
                    "source": "yaml_topology",
                }

                agents_a = spec_to_agent_ids.get(spec_a, [])
                agents_b = spec_to_agent_ids.get(spec_b, [])

                for a in agents_a:
                    for b in agents_b:
                        if a == b:
                            continue
                        await self.update_bond(
                            session,
                            a,
                            b,
                            weight=weight,
                            bond_kind=bond_kind,
                            meta=meta,
                            enforce_invariants=True,
                        )

            except Exception:
                logger.exception(f"Error applying bond: {bond}")

    # ---------------------------------------------------------------------
    # 2. RUNTIME PLASTICITY (UPDATING BONDS)
    # ---------------------------------------------------------------------
    async def update_bond(
        self,
        session: AsyncSession,
        agent_a: str,
        agent_b: str,
        *,
        weight: float,
        bond_kind: str = "dynamic",
        meta: Optional[Dict[str, Any]] = None,
        enforce_invariants: bool = True,
    ) -> None:
        """
        Create or update a bond between two agents.
        Can be called by:
            • learning organ
            • coordinator statistics
            • anomaly detection
            • user-defined tuning

        Tier-0 MUST NOT directly write topology; they call into Tier-1.
        """

        # Apply invariants before DB write
        if enforce_invariants:
            weight = max(self.DEFAULT_MIN_WEIGHT, min(weight, self.DEFAULT_MAX_WEIGHT))

        # Write to DB (symmetric)
        await self.repo.upsert_agent_collab_bond(
            session,
            src_agent=agent_a,
            dst_agent=agent_b,
            weight=weight,
            bond_kind=bond_kind,
            meta=meta or {},
        )

        # Optional: enforce degree limits
        if enforce_invariants:
            await self._enforce_max_degree(session, agent_a)
            await self._enforce_max_degree(session, agent_b)

    # ---------------------------------------------------------------------
    # 3. READ API (USED BY ROUTINGDIRECTORY)
    # ---------------------------------------------------------------------
    async def get_neighbors(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        min_weight: float = 0.1,
        limit: Optional[int] = None,
        bond_kinds: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return virtual neighbors for a given agent.

        Example use (Tier-0 RoutingDirectory):
            partners = topology.get_neighbors(session, target_agent)
        """
        return await self.repo.get_agent_collab_neighbors(
            session,
            agent_id=agent_id,
            min_weight=min_weight,
            bond_kinds=bond_kinds,
            limit=limit,
        )

    # ---------------------------------------------------------------------
    # 4. HYDRATE MATRIX FOR COGNITIVECORE / STATE SERVICE
    # ---------------------------------------------------------------------
    async def get_wpair_matrix(
        self,
        session: AsyncSession,
        *,
        organ_ids: Optional[List[str]] = None,
        min_weight: float = 0.1,
    ) -> Tuple[List[str], List[List[float]]]:
        """
        Returns (agent_ids, W_pair matrix) for the specified organ scope.

        Used by:
            • StateService (system aggregator)
            • CognitiveCore (HGNN reasoning)
            • Energy model (pairwise term)
        """
        return await self.repo.load_agent_overlay_matrix(
            session,
            organ_ids=organ_ids,
            min_weight=min_weight,
        )

    # ---------------------------------------------------------------------
    # 5. INVARIANTS
    # ---------------------------------------------------------------------
    async def _enforce_max_degree(
        self, session: AsyncSession, agent_id: str
    ) -> None:
        """
        If an agent has more neighbors than MAX_DEGREE,
        drop the weakest weights to restore stability.
        """

        neighbors = await self.get_neighbors(
            session,
            agent_id,
            min_weight=0.0,
            limit=None,
        )

        if len(neighbors) <= self.DEFAULT_MAX_DEGREE:
            return

        # Sort by weight descending
        neighbors.sort(key=lambda n: n["weight"], reverse=True)
        keep = neighbors[: self.DEFAULT_MAX_DEGREE]
        drop = neighbors[self.DEFAULT_MAX_DEGREE :]

        for edge in drop:
            await self.update_bond(
                session,
                agent_id,
                edge["agent_id"],
                weight=self.DEFAULT_MIN_WEIGHT,
                bond_kind="trimmed",
                meta={"reason": "max_degree_enforced"},
                enforce_invariants=False,
            )

