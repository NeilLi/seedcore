# Copyright 2024 SeedCore Contributors
# ... (Apache License) ...

"""
AgentAggregator - Proactive aggregator for agent state.

This service runs a continuous background loop to poll all live agent actors
and aggregate their state. It provides a real-time, cached view of the
entire organism's agent-level state and pre-computes system-wide metrics
for the Coordinator.

This replaces the on-demand AgentStateAggregator and is designed to be a
core component of the proactive StateService.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from collections import defaultdict
import numpy as np
import ray  # pyright: ignore[reportMissingImports]
from seedcore.graph.agent_repository import AgentGraphRepository  # pyright: ignore[reportMissingImports]
from seedcore.database import get_async_pg_session_factory

# --- Model Import ---
# AgentSnapshot is a dataclass from models.state that includes:
# - h: np.ndarray  # State embedding (128-dim)
# - p: Dict[str, float]  # Role probabilities (E/S/O)
# - c: float  # Capability score
# - mem_util: float  # Memory utilization
# - lifecycle: str  # Lifecycle state
# - learned_skills: Dict[str, float]  # Agent's skill levels (deltas)
# - load: float  # Operational activity load
# - timestamp: float  # When snapshot was taken
# - schema_version: str  # Schema version for compatibility
from ...models.state import AgentSnapshot


logger = logging.getLogger(__name__)


class AgentAggregator:
    """
    Runs a background loop to proactively collect and cache agent state
    and compute system-wide metrics.
    """

    def __init__(
        self,
        organism_router: Any,
        graph_repo: AgentGraphRepository,
        poll_interval: float = 2.0,
    ):
        """
        Initialize the proactive agent state aggregator.

        Args:
            organism_router: A Ray handle to the OrganismCore (v2) router,
                             which acts as the "global control plane".
            poll_interval: How often (in seconds) to poll all agents.
        """
        self.organism_router = organism_router
        self.graph_repo = graph_repo
        self.poll_interval = poll_interval

        # Internal state cache
        self._agent_snapshots: Dict[str, AgentSnapshot] = {}
        self._system_metrics: Dict[str, Any] = {}
        self._last_update_time: float = 0.0

        # Control
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._is_running = asyncio.Event()  # Set when first poll completes

        logger.info("✅ AgentAggregator initialized")

    async def start(self):
        """Start the proactive polling loop."""
        if self._loop_task is None or self._loop_task.done():
            logger.info(
                f"Starting proactive agent poll loop (interval: {self.poll_interval}s)"
            )
            self._loop_task = asyncio.create_task(self._poll_loop())
        else:
            logger.warning("Poll loop is already running.")

    async def stop(self):
        """Stop the proactive polling loop."""
        if self.is_running() and self._loop_task:
            logger.info("Stopping proactive agent poll loop...")
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        self._is_running.clear()
        logger.info("Proactive agent poll loop stopped.")

    def is_running(self) -> bool:
        """Check if the loop is running and has data."""
        return self._is_running.is_set()

    async def wait_for_first_poll(self, timeout: float = 10.0):
        """Waits for the first data poll to complete."""
        try:
            await asyncio.wait_for(self._is_running.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Timeout: Aggregator failed to get first poll data.")
            raise

    # --- Main Proactive Loop ---

    async def _poll_loop(self):
        """The main background task that continuously polls agents."""
        while True:
            try:
                start_time = time.monotonic()

                async with get_async_pg_session_factory()() as session:
                    agent_ids_W, W_pair = await self.graph_repo.load_agent_overlay_matrix(
                        session,
                        organ_ids=None,
                        min_weight=0.01,
                    )

                # 1. Discover all live agents from the global router
                # This call uses the new OrganismService (v2) which wraps OrganismCore.
                # OrganismCore aggregates handles from all organs.
                agent_handles_ref = (
                    self.organism_router.rpc_get_all_agent_handles.remote()
                )
                agent_handles: Dict[str, Any] = await self._async_ray_get(
                    agent_handles_ref
                )

                if not agent_handles:
                    logger.warning(
                        "No agent handles found. System may be scaling to zero."
                    )
                    empty_metrics = self._compute_system_metrics({}, {})
                    await self._update_state({}, empty_metrics)  # Clear state
                    await asyncio.sleep(self.poll_interval)
                    continue

                # 2. Batch-collect snapshots and specializations from all agents
                # Use get_snapshot() which directly returns AgentSnapshot (the bridge method)
                ordered_ids = list(agent_handles.keys())
                ordered_handles = list(agent_handles.values())

                snapshot_refs = [h.get_snapshot.remote() for h in ordered_handles]
                # Also fetch specializations in parallel for specialization distribution metrics
                specialization_refs = [
                    h.advertise_capabilities.remote() for h in ordered_handles
                ]

                snapshots = await self._async_ray_get(snapshot_refs)
                specialization_data = await self._async_ray_get(specialization_refs)

                # 3. Process snapshots and extract specializations
                new_snapshots: Dict[str, AgentSnapshot] = {}
                agent_specializations: Dict[str, str] = {}

                for i, agent_id in enumerate(ordered_ids):
                    try:
                        snapshot = (
                            snapshots[i]
                            if i < len(snapshots) and snapshots[i] is not None
                            else None
                        )
                        if snapshot is None:
                            logger.debug(
                                f"Agent {agent_id} returned None snapshot (likely unhealthy)."
                            )
                            continue  # Skip unhealthy/non-responsive agent

                        # Validate it's an AgentSnapshot
                        if not isinstance(snapshot, AgentSnapshot):
                            logger.warning(
                                f"Agent {agent_id} returned invalid snapshot type: {type(snapshot)}"
                            )
                            continue

                        new_snapshots[agent_id] = snapshot

                        # Extract specialization from advertisement data
                        spec_data = (
                            specialization_data[i]
                            if i < len(specialization_data)
                            and specialization_data[i] is not None
                            else None
                        )
                        if spec_data and isinstance(spec_data, dict):
                            agent_specializations[agent_id] = spec_data.get(
                                "specialization", "unknown"
                            )
                        else:
                            # Fallback: use "unknown" if we can't get specialization
                            agent_specializations[agent_id] = "unknown"

                    except Exception as e:
                        logger.warning(
                            f"Failed to process snapshot for agent {agent_id}: {e}"
                        )
                        continue

                # 4. Pre-compute system-wide metrics for the Coordinator (topology-aware)
                new_metrics = self._compute_system_metrics(
                    new_snapshots,
                    agent_specializations,
                    agent_ids_W=agent_ids_W,
                    W_pair=W_pair,
                )

                # 5. Atomically update the internal state
                await self._update_state(new_snapshots, new_metrics)

                # Signal that we have data
                self._is_running.set()

                # Account for processing time in sleep
                duration = time.monotonic() - start_time
                await asyncio.sleep(max(0, self.poll_interval - duration))

            except asyncio.CancelledError:
                logger.info("Poll loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in agent poll loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _update_state(
        self, snapshots: Dict[str, AgentSnapshot], metrics: Dict[str, Any]
    ):
        """Atomically update the shared state."""
        async with self._lock:
            self._agent_snapshots = snapshots
            self._system_metrics = metrics
            self._last_update_time = time.time()

    # --- Public API (Getters) ---
    # These methods are now O(1) cache lookups.

    async def get_all_agent_snapshots(self) -> Dict[str, AgentSnapshot]:
        """
        Get all cached agent snapshots. (O(1) lookup)
        """
        if not self.is_running():
            logger.warning("get_all_agent_snapshots called before first poll.")
            return {}

        async with self._lock:
            return self._agent_snapshots.copy()

    async def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get pre-computed system-wide metrics for the Coordinator. (O(1) lookup)

        Includes:
        - system_specialization_vector
        - total_agents
        - avg_capability
        - lifecycle_distribution
        - etc.
        """
        if not self.is_running():
            logger.debug("get_system_metrics called before first poll - returning empty metrics (not ready yet).")
            return {}

        async with self._lock:
            return self._system_metrics.copy()

    async def get_last_update_time(self) -> float:
        """Get the timestamp of the last successful poll."""
        return self._last_update_time

    # --- Helper Functions ---

    async def _async_ray_get(self, refs) -> Any:
        """
        Safely resolve Ray references with proper error handling.

        Optimized to batch ObjectRefs when possible to reduce thread overhead.
        """
        try:
            if isinstance(refs, list):
                if not refs:
                    return []

                # Optimization: Check if all refs are ObjectRefs (can be batched)
                # vs DeploymentResponses (need individual handling)
                all_object_refs = all(
                    not hasattr(ref, "result") for ref in refs if ref is not None
                )

                if all_object_refs:
                    # Batch get all ObjectRefs in a single executor call
                    # This is more efficient than spinning up N threads
                    def batch_get():
                        try:
                            return ray.get(refs, timeout=15.0)
                        except Exception as e:
                            # If batch fails, fall back to individual gets
                            logger.debug(
                                f"Batch ray.get failed, falling back to individual gets: {e}"
                            )
                            results = []
                            for ref in refs:
                                try:
                                    results.append(ray.get(ref, timeout=15.0))
                                except Exception:
                                    results.append(None)
                            return results

                    return await asyncio.get_event_loop().run_in_executor(
                        None, batch_get
                    )
                else:
                    # Mixed types or DeploymentResponses: handle individually
                    # Use return_exceptions=True to prevent one failure from
                    # failing the entire batch.
                    results = await asyncio.gather(
                        *[self._async_ray_get(ref) for ref in refs],
                        return_exceptions=True,
                    )
                    # Process exceptions, replacing them with None
                    processed_results = []
                    for res in results:
                        if isinstance(res, Exception):
                            logger.warning(f"Failed to resolve Ray reference: {res}")
                            processed_results.append(None)  # Use None as a poison pill
                        else:
                            processed_results.append(res)
                    return processed_results
            else:
                # Single reference
                if hasattr(refs, "result"):
                    # DeploymentResponse
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: refs.result(timeout_s=15.0)
                    )
                else:
                    # ObjectRef
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ray.get(refs, timeout=15.0)
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve Ray reference: {e}")
            raise

    # In: ProactiveAgentAggregator
    # Method: _compute_system_metrics
    def _compute_system_metrics(
        self,
        snapshots: Dict[str, AgentSnapshot],
        specializations: Dict[str, str],
        *,
        agent_ids_W: Optional[List[str]] = None,
        W_pair: Optional[List[List[float]]] = None,
    ) -> Dict[str, Any]:
        """
        Pre-compute the 'helpful parameters' for the Coordinator.

        Args:
            snapshots: Dict mapping agent_id -> AgentSnapshot
            specializations: Dict mapping agent_id -> specialization string
            agent_ids_W: Optional list of agent IDs in the topology matrix
            W_pair: Optional adjacency matrix (list of lists) for agent collaboration graph
        """
        if not snapshots:
            return {
                "total_agents": 0,
                "system_specialization_vector": {},
                "avg_capability": 0.0,
                "avg_memory_util": 0.0,
                "lifecycle_distribution": {},
                "specialization_distribution": {},
                "specialization_load": {},
                "h_hgnn": np.zeros(128, dtype=np.float32),
                "pair_matrix_present": False,
                "pair_degrees": {},
                "pair_neighbors": {},
            }

        # --- Topology / Virtual Network Overlay ---
        has_topology = (
            agent_ids_W is not None
            and W_pair is not None
            and len(agent_ids_W) > 0
            and len(W_pair) > 0
        )

        pair_degrees = {}
        pair_neighbors = defaultdict(list)

        if has_topology:
            # Map matrix indices to agent_ids in the topology scope
            W_index = {aid: idx for idx, aid in enumerate(agent_ids_W)}

            # Precompute degree & neighbors only for agents we actually have snapshots for
            for agent_id in snapshots.keys():
                if agent_id not in W_index:
                    continue
                i = W_index[agent_id]
                row = W_pair[i]

                deg = float(sum(row))
                pair_degrees[agent_id] = deg

                for j, w in enumerate(row):
                    if j == i:
                        continue
                    if w > 0.01:
                        neighbor_id = agent_ids_W[j]
                        pair_neighbors[agent_id].append((neighbor_id, float(w)))

        capabilities = []
        memory_utils = []
        lifecycles = defaultdict(int)
        skill_aggregator = defaultdict(list)

        # --- New: Track Specialization Counts and Load ---
        specialization_counts = defaultdict(int)
        specialization_load = defaultdict(list)

        # --- New h_hgnn Calculation ---
        embeddings = []
        weights = []

        for agent_id, snapshot in snapshots.items():
            capabilities.append(snapshot.c)
            memory_utils.append(snapshot.mem_util)
            lifecycles[snapshot.lifecycle] += 1

            for skill, value in snapshot.learned_skills.items():
                skill_aggregator[skill].append(value)

            # --- Aggregate Specialization Stats ---
            spec_name = specializations.get(agent_id, "unknown")
            specialization_counts[spec_name] += 1
            # Use load if available and > 0, otherwise use mem_util as a proxy
            load_value = snapshot.load if snapshot.load > 0 else snapshot.mem_util
            specialization_load[spec_name].append(load_value)

            # --- Add embedding and weight for h_hgnn ---
            if snapshot.h is not None and snapshot.h.size > 0:
                embeddings.append(snapshot.h)

                if has_topology:
                    # Graph-aware weighting: capability × degree
                    deg = pair_degrees.get(agent_id, 1.0)
                    weight = snapshot.c * deg
                else:
                    # Fallback: original heuristic
                    weight = snapshot.c * (1.0 + snapshot.mem_util)

                weights.append(max(0.1, weight))

        # Compute the final SystemSpecializationVector (average skill)
        system_spec_vector = {
            skill: float(np.mean(values)) for skill, values in skill_aggregator.items()
        }

        # --- Compute avg load per specialization ---
        spec_avg_load = {
            spec: float(np.mean(loads)) if loads else 0.0
            for spec, loads in specialization_load.items()
        }

        # --- Compute final h_hgnn ---
        if embeddings:
            h_hgnn = np.average(embeddings, axis=0, weights=weights)
        else:
            h_hgnn = np.zeros(128, dtype=np.float32)

        return {
            "total_agents": len(snapshots),
            "system_specialization_vector": system_spec_vector,
            "avg_capability": float(np.mean(capabilities)) if capabilities else 0.0,
            "avg_memory_util": float(np.mean(memory_utils)) if memory_utils else 0.0,
            "lifecycle_distribution": dict(lifecycles),
            "specialization_distribution": dict(specialization_counts),
            "specialization_load": spec_avg_load,
            "h_hgnn": h_hgnn,  # HGNN centroid (now topology-aware when available)
            "pair_matrix_present": has_topology,
            "pair_degrees": pair_degrees,
            "pair_neighbors": dict(pair_neighbors),
        }
