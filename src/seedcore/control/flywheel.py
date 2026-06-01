# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Hourly Flywheel Control Loop - Global weight adaptation.

The flywheel tunes SeedCore's energy weights from runtime evidence. It is a
control harness, not an authority path: AI intent still becomes executable only
through PDP admission, scoped ExecutionTokens, actuator enforcement, and
replayable evidence closure.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

from ..ops.energy.ledger import EnergyLedger

logger = logging.getLogger(__name__)


CORE_RULE = (
    "SeedCore is building a trust runtime for AI actions in high-consequence "
    "environments."
)


@dataclass
class FlywheelMetrics:
    """Metrics tracked by the flywheel for weight adaptation."""

    delta_spec: float = 0.0
    delta_acc: float = 0.0
    delta_smart: float = 0.0
    delta_reason: float = 0.0
    delta_drift: float = 0.0
    delta_anomaly: float = 0.0
    delta_total: float = 0.0


@dataclass
class FlywheelGate:
    """A deterministic flywheel harness gate with remediation guidance."""

    name: str
    passed: bool
    severity: str
    message: str
    remediation: str


@dataclass
class FlywheelHarnessPosture:
    """Legible posture emitted for each flywheel cycle."""

    adaptation_allowed: bool
    trust_runtime_aligned: bool
    circuit_open: bool
    failed_gate_streak: int
    gates: List[FlywheelGate] = field(default_factory=list)
    context_refs: List[str] = field(default_factory=list)
    core_rule: str = CORE_RULE

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["remediations"] = [
            gate.remediation for gate in self.gates if not gate.passed
        ]
        return payload


