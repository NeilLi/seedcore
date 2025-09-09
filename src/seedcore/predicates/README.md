# Predicate-Based Routing System

This module implements a comprehensive predicate-based routing system for the SeedCore Coordinator service. It provides auditable, YAML-configurable routing decisions based on canonical signals and mathematical variables.

## Overview

The predicate system consists of several key components:

- **Canonical Signal Registry**: Defines all mathematical variables used in routing decisions
- **YAML Configuration**: Human-readable, version-controlled routing rules
- **Safe Expression Evaluator**: Secure evaluation of boolean expressions without `eval()`
- **GPU Guard System**: Resource management for GPU-intensive operations
- **Prometheus Metrics**: Comprehensive monitoring and observability

## Architecture

```
Coordinator Service
├── PredicateRouter
│   ├── Signal Registry (p_fast, s_drift, ΔE_est, etc.)
│   ├── YAML Configuration Loader
│   ├── Safe Expression Evaluator
│   └── GPU Guard System
├── Prometheus Metrics Export
└── Background Maintenance Tasks
```

## Key Features

### 1. Canonical Signal Registry

All mathematical variables are defined in a central registry:

```python
from seedcore.predicates import SIGNALS, create_signal_context

# Get signal specification
spec = get_signal_spec("p_fast")
print(f"p_fast: {spec.description} (range: {spec.min_value}-{spec.max_value})")

# Create validated signal context
context = create_signal_context(
    p_fast=0.8,
    s_drift=0.3,
    gpu_queue_depth=2
)
```

### 2. YAML Configuration

Routing rules are defined in YAML for easy modification and version control:

```yaml
routing:
  - when: "task.type == 'anomaly_triage' and s_drift > 0.7"
    do: "escalate"
    priority: 10
    description: "Escalate high-drift anomaly triage tasks"

  - when: "task.type == 'general_query' and p_fast > 0.8"
    do: "fast_path:utility_organ_1"
    priority: 7
    description: "Fast path for confident general queries"

mutations:
  - when: "decision.action == 'tune' and ΔE_est > 0.05 and gpu.guard_ok"
    do: "submit_tuning"
    priority: 10
    description: "Submit high-value tuning jobs"
```

### 3. Safe Expression Evaluation

Boolean expressions are evaluated safely using AST parsing:

```python
from seedcore.predicates import PredicateEvaluator

evaluator = PredicateEvaluator()

# Safe evaluation
result = evaluator.eval_predicate(
    "p_fast > 0.8 and s_drift < 0.5",
    {"p_fast": 0.9, "s_drift": 0.3}
)
# Returns: True
```

### 4. GPU Guard System

Manages GPU resource allocation with concurrency limits and daily budgets:

```python
# Check if job can be submitted
can_submit, reason = gpu_guard.can_submit_job("tuning")

# Submit and track job
if can_submit:
    gpu_guard.submit_job("job_123", "tuning")
    gpu_guard.start_job("job_123")
    # ... job execution ...
    gpu_guard.complete_job("job_123", success=True)
```

### 5. Prometheus Metrics

All canonical signals are exported as Prometheus metrics:

- `coord_p_fast`: OCPS fast-path probability
- `coord_escalation_ratio`: Escalation ratio
- `coord_deltaE_est`: Expected energy improvement
- `coord_gpu_queue_depth`: GPU queue depth
- `coord_requests_total`: Request counters by path

## Usage

### Basic Setup

```python
from seedcore.predicates import PredicateRouter, load_predicates

# Load configuration
config = load_predicates("/path/to/predicates.yaml")

# Create router
router = PredicateRouter(config)

# Update signals
router.update_signals(
    p_fast=0.8,
    s_drift=0.3,
    memory_utilization=0.6
)

# Route task
task = {"type": "anomaly_triage", "priority": 7}
decision = router.route_task(task)
print(f"Action: {decision.action}, Reason: {decision.reason}")
```

### Integration with Coordinator

The predicate system is automatically integrated into the Coordinator service:

