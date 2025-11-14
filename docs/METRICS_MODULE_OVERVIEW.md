# 📊 **SeedCore Metrics Module (`ops.metrics`)**

## Purpose

The `metrics` module provides **centralized, thread-safe, and extensible observability** for tracking coordinator performance, routing efficiency, and execution outcomes across distributed SeedCore components.

It replaces local metric tracking in `coordinator_service.py` with a decoupled, production-ready observability layer — designed for **scalability, modularity, and exporter integration**.

---

## 🧩 **Architecture Overview**

### Core Components

| File           | Responsibility                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| `tracker.py`   | Core metrics logic. Thread-safe counters and latency tracking for routing, execution, and persistence. |
| `registry.py`  | Global singleton registry for consistent access to the shared tracker instance.                        |
| `schemas.py`   | Typed dataclasses defining structured metrics categories (routing, execution, persistence, dispatch).  |
| `exporters.py` | Pluggable exporter layer for Prometheus, OpenTelemetry, Redis, or file-based backends.                 |
| `__init__.py`  | Centralized exports for public API access.                                                             |

---

## ⚙️ **Core Class: `MetricsTracker`**

### Description

`MetricsTracker` is the in-memory metrics engine that records runtime events, aggregates performance data, and supports future exporter integration.

It replaces ad-hoc metric tracking in the Coordinator, providing:

* **Thread-safety** using `threading.Lock`
* **Bounded memory** via `deque(maxlen=N)` for latency histories
* **Encapsulated operations** (no direct access to `_task_metrics`)
* **Consistent aggregation** for both in-memory and external exporters

### Key Features

| Category                 | Description                                                             |
| ------------------------ | ----------------------------------------------------------------------- |
| **Routing Metrics**      | Tracks routing decisions (fast / planner / HGNN) and cache performance. |
| **Execution Metrics**    | Monitors task outcomes, latency distributions, and escalation failures. |
| **Persistence Metrics**  | Records DAO-level operations (proto_plan upsert, outbox enqueue).       |
| **Dispatch Metrics**     | Measures downstream dispatch success/failure rates.                     |
| **Aggregate Statistics** | Calculates success rates, routing ratios, and latency averages.         |

### Initialization

```python
from seedcore.ops.metrics import MetricsTracker, NoOpExporter

# Basic initialization
tracker = MetricsTracker(latency_reservoir_size=1000)

# With exporter
exporter = NoOpExporter()  # or PrometheusExporter, RedisExporter, etc.
tracker = MetricsTracker(latency_reservoir_size=1000, exporter=exporter)
```

### Configuration Parameters

| Parameter               | Default | Description                                          |
| ----------------------- | ------- | ----------------------------------------------------- |
| `latency_reservoir_size` | 1000    | Maximum number of latency samples retained per metric |
| `exporter`             | None    | Optional exporter for pushing metrics to external systems |

---

## 🧮 **Thread-Safe Metric Operations**

| Method                                       | Description                                                                 |
| -------------------------------------------- | --------------------------------------------------------------------------- |
| `increment_counter(key)`                     | Safely increments counter metrics.                                          |
| `append_latency(key, value)`                 | Appends latency while respecting the bounded deque.                         |
| `track_routing_decision(decision, has_plan)` | Records high-level routing logic outcomes.                                  |
| `track_metrics(path, success, latency_ms)`   | Updates execution stats and latency measurements.                           |
| `record_proto_plan_upsert(status)`           | Records persistence outcomes for proto plans.                               |
| `record_outbox_enqueue(status)`              | Tracks enqueue success, duplicates, or errors.                              |
| `record_dispatch(route, status)`             | Tracks dispatch performance per route.                                      |
| `record_route_latency(latency_ms)`           | Records end-to-end route and execute latency.                               |
| `get_metrics()`                              | Returns computed snapshot of all metrics (averages, rates, and raw values). |
| `get_metadata()`                             | Returns tracker metadata (uptime, reset info, exporter health).            |
| `reset()`                                    | Resets all metrics to zero (useful for testing).                            |

### Usage Examples

