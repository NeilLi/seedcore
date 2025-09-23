# Mw Integration Deployment Checklist

## ✅ Pre-Deployment Verification

### 1. Code Quality Checks
- [ ] **All global writes use `*_typed` API** - No manual key construction
- [ ] **No call sites pass `ttl` to `set_item`** - L0 doesn't support TTL
- [ ] **Key consistency verified** - Write/read/delete use same key format
- [ ] **Double-prefix guard working** - `is_global=True` prevents re-prefixing
- [ ] **Linter passes** - No syntax or style issues

### 2. Integration Tests
- [ ] **Run integration tests** - `pytest tests/test_ray_agent_mw_integration.py`
- [ ] **Test double-prefix prevention** - Verify no `global:item:global:item:` keys
- [ ] **Test task caching lifecycle** - Cache → Invalidate → Miss
- [ ] **Test telemetry collection** - Heartbeat includes Mw metrics
- [ ] **Test configurable TTLs** - Environment variables work

### 3. Key Consistency Verification
```bash
# Verify no double-prefixing in logs
grep -r "global:item:global:item" logs/ || echo "✅ No double-prefixing found"

# Verify typed API usage
grep -r "set_global_item_typed" src/ | wc -l  # Should be > 0
grep -r "set_global_item(" src/ | wc -l      # Should be minimal
```

## 🚀 Deployment Steps

### 1. Environment Configuration
Set these environment variables for tuning (optional):
```bash
# Task TTLs (seconds)
export MW_TASK_TTL_RUNNING_S=30
export MW_TASK_TTL_COMPLETED_S=600
export MW_TASK_TTL_FAILED_S=300
export MW_TASK_TTL_NEGATIVE_S=30

# Cache configuration
export MW_L1_TTL_S=30
export MW_L2_TTL_S=3600
```

### 2. Gradual Rollout
- [ ] **Deploy to staging** - Test with synthetic load
- [ ] **Monitor Mw telemetry** - Watch hit ratios and eviction rates
- [ ] **Validate task caching** - Check TTLs match expected values
- [ ] **Deploy to production** - Start with low-traffic agents

### 3. Monitoring Setup
- [ ] **Heartbeat alerts** - Monitor `mw_hit_ratio` drops
- [ ] **Cache size monitoring** - Watch for unbounded L0 growth
- [ ] **Task TTL validation** - Verify running tasks have short TTLs
- [ ] **Hot items tracking** - Monitor `mw_hot_items` in heartbeats

## 📊 Post-Deployment Validation

### 1. Telemetry Verification
Check these metrics in heartbeats:
```json
{
  "memory_metrics": {
    "mw_hit_ratio": 0.8,           // Should be > 0.7
    "mw_l0_hits": 100,             // Should be highest
    "mw_l1_hits": 50,              // Should be moderate
    "mw_l2_hits": 20,              // Should be lowest
    "mw_task_cache_hits": 10,      // Should increase over time
    "mw_task_evictions": 5,        // Should be reasonable
    "mw_hot_items": [["task:123", 5]] // Should appear occasionally
  }
}
```

### 2. Performance Validation
- [ ] **Cache hit ratio** - Should be > 70% for L0
- [ ] **Task TTL compliance** - Running tasks expire quickly
- [ ] **Memory usage** - L0 cache doesn't grow unbounded
- [ ] **DB load reduction** - Fewer Mlt queries for cached items

### 3. Functional Validation
- [ ] **Task caching works** - `cache_task_row()` stores with correct TTL
- [ ] **Invalidation works** - Status changes clear cache
- [ ] **Negative cache works** - Misses don't cause DB stampedes
- [ ] **Hot items appear** - Prewarming shows in telemetry

## 🔧 Troubleshooting

### Common Issues

#### Low Hit Ratios
```bash
# Check if keys are consistent
grep "MISS" logs/ | head -10

# Verify TTLs are reasonable
grep "Cached task.*with TTL" logs/ | head -10
```

#### Memory Growth
```bash
# Check L0 cache size
grep "Cleared L0 cache" logs/

# Monitor task evictions
grep "task_evictions" logs/ | tail -10
```

#### Double-Prefixing
```bash
# Search for double prefixes
grep -r "global:item:global:item" logs/ || echo "✅ Clean"
```

### Rollback Plan
If issues arise:
1. **Disable Mw caching** - Set `MW_ENABLED=false`
2. **Clear caches** - Restart Ray actors
3. **Revert code** - Deploy previous version
4. **Investigate** - Check logs for root cause

## 📈 Success Metrics

### Week 1 Targets
- [ ] **Hit ratio > 70%** - Cache effectiveness
- [ ] **Task TTLs working** - Running tasks expire quickly
- [ ] **No double-prefixing** - Clean key management
- [ ] **Telemetry flowing** - Heartbeats include Mw metrics

### Week 2+ Targets
- [ ] **Hit ratio > 80%** - Optimized caching
- [ ] **Hot items prewarming** - Proactive cache warming
- [ ] **Configurable TTLs** - Tuned for workload
- [ ] **Memory bounded** - No unbounded growth

## 🎯 Next Steps

After successful deployment:
1. **Tune TTLs** - Based on observed patterns
2. **Add more metrics** - Custom telemetry for specific use cases
3. **Optimize prewarming** - Improve hot item detection
4. **Scale testing** - Load test with more agents

---

**Deployment Date**: ___________  
**Deployed By**: ___________  
**Validation Complete**: ___________
