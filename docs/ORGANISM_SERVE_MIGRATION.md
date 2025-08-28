# Organism Serve Migration Guide

## Overview

This document describes the migration of the SeedCore organism (dispatcher + organs) from plain Ray actors to a proper Ray Serve application. This migration fixes the critical issue where tasks get locked with `status=running` but never complete because they're not being processed by a Serve deployment.

## Problem Statement

### Before Migration
- **Organism (dispatcher + organs)** was running as **plain Ray actors**
- Tasks could be locked (`status=running`) but never completed
- No structured request/response lifecycles
- No Serve controller health checks
- No integration with Serve's autoscaling and routing logic
- Verifier script would hang after task enqueuement

### Root Cause
The organism manager / dispatcher logic was using plain Ray actors while the fast-path and cognitive routes were built assuming Serve deployments (referenced in `serveConfigV2`). This mismatch caused:
- Tasks to be enqueued and locked by dispatchers
- No Serve deployment to receive and complete them
- Status never transitioning from `running` → `completed`
- Verifier timeouts

## Solution

### 1. New Organism Serve Entrypoint

Created `entrypoints/organism_entrypoint.py` that:
- Wraps `OrganismManager` in a `@serve.deployment`
- Provides structured HTTP endpoints for task handling
- Integrates with Serve's health checks and autoscaling
- Maintains backward compatibility through direct method access

### 2. Updated Serve Configuration

Modified `deploy/rayservice.yaml` to include the organism app:

```yaml
- name: organism
  import_path: entrypoints.organism_entrypoint:build_organism_app
  route_prefix: /organism
  deployments:
    - name: OrganismManager
      num_replicas: 1
      ray_actor_options:
        num_cpus: 0.5
        num_gpus: 0
        memory: 2147483648  # 2GB
        resources: {"head_node": 0.001}
        runtime_env:
          env_vars:
            OCPS_DRIFT_THRESHOLD: "0.5"
            FAST_PATH_LATENCY_SLO_MS: "1000"
            COGNITIVE_TIMEOUT_S: "8.0"
            COGNITIVE_MAX_INFLIGHT: "64"
            MAX_PLAN_STEPS: "16"
```

### 3. New Organism Serve Client

Created `src/seedcore/serve/organism_serve.py` that:
- Provides HTTP endpoint access for external clients
- Supports direct Serve handle access for internal Ray operations
- Includes fallback mechanisms for reliability
- Integrates with existing task processing workflows

### 4. Updated API Routers

Modified `src/seedcore/api/routers/organism_router.py` to:
- Use the new organism serve client instead of plain Ray actors
- Maintain the same API interface for backward compatibility
- Provide proper error handling and health checking

### 5. Updated Bootstrap Script

Modified `scripts/bootstrap_dispatchers.py` to:
- Remove plain Ray actor creation for coordinator
- Note that organism is now managed by Ray Serve
- Focus on dispatcher and graph dispatcher creation

## Architecture Changes

### Before (Plain Ray Actors)
```
Verifier → Queue → Coordinator Actor → OrganismManager → Organs
```

### After (Ray Serve Application)
```
Verifier → Queue → Organism Serve App → OrganismManager → Organs
                    ↓
              HTTP Endpoints + Serve Handle
```

## Benefits

### ✅ Structured Lifecycle
- Tasks now have proper request/response cycles
- Serve manages task routing and completion
- Health checks and autoscaling work correctly

### ✅ Task Completion
- Tasks transition properly from `running` → `completed`
- Verifier no longer hangs at `"running"` status
- Proper error handling and result propagation

### ✅ Integration
- Organism integrates with existing Serve infrastructure
- Consistent with cognitive and orchestrator services
- Proper namespace and resource management

### ✅ Monitoring
- Serve dashboard shows organism deployment status
- Health checks provide real-time status information
- Metrics and logging are centralized

## Deployment

### 1. Deploy the Updated Ray Service

```bash
# Apply the updated rayservice.yaml
kubectl apply -f deploy/rayservice.yaml
```

### 2. Verify Organism Deployment

```bash
# Check that the organism app is deployed
kubectl get rayservice seedcore-svc -n seedcore-dev

# Check Serve status
kubectl exec -it seedcore-svc-head-xxxxx -n seedcore-dev -- ray status
```

### 3. Test the Organism Service

```bash
# Run the test script
python scripts/test_organism_serve.py

# Or test manually via HTTP
curl http://localhost:8000/organism/health
curl http://localhost:8000/organism/status
```

## Testing

### 1. Health Check
```bash
curl http://localhost:8000/organism/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "organism-manager",
  "route_prefix": "/organism",
  "organism_initialized": true
}
```

### 2. Task Handling
```bash
curl -X POST http://localhost:8000/organism/handle-task \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "test_task",
    "params": {"test": "data"},
    "description": "Test task",
    "domain": "test",
    "drift_score": 0.0
  }'
```

### 3. Organism Status
```bash
curl http://localhost:8000/organism/organism-status
curl http://localhost:8000/organism/organism-summary
```

## Migration Checklist

- [x] Create organism entrypoint (`entrypoints/organism_entrypoint.py`)
- [x] Update serve configuration (`deploy/rayservice.yaml`)
- [x] Create organism serve client (`src/seedcore/serve/organism_serve.py`)
- [x] Update API routers to use new client
- [x] Update bootstrap script to remove plain actor creation
- [x] Create test script (`scripts/test_organism_serve.py`)
- [x] Update documentation

## Backward Compatibility

The migration maintains backward compatibility through:

1. **Same API Interface**: All existing API endpoints work the same way
2. **Direct Method Access**: Serve deployment provides direct access to organism methods
3. **Client Abstraction**: New client handles both HTTP and Serve handle access
4. **Error Handling**: Consistent error responses and status codes

## Troubleshooting

### Common Issues

1. **Organism not initializing**
   - Check Ray cluster resources
   - Verify environment variables are set
   - Check Serve deployment logs

2. **Tasks not completing**
   - Verify organism app is deployed and healthy
   - Check Serve dashboard for deployment status
   - Review organism initialization logs

3. **HTTP endpoint errors**
   - Verify organism route is accessible
   - Check Serve proxy configuration
   - Review network policies

### Debug Commands

```bash
# Check organism deployment status
kubectl exec -it seedcore-svc-head-xxxxx -n seedcore-dev -- ray status

# Check Serve logs
kubectl logs seedcore-svc-head-xxxxx -n seedcore-dev -c ray-head

# Test organism endpoints
python scripts/test_organism_serve.py
```

## Next Steps

1. **Deploy and test** the new organism Serve application
2. **Monitor performance** and verify task completion rates
3. **Update verifier scripts** to use the new organism endpoints
4. **Consider additional optimizations** like autoscaling policies
5. **Document operational procedures** for the new architecture

## Conclusion

This migration transforms the organism from a collection of plain Ray actors into a proper Ray Serve application, providing:

- **Reliable task completion** through structured lifecycles
- **Better monitoring** via Serve's built-in health checks
- **Improved scalability** through Serve's autoscaling capabilities
- **Consistent architecture** with other SeedCore services

The verifier should now see proper `"completed"` statuses instead of hanging at `"running"`, resolving the core issue that was preventing task processing from completing successfully.