```python
from seedcore.ops.metrics import get_global_metrics_tracker

tracker = get_global_metrics_tracker()

# Track routing decision
tracker.track_routing_decision("fast")
tracker.track_routing_decision("hgnn", has_plan=True)

# Track execution
tracker.track_metrics("fast", success=True, latency_ms=42.0)
tracker.track_metrics("hgnn", success=False, latency_ms=150.0)

# Record persistence operations
tracker.record_proto_plan_upsert("ok")
tracker.record_outbox_enqueue("dup")

# Record dispatch outcomes
tracker.record_dispatch("planner", "ok")
tracker.record_dispatch("hgnn", "err")

# Get metrics snapshot
metrics = tracker.get_metrics()
print(f"Success rate: {metrics.get('success_rate')}")
print(f"Fast path avg latency: {metrics.get('fast_path_latency_avg_ms')}ms")

# Get metadata
metadata = tracker.get_metadata()
print(f"Uptime: {metadata['uptime_seconds']}s")
print(f"Exporter health: {metadata['exporter_health']}")
```

---

## 🧠 **Schema Layer (`schemas.py`)**

Defines structured data classes for semantic clarity and external integrations.

### Available Schemas

1. **`RoutingMetrics`** - Routing decision tracking
   - `fast`, `planner`, `hgnn` counts
   - `hgnn_plan_generated`, `hgnn_plan_empty` counts
   - Computed rates: `fast_rate`, `planner_rate`, `hgnn_rate`, `hgnn_plan_success_rate`

2. **`ExecutionMetrics`** - Task execution tracking
   - `total`, `successful`, `failed` counts
   - `fast_path`, `hgnn`, `escalation_failures` counts
   - Computed rates: `success_rate`, `fast_path_rate`, `hgnn_rate`

3. **`LatencyMetrics`** - Latency statistics
   - `samples`, `count`, `min_ms`, `max_ms`, `mean_ms`
   - Validates non-negative samples and min/max consistency

4. **`DispatchMetrics`** - Dispatch operation tracking
   - `planner_ok`, `planner_err`, `hgnn_ok`, `hgnn_err` counts

5. **`PersistenceMetrics`** - Persistence operation tracking
   - Proto plan upsert: `ok`, `err`, `truncated`
   - Outbox enqueue: `ok`, `dup`, `err`

### Schema Features

* **Validation**: `__post_init__` methods validate non-negative values
* **Type Safety**: Type hints and Literal types for valid values
* **From Dict**: `from_dict()` class methods for safe construction
* **To Dict**: `to_dict()` methods for serialization

### Example

```python
from seedcore.ops.metrics.schemas import RoutingMetrics

# Create from dictionary (from MetricsTracker.get_metrics())
data = {
    "fast_routed_total": 50,
    "planner_routed_total": 30,
    "hgnn_routed_total": 20,
    "hgnn_plan_generated_total": 15,
    "hgnn_plan_empty_total": 5,
}

routing = RoutingMetrics.from_dict(data)
print(f"Fast routing rate: {routing.fast_rate}")  # 0.5
print(f"HGNN plan success rate: {routing.hgnn_plan_success_rate}")  # 0.75
```

---

## 🔗 **Registry Layer (`registry.py`)**

Manages a **global singleton** instance of the tracker to avoid duplicate metrics contexts.

### API

```python
from seedcore.ops.metrics import (
    get_global_metrics_tracker,
    reset_global_metrics_tracker,
    set_global_metrics_tracker
)

# Get or create global instance
tracker = get_global_metrics_tracker()
tracker.increment_counter("successful_tasks")

# Reset global instance (useful for testing)
reset_global_metrics_tracker()

# Set custom instance (useful for testing)
custom_tracker = MetricsTracker()
set_global_metrics_tracker(custom_tracker)
```

### Thread Safety

The registry uses a **double-check locking pattern** to ensure thread-safe singleton initialization:

```python
def get_global_metrics_tracker() -> MetricsTracker:
    global _global_metrics_tracker
    
    if _global_metrics_tracker is None:
        with _registry_lock:
            # Double-check pattern
            if _global_metrics_tracker is None:
                _global_metrics_tracker = MetricsTracker()
    
    return _global_metrics_tracker
```

### Pattern Consistency

This pattern mirrors other global managers in SeedCore:

* `get_global_pkg_manager()` (PKG module)
* `get_global_eventizer_client()` (Eventizer)

Ensures consistent observability context across distributed service layers.

---

## 📤 **Exporter Layer (`exporters.py`)**

Abstract base and implementations for metrics export destinations.

### Base Class

