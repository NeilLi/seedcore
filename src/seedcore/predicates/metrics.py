"""
Prometheus metrics for predicate-based routing system.

This module exports all the canonical signals as Prometheus metrics for
dashboard integration and monitoring.
"""

from .safe_metrics import create_safe_gauge, create_safe_counter, create_safe_histogram, create_safe_summary, get_safe_registry
from typing import Dict, Any, Optional
import time
import logging

logger = logging.getLogger(__name__)

class PredicateMetrics:
    """Prometheus metrics for predicate system."""
    
    def __init__(self):
        # Router metrics
        self.router_latency_ms = create_safe_histogram(
            "coord_router_ms", 
            "Coordinator routing latency (ms)",
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
        )
        
        self.organ_latency_ms = create_safe_histogram(
            "coord_organ_ms", 
            "Organ fast-path latency (ms)",
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
        )
        
        self.e2e_latency_ms = create_safe_histogram(
            "coord_e2e_ms", 
            "End-to-end request latency (ms)",
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000]
        )
        
        # OCPS and routing signals
        self.p_fast_gauge = create_safe_gauge("coord_p_fast", "OCPS fast-path probability")
        self.escalation_ratio_gauge = create_safe_gauge("coord_escalation_ratio", "Escalation ratio hgnn/total")
        self.s_drift_gauge = create_safe_gauge("coord_s_drift", "Drift slice gᵀh")
        
        # Energy signals
        self.deltaE_est_gauge = create_safe_gauge("coord_deltaE_est", "ΔE_est (expected energy improvement)")
        self.deltaE_realized_gauge = create_safe_gauge("coord_deltaE_realized", "ΔE realized (observed improvement)")
        self.energy_cost_gauge = create_safe_gauge("coord_energy_cost", "Current energy cost")
        
        # GPU guard signals
        self.gpu_queue_depth_gauge = create_safe_gauge("coord_gpu_queue_depth", "GPU queue depth")
        self.gpu_concurrent_jobs_gauge = create_safe_gauge("coord_gpu_concurrent_jobs", "Active GPU jobs")
        self.gpu_budget_remaining_gauge = create_safe_gauge("coord_gpu_budget_remaining_s", "GPU budget remaining (seconds)")
        self.gpu_guard_ok_gauge = create_safe_gauge("coord_gpu_guard_ok", "GPU guard status (1=ok, 0=blocked)")
        
        # System performance signals
        self.fast_path_latency_gauge = create_safe_gauge("coord_fast_path_latency_ms", "Average fast path latency (ms)")
        self.hgnn_latency_gauge = create_safe_gauge("coord_hgnn_latency_ms", "Average HGNN path latency (ms)")
        self.success_rate_gauge = create_safe_gauge("coord_success_rate", "Overall task success rate")
        
        # Memory and resource signals
        self.memory_utilization_gauge = create_safe_gauge("coord_memory_utilization", "Memory utilization ratio")
        self.cpu_utilization_gauge = create_safe_gauge("coord_cpu_utilization", "CPU utilization ratio")
        
        # Task-specific signals
        self.task_priority_gauge = create_safe_gauge("coord_task_priority", "Current task priority", labelnames=["task_type"])
        self.task_complexity_gauge = create_safe_gauge("coord_task_complexity", "Current task complexity", labelnames=["task_type"])
        
        # Request counters
        self.requests_total = create_safe_counter("coord_requests_total", "Total requests", labelnames=["path", "success"])
        self.routing_decisions = create_safe_counter("coord_routing_decisions_total", "Routing decisions", labelnames=["decision", "reason"])
        self.mutation_decisions = create_safe_counter("coord_mutation_decisions_total", "Mutation decisions", labelnames=["decision", "reason"])
        
        # Escalation ratio tracking
        self.escalation_requests = create_safe_counter("coord_escalation_requests_total", "Escalated requests")
        self.total_requests = create_safe_counter("coord_total_requests_total", "Total requests")
        
        # ΔE realized tracking
        self.deltaE_realized_sum = create_safe_counter("coord_deltaE_realized_sum", "Sum of realized energy improvements")
        self.deltaE_realized_count = create_safe_counter("coord_deltaE_realized_count", "Count of realized energy improvements")
        self.gpu_seconds_sum = create_safe_counter("coord_gpu_seconds_sum", "Sum of GPU seconds used")
        self.gpu_seconds_count = create_safe_counter("coord_gpu_seconds_count", "Count of GPU jobs")
        
        # Predicate evaluation metrics
        self.predicate_evaluations = create_safe_counter("coord_predicate_evaluations_total", "Predicate evaluations", labelnames=["rule_type", "result"])
        self.predicate_evaluation_time = create_safe_summary("coord_predicate_evaluation_seconds", "Predicate evaluation time")
        
        # GPU job metrics
        self.gpu_jobs_submitted = create_safe_counter("coord_gpu_jobs_submitted_total", "GPU jobs submitted", labelnames=["job_type"])
        self.gpu_jobs_completed = create_safe_counter("coord_gpu_jobs_completed_total", "GPU jobs completed", labelnames=["job_type", "status"])
        self.gpu_job_duration = create_safe_histogram("coord_gpu_job_duration_seconds", "GPU job duration", labelnames=["job_type"])
        
        # Memory synthesis metrics
        self.memory_synthesis_attempts = create_safe_counter("coord_memory_synthesis_attempts_total", "Memory synthesis attempts", labelnames=["status"])
        self.memory_synthesis_duration = create_safe_summary("coord_memory_synthesis_seconds", "Memory synthesis duration")
        
        # Drift detection metrics
        self.drift_computations = create_safe_counter("coord_drift_computations_total", "Drift computations", labelnames=["status", "drift_mode"])
        self.drift_computation_duration = create_safe_histogram("coord_drift_computation_seconds", "Drift computation duration", buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0])
        self.drift_scores = create_safe_histogram("coord_drift_scores", "Drift scores distribution", buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.5, 2.0])
        
        # Circuit breaker metrics
        self.circuit_breaker_events = create_safe_counter("coord_circuit_breaker_events_total", "Circuit breaker events", labelnames=["service", "event_type"])
        
        logger.info("✅ Predicate metrics initialized")
    
    def update_ocps_signals(self, p_fast: float, s_drift: float, escalation_ratio: float):
        """Update OCPS-related signals."""
        self.p_fast_gauge.set(p_fast)
        self.s_drift_gauge.set(s_drift)
        self.escalation_ratio_gauge.set(escalation_ratio)
    
    def update_energy_signals(self, deltaE_est: Optional[float] = None, 
                            deltaE_realized: Optional[float] = None, 
                            energy_cost: Optional[float] = None):
        """Update energy-related signals."""
        if deltaE_est is not None:
            self.deltaE_est_gauge.set(deltaE_est)
        if deltaE_realized is not None:
            self.deltaE_realized_gauge.set(deltaE_realized)
        if energy_cost is not None:
            self.energy_cost_gauge.set(energy_cost)
    
    def update_gpu_guard_signals(self, queue_depth: int, concurrent_jobs: int, 
                               budget_remaining_s: float, guard_ok: bool):
        """Update GPU guard signals."""
        self.gpu_queue_depth_gauge.set(queue_depth)
        self.gpu_concurrent_jobs_gauge.set(concurrent_jobs)
        self.gpu_budget_remaining_gauge.set(budget_remaining_s)
        self.gpu_guard_ok_gauge.set(1 if guard_ok else 0)
    
    def update_performance_signals(self, fast_path_latency_ms: Optional[float] = None,
                                 hgnn_latency_ms: Optional[float] = None,
                                 success_rate: Optional[float] = None):
        """Update performance signals."""
        if fast_path_latency_ms is not None:
            self.fast_path_latency_gauge.set(fast_path_latency_ms)
        if hgnn_latency_ms is not None:
            self.hgnn_latency_gauge.set(hgnn_latency_ms)
        if success_rate is not None:
            self.success_rate_gauge.set(success_rate)
    
    def update_resource_signals(self, memory_utilization: Optional[float] = None,
                              cpu_utilization: Optional[float] = None):
        """Update resource utilization signals."""
        if memory_utilization is not None:
            self.memory_utilization_gauge.set(memory_utilization)
        if cpu_utilization is not None:
            self.cpu_utilization_gauge.set(cpu_utilization)
    
    def update_task_signals(self, task_type: str, priority: int, complexity: float):
        """Update task-specific signals."""
        self.task_priority_gauge.labels(task_type=task_type).set(priority)
        self.task_complexity_gauge.labels(task_type=task_type).set(complexity)
    
    def record_request(self, path: str, success: bool):
        """Record a request completion."""
        self.requests_total.labels(path=path, success=str(success)).inc()
        self.total_requests.inc()
        
        # Track escalation ratio
        if path in ["hgnn", "escalation_failure"]:
            self.escalation_requests.inc()
    
    def record_routing_decision(self, decision: str, reason: str):
        """Record a routing decision."""
        self.routing_decisions.labels(decision=decision, reason=reason).inc()
    
    def record_mutation_decision(self, decision: str, reason: str):
        """Record a mutation decision."""
        self.mutation_decisions.labels(decision=decision, reason=reason).inc()
    
    def record_predicate_evaluation(self, rule_type: str, result: bool, duration_seconds: float):
        """Record predicate evaluation metrics."""
        self.predicate_evaluations.labels(rule_type=rule_type, result=str(result)).inc()
        self.predicate_evaluation_time.observe(duration_seconds)
    
    def record_gpu_job_submitted(self, job_type: str):
        """Record a GPU job submission."""
        self.gpu_jobs_submitted.labels(job_type=job_type).inc()
    
    def record_gpu_job_completed(self, job_type: str, status: str, duration_seconds: float):
        """Record a GPU job completion."""
        self.gpu_jobs_completed.labels(job_type=job_type, status=status).inc()
        self.gpu_job_duration.labels(job_type=job_type).observe(duration_seconds)
    
    def record_memory_synthesis(self, status: str, duration_seconds: float):
        """Record memory synthesis attempt."""
        self.memory_synthesis_attempts.labels(status=status).inc()
        self.memory_synthesis_duration.observe(duration_seconds)
    
    def record_deltaE_realized(self, deltaE: float, gpu_seconds: float = 0.0):
        """Record realized energy improvement."""
        self.deltaE_realized_sum.inc(deltaE)
        self.deltaE_realized_count.inc()
        if gpu_seconds > 0:
            self.gpu_seconds_sum.inc(gpu_seconds)
            self.gpu_seconds_count.inc()
    
    def get_escalation_ratio(self) -> float:
        """Get current escalation ratio."""
        escalation_rate = self.escalation_requests._value._value
        total_rate = self.total_requests._value._value
        return escalation_rate / total_rate if total_rate > 0 else 0.0
    
    def record_latency(self, latency_type: str, latency_ms: float):
        """Record latency metrics."""
        if latency_type == "router":
            self.router_latency_ms.observe(latency_ms)
        elif latency_type == "organ":
            self.organ_latency_ms.observe(latency_ms)
        elif latency_type == "e2e":
            self.e2e_latency_ms.observe(latency_ms)
    
    def record_drift_computation(self, status: str, drift_mode: str, duration_seconds: float, drift_score: float):
        """Record drift computation metrics."""
        self.drift_computations.labels(status=status, drift_mode=drift_mode).inc()
        self.drift_computation_duration.observe(duration_seconds)
        self.drift_scores.observe(drift_score)
    
    def record_circuit_breaker_event(self, service: str, event_type: str):
        """Record circuit breaker events."""
        self.circuit_breaker_events.labels(service=service, event_type=event_type).inc()

# Global metrics instance
_metrics = PredicateMetrics()

def get_metrics() -> PredicateMetrics:
    """Get the global metrics instance."""
    return _metrics

# Convenience functions for common operations
def update_ocps_signals(p_fast: float, s_drift: float, escalation_ratio: float):
    """Update OCPS signals."""
    _metrics.update_ocps_signals(p_fast, s_drift, escalation_ratio)

def update_energy_signals(deltaE_est: Optional[float] = None, 
                        deltaE_realized: Optional[float] = None, 
                        energy_cost: Optional[float] = None):
    """Update energy signals."""
    _metrics.update_energy_signals(deltaE_est, deltaE_realized, energy_cost)

def update_gpu_guard_signals(queue_depth: int, concurrent_jobs: int, 
                           budget_remaining_s: float, guard_ok: bool):
    """Update GPU guard signals."""
    _metrics.update_gpu_guard_signals(queue_depth, concurrent_jobs, budget_remaining_s, guard_ok)

def record_request(path: str, success: bool):
    """Record a request."""
    _metrics.record_request(path, success)

def record_latency(latency_type: str, latency_ms: float):
    """Record latency."""
    _metrics.record_latency(latency_type, latency_ms)
