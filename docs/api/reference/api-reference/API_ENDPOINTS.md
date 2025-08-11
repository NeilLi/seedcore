# SeedCore API Endpoints

## Overview

This document describes all available API endpoints in the SeedCore system, with a focus on the enhanced endpoints that provide real data from the Energy Model Foundation.

## Base URLs

- Main API (energy, system): `http://localhost:8002`
- Ray Serve ML (XGBoost, salience): `http://localhost:8000`

## Energy System Endpoints

### 1. Energy Gradient (`GET /energy/gradient`) — API 8002

**Description**: Enhanced endpoint that provides real energy data from the Energy Model Foundation.

**Features**:
- Real-time energy calculations using Tier0 Ray agents
- Automatic agent creation if none exist
- Comprehensive energy terms breakdown
- Real-time metrics and agent summaries

Notes:
- Telemetry constructs unified state via `build_unified_state(...)` and reads `E_patterns` from the HGNN shim.
- Energy terms are sourced from `EnergyLedger().terms` for compatibility.

**Response Example**:
```json
{
  "ts": 1753772601.6301455,
  "E_terms": {
    "pair": 0,
    "hyper": 0.0,
    "entropy": -0.3365784271677832,
    "reg": 3.7395735430183175,
    "mem": 0.0,
    "total": 3.4029951158505343
  },
  "deltaE_last": 0.0,
  "pair_stats_count": 2,
  "hyper_stats_count": 0,
  "role_entropy_count": 0,
  "mem_stats_count": 0,
  "real_time_metrics": {
    "active_agents": 3,
    "total_agents": 3,
    "memory_utilization": 0.0,
    "compression_knob": 0.5,
    "last_energy_update": 1753772601.6302235
  },
  "agent_summaries": [
    {
      "agent_id": "explorer_1",
      "capability": 0.5,
      "mem_util": 0.0,
      "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1}
    }
  ]
}
```

### 2. Energy Monitor (`GET /energy/monitor`) — API 8002

**Description**: Real-time energy monitoring endpoint with detailed metrics.

**Features**:
- Comprehensive energy terms breakdown
- Memory metrics and utilization
- Detailed agent metrics with energy proxies
- System health indicators

Notes:
- Uses `EnergyLedger.terms` for term formatting; includes derived metrics and memory stats.

**Response Example**:
```json
{
  "timestamp": 1753772612.8688385,
  "energy_terms": {
    "pair": 0,
    "hyper": 0.0,
    "entropy": -0.3365784271677832,
    "reg": 3.7064795404586555,
    "mem": 0.0,
    "total": 3.3699011132908723
  },
  "memory_metrics": {
    "cost_vq": 0.0,
    "bytes_used_kb": 0.0,
    "hit_count": 0,
    "compression_ratio": 0.5
  },
  "agent_metrics": {
    "total_agents": 3,
    "active_agents": 0,
    "avg_capability": 0.5,
    "avg_mem_util": 0.0,
    "agent_details": [
      {
        "agent_id": "monitor_explorer",
        "capability": 0.5,
        "mem_util": 0.0,
        "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1},
        "tasks_processed": 0,
        "success_rate": 0,
        "energy_proxy": {
          "capability": 0.5,
          "entropy_contribution": 0.9219280905592773,
          "mem_util": 0.0,
          "state_norm": 11.328928809310398
        },
        "last_heartbeat": 1753772612.8220115,
        "is_active": false
      }
    ]
  },
  "system_metrics": {
    "compression_knob": 0.5,
    "energy_slope": 0.0,
    "ray_initialized": true,
    "tier0_manager_available": true
  }
}
```

### 3. Energy Calibration (`GET /energy/calibrate`) — API 8002

**Description**: Energy calibration endpoint that runs synthetic tasks and returns calibration results.

**Features**:
- Automatic calibration agent creation
- Synthetic task execution
- Energy trend analysis
- Calibration quality assessment

**Response Example**:
```json
{
  "timestamp": 1753772633.1386566,
  "calibration_metrics": {
    "total_tasks": 8,
    "successful_tasks": 8,
    "final_energy": 0.07391075699644993,
    "energy_trend": 0.01117222790155356,
    "energy_range": {
      "min": 0.0506986747640152,
      "max": 0.08903937022543751
    },
    "trend_direction": "increasing",
    "calibration_quality": "needs_adjustment"
  },
  "energy_history": [
    {
      "task_num": 1,
      "energy": 0.06273852909489637,
      "timestamp": 1753772632.7828085
    }
  ],
  "task_results": [
    {
      "task_id": "calibration_task_0",
      "agent_id": "cal_balanced",
      "success": true,
      "energy": 0.06273852909489637
    }
  ],
  "agent_summary": {
    "total_agents": 3,
    "active_agents": 3,
    "agent_ids": ["cal_explorer", "cal_specialist", "cal_balanced"]
  }
}
```

