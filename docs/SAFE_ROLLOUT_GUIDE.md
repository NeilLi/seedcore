# Safe Rollout Guide - Predicate System

This guide provides a safe rollout strategy for the predicate-based routing system without requiring Prometheus/Grafana or Redis dependencies.

## 🎯 **Quick Answer: Is it safe to run?**

**YES!** The system is now designed to run safely without external dependencies:

- ✅ **No Prometheus required** - Uses NullMetric fallback
- ✅ **No Redis required** - Falls back to in-memory storage  
- ✅ **No GPU guard by default** - Disabled via feature flag
- ✅ **Conservative timeouts** - Won't break existing workflows
- ✅ **Last-good config fallback** - Won't crash on bad YAML
- ✅ **Catch-all routing** - Every task gets a decision

## 🚀 **Safe Rollout Steps**

### 1. **Use the Bootstrap Configuration**

```bash
# Copy the safe bootstrap config
cp config/predicates-bootstrap.yaml /app/config/predicates-bootstrap.yaml

# Set safe environment variables
export METRICS_ENABLED=0
export GPU_GUARD_ENABLED=0
export COORD_PREDICATES_PATH=/app/config/predicates-bootstrap.yaml
export CB_ML_TIMEOUT_S=2
export CB_COG_TIMEOUT_S=4
export CB_ORG_TIMEOUT_S=5
export CB_FAIL_THRESHOLD=5
export CB_RESET_S=30
```

### 2. **Run the Safe Rollout Script**

```bash
./scripts/safe-rollout.sh
```

### 3. **Verify System Health**

```bash
# Check system status
curl http://localhost:8000/pipeline/predicates/status

# Test basic routing
curl -X POST http://localhost:8000/pipeline/route-and-execute \
  -H 'Content-Type: application/json' \
  -d '{"type": "health_check", "params": {}}'

# Test anomaly triage
curl -X POST http://localhost:8000/pipeline/anomaly-triage \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "test", "series": [1,2,3], "drift_score": 0.1}'
```

## 🛡️ **Safety Features Implemented**

### **1. NullMetric Guard**
- **File**: `src/seedcore/predicates/safe_metrics.py`
- **Purpose**: Prevents crashes when Prometheus is not available
- **Behavior**: All metrics become no-op objects if Prometheus unavailable
- **Environment**: `METRICS_ENABLED=0` disables metrics entirely

### **2. Optional Redis Storage**
- **File**: `src/seedcore/predicates/safe_storage.py`
- **Purpose**: Graceful fallback when Redis is unavailable
- **Behavior**: Falls back to in-memory storage with TTL support
- **Environment**: `REDIS_URL` optional, defaults to in-memory

### **3. Last-Good Config Fallback**
- **File**: `src/seedcore/predicates/loader.py`
- **Purpose**: Prevents crashes on bad YAML configuration
- **Behavior**: Keeps last working config, creates minimal fallback if needed
- **Recovery**: Automatic fallback to catch-all routing rule

### **4. Conservative Circuit Breakers**
- **File**: `src/seedcore/services/coordinator_service.py`
- **Purpose**: Prevents cascade failures
- **Defaults**:
  - ML service: 2s timeout, 1 retry
  - Cognitive: 4s timeout, 0 retries
  - Organism: 5s timeout, 0 retries
  - Failure threshold: 5 consecutive failures
  - Recovery: 30s half-open period

### **5. Optional GPU Guard**
- **File**: `src/seedcore/predicates/router.py`
- **Purpose**: Prevents resource exhaustion
- **Behavior**: Disabled by default, can be enabled via feature flag
- **Environment**: `GPU_GUARD_ENABLED=0` (default)

### **6. Minimal Bootstrap Config**
- **File**: `config/predicates-bootstrap.yaml`
- **Purpose**: Safe starting configuration
- **Features**:
  - Single catch-all routing rule
  - No mutation rules
  - GPU guard disabled
  - All tasks go to fast path

## 📊 **Monitoring Without Prometheus**

### **Status Endpoint**
```bash
curl http://localhost:8000/pipeline/predicates/status
```

**Response includes**:
- Configuration version and hash
- Feature flag status
- Circuit breaker health
- Storage backend type
- GPU guard status
- Load failure count

### **Key Health Indicators**
- `predicate_config.is_fallback`: `true` if using emergency config
- `predicate_config.gpu_guard_enabled`: `false` means GPU guard disabled
- `storage.backend`: `"in_memory"` means Redis unavailable
- `circuit_breakers.*.state`: `"closed"` means healthy

## 🔧 **Configuration Management**

### **Hot Reload**
```bash
# Reload configuration
curl -X POST http://localhost:8000/pipeline/predicates/reload

# Get current config
curl http://localhost:8000/pipeline/predicates/config
```

### **Feature Flags**
```yaml
# In predicates.yaml
routing_enabled: true      # Enable/disable routing rules
mutations_enabled: false   # Enable/disable mutation rules  
gpu_guard_enabled: false   # Enable/disable GPU guard
```

## 🚨 **Troubleshooting**

### **Common Issues**

1. **"No decision" errors**
   - **Cause**: Missing catch-all rule
   - **Fix**: Ensure `when: "true"` rule exists with priority -1

2. **Circuit breaker open**
   - **Cause**: Downstream service failures
   - **Fix**: Check service health, wait for recovery timeout

3. **Configuration load failures**
   - **Cause**: Invalid YAML or unknown signals
   - **Fix**: Check `/predicates/status` for fallback status

4. **Redis connection errors**
   - **Cause**: Redis unavailable
   - **Fix**: System automatically falls back to in-memory storage

### **Emergency Procedures**

1. **Disable all features**:
   ```yaml
   routing_enabled: false
   mutations_enabled: false
   gpu_guard_enabled: false
   ```

2. **Force fallback config**:
   ```bash
   # Delete predicates.yaml to force fallback
   rm /app/config/predicates.yaml
   curl -X POST http://localhost:8000/pipeline/predicates/reload
   ```

3. **Check system status**:
   ```bash
   curl http://localhost:8000/pipeline/predicates/status | jq
   ```

## 📈 **Gradual Feature Enablement**

### **Phase 1: Basic Routing (Safe)**
- ✅ Routing enabled
- ❌ Mutations disabled
- ❌ GPU guard disabled
- ❌ Metrics disabled

### **Phase 2: Add Metrics**
```bash
export METRICS_ENABLED=1
# Add Prometheus scrape config
# Restart service
```

### **Phase 3: Enable GPU Guard**
```yaml
# In predicates.yaml
gpu_guard_enabled: true
```

### **Phase 4: Enable Mutations**
```yaml
# In predicates.yaml
mutations_enabled: true
```

### **Phase 5: Full Production**
- All features enabled
- Prometheus/Grafana monitoring
- Redis persistence
- Full predicate rules

## 🎉 **Success Criteria**

The system is successfully rolled out when:

1. ✅ Status endpoint returns healthy state
2. ✅ Basic routing works (health checks go to fast path)
3. ✅ Anomaly triage completes without errors
4. ✅ Circuit breakers show "closed" state
5. ✅ No crashes or "no decision" errors
6. ✅ Configuration can be hot-reloaded

## 📋 **Rollback Plan**

If issues occur:

1. **Immediate**: Set all feature flags to `false`
2. **Quick**: Use bootstrap configuration
3. **Emergency**: Disable predicate system entirely
4. **Recovery**: Check logs and status endpoint for root cause

The system is designed to fail gracefully and provide clear indicators of what's working and what isn't.
