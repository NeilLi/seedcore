# Neural-CUSUM Drift Detection Pipeline

This document describes the implementation of the Neural-CUSUM drift detection pipeline as recommended in the analysis. The pipeline consolidates drift detection, reduces redundancy, and aligns the codebase with the paper's drift-detection architecture.

## Overview

The drift detection pipeline consists of three main components:

1. **Drift Detector Module** (`src/seedcore/ml/drift_detector.py`) - Centralized drift scoring
2. **OCPSValve Integration** (`src/seedcore/services/coordinator_service.py`) - Neural-CUSUM accumulator
3. **Predicate System Integration** - Unified signal routing

## Architecture

```
Task Input
    ↓
ML Service (/drift/score)
    ├── SentenceTransformer (text embeddings)
    ├── Runtime Metrics Extraction
    ├── Feature Vector Combination
    └── Lightweight MLP (log-likelihood)
    ↓
Drift Score (s_t)
    ↓
OCPSValve (Neural-CUSUM)
    ├── S_t = max(0, S_{t-1} + s_t - ν)
    ├── Escalation: S_t > h
    └── Reset on escalation
    ↓
Predicate System
    ├── s_drift (drift slice)
    ├── p_fast (fast-path probability)
    └── Routing Decisions
```

## Implementation Details

### 1. Drift Detector Module

**Location**: `src/seedcore/ml/drift_detector.py`

**Key Features**:
- SentenceTransformer embeddings for text features
- Runtime metrics extraction (latency, memory, CPU, priority, complexity)
- Two-layer MLP with dropout for regularization
- Asynchronous processing with thread pool
- Performance tracking and statistics

**API**:
```python
async def compute_drift_score(task: Dict[str, Any], text: Optional[str] = None) -> DriftScore
```

**Performance Requirements**:
- Target latency: < 50ms for typical feature sizes
- Supports concurrent requests
- Graceful fallback on errors

### 2. ML Service Integration

**Location**: `src/seedcore/ml/serve_app.py`

**Endpoints**:
- `POST /drift/score` - Compute drift score for a task
- `POST /detect/anomaly` - Enhanced anomaly detection using drift scoring

**Request Format**:
```json
{
  "task": {
    "id": "task_123",
    "type": "general_query",
    "description": "Task description",
    "priority": 5,
    "complexity": 0.5,
    "latency_ms": 100.0,
    "memory_usage": 0.4,
    "cpu_usage": 0.3,
    "history_ids": ["task_1", "task_2"]
  },
  "text": "Optional text description"
}
```

**Response Format**:
```json
{
  "drift_score": 0.75,
  "log_likelihood": -0.29,
  "confidence": 0.85,
  "processing_time_ms": 23.4,
  "model_version": "1.0.0",
  "status": "success",
  "timestamp": 1640995200.0
}
```

### 3. Coordinator Service Integration

**Location**: `src/seedcore/services/coordinator_service.py`

**Key Changes**:
- Removed `drift_score` field from Task and AnomalyTriageRequest models
- Added `_compute_drift_score()` method for ML service integration
- Added `_fallback_drift_score()` method for graceful degradation
- Updated routing logic to use computed drift scores

**Integration Points**:
- `route_and_execute()` - Main task routing
- `anomaly_triage()` - Anomaly detection pipeline
- `_hgnn_decompose()` - Cognitive reasoning context

### 4. OCPSValve (Neural-CUSUM Accumulator)

**Location**: `src/seedcore/services/coordinator_service.py` (lines 67-89)

**Algorithm**:
```python
def update(self, drift: float) -> bool:
    self.S = max(0.0, self.S + drift - self.nu)
    esc = self.S > self.h
    if esc:
        self.esc_hits += 1
        self.S = 0.0  # Reset on escalation
    else:
        self.fast_hits += 1
    return esc
```

**Configuration**:
- `nu` (drift threshold): 0.1 (default)
- `h` (escalation threshold): 0.5 (from `OCPS_DRIFT_THRESHOLD` env var)

### 5. Predicate System Integration

**Location**: `src/seedcore/predicates/signals.py`

**Signals**:
- `s_drift`: Drift slice from OCPS (computed by drift detector)
- `p_fast`: Fast-path probability from OCPSValve
- `escalation_ratio`: Ratio of escalated requests

**Routing Rules** (from `config/predicates.yaml`):
```yaml
- when: "task.type == 'anomaly_triage' and s_drift > 0.7"
  do: "escalate"
  priority: 10
  description: "Escalate high-drift anomaly triage tasks"

- when: "task.type == 'anomaly_triage' and s_drift <= 0.7 and p_fast > 0.8"
  do: "fast_path:utility_organ_1"
  priority: 9
  description: "Fast path for low-drift anomaly triage with high confidence"
```

