# Agent Distribution Analysis Guide

## Overview

This guide explains how to analyze how agents are distributed across Ray workers in the SeedCore system. Understanding agent distribution helps optimize performance and resource utilization.

## Quick Analysis Commands

### 1. Basic Agent Distribution Analysis

```bash
# Navigate to docker directory
cd docker

# Run the analysis script
docker cp ../scripts/analyze_agent_distribution.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/analyze_agent_distribution.py
```

### 2. Detailed Agent Placement Analysis

```bash
# Run detailed placement analysis
docker cp ../scripts/detailed_agent_placement.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/detailed_agent_placement.py
```

### 3. Manual Analysis Commands

```bash
# Check cluster resources
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
print('Cluster Resources:', ray.cluster_resources())
print('Available Resources:', ray.available_resources())
print('Nodes:', len(ray.nodes()))
"

# Check COA organs
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
organs = ['cognitive_organ_1', 'actuator_organ_1', 'utility_organ_1']
for organ in organs:
    try:
        actor = ray.get_actor(organ)
        status = ray.get(actor.get_status.remote())
        print(f'{organ}: {status.get(\"agent_count\", 0)} agents')
    except:
        print(f'{organ}: Not found')
"
```

## Current Agent Distribution

Based on the analysis, here's the current distribution:

### Cluster Structure
- **Head Node**: 1 (Ray cluster management)
- **Worker Nodes**: 3 (Agent computation)
- **Total Agents**: 3

### Agent Distribution
```
COA Organs:
├── cognitive_organ_1: 1 agent (cognitive_organ_1_agent_0)
├── actuator_organ_1: 1 agent (actuator_organ_1_agent_0)
└── utility_organ_1: 1 agent (utility_organ_1_agent_0)

Distribution Pattern: Concentrated (1 agent per worker average)
```

### Node Details
- **Node 1 (Head)**: Ray cluster management, dashboard, Redis
- **Node 2 (Worker)**: Available for agent computation
- **Node 3 (Worker)**: Available for agent computation  
- **Node 4 (Worker)**: Available for agent computation

## Analysis Methods

### 1. Ray Python API Analysis

The most reliable method uses Ray's Python API:

```python
import ray

# Initialize Ray
ray.init(address="ray://ray-head:10001", namespace="seedcore")

# Get cluster information
cluster_resources = ray.cluster_resources()
available_resources = ray.available_resources()
nodes = ray.nodes()

# Analyze organs
organ_actors = ["cognitive_organ_1", "actuator_organ_1", "utility_organ_1"]
for organ_name in organ_actors:
    try:
        actor = ray.get_actor(organ_name)
        status = ray.get(actor.get_status.remote())
        print(f"{organ_name}: {status.get('agent_count', 0)} agents")
    except:
        print(f"{organ_name}: Not found")
```

### 2. API-based Analysis

Use the SeedCore API endpoints:

```bash
# Check organism status
curl http://localhost:8002/organism/status

# Check Tier 0 agents
curl http://localhost:8002/tier0/summary

# Check specific organ
curl http://localhost:8002/organism/organs/cognitive_organ_1
```

### 3. Ray Dashboard Analysis

Access the Ray dashboard at `http://localhost:8265`:

- **Cluster Tab**: Shows all nodes and their status
- **Actors Tab**: Shows all actors and their placement
- **Jobs Tab**: Shows job distribution across nodes

### 4. Container-based Analysis

Since Ray runs in containers, analyze from within:

```bash
# Access Ray head container
docker exec -it ray-head bash

# Check Ray processes
ps aux | grep ray

# Check Ray logs
tail -f /tmp/ray/session_latest/logs/raylet.out
```

## Distribution Patterns

### 1. Concentrated Distribution
- **Pattern**: Agents clustered on few workers
- **Current State**: 1 agent per worker average
- **Benefits**: Reduced communication overhead
- **Drawbacks**: Potential resource underutilization

### 2. Balanced Distribution
- **Pattern**: Agents evenly spread across workers
- **Benefits**: Better resource utilization
- **Drawbacks**: Increased communication overhead

### 3. Distributed Distribution
- **Pattern**: Many agents per worker
- **Benefits**: High resource utilization
- **Drawbacks**: Potential resource contention

## Optimization Recommendations

### Current State Analysis
- **CPU Utilization**: Low (0.0/4.0 cores used)
- **Agent Distribution**: Concentrated
- **Worker Utilization**: Underutilized

### Optimization Strategies

#### 1. Scale Agents
```bash
# Create more agents for better distribution
curl -X POST http://localhost:8002/tier0/agents/create \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test_agent_1", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}}'
```

#### 2. Scale Workers
```bash
# Add more worker nodes
cd docker
./ray-workers.sh scale 5
```

#### 3. Monitor Performance
```bash
# Check resource utilization
docker stats

# Monitor Ray dashboard
open http://localhost:8265
```

## Troubleshooting

### Common Issues

#### 1. Agents Not Found
```bash
# Check if organism is initialized
curl http://localhost:8002/organism/status

# Reinitialize if needed
curl -X POST http://localhost:8002/organism/initialize
```

#### 2. Workers Not Available
```bash
# Check worker status
cd docker
./ray-workers.sh status

# Restart workers if needed
./ray-workers.sh restart
```

#### 3. Dashboard Not Accessible
```bash
# Check Ray head status
docker compose ps ray-head

# Check Ray head logs
docker compose logs ray-head
```

## Monitoring and Alerts

### Key Metrics to Monitor
1. **Agent Distribution**: Number of agents per worker
2. **CPU Utilization**: Per worker and cluster-wide
3. **Memory Usage**: Per worker and cluster-wide
4. **Agent Performance**: Success rates and response times
5. **Worker Health**: Node status and connectivity

### Alert Thresholds
- **CPU Utilization**: > 80% per worker
- **Memory Usage**: > 85% per worker
- **Agent Failures**: > 5% failure rate
- **Worker Failures**: Any worker down

## Best Practices

### 1. Regular Monitoring
- Run distribution analysis daily
- Monitor resource utilization
- Track agent performance metrics

### 2. Balanced Scaling
- Scale agents and workers together
- Maintain reasonable agent-to-worker ratios
- Monitor for resource contention

### 3. Performance Optimization
- Distribute agents based on workload
- Monitor communication patterns
- Optimize agent placement algorithms

### 4. Documentation
- Document distribution patterns
- Track optimization changes
- Maintain performance baselines

## Conclusion

Understanding agent distribution is crucial for optimizing SeedCore performance. Regular analysis helps identify bottlenecks and opportunities for improvement. Use the provided tools and methods to maintain optimal agent distribution across your Ray cluster. 