```python
class MetricsExporter(ABC):
    @abstractmethod
    def export(self, metrics: Dict[str, Any]) -> bool:
        """Export metrics to external system."""
        pass
    
    @abstractmethod
    def flush(self) -> bool:
        """Flush any buffered metrics."""
        pass
    
    def get_health(self) -> Dict[str, Any]:
        """Get exporter health status."""
        return {
            "type": type(self).__name__,
            "available": True,
            "healthy": True,
        }
```

### Implementations

| Exporter                       | Status     | Description                                                            |
| ------------------------------ | ---------- | ---------------------------------------------------------------------- |
| `NoOpExporter`                 | ✅ Active   | No-op exporter (default, discards metrics)                            |
| `LoggingExporter`              | ✅ Active   | Periodically logs metrics for local debugging                         |
| `PrometheusExporter`           | 🧩 Stub     | Exposes `/metrics` endpoint for Prometheus scrape (requires `prometheus-client`) |
| `OpenTelemetryExporter`        | 🧩 Stub     | Sends metrics via OTLP for distributed tracing (requires `opentelemetry`) |
| `RedisExporter`                | 🧩 Stub     | Publishes metrics snapshots to Redis channels for external aggregation |

### Exporter Health Status

All exporters provide health status via `get_health()`:

```python
exporter = PrometheusExporter()
health = exporter.get_health()

# Returns:
# {
#     "type": "PrometheusExporter",
#     "available": False,  # True if prometheus_client is installed
#     "healthy": False
# }
```

### Integration Example

```python
from seedcore.ops.metrics import MetricsTracker, LoggingExporter

# Create tracker with exporter
exporter = LoggingExporter(log_level=logging.INFO)
tracker = MetricsTracker(exporter=exporter)

# Metrics are automatically exported (if exporter is configured)
tracker.track_routing_decision("fast")
metrics = tracker.get_metrics()
exporter.export(metrics)  # Logs metrics summary
```

---

## 🧭 **Integration in Coordinator**

### Before

Metrics were tracked manually inside `coordinator_service.py`:

```python
# Old approach - direct access to internal state
self.metrics = MetricsTracker()
self.metrics._task_metrics["successful_tasks"] += 1
self.metrics._task_metrics["route_cache_hit_total"] += 1
self.metrics._task_metrics["route_remote_latency_ms"].append(latency_ms)
```

**Problems:**
* Direct access to `_task_metrics` dict (violates encapsulation)
* No thread-safety guarantees
* Tight coupling to implementation details

### After

Now integrated via the registry pattern:

```python
from seedcore.ops.metrics import get_global_metrics_tracker

# In Coordinator.__init__()
self.metrics = get_global_metrics_tracker()

# Thread-safe operations
self.metrics.increment_counter("route_cache_hit_total")
self.metrics.increment_counter("route_remote_total")
self.metrics.append_latency("route_remote_latency_ms", latency_ms)
self.metrics.track_routing_decision(decision, has_plan=has_plan)
```

**Benefits:**
* ✅ Encapsulated operations (no direct dict access)
* ✅ Thread-safe by design
* ✅ Global singleton ensures consistency across workers
* ✅ Ready for exporter integration

---

## 🛠️ **Design Principles**

1. **Thread-safe by design** — All operations use `threading.Lock` for concurrent safety
2. **Bounded resource usage** — Fixed `deque(maxlen=N)` sizes prevent unbounded memory growth
3. **Modular extensibility** — New exporters and schemas can be added seamlessly
4. **Cross-service observability** — Ready for integration across distributed Coordinator instances
5. **Consistency with PKG architecture** — Shared patterns (singleton registry, metadata) and initialization semantics
6. **Type safety** — Schemas with validation and type hints
7. **Encapsulation** — No direct access to internal `_task_metrics` dict

---

## 📊 **Metrics Categories**

### Routing Metrics

| Metric                          | Description                                    |
| ------------------------------- | ---------------------------------------------- |
| `route_cache_hit_total`          | Number of route cache hits                     |
| `route_remote_total`             | Number of remote route resolutions             |
| `route_remote_latency_ms`        | Latency samples for remote route resolution    |
| `route_remote_fail_total`        | Number of failed remote route resolutions      |
| `bulk_resolve_items`             | Number of items in bulk resolve operations     |
| `bulk_resolve_failed_items`      | Number of failed items in bulk resolve         |
| `fast_routed_total`              | Number of requests routed to fast path         |
| `planner_routed_total`           | Number of requests routed to planner           |
| `hgnn_routed_total`              | Number of requests routed to HGNN              |
| `hgnn_plan_generated_total`      | Number of HGNN routes with generated plans     |
| `hgnn_plan_empty_total`          | Number of HGNN routes with empty plans         |

