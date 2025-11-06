"""
Unit tests for coordinator.core.policies module.

Tests policies for drift scoring, energy state management, and routing decisions.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import pytest
from unittest.mock import Mock, AsyncMock, patch
from seedcore.coordinator.core.policies import (
    SurpriseComputer,
    OCPSValve,
    create_ocps_valve,
    decide_route_with_hysteresis,
    generate_proto_subtasks,
    compute_drift_score,
    get_current_energy_state,
    _clip01,
    _normalize_weights,
    _normalized_entropy,
)


class TestClip01:
    """Tests for _clip01 function."""
    
    def test_clip_positive(self):
        """Test clipping positive values."""
        assert _clip01(0.5) == 0.5
        assert _clip01(1.0) == 1.0
        assert _clip01(1.5) == 1.0
    
    def test_clip_negative(self):
        """Test clipping negative values."""
        assert _clip01(-0.5) == 0.0
        assert _clip01(0.0) == 0.0


class TestNormalizeWeights:
    """Tests for _normalize_weights function."""
    
    def test_normalize_weights(self):
        """Test normalizing weights."""
        weights = [0.25, 0.20, 0.15, 0.20, 0.10, 0.10]
        normalized = _normalize_weights(weights)
        assert len(normalized) == 6
        assert abs(sum(normalized) - 1.0) < 1e-10
    
    def test_normalize_negative_weights(self):
        """Test normalizing weights with negative values."""
        weights = [0.5, -0.1, 0.3, 0.2, 0.1, 0.0]
        normalized = _normalize_weights(weights)
        assert all(w >= 0 for w in normalized)
        assert abs(sum(normalized) - 1.0) < 1e-10


class TestNormalizedEntropy:
    """Tests for _normalized_entropy function."""
    
    def test_entropy_uniform(self):
        """Test entropy for uniform distribution."""
        probs = [0.5, 0.5]
        entropy = _normalized_entropy(probs)
        assert abs(entropy - 1.0) < 1e-6  # Should be 1.0 for uniform
    
    def test_entropy_deterministic(self):
        """Test entropy for deterministic distribution."""
        probs = [1.0, 0.0]
        entropy = _normalized_entropy(probs)
        assert abs(entropy - 0.0) < 1e-6  # Should be 0.0 for deterministic
    
    def test_entropy_empty(self):
        """Test entropy for empty list."""
        entropy = _normalized_entropy([])
        assert entropy == 0.5  # Default value


class TestSurpriseComputer:
    """Tests for SurpriseComputer class."""
    
    def test_init_default_weights(self):
        """Test initializing with default weights."""
        computer = SurpriseComputer()
        assert len(computer.w_hat) == 6
        assert abs(sum(computer.w_hat) - 1.0) < 1e-10
    
    def test_init_custom_weights(self):
        """Test initializing with custom weights."""
        weights = (0.3, 0.2, 0.2, 0.15, 0.1, 0.05)
        computer = SurpriseComputer(weights=weights)
        assert len(computer.w_hat) == 6
    
    def test_compute_surprise_fast_path(self):
        """Test computing surprise score for fast path."""
        computer = SurpriseComputer(tau_fast=0.35, tau_plan=0.60)
        signals = {
            "mw_hit": 0.1,
            "ocps": {"S_t": 0.2, "h": 0.5},
            "spikes": [0.1, 0.2],
            "fatigue": [0.1],
            "novelty": [0.1],
            "reward": [0.1],
            "tips": [0.1],
            "speed": 0.5,
            "quality": 0.8,
            "status": {},
            "drift_minmax": (0.0, 1.0),
            "ood_dist": 0.1,
            "ood_to01": lambda x: x,
            "graph_delta": 0.1,
            "mu_delta": 0.1,
            "dep_probs": [0.5, 0.5],
            "est_runtime": 1.0,
            "SLO": 1.0,
            "kappa": 1.0,
            "criticality": 0.5,
        }
        result = computer.compute(signals)
        assert "S" in result
        assert "x" in result
        assert "weights" in result
        assert "decision" in result
        assert result["S"] >= 0.0
        assert result["S"] <= 1.0
    
    def test_compute_surprise_planner_path(self):
        """Test computing surprise score for planner path."""
        computer = SurpriseComputer(tau_fast=0.35, tau_plan=0.60)
        signals = {
            "mw_hit": 0.5,
            "ocps": {"S_t": 0.4, "h": 0.5},
            "spikes": [0.3, 0.4],
            "fatigue": [0.2],
            "novelty": [0.3],
            "reward": [0.2],
            "tips": [0.2],
            "speed": 0.3,
            "quality": 0.6,
            "status": {},
            "drift_minmax": (0.0, 1.0),
            "ood_dist": 0.3,
            "ood_to01": lambda x: x,
            "graph_delta": 0.3,
            "mu_delta": 0.3,
            "dep_probs": [0.3, 0.3, 0.4],
            "est_runtime": 2.0,
            "SLO": 1.0,
            "kappa": 1.0,
            "criticality": 0.7,
        }
        result = computer.compute(signals)
        assert result["decision"] in ["fast", "planner", "hgnn"]


class TestOCPSValve:
    """Tests for OCPSValve class."""
    
    def test_init_default(self):
        """Test initializing with default parameters."""
        valve = OCPSValve()
        assert valve.nu > 0
        assert valve.h > 0
        assert valve.S == 0.0
    
    def test_init_custom(self):
        """Test initializing with custom parameters."""
        valve = OCPSValve(nu=0.2, h=0.6)
        assert valve.nu == 0.2
        assert valve.h == 0.6
    
    def test_update_no_escalation(self):
        """Test update without escalation."""
        valve = OCPSValve(nu=0.1, h=0.5)
        result = valve.update(0.15)  # drift > nu, but S < h
        assert result is False
        assert valve.S > 0.0
    
    def test_update_with_escalation(self):
        """Test update with escalation."""
        valve = OCPSValve(nu=0.1, h=0.5)
        # Accumulate enough drift to trigger escalation
        valve.S = 0.4  # Pre-accumulate
        result = valve.update(0.2)  # Should push S over h
        # After escalation, S should reset to 0
        assert valve.S == 0.0
        assert valve.esc_hits > 0
    
    def test_update_resets_on_escalation(self):
        """Test that update resets S on escalation."""
        valve = OCPSValve(nu=0.1, h=0.5)
        valve.S = 0.4
        valve.update(0.2)  # Should trigger escalation
        assert valve.S == 0.0  # Should reset
    
    def test_p_fast_property(self):
        """Test p_fast property."""
        valve = OCPSValve()
        valve.fast_hits = 8
        valve.esc_hits = 2
        assert abs(valve.p_fast - 0.8) < 1e-6
    
    def test_p_fast_no_hits(self):
        """Test p_fast with no hits."""
        valve = OCPSValve()
        assert valve.p_fast == 1.0
    
    def test_state(self):
        """Test state method."""
        valve = OCPSValve(nu=0.1, h=0.5)
        valve.S = 0.3
        state = valve.state()
        assert state.S_t == 0.3
        assert state.h == 0.5
        assert state.flag_on is False  # S < h
    
    def test_invalid_nu_raises_error(self):
        """Test that invalid nu raises error."""
        with pytest.raises(ValueError):
            OCPSValve(nu=0.0)
    
    def test_invalid_h_raises_error(self):
        """Test that invalid h raises error."""
        with pytest.raises(ValueError):
            OCPSValve(h=0.0)


class TestCreateOCPSValve:
    """Tests for create_ocps_valve function."""
    
    def test_create_default(self):
        """Test creating default OCPS valve."""
        valve = create_ocps_valve()
        assert isinstance(valve, OCPSValve)
        assert valve.nu > 0
        assert valve.h > 0


class TestDecideRouteWithHysteresis:
    """Tests for decide_route_with_hysteresis function."""
    
    def test_fast_path_decision(self):
        """Test fast path decision."""
        decision = decide_route_with_hysteresis(
            S=0.2,
            tau_fast=0.35,
            tau_plan=0.60,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            last_decision="fast"
        )
        assert decision == "fast"
    
    def test_planner_path_decision(self):
        """Test planner path decision."""
        decision = decide_route_with_hysteresis(
            S=0.45,
            tau_fast=0.35,
            tau_plan=0.60,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            last_decision=None
        )
        assert decision == "planner"
    
    def test_hgnn_path_decision(self):
        """Test HGNN path decision."""
        decision = decide_route_with_hysteresis(
            S=0.75,
            tau_fast=0.35,
            tau_plan=0.60,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            last_decision=None
        )
        assert decision == "hgnn"
    
    def test_hysteresis_fast_exit(self):
        """Test hysteresis prevents fast exit too early."""
        # S is between tau_fast and tau_fast_exit, but last decision was fast
        decision = decide_route_with_hysteresis(
            S=0.36,  # Between tau_fast and tau_fast_exit
            tau_fast=0.35,
            tau_plan=0.60,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            last_decision="fast"
        )
        assert decision == "fast"  # Should stay in fast due to hysteresis
    
    def test_hysteresis_planner_exit(self):
        """Test hysteresis prevents planner exit too early."""
        # S is between tau_plan_exit and tau_plan, but last decision was planner
        decision = decide_route_with_hysteresis(
            S=0.58,  # Between tau_plan_exit and tau_plan
            tau_fast=0.35,
            tau_plan=0.60,
            tau_fast_exit=0.38,
            tau_plan_exit=0.57,
            last_decision="planner"
        )
        assert decision == "planner"  # Should stay in planner due to hysteresis


class TestGenerateProtoSubtasks:
    """Tests for generate_proto_subtasks function."""
    
    def test_generate_from_pkg_result(self):
        """Test generating proto subtasks from PKG result."""
        pkg_result = {
            "tasks": [
                {"organ_id": "organ-1", "task": {"type": "test1"}},
                {"organ_id": "organ-2", "task": {"type": "test2"}}
            ],
            "edges": [{"from": 0, "to": 1}],
            "version": "v1.0"
        }
        subtasks = generate_proto_subtasks(pkg_result)
        assert len(subtasks) == 2
        assert subtasks[0]["organ_id"] == "organ-1"
        assert subtasks[1]["organ_id"] == "organ-2"
    
    def test_generate_empty_result(self):
        """Test generating from empty PKG result."""
        pkg_result = {"tasks": [], "edges": [], "version": "v1.0"}
        subtasks = generate_proto_subtasks(pkg_result)
        assert len(subtasks) == 0


@pytest.mark.asyncio
class TestComputeDriftScore:
    """Tests for compute_drift_score function."""
    
    async def test_compute_drift_score_success(self):
        """Test computing drift score successfully."""
        ml_client = Mock()
        ml_client.detect_drift = AsyncMock(return_value={"drift_score": 0.75})
        
        task = {"type": "test", "description": "test task"}
        metrics = Mock()
        
        drift_score = await compute_drift_score(
            task=task,
            ml_client=ml_client,
            metrics=metrics
        )
        
        assert drift_score == 0.75
        ml_client.detect_drift.assert_called_once()
    
    async def test_compute_drift_score_fallback(self):
        """Test computing drift score with fallback on error."""
        ml_client = Mock()
        ml_client.detect_drift = AsyncMock(side_effect=Exception("ML service error"))
        
        task = {"type": "test"}
        metrics = Mock()
        
        drift_score = await compute_drift_score(
            task=task,
            ml_client=ml_client,
            metrics=metrics
        )
        
        # Should return fallback value (0.0) on error
        assert drift_score == 0.0


class TestGetCurrentEnergyState:
    """Tests for get_current_energy_state function."""
    
    @patch('seedcore.coordinator.core.policies.get_current_energy_state')
    def test_get_energy_state(self, mock_get):
        """Test getting current energy state."""
        mock_get.return_value = 100.0
        result = get_current_energy_state("agent-123")
        assert result == 100.0
    
    @patch('seedcore.coordinator.core.policies.get_current_energy_state')
    def test_get_energy_state_none(self, mock_get):
        """Test getting energy state when not available."""
        mock_get.return_value = None
        result = get_current_energy_state("agent-123")
        assert result is None

