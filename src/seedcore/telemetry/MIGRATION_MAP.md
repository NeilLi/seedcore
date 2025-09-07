# Telemetry Module Migration Map

This document outlines the migration of existing telemetry files into the new modular structure.

## File Migration Map

### ✅ Already Migrated
- `app.py` - Main FastAPI application (NEW)
- `routers/` - Router modules for endpoints (NEW)
- `schemas/` - Pydantic models (NEW)
- `deps.py` - Shared dependencies (NEW)
- `clients/ray_clients.py` - Ray client handles (NEW)
- `server_shim.py` - Backward compatibility shim (NEW)

### 🔄 Files to Migrate

#### 1. `metrics.py` → `services/metrics.py`
**Current**: Contains Prometheus metrics definitions and update functions
**New Location**: `services/metrics.py`
**Reason**: Business logic for metrics collection and updates
**Content**: 
- Prometheus gauge/counter definitions
- Update functions for different metric types
- Metric collection logic

#### 2. `metrics_integration.py` → Split into multiple files
**Current**: Service that polls API endpoints to update metrics
**Split Into**:
- `services/metrics_integration.py` - Core service logic
- `routers/metrics.py` - Metrics endpoint exposure
- `clients/prometheus_client.py` - Prometheus client integration

#### 3. `schema.py` → `schemas/energy.py`
**Current**: Contains energy-related schema definitions
**New Location**: `schemas/energy.py`
**Reason**: Energy-specific Pydantic models
**Content**:
- `ENERGY_PAYLOAD_FIELDS` constant
- Energy-related data structures

#### 4. `stats.py` → `services/stats.py`
**Current**: StatsCollector class and database query helpers
**New Location**: `services/stats.py`
**Reason**: Business logic for statistics collection
**Content**:
- `StatsCollector` class
- Database query methods
- Statistics calculation logic

#### 5. `server.py` → Migrate endpoints to routers
**Current**: Monolithic FastAPI server with all endpoints
**Migration**: Move individual endpoints to appropriate router files
**Process**:
- Extract endpoint functions
- Move to correct router files
- Update decorators from `@app.method` to `@router.method`
- Update imports and dependencies

## Detailed Migration Steps

### Step 1: Migrate Metrics
```bash
# Move metrics.py to services/
mv metrics.py services/metrics.py
# Update imports in other files
```

### Step 2: Split Metrics Integration
```bash
# Keep core service logic
# Move API endpoint logic to routers/metrics.py
# Move Prometheus client to clients/prometheus_client.py
```

### Step 3: Migrate Schema
```bash
# Move schema.py content to schemas/energy.py
# Update imports throughout codebase
```

### Step 4: Migrate Stats
```bash
# Move stats.py to services/stats.py
# Update imports in other files
```

### Step 5: Migrate Server Endpoints
```bash
# Extract each endpoint from server.py
# Move to appropriate router file
# Update decorators and imports
```

## Import Updates Required

After migration, update imports in:
- `app.py`
- `routers/*.py`
- `services/*.py`
- `clients/*.py`
- Any other files that import from telemetry module

## Backward Compatibility

- Keep `server_shim.py` for transition period
- Update `server_shim.py` to import from new structure
- Remove old files only after all imports are updated

## Verification Checklist

- [ ] All files migrated to correct locations
- [ ] All imports updated
- [ ] All endpoints accessible through new structure
- [ ] No functionality lost
- [ ] Tests pass
- [ ] Documentation updated