**Computed Rates:**
* `fast_routed_rate` - Fast path routing percentage
* `planner_routed_rate` - Planner routing percentage
* `hgnn_routed_rate` - HGNN routing percentage
* `hgnn_plan_success_rate` - HGNN plan generation success rate

### Execution Metrics

| Metric                    | Description                           |
| ------------------------- | ------------------------------------- |
| `total_tasks`             | Total number of tasks executed        |
| `successful_tasks`         | Number of successfully executed tasks |
| `failed_tasks`            | Number of failed tasks                |
| `fast_path_tasks`         | Number of tasks executed via fast path |
| `hgnn_tasks`              | Number of tasks executed via HGNN     |
| `escalation_failures`      | Number of escalation failures          |
| `fast_path_latency_ms`    | Latency samples for fast path          |
| `hgnn_latency_ms`         | Latency samples for HGNN path          |
| `escalation_latency_ms`    | Latency samples for escalation failures |

**Computed Rates:**
* `success_rate` - Overall task success rate
* `fast_path_rate` - Fast path execution percentage
* `hgnn_rate` - HGNN execution percentage

### Persistence Metrics

| Metric                                | Description                          |
| ------------------------------------ | ------------------------------------ |
| `proto_plan_upsert_ok_total`         | Successful proto plan upserts        |
| `proto_plan_upsert_err_total`        | Failed proto plan upserts            |
| `proto_plan_upsert_truncated_total`   | Truncated proto plan upserts         |
| `outbox_embed_enqueue_ok_total`      | Successful outbox enqueues           |
| `outbox_embed_enqueue_dup_total`     | Duplicate outbox enqueues            |
| `outbox_embed_enqueue_err_total`     | Failed outbox enqueues               |

### Dispatch Metrics

| Metric                      | Description                    |
| --------------------------- | ------------------------------ |
| `dispatch_planner_ok_total` | Successful planner dispatches  |
| `dispatch_planner_err_total` | Failed planner dispatches     |
| `dispatch_hgnn_ok_total`   | Successful HGNN dispatches     |
| `dispatch_hgnn_err_total`   | Failed HGNN dispatches         |

### End-to-End Metrics

| Metric                           | Description                           |
| -------------------------------- | ------------------------------------- |
| `route_and_execute_latency_ms`   | Total route + execute latency samples |

**Computed Aggregates:**
* `fast_path_latency_avg_ms` - Average fast path latency
* `hgnn_latency_avg_ms` - Average HGNN latency
* `escalation_latency_avg_ms` - Average escalation latency
* `route_remote_latency_avg_ms` - Average remote route resolution latency
* `route_and_execute_latency_avg_ms` - Average end-to-end latency

---

## 🧪 **Testing**

### Test Files

The module includes comprehensive unit tests:

```
tests/
  ├── test_metrics_tracker.py      # Core tracker functionality
  ├── test_metrics_schemas.py      # Schema validation and conversions
  ├── test_metrics_registry.py     # Singleton pattern and thread-safety
  └── test_metrics_exporters.py    # Exporter implementations
```

### Test Coverage

* **Unit tests**
  * Counter increments and latency append under concurrency
  * Metrics aggregation accuracy (averages, success rates)
  * Schema validation and error handling
  * Registry singleton pattern and thread-safety
  
* **Integration tests**
  * Coordinator metrics lifecycle under simulated workloads
  * Exporter health checks and error handling

### Running Tests

```bash
# Run all metrics tests
pytest tests/test_metrics_*.py -v

# Run specific test file
pytest tests/test_metrics_tracker.py -v

# Run with coverage
pytest tests/test_metrics_*.py --cov=src/seedcore/ops/metrics --cov-report=html
```

---

## 🚀 **Next Extensions**

