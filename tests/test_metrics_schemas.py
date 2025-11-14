#!/usr/bin/env python3
"""
Unit tests for metrics schemas.

Tests validation, from_dict, and to_dict methods for all schema classes.
"""

import pytest
from seedcore.ops.metrics.schemas import (
    RoutingMetrics,
    ExecutionMetrics,
    LatencyMetrics,
    DispatchMetrics,
    PersistenceMetrics,
    validate_non_negative,
    validate_positive_if_present,
    validate_metric_key,
    VALID_ROUTING_KEYS,
    VALID_EXECUTION_KEYS,
    VALID_LATENCY_KEYS,
    VALID_DISPATCH_KEYS,
    VALID_PERSISTENCE_KEYS,
)


class TestRoutingMetrics:
    """Tests for RoutingMetrics schema."""
    
    def test_default_initialization(self):
        """Test default initialization."""
        metrics = RoutingMetrics()
        assert metrics.total == 0
        assert metrics.fast == 0
        assert metrics.planner == 0
        assert metrics.hgnn == 0
    
    def test_initialization_with_values(self):
        """Test initialization with values."""
        metrics = RoutingMetrics(
            total=100,
            fast=50,
            planner=30,
            hgnn=20,
            hgnn_plan_generated=15,
            hgnn_plan_empty=5
        )
        assert metrics.total == 100
        assert metrics.fast == 50
        assert metrics.planner == 30
        assert metrics.hgnn == 20
    
    def test_validation_negative_values(self):
        """Test validation rejects negative values."""
        with pytest.raises(ValueError, match="must be non-negative"):
            RoutingMetrics(fast=-1)
    
    def test_rate_calculations(self):
        """Test rate property calculations."""
        metrics = RoutingMetrics(total=100, fast=50, planner=30, hgnn=20)
        
        assert metrics.fast_rate == pytest.approx(0.5)
        assert metrics.planner_rate == pytest.approx(0.3)
        assert metrics.hgnn_rate == pytest.approx(0.2)
    
    def test_rate_calculations_zero_total(self):
        """Test rate calculations with zero total."""
        metrics = RoutingMetrics()
        assert metrics.fast_rate is None
        assert metrics.planner_rate is None
        assert metrics.hgnn_rate is None
    
    def test_hgnn_plan_success_rate(self):
        """Test HGNN plan success rate calculation."""
        metrics = RoutingMetrics(hgnn=20, hgnn_plan_generated=15, hgnn_plan_empty=5)
        assert metrics.hgnn_plan_success_rate == pytest.approx(0.75)
    
    def test_hgnn_plan_success_rate_zero(self):
        """Test HGNN plan success rate with zero HGNN."""
        metrics = RoutingMetrics()
        assert metrics.hgnn_plan_success_rate is None
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "fast_routed_total": 50,
            "planner_routed_total": 30,
            "hgnn_routed_total": 20,
            "hgnn_plan_generated_total": 15,
            "hgnn_plan_empty_total": 5,
        }
        
        metrics = RoutingMetrics.from_dict(data)
        
        assert metrics.fast == 50
        assert metrics.planner == 30
        assert metrics.hgnn == 20
        assert metrics.hgnn_plan_generated == 15
        assert metrics.hgnn_plan_empty == 5
        assert metrics.total == 100  # Sum of routes
    
    def test_from_dict_with_total(self):
        """Test from_dict with explicit total."""
        data = {
            "fast_routed_total": 50,
            "planner_routed_total": 30,
            "hgnn_routed_total": 20,
            "total": 150,  # Explicit total
        }
        
        metrics = RoutingMetrics.from_dict(data)
        assert metrics.total == 150
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        metrics = RoutingMetrics(total=100, fast=50, planner=30, hgnn=20)
        result = metrics.to_dict()
        
        assert result["total"] == 100
        assert result["fast"] == 50
        assert result["planner"] == 30
        assert result["hgnn"] == 20
        assert "fast_rate" in result
        assert "planner_rate" in result
        assert "hgnn_rate" in result


