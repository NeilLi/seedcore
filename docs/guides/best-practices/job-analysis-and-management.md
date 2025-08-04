# Ray Job Analysis and Management Guide

## Overview

This document provides comprehensive guidance for analyzing and managing Ray jobs in the SeedCore system, including job scheduling, management responsibilities, and troubleshooting procedures.

## Job Types and Responsibilities

### 1. Cluster Initialization Jobs

**Example**: Job `30000000` (SUCCEEDED)

- **Scheduled by**: Docker Compose (`ray-head` service)
- **Managed by**: Ray head node
- **Entrypoint**: `ray start --head` command
- **Purpose**: Initialize Ray cluster, start Redis, launch dashboard
- **Expected Status**: Should complete successfully and exit
- **Duration**: Typically 5-30 seconds

**Configuration**:
```yaml
# docker-compose.yml
ray-head:
  command: >
    ray start --head
              --dashboard-host 0.0.0.0
              --dashboard-port 8265
              --port=6379
              --include-dashboard true
              --metrics-export-port=8080
              --num-cpus 1
              --block
```

### 2. Application Server Jobs

**Example**: Job `2f000000` (RUNNING)

- **Scheduled by**: Docker Compose (`seedcore-api` service)
- **Managed by**: FastAPI server (uvicorn)
- **Entrypoint**: `uvicorn src.seedcore.telemetry.server:app --host 0.0.0.0 --port 8000 --reload`
- **Purpose**: Run the main COA application server
- **Expected Status**: Should run continuously
- **Duration**: Continuous (until container stops)

**Configuration**:
```yaml
# docker-compose.yml
seedcore-api:
  command: uvicorn src.seedcore.telemetry.server:app --host 0.0.0.0 --port 8000 --reload
```

### 3. COA Initialization Jobs

**Example**: Job `2e000000` (SUCCEEDED)

- **Scheduled by**: OrganismManager (during FastAPI startup)
- **Managed by**: OrganismManager
- **Entrypoint**: COA organism initialization
- **Purpose**: Create and distribute COA organs and agents
- **Expected Status**: Should complete successfully
- **Duration**: Typically 10-60 seconds

**Code Path**:
```python
# src/seedcore/telemetry/server.py
@app.on_event("startup")
async def startup_event():
    # Initialize Ray
    ray.init(address="ray://ray-head:10001", namespace="seedcore")
    
    # Initialize COA organism
    await organism_manager.initialize_organism()
```

## Job Management Hierarchy

```
Docker Compose (Master Scheduler)
├── ray-head service
│   ├── Job 30000000: Ray cluster initialization
│   ├── Dashboard (Port 8265)
│   ├── Redis (Port 6379)
│   └── Job distribution and management
├── seedcore-api service
│   ├── Job 2f000000: FastAPI server (RUNNING)
│   ├── Job 2e000000: COA initialization (SUCCEEDED)
│   ├── HTTP endpoints (Port 8000)
│   ├── OrganismManager
│   └── Task execution coordination
└── ray-worker services (ray-workers.yml)
    ├── 3 worker nodes
    ├── Distributed task execution
    └── Agent computations
```

## Job Lifecycle Analysis

### Startup Sequence

1. **Docker Compose starts containers**
   ```bash
   docker compose up -d
   ```

2. **Ray head initializes** (Job 30000000)
   - Starts Ray cluster
   - Launches Redis server
   - Starts dashboard
   - Job completes successfully

3. **FastAPI server starts** (Job 2f000000)
   - Initializes Ray client connection
   - Starts uvicorn server
   - Job continues running

4. **COA organism initializes** (Job 2e000000)
   - Creates organ actors
   - Distributes agents
   - Job completes successfully

5. **System ready for operation**
   - Job 2f000000 continues running
   - Organs and agents available
   - API endpoints active

### Job Status Interpretation

#### ✅ SUCCEEDED Jobs
- **Expected for**: Initialization jobs
- **Examples**: Job 30000000, Job 2e000000
- **Action**: No action needed - normal completion

#### 🔄 RUNNING Jobs
- **Expected for**: Continuous service jobs
- **Examples**: Job 2f000000 (FastAPI server)
- **Action**: Monitor for unexpected termination

#### ❌ FAILED Jobs
- **Unexpected for**: Any job type
- **Action**: Investigate logs and restart if necessary

## Job Scheduling Analysis

### Docker Compose as Master Scheduler

Docker Compose manages the entire job ecosystem:

```yaml
# Primary services and their job responsibilities
services:
  ray-head:
    # Schedules: Ray cluster initialization
    # Manages: Cluster resources, dashboard, Redis
    
  seedcore-api:
    # Schedules: FastAPI server, COA initialization
    # Manages: HTTP endpoints, organism lifecycle
    
  ray-worker:
    # Schedules: Distributed task execution
    # Manages: Agent computations, workload distribution
```

### Ray Head Node Management

The Ray head node provides:

- **Job Distribution**: Routes tasks to appropriate workers
- **Resource Management**: Tracks CPU, memory, and GPU usage
- **Dashboard**: Web UI for monitoring (Port 8265)
- **Redis**: Internal state management (Port 6379)

### FastAPI Server Management