### 4. Energy Health Check (`GET /healthz/energy`) — API 8002

**Description**: Health check endpoint for energy system readiness.

**Features**:
- System health status
- Energy calculation verification
- Agent metrics
- Comprehensive health checks

**Response Example**:
```json
{
  "status": "healthy",
  "message": "Energy system operational",
  "timestamp": 1753772640.4381404,
  "energy_snapshot": {
    "ts": 1753772640.4380822,
    "E_terms": {
      "pair": 0.0,
      "hyper": 0.0,
      "entropy": 0.0,
      "reg": 0.0,
      "mem": 0.0,
      "total": 0.0
    },
    "deltaE_last": 0.0,
    "pair_stats_count": 0,
    "hyper_stats_count": 0,
    "role_entropy_count": 0,
    "mem_stats_count": 0
  },
  "agent_metrics": {
    "total_agents": 0,
    "active_agents": 0,
    "avg_capability": 0.0,
    "avg_mem_util": 0.0
  },
  "checks": {
    "energy_calculation": "pass",
    "ledger_accessible": "pass",
    "ray_connection": "pass",
    "tier0_manager": "pass",
    "pair_stats_count": 0,
    "hyper_stats_count": 0,
    "role_entropy_count": 0,
    "mem_stats_count": 0
  }
}
```

## System Status Endpoints

### 5. System Status (`GET /system/status`) — API 8002

**Description**: Returns the current status of the persistent system with real data.

**Features**:
- Comprehensive system information
- Agent statistics (Tier0 and legacy)
- Energy system status
- Memory system metrics
- Performance indicators

**Response Example**:
```json
{
  "system_info": {
    "timestamp": 1753772620.3950813,
    "version": "1.0.0",
    "status": "operational"
  },
  "agents": {
    "tier0_agents": 0,
    "legacy_agents": 3,
    "total_agents": 3,
    "agent_details": []
  },
  "organs": [
    {
      "id": "cognitive_organ_1",
      "agent_count": 3
    }
  ],
  "energy_system": {
    "energy_state": {
      "ts": 1753772620.3950133,
      "E_terms": {
        "pair": 0.0,
        "hyper": 0.0,
        "entropy": 0.0,
        "reg": 0.0,
        "mem": 0.0,
        "total": 0.0
      },
      "deltaE_last": 0.0,
      "pair_stats_count": 0,
      "hyper_stats_count": 0,
      "role_entropy_count": 0,
      "mem_stats_count": 0
    },
    "compression_knob": 0.5,
    "cost_vq": 0.0,
    "energy_slope": 0.0
  },
  "memory_system": {
    "Mw": {
      "bytes_used": 0,
      "max_capacity": 100,
      "hit_count": 0,
      "data_count": 0
    },
    "Mlt": {
      "bytes_used": 0,
      "max_capacity": 1000,
      "hit_count": 0,
      "data_count": 0
    },
    "total_bytes": 0,
    "total_hits": 0,
    "compression_knob": 0.5,
    "cost_vq": 0.0,
    "energy_slope": 0.0
  },
  "pair_stats": {},
  "performance_metrics": {
    "memory_utilization_kb": 0.0,
    "hit_rate": 0.0,
    "compression_efficiency": 0.5,
    "active_agents": 0
  }
}
```

### 6. Agents State (`GET /tier0/agents/state`) — API 8002

**Description**: Returns the current state of all agents in the simulation with real data.

**Features**:
- Tier0 Ray agents and legacy organ agents
- Auto-discovers detached, named `RayAgent` actors already running in the Ray cluster and attaches them into the manager registry
- Optional environment-driven attachment via `TIER0_ATTACH_ACTORS` (comma/space/semicolon-separated names) and `RAY_NAMESPACE`
- Comprehensive agent metrics
- Energy state information
- Performance statistics

**Response Example**:
```json
{
  "agents": [
    {
      "id": "explorer_1",
      "type": "tier0_ray_agent",
      "capability": 0.5,
      "mem_util": 0.0,
      "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1},
      "state_embedding": [0.1, 0.2, 0.3, ...],
      "memory_writes": 0,
      "memory_hits_on_writes": 0,
      "salient_events_logged": 0,
      "total_compression_gain": 0.0,
      "tasks_processed": 0,
      "success_rate": 0.0,
      "avg_quality": 0.0,
      "peer_interactions": 0,
      "last_heartbeat": 1753772601.6302235,
      "energy_state": {},
      "created_at": 1753772601.6302235
    }
  ],
  "summary": {
    "total_agents": 3,
    "tier0_agents": 3,
    "legacy_agents": 0,
    "active_agents": 3,
    "timestamp": 1753772601.6302235
  }
}
```

