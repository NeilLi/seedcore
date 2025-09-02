# SeedCore API Consolidation Summary

## Overview

Successfully consolidated the SeedCore API by standardizing on `src/seedcore/main.py` as the primary API entrypoint, replacing the complex `src/seedcore/telemetry/server.py` for simple API deployments.

## Changes Made

### 1. Docker Entrypoints Updated

**Files Modified:**
- `docker/api_entrypoint.sh`
- `docker/api_entrypoint_wrapper.sh`

**Changes:**
- Updated uvicorn command from `src.seedcore.telemetry.server:app` to `src.seedcore.main:app`
- Updated file existence checks from `server.py` to `main.py`
- Updated log messages to reflect the new entrypoint

### 2. Kubernetes Deployment

**Status:** ✅ Already correctly configured
- `deploy/k8s/seedcore-api.yaml` already uses `src.seedcore.main:app`
- No changes needed

## Architecture Comparison

### `src/seedcore/main.py` (New Primary API)
- **Purpose**: Simple, database-backed task management API
- **Size**: ~100 lines
- **Features**:
  - FastAPI app with database initialization
  - Task and control routers
  - Health/readiness endpoints (`/health`, `/readyz`)
  - CORS middleware
  - Simple lifespan management
- **Dependencies**: Minimal (database, basic routers)

### `src/seedcore/telemetry/server.py` (Legacy Complex API)
- **Purpose**: Full-featured telemetry and simulation control server
- **Size**: ~2700+ lines
- **Features**:
  - Complex lifespan management with Ray initialization
  - Multiple routers (mfb, salience, organism, tier0, energy, holon, control, tasks, ocps, dspy)
  - Memory system management
  - Energy system management
  - Organism management
  - Prometheus metrics
  - Complex startup/shutdown logic
- **Dependencies**: Heavy (Ray, memory systems, energy systems, etc.)

## Benefits of Consolidation

1. **Simplified Deployment**: Single, focused API entrypoint
2. **Reduced Complexity**: Eliminates heavy dependencies for simple use cases
3. **Better Separation**: Complex features remain available via separate services
4. **Consistent Configuration**: All deployments now use the same entrypoint
5. **Easier Maintenance**: Single codebase to maintain for basic API functionality

## Deployment Options

### Simple API (Recommended for most use cases)
```bash
# Uses main.py - simple, database-backed task management
uvicorn src.seedcore.main:app --host 0.0.0.0 --port 8002
```

### Complex Telemetry API (For advanced features)
```bash
# Uses server.py - full telemetry and simulation features
uvicorn src.seedcore.telemetry.server:app --host 0.0.0.0 --port 8002
```

## Environment Variables

The consolidated API supports the following environment variables:

- `ENABLE_DEBUG_ENV`: Enable debug environment endpoint (default: false)
- `RUN_DDL_ON_STARTUP`: Run database DDL on startup (default: true)
- `CORS_ALLOW_ORIGINS`: CORS allowed origins (default: "*")
- `HOST`: Server host (default: "0.0.0.0")
- `PORT`: Server port (default: "8002")

## Health Endpoints

- `GET /health`: Basic health check
- `GET /readyz`: Readiness check (includes database connectivity)
- `GET /`: Root endpoint with API information
- `GET /_env`: Debug environment dump (if enabled)

## Next Steps

1. **Test the consolidated API** in your deployment environment
2. **Update any documentation** that references the old entrypoint
3. **Consider deprecating** `server.py` if not needed for complex features
4. **Monitor** the simplified API for any missing functionality

## Rollback Plan

If issues arise, you can quickly rollback by:
1. Reverting the Docker entrypoint changes
2. Changing the uvicorn command back to `src.seedcore.telemetry.server:app`
3. Updating file existence checks back to `server.py`

The Kubernetes deployment can be updated independently if needed.