The FastAPI server coordinates:

- **HTTP Endpoints**: API access for external clients
- **OrganismManager**: COA lifecycle management
- **Task Execution**: Routes requests to appropriate organs
- **Health Monitoring**: System status and metrics

## Diagnostic Procedures

### 1. Job Status Check

```bash
# Check Ray dashboard
curl http://localhost:8265/#/jobs

# Check current job ID
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
print('Current Job ID:', ray.get_runtime_context().get_job_id())
"
```

### 2. Container Status Check

```bash
# Check container status
docker compose ps

# Check container logs
docker compose logs ray-head
docker compose logs seedcore-api
```

### 3. Resource Utilization

```bash
# Check cluster resources
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
print('Cluster Resources:', ray.cluster_resources())
print('Available Resources:', ray.available_resources())
"
```

### 4. Actor Status Check

```bash
# Check COA organs
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')

organs = ['cognitive_organ_1', 'actuator_organ_1', 'utility_organ_1']
for organ in organs:
    try:
        actor = ray.get_actor(organ)
        print(f'✅ {organ}: Active')
    except:
        print(f'❌ {organ}: Not Found')
"
```

## Troubleshooting Guide

### Common Job Issues

#### 1. Job Stuck in RUNNING State

**Symptoms**: Job appears to be running but system is unresponsive

**Diagnosis**:
```bash
# Check container logs
docker compose logs seedcore-api

# Check Ray cluster status
docker exec -it seedcore-api python3 -c "
import ray
ray.init(address='ray://ray-head:10001', namespace='seedcore')
print('Ray Status:', ray.is_initialized())
"
```

**Solutions**:
- Restart the specific container: `docker compose restart seedcore-api`
- Check for resource constraints
- Verify network connectivity

#### 2. Job Failed During Initialization

**Symptoms**: Job shows FAILED status

**Diagnosis**:
```bash
# Check detailed logs
docker compose logs ray-head
docker compose logs seedcore-api

# Check configuration
docker exec -it seedcore-api cat /app/src/seedcore/config/defaults.yaml
```

**Solutions**:
- Fix configuration issues
- Check for missing dependencies
- Verify Ray cluster connectivity

#### 3. Organs Not Created

**Symptoms**: COA organs not available

**Diagnosis**:
```bash
# Check organ status
curl -X GET "http://localhost:8000/organism/status"

# Check OrganismManager logs
docker compose logs seedcore-api | grep -i organ
```

**Solutions**:
- Restart COA initialization: `curl -X POST "http://localhost:8000/organism/initialize"`
- Use cleanup script for fresh start
- Check Ray actor creation permissions

### Advanced Troubleshooting

#### Complete System Reset

```bash
# Stop all services
docker compose down

# Clean up Ray actors (if needed)
docker cp cleanup_organs.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/cleanup_organs.py

# Restart services
docker compose up -d

# Verify system health
docker exec -it seedcore-api python3 /tmp/comprehensive_job_analysis.py
```

#### Performance Monitoring

```bash
# Monitor resource usage
docker stats

# Check Ray metrics
curl http://localhost:8265/api/cluster

# Monitor API performance
curl -X GET "http://localhost:8000/organism/status" -w "@curl-format.txt"
```

## Best Practices

### 1. Job Monitoring

- **Regular Status Checks**: Monitor job status daily
- **Resource Monitoring**: Track CPU and memory usage
- **Log Analysis**: Review logs for errors and warnings
- **Performance Metrics**: Monitor response times and throughput

### 2. Job Management

- **Graceful Shutdown**: Implement proper shutdown procedures
- **Error Recovery**: Handle job failures gracefully
- **Resource Limits**: Set appropriate resource constraints
- **Backup Procedures**: Maintain system state backups

### 3. Documentation

- **Job Documentation**: Document all job types and purposes
- **Troubleshooting Guides**: Maintain up-to-date troubleshooting procedures
- **Configuration Management**: Version control all configuration files
- **Change Logging**: Log all system changes and updates

## Monitoring and Alerts

### Key Metrics

1. **Job Success Rate**: Percentage of successful job completions
2. **Job Duration**: Time taken for job completion
3. **Resource Utilization**: CPU, memory, and network usage
4. **Error Rates**: Frequency of job failures
5. **Response Times**: API endpoint response times

### Alert Thresholds

- **Job Failure Rate**: > 5% of jobs failing
- **Resource Utilization**: > 80% CPU or memory usage
- **Response Time**: > 5 seconds for API calls
- **Organ Availability**: Any organ not responding

### Dashboard Access

- **Ray Dashboard**: `http://localhost:8265`
- **Grafana**: `http://localhost:3000`
- **Prometheus**: `http://localhost:9090`

## Conclusion

Understanding Ray job scheduling and management is crucial for maintaining a healthy SeedCore system. The hierarchical management structure ensures proper coordination between different system components while providing clear separation of responsibilities.

For more information, refer to:
- [Ray Cluster Diagnostics](./ray-cluster-diagnostics.md)
- [COA Implementation Guide](./coa-implementation-guide.md)
- [Docker Compose Configuration](../docker/docker-compose.yml)
- [Ray Documentation](https://docs.ray.io/) 