```python
# In coordinator_service.py
class Coordinator:
    def __init__(self):
        # Load predicate configuration
        self.predicate_config = load_predicates(PREDICATES_CONFIG_PATH)
        self.predicate_router = PredicateRouter(self.predicate_config)
    
    async def route_and_execute(self, task: Task):
        # Update signals
        self.predicate_router.update_signals(
            p_fast=self.ocps.p_fast,
            s_drift=task.drift_score,
            # ... other signals
        )
        
        # Route using predicates
        decision = self.predicate_router.route_task(task.model_dump())
        
        # Execute based on decision
        if decision.action == "fast_path":
            return await self._execute_fast(task, decision.organ_id)
        else:
            return await self._execute_hgnn(task)
```

## Configuration

### Signal Definitions

All signals are defined in `signals.py` with validation rules:

```python
SIGNALS = {
    "p_fast": SignalSpec("p_fast", float, "Fast-path probability", 
                        min_value=0.0, max_value=1.0),
    "s_drift": SignalSpec("s_drift", float, "Drift slice gᵀh"),
    "ΔE_est": SignalSpec("ΔE_est", float, "Expected energy improvement"),
    # ... more signals
}
```

### YAML Schema

The configuration follows a strict schema defined in `schema.py`:

```python
class PredicatesConfig(BaseModel):
    routing: List[Rule]
    mutations: List[Rule]
    gpu_guard: GpuGuard
    metadata: Metadata
```

### Expression Syntax

Supported expression syntax:

- **Comparisons**: `p_fast > 0.8`, `s_drift <= 0.5`
- **Boolean operations**: `and`, `or`, `not`
- **Membership**: `task.type in ['query', 'triage']`
- **Attribute access**: `task.priority`, `gpu.guard_ok`
- **Arithmetic**: `ΔE_est * 2`, `budget_remaining_s - 600`

## Monitoring

### Prometheus Metrics

Key metrics for monitoring:

```promql
# Fast-path probability
coord_p_fast

# Escalation ratio
rate(coord_requests_total{path="hgnn"}[5m]) / rate(coord_requests_total[5m])

# GPU guard status
coord_gpu_guard_ok

# Request latency
histogram_quantile(0.95, coord_e2e_ms)
```

### Grafana Dashboards

Recommended dashboard panels:

1. **OCPS Signals**: `coord_p_fast`, `coord_s_drift`
2. **Routing Decisions**: `coord_routing_decisions_total`
3. **GPU Guard**: `coord_gpu_queue_depth`, `coord_gpu_budget_remaining_s`
4. **Performance**: `coord_e2e_ms`, `coord_success_rate`

## Testing

Run the test suite:

```bash
pytest tests/test_predicates.py -v
```

Key test categories:

- Expression evaluation
- Signal validation
- Configuration loading
- GPU guard operations
- Router decision making

## Development

### Adding New Signals

1. Add signal definition to `signals.py`:
```python
"new_signal": SignalSpec("new_signal", float, "Description", unit="units")
```

2. Update metrics in `metrics.py`:
```python
new_signal_gauge = Gauge("coord_new_signal", "Description")
```

3. Update router to emit the signal:
```python
router.update_signals(new_signal=value)
```

### Adding New Rules

1. Add rule to YAML configuration:
```yaml
routing:
  - when: "new_signal > threshold"
    do: "action"
    priority: 5
    description: "Rule description"
```

2. Reload configuration:
```bash
curl -X POST http://coordinator:8000/pipeline/predicates/reload
```

## Troubleshooting

### Common Issues

1. **Expression evaluation errors**: Check signal names and syntax
2. **Configuration loading failures**: Validate YAML syntax and schema
3. **GPU guard blocking**: Check concurrency limits and budget
4. **Metrics not updating**: Verify signal values are being set

### Debug Endpoints

- `GET /pipeline/predicates/status`: System status
- `GET /pipeline/predicates/config`: Current configuration
- `POST /pipeline/predicates/reload`: Reload configuration

### Logging

Enable debug logging:

```python
import logging
logging.getLogger("seedcore.predicates").setLevel(logging.DEBUG)
```

## Future Enhancements

- [ ] Machine learning-based rule optimization
- [ ] A/B testing framework for rule changes
- [ ] Real-time rule performance analytics
- [ ] Integration with external monitoring systems
- [ ] Advanced expression functions and operators