| Goal                       | Description                                                           |
| -------------------------- | --------------------------------------------------------------------- |
| **Prometheus integration** | Native endpoint exporter with configurable histogram buckets          |
| **OpenTelemetry bridge**   | Distributed trace correlation between Coordinator, PKG, and Eventizer |
| **Cluster aggregation**    | Combine metrics across nodes for multi-instance monitoring            |
| **Adaptive retention**     | Auto-reset or persistence thresholds for long-running services        |
| **Metrics persistence**   | Optional database persistence for historical metrics analysis         |
| **Alerting integration**   | Threshold-based alerting for critical metrics                         |

### Planned Enhancements

1. **Prometheus Exporter Implementation**
   ```python
   # Future: Full Prometheus integration
   from prometheus_client import Counter, Histogram, Gauge
   
   class PrometheusExporter(MetricsExporter):
       def __init__(self):
           self.task_counter = Counter('coordinator_tasks_total', 'Total tasks')
           self.latency_histogram = Histogram('coordinator_latency_ms', 'Latency in ms')
   ```

2. **Metrics Persistence**
   - Optional PostgreSQL persistence for historical analysis
   - Time-series aggregation for long-term trends

3. **Cluster Federation**
   - Aggregate metrics across multiple Coordinator instances
   - Global routing and execution statistics

---

## 📝 **API Reference**

### Public API

```python
from seedcore.ops.metrics import (
    # Core tracker
    MetricsTracker,
    
    # Registry
    get_global_metrics_tracker,
    reset_global_metrics_tracker,
    set_global_metrics_tracker,
    
    # Exporters
    MetricsExporter,
    NoOpExporter,
    LoggingExporter,
    PrometheusExporter,
    OpenTelemetryExporter,
    RedisExporter,
    
    # Schemas
    RoutingMetrics,
    ExecutionMetrics,
    LatencyMetrics,
    DispatchMetrics,
    PersistenceMetrics,
)
```

### Common Usage Patterns

#### Pattern 1: Basic Tracking

```python
from seedcore.ops.metrics import get_global_metrics_tracker

tracker = get_global_metrics_tracker()

# Track operations
tracker.track_routing_decision("fast")
tracker.track_metrics("fast", success=True, latency_ms=42.0)

# Get metrics
metrics = tracker.get_metrics()
```

#### Pattern 2: With Exporter

```python
from seedcore.ops.metrics import MetricsTracker, LoggingExporter

exporter = LoggingExporter(log_level=logging.INFO)
tracker = MetricsTracker(exporter=exporter)

# Metrics automatically exported
tracker.track_routing_decision("fast")
```

#### Pattern 3: Using Schemas

```python
from seedcore.ops.metrics import get_global_metrics_tracker
from seedcore.ops.metrics.schemas import RoutingMetrics

tracker = get_global_metrics_tracker()
raw_metrics = tracker.get_metrics()

# Convert to structured schema
routing = RoutingMetrics.from_dict(raw_metrics)
print(f"Fast routing rate: {routing.fast_rate}")
```

---

## 🧩 **Summary**

| Attribute          | Description                                                    |
| ------------------ | -------------------------------------------------------------- |
| **Module name**    | `seedcore.ops.metrics`                                         |
| **Purpose**        | Unified observability framework for Coordinator and submodules |
| **Core class**     | `MetricsTracker`                                               |
| **Pattern**        | Singleton registry (consistent with PKG)                     |
| **Thread-safety**  | ✅ Yes                                                          |
| **Exporter-ready** | ✅ Yes (Prometheus, OTel, Redis stubs)                          |
| **Schema-driven**  | ✅ Dataclasses for structured metrics                           |
| **Adopted in**     | `services/coordinator_service.py`                              |
| **Future scope**   | Cluster-wide metric federation and external exporters          |

---

## 📚 **Related Documentation**

* [PKG Module Architecture](./PKG_MODULE_ARCHITECTURE.md) - Similar singleton pattern
* [Coordinator Service](./COORDINATOR_MIGRATION_SUMMARY.MD) - Integration details
* [Eventizer Integration](./EVENTIZER_IMPLEMENTATION_SUMMARY.md) - Cross-module observability

---

## 🔗 **See Also**

* `src/seedcore/ops/metrics/__init__.py` - Public API exports
* `src/seedcore/ops/metrics/tracker.py` - Core implementation
* `src/seedcore/services/coordinator_service.py` - Integration example
* `tests/test_metrics_*.py` - Test suite

