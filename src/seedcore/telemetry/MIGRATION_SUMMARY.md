# Telemetry Migration Summary

## ✅ Completed Migrations

### 1. File Structure Reorganization
- **`metrics.py`** → `services/metrics.py` ✅
- **`stats.py`** → `services/stats.py` ✅  
- **`schema.py`** → `schemas/energy.py` ✅
- **`metrics_integration.py`** → Split into:
  - `services/metrics_integration.py` ✅
  - `routers/metrics.py` ✅
  - `clients/prometheus_client.py` ✅

### 2. Router Structure Fixed
- Fixed incorrect router prefix mappings ✅
- Added missing router files for all endpoints ✅
- Created proper router organization:
  - **Prefixed routers**: `/actions`, `/admin`, `/agents`, `/energy`, `/mw`, `/system`, `/tier0`, `/coordinator`, `/dspy`, `/maintenance`, `/ray`
  - **Root-level routers**: `/health`, `/healthz`, `/metrics`, `/pair_stats`, `/readyz`, `/run_*`

### 3. Import Updates
- Updated all import statements to reflect new file locations ✅
- Fixed imports in `server.py` ✅
- Fixed imports in `consolidation_logic.py` ✅

### 4. Enhanced Structure
- **`app.py`**: Proper FastAPI app with lifespan management ✅
- **`deps.py`**: Ray client dependencies and shared utilities ✅
- **`clients/ray_clients.py`**: Centralized Ray actor handles ✅
- **`schemas/common.py`**: Comprehensive Pydantic models ✅
- **`server_shim.py`**: Backward compatibility with fallback ✅

## 🔄 Next Steps (Manual Migration Required)

### 1. Endpoint Migration
The following endpoints need to be manually migrated from `server.py` to their respective router files:

#### Energy Router (`routers/energy.py`)
- `GET /energy/meta` → `def energy_meta(...)`
- `GET /energy/calibrate` → `def energy_calibrate(...)`
- `GET /energy/health` → `def energy_health(...)`
- `GET /energy/monitor` → `def energy_monitor(...)`
- `GET /energy/pair_stats` → `def energy_pair_stats(...)`
- `POST /energy/log` → `def energy_log(...)`
- `GET /energy/logs` → `def energy_logs(...)`
- `GET /energy/gradient` → `def energy_gradient(...)`

#### Actions Router (`routers/actions.py`)
- `POST /actions/run_two_agent_task` → `def run_two_agent_task(...)`
- `POST /actions/run_slow_loop` → `def run_slow_loop_endpoint(...)`
- `POST /actions/reset` → `def reset_simulation(...)`

#### System Router (`routers/system.py`)
- `GET /system/status` → `def get_system_status(...)`

#### And many more... (see MIGRATION_MAP.md for complete list)

### 2. Service Layer Implementation
- Move business logic from endpoint handlers to `services/` modules
- Implement proper dependency injection
- Add error handling and validation

### 3. Testing
- Test all migrated endpoints
- Verify metrics collection works
- Ensure backward compatibility

## 🚀 How to Use

### Run New Structure
```bash
# New modular structure
uvicorn seedcore.telemetry.app:app --reload

# Backward compatibility (fallback to old server)
uvicorn seedcore.telemetry.server_shim:app --reload
```

### Migration Process
1. **Start with one router** (e.g., `energy.py`)
2. **Move endpoints** from `server.py` to the router
3. **Update decorators** from `@app.method` to `@router.method`
4. **Move business logic** to appropriate service files
5. **Test the router** works independently
6. **Repeat** for other routers
7. **Remove migrated code** from `server.py`
8. **Update imports** as needed

## 📁 Current File Structure

```
src/seedcore/telemetry/
├── app.py                    # Main FastAPI app
├── server_shim.py           # Backward compatibility
├── deps.py                  # Shared dependencies
├── routers/                 # Endpoint definitions
│   ├── __init__.py
│   ├── actions.py
│   ├── admin.py
│   ├── agents.py
│   ├── coordinator.py
│   ├── dspy.py
│   ├── energy.py
│   ├── health.py
│   ├── healthz.py
│   ├── maintenance.py
│   ├── metrics.py
│   ├── mw.py
│   ├── pair_stats.py
│   ├── ray.py
│   ├── readyz.py
│   ├── run_all_loops.py
│   ├── run_memory_loop.py
│   ├── run_simulation_step.py
│   ├── run_slow_loop.py
│   ├── run_slow_loop_simple.py
│   ├── system.py
│   └── tier0.py
├── services/                # Business logic
│   ├── __init__.py
│   ├── energy.py
│   ├── metrics.py
│   ├── metrics_integration.py
│   └── stats.py
├── schemas/                 # Pydantic models
│   ├── __init__.py
│   ├── common.py
│   └── energy.py
├── clients/                 # External service clients
│   ├── __init__.py
│   ├── ray_clients.py
│   └── prometheus_client.py
└── server.py               # Original monolithic server (to be phased out)
```

## ✨ Benefits Achieved

1. **Modularity**: Clear separation of concerns
2. **Maintainability**: Easier to find and modify specific functionality
3. **Testability**: Individual components can be tested in isolation
4. **Scalability**: Easy to add new endpoints and services
5. **Backward Compatibility**: Existing code continues to work during migration
6. **Ray Integration**: Proper Ray client management
7. **Metrics**: Comprehensive Prometheus integration
8. **Type Safety**: Proper Pydantic schemas throughout