class HourlyFlywheel:
    """
    Hourly global weight adaptation using windowed metrics.

    The harness gates keep the flywheel inside SeedCore's trust-runtime posture:
    adaptation is paused when telemetry is non-finite, drift/anomaly pressure is
    above policy-shaped caps, or the same blocking gate keeps failing.
    """

    def __init__(
        self,
        organism_manager: Any,
        energy_ledger: EnergyLedger,
        energy_weights: Optional[Any] = None,
    ):
        self.organism = organism_manager
        self.ledger = energy_ledger
        self.weights = energy_weights or energy_ledger
        self.weight_history: List[Dict[str, Any]] = []
        self.metrics_history: List[FlywheelMetrics] = []
        self.harness_history: List[Dict[str, Any]] = []
        self.is_running = False
        self.cycle_interval = 3600

        # Performance tracking windows.
        self.performance_window = 3600
        self.min_data_points = 10

        # Weight adaptation parameters.
        self.adaptation_rate = 0.05
        self.weight_bounds = {
            "alpha": (0.1, 2.0),
            "lambda_reg": (0.001, 0.1),
            "beta_mem": (0.05, 0.5),
        }

        # Harness gates: deterministic, boring, and auditable.
        self.drift_ceiling = 0.70
        self.anomaly_ceiling = 0.70
        self.max_positive_delta_total = 0.0
        self.max_same_gate_failures = 3
        self._last_blocking_gate: Optional[str] = None
        self._failed_gate_streak = 0
        self.context_refs = [
            "README.md",
            "docs/development/trust_runtime_category_distinction.md",
            "docs/development/policy_gate_matrix.md",
            "docs/development/seedcore_flywheel_harness.md",
        ]

    async def start(self):
        """Start the hourly flywheel loop."""
        if self.is_running:
            logger.warning("Flywheel is already running")
            return

        self.is_running = True
        logger.info("Starting hourly flywheel control loop")

        try:
            while self.is_running:
                await self.run_flywheel_cycle()
                await asyncio.sleep(self.cycle_interval)
        except Exception as e:
            logger.error("Error in flywheel loop: %s", e)
            self.is_running = False
            raise

    async def stop(self):
        """Stop the hourly flywheel loop."""
        self.is_running = False
        logger.info("Stopping hourly flywheel control loop")

    async def run_flywheel_cycle(self):
        """Run a single flywheel cycle with harness-gated weight adaptation."""
        logger.info("Running hourly flywheel cycle...")

        try:
            recent_energy = self.ledger.get_recent_energy(self.performance_window)
            posture = self.evaluate_harness_posture(recent_energy)
            data_points = len(recent_energy.get("total", []))

            if data_points < self.min_data_points:
                logger.warning(
                    "Insufficient data for flywheel cycle. Need %s, have %s",
                    self.min_data_points,
                    data_points,
                )
                self._record_cycle(
                    metrics=FlywheelMetrics(),
                    old_weights=self.get_current_weights(),
                    new_weights=self.get_current_weights(),
                    posture=posture,
                    skipped=True,
                    reason="insufficient_data",
                )
                return

            metrics = self.calculate_performance_deltas(recent_energy)
            old_weights = self.get_current_weights()

            if posture.adaptation_allowed:
                self.update_global_weights(metrics)
            else:
                logger.warning(
                    "Flywheel adaptation paused by harness gates: %s",
                    [
                        gate.name
                        for gate in posture.gates
                        if not gate.passed and gate.severity == "block"
                    ],
                )

            new_weights = self.get_current_weights()
            cycle_result = self._record_cycle(
                metrics=metrics,
                old_weights=old_weights,
                new_weights=new_weights,
                posture=posture,
                skipped=not posture.adaptation_allowed,
                reason=None if posture.adaptation_allowed else "harness_gate",
            )

            logger.info("Flywheel cycle complete:")
            logger.info(
                "  dSpec: %.4f, dAcc: %.4f, dSmart: %.4f, dReason: %.4f",
                metrics.delta_spec,
                metrics.delta_acc,
                metrics.delta_smart,
                metrics.delta_reason,
            )
            logger.info("  Weight changes: %s", cycle_result["weight_changes"])

        except Exception as e:
            logger.error("Error in flywheel cycle: %s", e)
            raise

    def evaluate_harness_posture(
        self, recent_energy: Dict[str, List[float]]
    ) -> FlywheelHarnessPosture:
        """Evaluate deterministic flywheel harness gates."""

        gates: List[FlywheelGate] = []
        total = recent_energy.get("total", [])
        drift = recent_energy.get("drift", [])
        anomaly = recent_energy.get("anomaly", [])

        gates.append(
            FlywheelGate(
                name="minimum_evidence_window",
                passed=len(total) >= self.min_data_points,
                severity="block",
                message=(
                    f"{len(total)} energy samples available; "
                    f"{self.min_data_points} required."
                ),
                remediation=(
                    "Keep collecting EnergyService samples before adapting "
                    "global weights."
                ),
            )
        )

        finite_ok = self._all_energy_values_are_finite(recent_energy.values())
        gates.append(
            FlywheelGate(
                name="finite_energy_terms",
                passed=finite_ok,
                severity="block",
                message="All flywheel telemetry terms must be finite numbers.",
                remediation=(
                    "Quarantine the cycle, inspect the energy sampler, and do "
                    "not adapt weights from NaN or infinite telemetry."
                ),
            )
        )

        latest_drift = self._last(drift)
        gates.append(
            FlywheelGate(
                name="drift_within_trust_ceiling",
                passed=latest_drift <= self.drift_ceiling,
                severity="block",
                message=(
                    f"Latest drift={latest_drift:.4f}; "
                    f"ceiling={self.drift_ceiling:.4f}."
                ),
                remediation=(
                    "Run replay/result-verifier checks and resolve state drift "
                    "before allowing the flywheel to reinforce routing weights."
                ),
            )
        )

        latest_anomaly = self._last(anomaly)
        gates.append(
            FlywheelGate(
                name="anomaly_within_trust_ceiling",
                passed=latest_anomaly <= self.anomaly_ceiling,
                severity="block",
                message=(
                    f"Latest anomaly={latest_anomaly:.4f}; "
                    f"ceiling={self.anomaly_ceiling:.4f}."
                ),
                remediation=(
                    "Hold adaptation, surface operator legibility, and verify "
                    "policy/evidence closure for the affected workflow."
                ),
            )
        )

        delta_total = self._delta(total)
        gates.append(
            FlywheelGate(
                name="non_worsening_energy_trend",
                passed=delta_total <= self.max_positive_delta_total,
                severity="warn",
                message=(
                    f"Window total energy delta={delta_total:.4f}; "
                    f"non-worsening threshold={self.max_positive_delta_total:.4f}."
                ),
                remediation=(
                    "Treat this as a review-loop signal: keep adaptation "
                    "bounded and compare the next cycle before promotion."
                ),
            )
        )

        blocking_failures = [
            gate for gate in gates if not gate.passed and gate.severity == "block"
        ]
        primary_failure = blocking_failures[0].name if blocking_failures else None
        if primary_failure and primary_failure == self._last_blocking_gate:
            self._failed_gate_streak += 1
        elif primary_failure:
            self._last_blocking_gate = primary_failure
            self._failed_gate_streak = 1
        else:
            self._last_blocking_gate = None
            self._failed_gate_streak = 0

        circuit_open = self._failed_gate_streak >= self.max_same_gate_failures
        if circuit_open:
            gates.append(
                FlywheelGate(
                    name="flywheel_circuit_breaker",
                    passed=False,
                    severity="block",
                    message=(
                        f"Gate {self._last_blocking_gate!r} failed "
                        f"{self._failed_gate_streak} consecutive cycles."
                    ),
                    remediation=(
                        "Stop autonomous iteration and escalate to a human "
                        "operator with the cycle artifacts and verifier output."
                    ),
                )
            )

        adaptation_allowed = not any(
            not gate.passed and gate.severity == "block" for gate in gates
        )
        return FlywheelHarnessPosture(
            adaptation_allowed=adaptation_allowed,
            trust_runtime_aligned=True,
            circuit_open=circuit_open,
            failed_gate_streak=self._failed_gate_streak,
            gates=gates,
            context_refs=list(self.context_refs),
        )

    def calculate_performance_deltas(
        self, recent_energy: Dict[str, List[float]]
    ) -> FlywheelMetrics:
        """
        Calculate performance deltas using the adaptive formula from the energy
        validation blueprint.
        """

        metrics = FlywheelMetrics()

        try:
            total_energy = recent_energy.get("total", [])
            pair_energy = recent_energy.get("pair", [])
            entropy_energy = recent_energy.get("entropy", [])
            reg_energy = recent_energy.get("reg", [])
            mem_energy = recent_energy.get("mem", [])
            drift_energy = recent_energy.get("drift", [])
            anomaly_energy = recent_energy.get("anomaly", [])

            metrics.delta_total = self._delta(total_energy)
            metrics.delta_spec = self._delta(entropy_energy)
            metrics.delta_acc = -self._delta(reg_energy)
            metrics.delta_smart = -self._delta(mem_energy)
            metrics.delta_reason = -self._delta(pair_energy)
            metrics.delta_drift = self._delta(drift_energy)
            metrics.delta_anomaly = self._delta(anomaly_energy)

        except Exception as e:
            logger.error("Error calculating performance deltas: %s", e)

        return metrics

    def update_global_weights(self, metrics: FlywheelMetrics):
        """Update global weights based on performance deltas."""
        try:
            alpha = self._get_weight("alpha")
            lambda_reg = self._get_weight("lambda_reg")
            beta_mem = self._get_weight("beta_mem")

            if metrics.delta_spec < 0:
                self._set_weight("alpha", alpha * (1 + self.adaptation_rate))
                logger.debug("Increased alpha (specialization improving)")
            else:
                self._set_weight("alpha", alpha * (1 - self.adaptation_rate))
                logger.debug("Decreased alpha (specialization declining)")

            if metrics.delta_acc > 0:
                self._set_weight(
                    "lambda_reg", lambda_reg * (1 - self.adaptation_rate)
                )
                logger.debug("Decreased lambda_reg (accuracy improving)")
            else:
                self._set_weight(
                    "lambda_reg", lambda_reg * (1 + self.adaptation_rate)
                )
                logger.debug("Increased lambda_reg (accuracy declining)")

            if metrics.delta_smart > 0:
                self._set_weight("beta_mem", beta_mem * (1 + self.adaptation_rate))
                logger.debug("Increased beta_mem (memory efficiency improving)")
            else:
                self._set_weight("beta_mem", beta_mem * (1 - self.adaptation_rate))
                logger.debug("Decreased beta_mem (memory efficiency declining)")

            self.clamp_weights()

        except Exception as e:
            logger.error("Error updating global weights: %s", e)

    def clamp_weights(self):
        """Clamp weights to their defined bounds."""
        try:
            for weight_name, (low, high) in self.weight_bounds.items():
                self._set_weight(
                    weight_name,
                    float(np.clip(self._get_weight(weight_name), low, high)),
                )
        except Exception as e:
            logger.error("Error clamping weights: %s", e)

    def get_current_weights(self) -> Dict[str, float]:
        """Get current weight values."""
        return {
            "alpha": self._get_weight("alpha"),
            "lambda_reg": self._get_weight("lambda_reg"),
            "beta_mem": self._get_weight("beta_mem"),
        }

    def get_weight_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent weight history."""
        if limit > 0:
            return self.weight_history[-limit:]
        return self.weight_history

    def get_metrics_history(self, limit: int = 100) -> List[FlywheelMetrics]:
        """Get recent metrics history."""
        if limit > 0:
            return self.metrics_history[-limit:]
        return self.metrics_history

    def get_harness_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent harness posture history."""
        if limit > 0:
            return self.harness_history[-limit:]
        return self.harness_history

    def get_flywheel_stats(self) -> Dict[str, Any]:
        """Get flywheel statistics and performance metrics."""
        try:
            if not self.weight_history:
                return {"error": "No flywheel history available"}

            recent_cycles = self.weight_history[-10:]
            avg_changes = {}
            for weight_name in ["alpha", "lambda_reg", "beta_mem"]:
                changes = [
                    cycle["weight_changes"].get(weight_name, 0.0)
                    for cycle in recent_cycles
                ]
                avg_changes[weight_name] = float(np.mean(changes)) if changes else 0.0

            recent_metrics = self.metrics_history[-10:] if self.metrics_history else []
            avg_metrics = FlywheelMetrics()
            if recent_metrics:
                avg_metrics.delta_spec = float(
                    np.mean([m.delta_spec for m in recent_metrics])
                )
                avg_metrics.delta_acc = float(
                    np.mean([m.delta_acc for m in recent_metrics])
                )
                avg_metrics.delta_smart = float(
                    np.mean([m.delta_smart for m in recent_metrics])
                )
                avg_metrics.delta_reason = float(
                    np.mean([m.delta_reason for m in recent_metrics])
                )
                avg_metrics.delta_drift = float(
                    np.mean([m.delta_drift for m in recent_metrics])
                )
                avg_metrics.delta_anomaly = float(
                    np.mean([m.delta_anomaly for m in recent_metrics])
                )
                avg_metrics.delta_total = float(
                    np.mean([m.delta_total for m in recent_metrics])
                )

            return {
                "is_running": self.is_running,
                "total_cycles": len(self.weight_history),
                "current_weights": self.get_current_weights(),
                "average_weight_changes": avg_changes,
                "average_metrics": asdict(avg_metrics),
                "last_cycle": self.weight_history[-1] if self.weight_history else None,
                "last_harness_posture": (
                    self.harness_history[-1] if self.harness_history else None
                ),
            }

        except Exception as e:
            logger.error("Error getting flywheel stats: %s", e)
            return {"error": str(e)}

    def _record_cycle(
        self,
        *,
        metrics: FlywheelMetrics,
        old_weights: Dict[str, float],
        new_weights: Dict[str, float],
        posture: FlywheelHarnessPosture,
        skipped: bool,
        reason: Optional[str],
    ) -> Dict[str, Any]:
        posture_payload = posture.to_dict()
        cycle_result = {
            "timestamp": time.time(),
            "metrics": asdict(metrics),
            "old_weights": old_weights,
            "new_weights": new_weights,
            "weight_changes": {
                key: new_weights.get(key, 0.0) - old_weights.get(key, 0.0)
                for key in old_weights.keys()
            },
            "harness_posture": posture_payload,
            "skipped": skipped,
            "skip_reason": reason,
        }
        self.weight_history.append(cycle_result)
        self.metrics_history.append(metrics)
        self.harness_history.append(posture_payload)
        return cycle_result

    def _get_weight(self, name: str) -> float:
        attr = self._weight_attr(name)
        if attr and hasattr(self.weights, attr):
            return float(getattr(self.weights, attr))
        if hasattr(self.ledger, name):
            return float(getattr(self.ledger, name))
        low, _high = self.weight_bounds[name]
        return float(low)

    def _set_weight(self, name: str, value: float) -> None:
        attr = self._weight_attr(name)
        if attr and hasattr(self.weights, attr):
            setattr(self.weights, attr, float(value))
            return
        if hasattr(self.ledger, name):
            setattr(self.ledger, name, float(value))
            return
        setattr(self.weights, attr or name, float(value))

    @staticmethod
    def _weight_attr(name: str) -> str:
        return {"alpha": "alpha_entropy"}.get(name, name)

    @staticmethod
    def _delta(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        return float(values[-1] - values[0])

    @staticmethod
    def _last(values: List[float]) -> float:
        if not values:
            return 0.0
        return float(values[-1])

    @staticmethod
    def _all_energy_values_are_finite(series: Iterable[List[float]]) -> bool:
        for values in series:
            for value in values:
                try:
                    if not math.isfinite(float(value)):
                        return False
                except (TypeError, ValueError):
                    return False
        return True


_flywheel_instance: Optional[HourlyFlywheel] = None


def get_flywheel_instance():
    """Get the global flywheel instance with lazy initialization."""
    global _flywheel_instance
    if _flywheel_instance is None:
        from ..services.energy_service import state as energy_state

        _flywheel_instance = HourlyFlywheel(
            organism_manager=None,
            energy_ledger=energy_state.ledger,
            energy_weights=energy_state.default_weights,
        )
    return _flywheel_instance


async def start_flywheel():
    """Start the global flywheel instance."""
    await get_flywheel_instance().start()


async def stop_flywheel():
    """Stop the global flywheel instance."""
    if _flywheel_instance is not None:
        await _flywheel_instance.stop()