## Legacy Endpoints

### 7. Basic Health Check (`GET /health`) — API 8002

**Description**: Basic health check endpoint.

### 8. Metrics (`GET /metrics`) — API 8002

**Description**: Prometheus metrics endpoint.

### 9. Ray Status (`GET /ray/status`) — API 8002

## ML (Ray Serve) Endpoints — Port 8000

### 10. XGBoost Promote (`POST /xgboost/promote`)

Transactional, gated promotion with ΔE guard and runtime contractivity audit via `/energy/meta`.

Request:

```bash
curl -sS -X POST http://localhost:8000/xgboost/promote \
  -H 'Content-Type: application/json' \
  -d '{"model_path":"/app/docker/artifacts/models/docker_test_model/model.xgb","delta_E":-0.05}'
```

Response (example):

```json
{
  "accepted": true,
  "current_model_path": "/app/docker/artifacts/models/docker_test_model/model.xgb",
  "meta": { "L_tot": 0.0, "cap": 0.98, "ok_for_promotion": true }
}
```

### 11. XGBoost Train/Infer/Manage

- `POST /xgboost/train`
- `POST /xgboost/predict`
- `POST /xgboost/batch_predict`
- `POST /xgboost/load_model`
- `GET /xgboost/list_models`
- `GET /xgboost/model_info`
- `DELETE /xgboost/delete_model`
- `POST /xgboost/tune`
- `POST /xgboost/refresh_model` (now includes pre/post `/energy/meta` gate)

**Description**: Ray cluster status information.

## Usage Examples

### Testing Energy System (API 8002)

```bash
# Get real-time energy data
curl http://localhost:8002/energy/gradient

# Monitor energy system
curl http://localhost:8002/energy/monitor

# Run energy calibration
curl http://localhost:8002/energy/calibrate

# Check energy system health
curl http://localhost:8002/healthz/energy
```

### System Monitoring (API 8002)

```bash
# Get comprehensive system status
curl http://localhost:8002/system/status

# Get all agent states
curl http://localhost:8002/tier0/agents/state

# Basic health check
curl http://localhost:8002/health
```

### Data Analysis

```bash
# Get formatted JSON output
curl http://localhost:80/energy/gradient | jq .

# Monitor specific metrics
curl http://localhost:80/energy/monitor | jq '.energy_terms'

# Check agent capabilities
curl http://localhost:80/agents/state | jq '.agents[].capability'
```

## Error Handling

All endpoints return appropriate HTTP status codes:

- `200 OK`: Successful response
- `400 Bad Request`: Invalid request parameters
- `500 Internal Server Error`: Server-side error

Error responses include:
```json
{
  "error": "Error description",
  "timestamp": 1753772601.6302235,
  "status": "error"
}
```

## Real Data Features

### Energy Model Foundation Integration

All enhanced endpoints now provide real data from:

1. **Tier0 Ray Agents**: Real Ray actors with state tracking
2. **Energy Calculations**: Actual energy terms using the Unified Energy Function
3. **Memory System**: Real memory utilization and metrics
4. **Agent Performance**: Live capability scores and task statistics
5. **System Health**: Real-time health monitoring

### Automatic Agent Creation and Discovery

Endpoints automatically create demonstration agents if none exist; the Tier0 manager will also attempt to discover existing `RayAgent` actors in the cluster:
- Explorer agents (high exploration probability)
- Specialist agents (high specialization probability)
- Balanced agents (mixed role probabilities)

### Real-Time Updates

All data is fetched in real-time:
- Agent heartbeats and state
- Energy calculations
- Memory system metrics
- Performance statistics

## Performance Considerations

- **Caching**: Some endpoints cache data for performance
- **Rate Limiting**: Consider implementing rate limiting for high-frequency requests
- **Error Recovery**: Endpoints gracefully handle Ray connection issues
- **Fallback Data**: Provides fallback data when real data is unavailable

## Future Enhancements

1. **WebSocket Support**: Real-time streaming of energy data
2. **Historical Data**: Energy trend analysis over time
3. **Custom Queries**: Filtering and aggregation capabilities
4. **Authentication**: Secure access to sensitive system data
5. **Rate Limiting**: Protection against excessive requests 