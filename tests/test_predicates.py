"""
Tests for the predicate-based routing system.
"""

import pytest
import tempfile
import yaml
from pathlib import Path

from src.seedcore.predicates import (
    PredicateRouter, 
    load_predicates, 
    create_signal_context,
    validate_signal_value,
    get_signal_spec
)
from src.seedcore.predicates.schema import PredicatesConfig, Rule, GpuGuard, Metadata
from src.seedcore.predicates.evaluator import PredicateEvaluator
from src.seedcore.predicates.loader import create_default_config, save_default_config

class TestPredicateEvaluator:
    """Test the predicate evaluator."""
    
    def test_simple_expressions(self):
        """Test simple boolean expressions."""
        evaluator = PredicateEvaluator()
        
        # Test basic comparisons
        assert evaluator.eval_predicate("p_fast > 0.8", {"p_fast": 0.9}) == True
        assert evaluator.eval_predicate("p_fast > 0.8", {"p_fast": 0.7}) == False
        assert evaluator.eval_predicate("s_drift <= 0.5", {"s_drift": 0.3}) == True
        
        # Test boolean operations
        assert evaluator.eval_predicate("p_fast > 0.8 and s_drift < 0.5", {"p_fast": 0.9, "s_drift": 0.3}) == True
        assert evaluator.eval_predicate("p_fast > 0.8 or s_drift < 0.5", {"p_fast": 0.7, "s_drift": 0.3}) == True
        assert evaluator.eval_predicate("not (p_fast < 0.5)", {"p_fast": 0.8}) == True
        
        # Test task context
        context = {
            "task": {"type": "anomaly_triage", "priority": 8},
            "p_fast": 0.9,
            "s_drift": 0.3
        }
        assert evaluator.eval_predicate("task.type == 'anomaly_triage' and p_fast > 0.8", context) == True
        assert evaluator.eval_predicate("task.priority >= 7", context) == True
    
    def test_complex_expressions(self):
        """Test complex expressions with multiple conditions."""
        evaluator = PredicateEvaluator()
        
        context = {
            "task": {"type": "general_query", "priority": 5, "complexity": 0.3},
            "p_fast": 0.9,
            "s_drift": 0.2,
            "fast_path_latency_ms": 50.0,
            "memory_utilization": 0.6,
            "gpu": {"guard_ok": True, "budget_remaining_s": 1000.0}
        }
        
        # Complex routing rule
        expr = "task.type == 'general_query' and p_fast > 0.8 and fast_path_latency_ms < 100 and memory_utilization < 0.8"
        assert evaluator.eval_predicate(expr, context) == True
        
        # GPU guard rule
        expr = "gpu.guard_ok and gpu.budget_remaining_s > 600"
        assert evaluator.eval_predicate(expr, context) == True
        
        # List membership
        expr = "task.type in ['general_query', 'health_check']"
        assert evaluator.eval_predicate(expr, context) == True
    
    def test_error_handling(self):
        """Test error handling for invalid expressions."""
        evaluator = PredicateEvaluator()
        
        # Undefined variable
        with pytest.raises(ValueError):
            evaluator.eval_predicate("undefined_var > 0", {})
        
        # Invalid syntax
        with pytest.raises(ValueError):
            evaluator.eval_predicate("p_fast >", {"p_fast": 0.8})

class TestSignalRegistry:
    """Test the signal registry."""
    
    def test_signal_validation(self):
        """Test signal value validation."""
        # Valid values
        assert validate_signal_value("p_fast", 0.8) == True
        assert validate_signal_value("gpu_queue_depth", 5) == True
        assert validate_signal_value("gpu_guard_ok", True) == True
        
        # Invalid values
        assert validate_signal_value("p_fast", 1.5) == False  # Above max
        assert validate_signal_value("p_fast", -0.1) == False  # Below min
        assert validate_signal_value("gpu_queue_depth", -1) == False  # Below min
    
    def test_signal_specs(self):
        """Test signal specifications."""
        spec = get_signal_spec("p_fast")
        assert spec.name == "p_fast"
        assert spec.dtype == float
        assert spec.min_value == 0.0
        assert spec.max_value == 1.0
    
    def test_signal_context(self):
        """Test signal context creation."""
        context = create_signal_context(
            p_fast=0.8,
            s_drift=0.3,
            gpu_queue_depth=2,
            gpu_guard_ok=True
        )
        
        assert context["p_fast"] == 0.8
        assert context["s_drift"] == 0.3
        assert context["gpu_queue_depth"] == 2
        assert context["gpu_guard_ok"] == True