class TestExecutionMetrics:
    """Tests for ExecutionMetrics schema."""
    
    def test_default_initialization(self):
        """Test default initialization."""
        metrics = ExecutionMetrics()
        assert metrics.total == 0
        assert metrics.successful == 0
        assert metrics.failed == 0
    
    def test_validation_negative_values(self):
        """Test validation rejects negative values."""
        with pytest.raises(ValueError, match="must be non-negative"):
            ExecutionMetrics(total=-1)
    
    def test_rate_calculations(self):
        """Test rate property calculations."""
        metrics = ExecutionMetrics(
            total=100,
            successful=80,
            fast_path=60,
            hgnn=20
        )
        
        assert metrics.success_rate == pytest.approx(0.8)
        assert metrics.fast_path_rate == pytest.approx(0.6)
        assert metrics.hgnn_rate == pytest.approx(0.2)
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "total_tasks": 100,
            "successful_tasks": 80,
            "failed_tasks": 20,
            "fast_path_tasks": 60,
            "hgnn_tasks": 20,
            "escalation_failures": 5,
        }
        
        metrics = ExecutionMetrics.from_dict(data)
        
        assert metrics.total == 100
        assert metrics.successful == 80
        assert metrics.failed == 20
        assert metrics.fast_path == 60
        assert metrics.hgnn == 20
        assert metrics.escalation_failures == 5
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        metrics = ExecutionMetrics(total=100, successful=80, fast_path=60)
        result = metrics.to_dict()
        
        assert result["total"] == 100
        assert result["successful"] == 80
        assert result["fast_path"] == 60
        assert "success_rate" in result
        assert "fast_path_rate" in result


class TestLatencyMetrics:
    """Tests for LatencyMetrics schema."""
    
    def test_default_initialization(self):
        """Test default initialization."""
        metrics = LatencyMetrics()
        assert metrics.samples == []
        assert metrics.count == 0
        assert metrics.min_ms is None
        assert metrics.max_ms is None
    
    def test_initialization_with_samples(self):
        """Test initialization with samples."""
        samples = [50.0, 75.0, 100.0, 25.0]
        metrics = LatencyMetrics(
            samples=samples,
            count=4,
            min_ms=25.0,
            max_ms=100.0,
            mean_ms=62.5
        )
        
        assert metrics.samples == samples
        assert metrics.count == 4
        assert metrics.min_ms == 25.0
        assert metrics.max_ms == 100.0
        assert metrics.mean_ms == 62.5
    
    def test_validation_negative_samples(self):
        """Test validation rejects negative samples."""
        with pytest.raises(ValueError, match="must be non-negative"):
            LatencyMetrics(samples=[50.0, -10.0, 75.0])
    
    def test_validation_min_max_consistency(self):
        """Test validation of min/max consistency."""
        with pytest.raises(ValueError, match="cannot be greater than max_ms"):
            LatencyMetrics(min_ms=100.0, max_ms=50.0)
    
    def test_avg_ms_property(self):
        """Test avg_ms property alias."""
        metrics = LatencyMetrics(mean_ms=62.5)
        assert metrics.avg_ms == 62.5
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "fast_path_latency_ms": [50.0, 75.0, 100.0, 25.0]
        }
        
        metrics = LatencyMetrics.from_dict(data, "fast_path_latency_ms")
        
        assert metrics.count == 4
        assert metrics.min_ms == 25.0
        assert metrics.max_ms == 100.0
        assert metrics.mean_ms == pytest.approx(62.5)
        assert len(metrics.samples) == 4
    
    def test_from_dict_empty(self):
        """Test from_dict with empty list."""
        data = {"fast_path_latency_ms": []}
        metrics = LatencyMetrics.from_dict(data, "fast_path_latency_ms")
        
        assert metrics.count == 0
        assert metrics.min_ms is None
        assert metrics.max_ms is None
        assert metrics.mean_ms is None
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        metrics = LatencyMetrics(
            samples=[50.0, 75.0],
            count=2,
            min_ms=50.0,
            max_ms=75.0,
            mean_ms=62.5
        )
        result = metrics.to_dict()
        
        assert result["count"] == 2
        assert result["min_ms"] == 50.0
        assert result["max_ms"] == 75.0
        assert result["mean_ms"] == 62.5
        assert result["avg_ms"] == 62.5


