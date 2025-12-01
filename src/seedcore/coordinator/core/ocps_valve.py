"""
Online Change-Point Sentinel (OCPS) - Neural-CUSUM Implementation.

This module implements a rigorous CUSUM (Cumulative Sum) drift detector used to
govern the transition between System 1 (Fast/Reflexive) and System 2 (Deep/Reasoning).

It is "Neural" because it is designed to consume normalized uncertainty scores
(entropy, perplexity, energy) derived from Neural Network outputs.
"""

from dataclasses import dataclass


@dataclass
class DriftState:
    is_breached: bool  # True if we should escalate to System 2
    score: float  # Current CUSUM statistic (S_t)
    severity: float  # 0.0 to 1.0 (How far past threshold are we?)
    run_length: int  # How many consecutive steps have we been accumulating?
    instant_llr: float  # The instantaneous log-likelihood ratio of this step


class NeuralCUSUMValve:
    """
    A robust Cumulative Sum (CUSUM) detector for monitoring sequential drift
    in neural uncertainty streams.

    Math:
        S_t = max(0, S_{t-1} + LLR_t)
        LLR_t = (x_t - mu_0) / sigma^2 - nu

    Where:
        mu_0:  Expected baseline drift (System 1 state)
        nu:    Drift allowance (slack parameter)
        x_t:   Observed drift score (0..1)
    """

    def __init__(
        self,
        expected_baseline: float = 0.1,  # mu_0 (Normal System 1 drift)
        min_detectable_change: float = 0.2,  # delta (We want to detect shifts >= 0.3 total)
        threshold: float = 2.5,  # h (Decision boundary)
        sigma: float = 0.15,  # Estimated noise/variance in the stream
    ):
        """
        Args:
            expected_baseline (mu0): The expected entropy/drift when Agent is confident.
            min_detectable_change (delta): The smallest jump in drift we care about.
            threshold (h): The accumulation limit before triggering System 2.
            sigma: Standard deviation of the drift signal (tuning param).
        """
        self.mu0 = expected_baseline
        self.mu1 = expected_baseline + min_detectable_change
        self.h = threshold
        self.sigma2 = sigma**2

        # Calculate the optimal slack variable (nu) for LLR
        # nu = (mu1 - mu0) / 2  <-- Approximation for Gaussian mean shift
        self.nu = (self.mu1 + self.mu0) / 2.0

        # Scaling factor for the LLR
        self.scale = (self.mu1 - self.mu0) / self.sigma2

        # State
        self.S = 0.0  # Cumulative Statistic
        self.run_length = 0  # Persistence counter
        self.max_S = 0.0  # Telemetry: Max value seen

        # Metrics
        self.fast_count = 0
        self.slow_count = 0

    def update(self, drift_score: float) -> DriftState:
        """
        Ingest a new drift score (e.g., Agent Entropy, 0.0-1.0) and update state.

        Returns:
            DriftState object with decision and telemetry.
        """
        # 1. Clamp input for numerical stability (Neural outputs can be noisy)
        x_t = max(0.0, min(1.0, drift_score))

        # 2. Calculate Log-Likelihood Ratio (LLR) step
        # Ideally: s = (x_t - self.nu) * self.scale
        # Simplified: We use the standard deviation form: x_t - nu
        # If x_t > nu, we accumulate positive evidence of drift.
        # If x_t < nu, we reduce the accumulator (cooling).
        instant_deviation = x_t - self.nu

        # 3. Update CUSUM Statistic
        self.S = max(0.0, self.S + instant_deviation)

        # 4. Update Run Length
        if self.S > 0:
            self.run_length += 1
        else:
            self.run_length = 0

        self.max_S = max(self.max_S, self.S)

        # 5. Check Threshold (Breach)
        is_breached = self.S > self.h

        # Calculate severity (how much did we overshoot?)
        severity = 0.0
        if is_breached:
            severity = min(1.0, (self.S - self.h) / self.h)
            self.slow_count += 1
            # Soft Reset: We don't clear to 0 immediately to prevent "flapping".
            # We reset to the threshold (minus a small hysteresis) to keep System 2 active
            # if the pressure remains high.
            self.S = self.h * 0.8
        else:
            self.fast_count += 1

        return DriftState(
            is_breached=is_breached,
            score=self.S,
            severity=severity,
            run_length=self.run_length,
            instant_llr=instant_deviation,
        )

    def reset(self):
        """Hard reset of the accumulator (e.g., after a full Re-Planning)."""
        self.S = 0.0
        self.run_length = 0
        self.max_S = 0.0

    @property
    def p_fast(self) -> float:
        """Ratio of Fast Path (System 1) usage."""
        total = self.fast_count + self.slow_count
        return (self.fast_count / total) if total > 0 else 1.0
