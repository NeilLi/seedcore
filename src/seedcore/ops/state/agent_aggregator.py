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
from typing import Dict, Any, Optional
from collections import defaultdict
import numpy as np
import ray  # pyright: ignore[reportMissingImports]

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

    def __init__(self, organism_router: Any, poll_interval: float = 2.0):
        """
        Initialize the proactive agent state aggregator.

        Args:
            organism_router: A Ray handle to the OrganismCore (v2) router,
                             which acts as the "global control plane".
            poll_interval: How often (in seconds) to poll all agents.
        """
        self.organism_router = organism_router
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

                # 1. Discover all live agents from the global router
                # This call uses the new OrganismService (v2) which wraps OrganismCore.
                # OrganismCore aggregates handles from all organs.
                agent_handles_ref = self.organism_router.get_all_agent_handles.remote()
                agent_handles: Dict[str, Any] = await self._async_ray_get(agent_handles_ref)

                if not agent_handles:
                    logger.warning(
                        "No agent handles found. System may be scaling to zero."
                    )
                    await self._update_state({}, {})  # Clear state
                    await asyncio.sleep(self.poll_interval)
                    continue

                # 2. Batch-collect snapshots from all agents
                # Use get_snapshot() which directly returns AgentSnapshot (the bridge method)
                ordered_ids = list(agent_handles.keys())
                ordered_handles = list(agent_handles.values())

                snapshot_refs = [h.get_snapshot.remote() for h in ordered_handles]
                snapshots = await self._async_ray_get(snapshot_refs)

                # 3. Process snapshots into new_snapshots dict
                new_snapshots: Dict[str, AgentSnapshot] = {}
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
                    except Exception as e:
                        logger.warning(
                            f"Failed to process snapshot for agent {agent_id}: {e}"
                        )
                        continue

                # 4. Pre-compute system-wide metrics for the Coordinator
                new_metrics = self._compute_system_metrics(new_snapshots)

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
            logger.warning("get_system_metrics called before first poll.")
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
        (This utility function is unchanged and remains essential)
        """
        try:
            if isinstance(refs, list):
                # Use return_exceptions=True to prevent one failure from
                # failing the entire batch.
                results = await asyncio.gather(
                    *[self._async_ray_get(ref) for ref in refs], return_exceptions=True
                )
                # Process exceptions, replacing them with None or an empty dict
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
        self, snapshots: Dict[str, AgentSnapshot]
    ) -> Dict[str, Any]:
        """
        Pre-compute the 'helpful parameters' for the Coordinator.
        """
        if not snapshots:
            return {
                "total_agents": 0,
                "system_specialization_vector": {},
                "avg_capability": 0.0,
                "avg_memory_util": 0.0,
                "lifecycle_distribution": {},
                "h_hgnn": np.zeros(128, dtype=np.float32),  # Add this
            }

        capabilities = []
        memory_utils = []
        lifecycles = defaultdict(int)
        skill_aggregator = defaultdict(list)

        # --- New h_hgnn Calculation ---
        embeddings = []
        weights = []

        for snapshot in snapshots.values():
            capabilities.append(snapshot.c)
            memory_utils.append(snapshot.mem_util)
            lifecycles[snapshot.lifecycle] += 1

            for skill, value in snapshot.learned_skills.items():
                skill_aggregator[skill].append(value)

            # --- Add embedding and weight for h_hgnn ---
            if snapshot.h is not None and snapshot.h.size > 0:
                embeddings.append(snapshot.h)
                # Replicate original logic: weight by capability and mem_util
                weight = snapshot.c * (1.0 + snapshot.mem_util)
                weights.append(max(0.1, weight))  # Use max to avoid zero-weight

        # Compute the final SystemSpecializationVector (average skill)
        system_spec_vector = {
            skill: float(np.mean(values)) for skill, values in skill_aggregator.items()
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
            "h_hgnn": h_hgnn,  # The new pre-computed parameter
        }