## Initialization Flow

### 1. System Startup

1. **ML Service** starts and loads drift detector models
2. **Coordinator Service** initializes OCPSValve and predicate system
3. **Predicate Router** loads configuration and signal registry

### 2. Task Processing Flow

1. **Task Arrival** → Coordinator receives task
2. **Drift Computation** → Coordinator calls ML service `/drift/score`
3. **OCPSValve Update** → Drift score fed to Neural-CUSUM accumulator
4. **Signal Update** → Predicate system receives `s_drift` and `p_fast`
5. **Routing Decision** → Predicate router determines fast path vs escalation
6. **Execution** → Task routed to appropriate organ

### 3. Error Handling

- **ML Service Unavailable**: Fallback to heuristic drift scoring
- **Model Loading Failure**: Graceful degradation with default scores
- **Timeout**: Circuit breaker prevents cascading failures

## Performance Characteristics

### Latency Requirements

- **Target**: < 50ms end-to-end for drift scoring
- **Components**:
  - SentenceTransformer: ~20ms
  - Feature extraction: ~5ms
  - MLP inference: ~10ms
  - Network overhead: ~15ms

### Scalability

- **Concurrent Requests**: Supports multiple simultaneous drift computations
- **Model Caching**: SentenceTransformer and MLP models cached in memory
- **Thread Pool**: Asynchronous processing for I/O operations

### Monitoring

- **Metrics**: Processing time, success rate, model performance
- **Logging**: Detailed logs for debugging and optimization
- **Health Checks**: Service availability and model status

## Configuration

### Environment Variables

```bash
# OCPSValve configuration
OCPS_DRIFT_THRESHOLD=0.5  # Escalation threshold

# ML Service configuration
SEEDCORE_MODEL_PATH=/app/models  # Model storage path
SEEDCORE_NS=seedcore-dev  # Ray namespace

# Performance tuning
COORDINATOR_NUM_CPUS=0.2  # CPU allocation
ML_SERVICE_TIMEOUT=8      # ML service timeout
```

### Model Configuration

```python
# DriftDetector parameters
model_name = "all-MiniLM-L6-v2"  # SentenceTransformer model
input_dim = 768                   # Embedding dimension
hidden_dim = 128                  # MLP hidden layer size
device = "cuda" if available else "cpu"
```

## Testing

### Performance Tests

**Location**: `tests/test_drift_detector_performance.py`

**Test Cases**:
- Latency requirements (< 50ms)
- Text length scaling
- Concurrent request handling
- End-to-end pipeline testing

**Running Tests**:
```bash
pytest tests/test_drift_detector_performance.py -v
```

### Integration Tests

**Test Scenarios**:
- ML service drift scoring
- Coordinator service integration
- Predicate system routing
- Error handling and fallbacks

## Migration Guide

### From Ad-hoc Drift Scoring

1. **Remove** `drift_score` fields from Task models
2. **Update** task creation to exclude drift scores
3. **Verify** ML service is available and healthy
4. **Test** fallback behavior when ML service is unavailable

### Backward Compatibility

- **Graceful Degradation**: System continues to function with fallback scoring
- **Circuit Breakers**: Prevent cascading failures
- **Monitoring**: Track drift detector availability and performance

## Troubleshooting

### Common Issues

1. **High Latency**: Check model loading and GPU availability
2. **Memory Issues**: Monitor SentenceTransformer model size
3. **Network Timeouts**: Verify ML service connectivity
4. **Model Loading Failures**: Check model file paths and permissions

### Debugging

1. **Enable Debug Logging**: Set log level to DEBUG
2. **Check Performance Stats**: Use `get_performance_stats()` method
3. **Monitor Circuit Breakers**: Check service health endpoints
4. **Verify Model Status**: Check ML service health endpoint

## Future Enhancements

### Planned Improvements

1. **Model Training**: Online learning for drift detection
2. **Feature Engineering**: Additional runtime metrics
3. **Ensemble Methods**: Multiple drift detectors
4. **Adaptive Thresholds**: Dynamic threshold adjustment

### Research Directions

1. **Novelty Detection**: Beyond drift detection
2. **Causal Analysis**: Understanding drift causes
3. **Predictive Drift**: Anticipating future drift
4. **Multi-modal Detection**: Beyond text and metrics

---

*This document provides a comprehensive guide to the Neural-CUSUM drift detection pipeline implementation. For questions or issues, please refer to the troubleshooting section or contact the development team.*