class TestDispatchMetrics:
    """Tests for DispatchMetrics schema."""
    
    def test_default_initialization(self):
        """Test default initialization."""
        metrics = DispatchMetrics()
        assert metrics.planner_ok == 0
        assert metrics.planner_err == 0
        assert metrics.hgnn_ok == 0
        assert metrics.hgnn_err == 0
    
    def test_validation_negative_values(self):
        """Test validation rejects negative values."""
        with pytest.raises(ValueError, match="must be non-negative"):
            DispatchMetrics(planner_ok=-1)
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "dispatch_planner_ok_total": 100,
            "dispatch_planner_err_total": 5,
            "dispatch_hgnn_ok_total": 80,
            "dispatch_hgnn_err_total": 3,
        }
        
        metrics = DispatchMetrics.from_dict(data)
        
        assert metrics.planner_ok == 100
        assert metrics.planner_err == 5
        assert metrics.hgnn_ok == 80
        assert metrics.hgnn_err == 3
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        metrics = DispatchMetrics(planner_ok=100, planner_err=5, hgnn_ok=80, hgnn_err=3)
        result = metrics.to_dict()
        
        assert result["planner_ok"] == 100
        assert result["planner_err"] == 5
        assert result["hgnn_ok"] == 80
        assert result["hgnn_err"] == 3


class TestPersistenceMetrics:
    """Tests for PersistenceMetrics schema."""
    
    def test_default_initialization(self):
        """Test default initialization."""
        metrics = PersistenceMetrics()
        assert metrics.proto_plan_upsert_ok == 0
        assert metrics.outbox_embed_enqueue_ok == 0
    
    def test_validation_negative_values(self):
        """Test validation rejects negative values."""
        with pytest.raises(ValueError, match="must be non-negative"):
            PersistenceMetrics(proto_plan_upsert_ok=-1)
    
    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "proto_plan_upsert_ok_total": 100,
            "proto_plan_upsert_err_total": 5,
            "proto_plan_upsert_truncated_total": 2,
            "outbox_embed_enqueue_ok_total": 200,
            "outbox_embed_enqueue_dup_total": 10,
            "outbox_embed_enqueue_err_total": 3,
        }
        
        metrics = PersistenceMetrics.from_dict(data)
        
        assert metrics.proto_plan_upsert_ok == 100
        assert metrics.proto_plan_upsert_err == 5
        assert metrics.proto_plan_upsert_truncated == 2
        assert metrics.outbox_embed_enqueue_ok == 200
        assert metrics.outbox_embed_enqueue_dup == 10
        assert metrics.outbox_embed_enqueue_err == 3
    
    def test_to_dict(self):
        """Test converting to dictionary."""
        metrics = PersistenceMetrics(
            proto_plan_upsert_ok=100,
            outbox_embed_enqueue_ok=200
        )
        result = metrics.to_dict()
        
        assert result["proto_plan_upsert_ok"] == 100
        assert result["outbox_embed_enqueue_ok"] == 200


class TestValidationHelpers:
    """Tests for validation helper functions."""
    
    def test_validate_non_negative_valid(self):
        """Test validate_non_negative with valid value."""
        validate_non_negative(0, "test")
        validate_non_negative(100, "test")
    
    def test_validate_non_negative_invalid(self):
        """Test validate_non_negative with invalid value."""
        with pytest.raises(ValueError, match="must be non-negative"):
            validate_non_negative(-1, "test")
    
    def test_validate_positive_if_present_none(self):
        """Test validate_positive_if_present with None."""
        validate_positive_if_present(None, "test")
    
    def test_validate_positive_if_present_valid(self):
        """Test validate_positive_if_present with valid value."""
        validate_positive_if_present(0.0, "test")
        validate_positive_if_present(100.0, "test")
    
    def test_validate_positive_if_present_invalid(self):
        """Test validate_positive_if_present with invalid value."""
        with pytest.raises(ValueError, match="must be non-negative"):
            validate_positive_if_present(-1.0, "test")
    
    def test_validate_metric_key_valid(self):
        """Test validate_metric_key with valid key."""
        validate_metric_key("fast_routed_total", VALID_ROUTING_KEYS, "routing")
    
    def test_validate_metric_key_invalid(self):
        """Test validate_metric_key with invalid key."""
        with pytest.raises(ValueError, match="Invalid routing key"):
            validate_metric_key("invalid_key", VALID_ROUTING_KEYS, "routing")