class TestPredicateRouter:
    """Test the predicate router."""
    
    def test_router_initialization(self):
        """Test router initialization with default config."""
        config = create_default_config()
        router = PredicateRouter(config)
        
        assert router.config == config
        assert router.evaluator is not None
        assert router.gpu_guard is not None
    
    def test_task_routing(self):
        """Test task routing decisions."""
        config = create_default_config()
        router = PredicateRouter(config)
        
        # Update signals
        router.update_signals(
            p_fast=0.9,
            s_drift=0.3,
            fast_path_latency_ms=50.0
        )
        
        # Test anomaly triage routing
        task = {
            "type": "anomaly_triage",
            "domain": "anomaly",
            "priority": 7,
            "complexity": 0.8
        }
        
        decision = router.route_task(task)
        assert decision.action in ["escalate", "fast_path"]
        assert decision.reason != ""
    
    def test_mutation_evaluation(self):
        """Test mutation evaluation."""
        config = create_default_config()
        router = PredicateRouter(config)
        
        # Update signals
        router.update_signals(
            ΔE_est=0.05,
            p_fast=0.8
        )
        
        # Test mutation decision
        task = {"type": "anomaly_triage", "priority": 7, "complexity": 0.8}
        decision = {"action": "tune", "confidence": 0.9}
        
        mutation_decision = router.evaluate_mutation(task, decision)
        assert mutation_decision.action in ["submit_tuning", "hold"]
        assert mutation_decision.reason != ""

class TestConfigurationLoading:
    """Test configuration loading and validation."""
    
    def test_default_config_creation(self):
        """Test default configuration creation."""
        config = create_default_config()
        
        assert isinstance(config, PredicatesConfig)
        assert len(config.routing) > 0
        assert len(config.mutations) > 0
        assert config.gpu_guard.max_concurrent > 0
        assert config.metadata.version is not None
    
    def test_config_loading(self):
        """Test configuration loading from file."""
        # Create a temporary config file
        config = create_default_config()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_dict = config.dict()
            yaml.dump(config_dict, f)
            temp_path = f.name
        
        try:
            # Load the configuration
            loaded_config = load_predicates(temp_path)
            
            assert loaded_config.metadata.version == config.metadata.version
            assert len(loaded_config.routing) == len(config.routing)
            assert len(loaded_config.mutations) == len(config.mutations)
            
        finally:
            # Clean up
            Path(temp_path).unlink()
    
    def test_config_validation(self):
        """Test configuration validation."""
        config = create_default_config()
        
        # Should be valid
        assert config.routing[0].when != ""
        assert config.routing[0].do != ""
        assert config.gpu_guard.max_concurrent > 0
        assert config.metadata.version != ""

class TestGPUGuard:
    """Test GPU guard system."""
    
    def test_gpu_guard_initialization(self):
        """Test GPU guard initialization."""
        config = create_default_config()
        router = PredicateRouter(config)
        
        status = router.get_gpu_guard_status()
        assert "guard_ok" in status
        assert "active_jobs" in status
        assert "budget_remaining_s" in status
    
    def test_gpu_job_submission(self):
        """Test GPU job submission."""
        config = create_default_config()
        router = PredicateRouter(config)
        
        # Should be able to submit a job initially
        can_submit, reason = router.gpu_guard.can_submit_job("tuning")
        assert can_submit == True
        
        # Submit a job
        success = router.gpu_guard.submit_job("test_job_1", "tuning")
        assert success == True
        
        # Start the job
        started = router.gpu_guard.start_job("test_job_1")
        assert started == True
        
        # Complete the job
        completed = router.gpu_guard.complete_job("test_job_1", success=True)
        assert completed == True

if __name__ == "__main__":
    pytest.main([__file__])
