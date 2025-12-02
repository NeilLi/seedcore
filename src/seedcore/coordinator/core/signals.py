"""
Signal Enrichment Module.

Fetches contextual signals (Capability, Energy, Load) from the State/Energy services
to determine if the system is stressed.
"""

import asyncio
import logging
from typing import Any, Dict

# Type checking imports
from seedcore.models.task_payload import TaskPayload

logger = logging.getLogger(__name__)


class SignalEnricher:
    """
    Computes 'Contextual Surprise' by comparing the Task Intent against
    the Organism's current STATE (Capabilities, Energy, Load).
    """

    def __init__(self, state_client: Any, energy_client: Any):
        self.state_client = state_client  # Client for StateService
        self.energy_client = energy_client  # Client for EnergyService

    async def compute_contextual_signals(
        self,
        intent: Any,  # RoutingIntent
        task: TaskPayload,
    ) -> Dict[str, float]:
        """
        Returns normalized signals (0.0 - 1.0) representing system stress.
        """
        # Parallel fetch for speed (Critical for Fast Path latency)
        results = await asyncio.gather(
            self._calculate_capability_gap(intent),
            self._calculate_energy_stress(),
            return_exceptions=True,
        )

        # Safe Unpacking
        cap_gap = 0.0
        if isinstance(results[0], float):
            cap_gap = results[0]
        elif isinstance(results[0], Exception):
            logger.warning(f"[SignalEnricher] Capability check failed: {results[0]}")

        energy_stress = 0.0
        if isinstance(results[1], float):
            energy_stress = results[1]
        elif isinstance(results[1], Exception):
            logger.warning(f"[SignalEnricher] Energy check failed: {results[1]}")

        return {
            "capability_gap": cap_gap,  # 1.0 = No agents exist for this job
            "energy_stress": energy_stress,  # 1.0 = System is exhausted
        }

    async def _calculate_capability_gap(self, intent: Any) -> float:
        """
        Quantifies mismatch: Do we have active agents for this specialization?
        """
        if not self.state_client:
            return 0.0  # Fail open

        required_spec = getattr(intent, "specialization", None)
        if not required_spec:
            return 0.0  # No specific requirement

        try:
            # 1. Query StateService for O(1) System Metrics
            response = await self.state_client.get_system_metrics()

            # Extract 'ma' from nested structure: metrics -> memory -> ma
            metrics = response.get("metrics", {}) if isinstance(response, dict) else {}
            memory = metrics.get("memory", {}) if isinstance(metrics, dict) else {}
            ma = memory.get("ma", {}) if isinstance(memory, dict) else {}

            if not isinstance(ma, dict) or not ma:
                # No data yet, assume capacity exists
                return 0.0

            # 2. Extract Specialization Stats
            spec_counts = ma.get("specialization_distribution", {}) or {}
            spec_loads = ma.get("specialization_load", {}) or {}

            # Normalize keys to lowercase for robust, case-insensitive matching
            spec_counts_l = {str(k).lower(): v for k, v in spec_counts.items()}
            spec_loads_l = {str(k).lower(): v for k, v in spec_loads.items()}

            key = str(required_spec).lower()

            count = spec_counts_l.get(key, 0)
            avg_load = float(spec_loads_l.get(key, 0.0))

            if count == 0:
                # CRITICAL SURPRISE: We have ZERO agents for this job.
                return 1.0

            # 3. Load Penalty
            # If load > 0.8, we start adding surprise penalty
            # 0.8 -> 0.0, 1.0 -> 1.0
            load_penalty = max(0.0, (avg_load - 0.8) * 5.0)

            return min(1.0, load_penalty)

        except Exception as e:
            logger.debug(f"Failed to query capability stats: {e}")
            return 0.0

    async def _calculate_energy_stress(self) -> float:
        """
        Quantifies system fatigue via EnergyService ledger.
        """
        if not self.energy_client:
            return 0.0

        try:
            # Fast O(1) read from Energy Ledger
            metrics = await self.energy_client.get_metrics()

            # Metrics returns: { "total": ..., "entropy": ..., "scaling_score": ... }

            # 1. Check Scaling Score (ML-derived stress prediction)
            ml_stress = metrics.get("scaling_score", 0.0)

            # 2. Check Entropy (System Disorder)
            entropy = metrics.get("entropy", 0.0)

            # 3. Check Total Energy (Overall Instability)
            # If total energy is rising rapidly (positive delta_E), it's stressful
            # This logic mimics the Flywheel check but normalized for Surprise
            # Assuming metrics has 'total' which could be negative (stable) or positive (unstable)
            # We rely mostly on 'scaling_score' as the cleanest 0-1 signal.

            return max(ml_stress, min(1.0, entropy))

        except Exception as e:
            logger.debug(f"Failed to query energy stats: {e}")
            return 0.0
