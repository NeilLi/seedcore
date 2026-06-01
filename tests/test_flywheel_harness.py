import pytest
import numpy as np

from seedcore.control.flywheel import CORE_RULE, HourlyFlywheel
from seedcore.ops.energy.ledger import EnergyLedger
from seedcore.ops.energy.weights import EnergyWeights


def _weights() -> EnergyWeights:
    return EnergyWeights(
        W_pair=np.array([[1.0]], dtype=np.float32),
        W_hyper=np.array([1.0], dtype=np.float32),
        alpha_entropy=0.1,
        lambda_reg=0.01,
        beta_mem=0.05,
        lambda_drift=0.05,
        mu_anomaly=0.03,
    )


def _ledger_with_window(*, drift: float = 0.1, anomaly: float = 0.1) -> EnergyLedger:
    ledger = EnergyLedger()
    for idx in range(10):
        # Declining energy terms represent an improving window.
        ledger.total_history.append(10.0 - idx)
        ledger.pair_history.append(1.0 - idx * 0.02)
        ledger.hyper_history.append(0.5)
        ledger.entropy_history.append(2.0 - idx * 0.05)
        ledger.reg_history.append(1.0 - idx * 0.03)
        ledger.mem_history.append(1.0 - idx * 0.02)
        ledger.drift_history.append(drift)
        ledger.anomaly_history.append(anomaly)
        ledger.scaling_history.append(0.2)
    return ledger


@pytest.mark.asyncio
async def test_flywheel_adapts_inside_trust_harness():
    weights = _weights()
    flywheel = HourlyFlywheel(None, _ledger_with_window(), weights)

    await flywheel.run_flywheel_cycle()

    stats = flywheel.get_flywheel_stats()
    assert stats["last_harness_posture"]["adaptation_allowed"] is True
    assert stats["last_harness_posture"]["core_rule"] == CORE_RULE
    assert weights.alpha_entropy > 0.1
    assert weights.lambda_reg < 0.01
    assert weights.beta_mem > 0.05


@pytest.mark.asyncio
async def test_flywheel_blocks_adaptation_when_trust_drift_is_high():
    weights = _weights()
    flywheel = HourlyFlywheel(None, _ledger_with_window(drift=0.9), weights)

    await flywheel.run_flywheel_cycle()

    stats = flywheel.get_flywheel_stats()
    posture = stats["last_harness_posture"]
    assert posture["adaptation_allowed"] is False
    assert posture["trust_runtime_aligned"] is True
    assert weights.alpha_entropy == 0.1
    assert any("verifier" in item for item in posture["remediations"])


@pytest.mark.asyncio
async def test_flywheel_circuit_breaker_after_repeated_gate_failure():
    weights = _weights()
    flywheel = HourlyFlywheel(None, _ledger_with_window(drift=0.9), weights)

    await flywheel.run_flywheel_cycle()
    await flywheel.run_flywheel_cycle()
    await flywheel.run_flywheel_cycle()

    posture = flywheel.get_flywheel_stats()["last_harness_posture"]
    assert posture["circuit_open"] is True
    assert posture["failed_gate_streak"] == 3
    assert any(gate["name"] == "flywheel_circuit_breaker" for gate in posture["gates"])
