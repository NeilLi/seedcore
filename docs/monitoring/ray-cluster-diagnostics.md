# Ray Cluster Diagnostics Guide

## Overview

This document provides comprehensive guidance for diagnosing and analyzing Ray clusters, including job scheduling, management, and troubleshooting procedures.

## Prerequisites

- Docker and Docker Compose installed
- Access to the SeedCore project directory
- Basic understanding of Ray distributed computing

## Quick Start

### 1. Check Ray Cluster Status

```bash
# Navigate to the docker directory
cd docker

# Check if containers are running
docker compose ps

# Check Ray dashboard (accessible externally)
curl http://localhost:8265/#/jobs
```

### 2. Basic Cluster Information

```bash
# Check Ray version and cluster resources
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
print('Ray Version:', ray.__version__)
print('Cluster Resources:', ray.cluster_resources())
print('Available Resources:', ray.available_resources())
"
```

## Detailed Diagnostics

### Container-Based Analysis

Since Ray runs in Docker containers, all diagnostic scripts must be executed within the appropriate containers:

```bash
# Copy diagnostic scripts to containers
docker cp monitor_actors.py seedcore-api:/tmp/
docker cp check_ray_version.py seedcore-api:/tmp/

# Execute from within the container
docker exec -it seedcore-api python3 /tmp/monitor_actors.py
docker exec -it seedcore-api python3 /tmp/check_ray_version.py
```

### Job Analysis

#### Understanding Ray Jobs

Ray jobs represent different components of the distributed system:

1. **Cluster Initialization Jobs** (e.g., Job `30000000`)
   - Scheduled by: Docker Compose (`ray-head` service)
   - Purpose: Initialize Ray cluster
   - Status: Should complete successfully

2. **Application Server Jobs** (e.g., Job `2f000000`)
   - Scheduled by: Docker Compose (`seedcore-api` service)
   - Purpose: Run FastAPI server
   - Status: Should run continuously

3. **COA Initialization Jobs** (e.g., Job `2e000000`)
   - Scheduled by: OrganismManager
   - Purpose: Initialize COA organs and agents
   - Status: Should complete successfully

#### Job Management Hierarchy

```
Docker Compose (Master Scheduler)
├── Ray Head Node (Cluster Management)
│   ├── Dashboard (Port 8265)
│   ├── Redis (Port 6379)
│   └── Job Distribution
├── FastAPI Server (Application Layer)
│   ├── HTTP Endpoints
│   ├── OrganismManager
│   └── Task Execution
└── Ray Workers (Distributed Processing)
    ├── Agent Computations
    └── Task Execution
```

### Actor Analysis

#### Core System Actors

The system maintains several singleton Ray actors:

- **MissTracker**: Tracks missed operations
- **SharedCache**: Shared memory cache
- **MwStore**: Memory weight storage

#### COA Organ Actors

- **cognitive_organ_1**: Handles reasoning and planning
- **actuator_organ_1**: Executes actions and API interactions
- **utility_organ_1**: Manages memory and system tasks

### Resource Monitoring

#### Cluster Resources

```python
# Get cluster resource information
cluster_resources = ray.cluster_resources()
available_resources = ray.available_resources()

print(f"Total CPU: {cluster_resources.get('CPU', 0)}")
print(f"Used CPU: {cluster_resources.get('CPU', 0) - available_resources.get('CPU', 0)}")
print(f"Total Memory: {cluster_resources.get('memory', 0) / (1024**3):.2f} GB")
```

#### Node Information

```python
# Get node information
nodes = ray.nodes()
for node in nodes:
    print(f"Node: {node['NodeID']}")
    print(f"  - State: {node['Alive']}")
    print(f"  - Resources: {node['Resources']}")
```

## Troubleshooting

### Common Issues

1. **Ray State API Limitations**
   - Older Ray versions may not support all state API methods
   - Use alternative methods: `ray.cluster_resources()`, `ray.nodes()`

2. **Container Access Issues**
   - Ensure scripts are copied to containers before execution
   - Use `docker exec` for container-based execution

3. **Job Status Confusion**
   - Running jobs are normal for continuous services
   - Only initialization jobs should complete and exit

### Diagnostic Scripts

#### monitor_actors.py
- Lists all active Ray actors
- Shows actor types and status
- Identifies COA organs and agents

#### check_ray_version.py
- Verifies Ray and Python versions
- Confirms cluster connectivity
- Basic health check

#### comprehensive_job_analysis.py
- Detailed cluster analysis
- Resource utilization
- Actor status verification
- API endpoint testing

## Best Practices

1. **Always use container-based execution** for Ray diagnostics
2. **Check job context** before assuming issues
3. **Understand the job lifecycle** - some jobs should run continuously
4. **Use appropriate diagnostic tools** for different analysis needs
5. **Monitor resource utilization** regularly

## Integration with COA

The Ray cluster diagnostics are particularly important for the Cognitive Organism Architecture (COA):

- **Organs**: Ray actors managing agent pools
- **Agents**: Ray actors with private memory and performance tracking
- **OrganismManager**: Central coordinator for organ and agent lifecycle

### COA-Specific Diagnostics

```python
# Check COA organ status
from src.seedcore.organs import organism_manager

status = await organism_manager.get_organism_status()
print(f"Organs: {status['organs']}")
print(f"Agents: {status['total_agents']}")
```

## Monitoring and Alerts

### Key Metrics to Monitor

1. **Cluster Resources**: CPU and memory utilization
2. **Job Status**: Success/failure rates
3. **Actor Health**: Organ and agent status
4. **API Response**: Endpoint availability

### Dashboard Access

- **Ray Dashboard**: External access for cluster monitoring
- **Grafana**: Metrics visualization
- **Prometheus**: Metrics collection

## Conclusion

Ray cluster diagnostics provide essential insights into the distributed computing infrastructure. Understanding job scheduling, management, and troubleshooting procedures ensures reliable operation of the SeedCore system.

For more information, refer to:
- [Ray Documentation](https://docs.ray.io/)
- [COA Implementation Guide](../coa-implementation-guide.md)
- [Docker Compose Configuration](../docker/docker-compose.yml) 