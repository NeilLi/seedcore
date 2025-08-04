# Service Dependencies Summary

## Quick Reference for Operators

### 🚨 Critical Information

**The SeedCore system has specific dependency requirements that affect service restart behavior.**

### ✅ Always Use: Full Cluster Restart

```bash
cd docker
./start-cluster.sh
```

### ❌ Avoid: Individual Service Restart

```bash
# This may fail due to dependency issues
docker compose restart seedcore-api
```

## Why This Matters

### Ray Cluster State Dependencies

- **`seedcore-api` connects to Ray cluster** at startup
- **Ray client connections are stateful** - they can hang if cluster state is inconsistent
- **Actors and namespaces** exist only for the life of the Ray cluster
- **Independent restarts** may fail if dependencies aren't fully ready

### Dependency Tree

```
seedcore-api
  ├──> ray-head (Ray cluster, Serve deployment, actor registry)
  ├──> seedcore-mysql / seedcore-postgres / seedcore-neo4j (DBs)
  └──> application code (models, config)
```

## Common Scenarios

### Scenario 1: API Hangs After Restart

**Symptoms:**
- API container shows "health: starting" for extended periods
- No response from API endpoints
- Empty replies from server

**Solution:**
```bash
# Restart entire cluster
cd docker
./start-cluster.sh
```

### Scenario 2: ML Service Not Available

**Symptoms:**
- Salience health endpoint returns `"model_loaded": false`
- Fallback scoring being used

**Diagnosis:**
```bash
# Check Ray Serve deployment
curl -s http://localhost:8265/api/serve/applications/ | jq .

# Test ML endpoint directly
curl http://localhost:8000/ml/score/salience -X POST -H "Content-Type: application/json" -d '{"features": [{"task_risk": 0.8, "failure_severity": 0.9}]}'
```

**Solution:**
- Ensure Ray head container is running and healthy
- Restart entire cluster if needed

## Quick Diagnostic Commands

### Check System Health

```bash
# 1. Ray head health
docker ps | grep seedcore-ray-head

# 2. Ray cluster status
docker exec seedcore-ray-head ray status

# 3. Database health
docker ps | grep -E "(seedcore-postgres|seedcore-mysql|seedcore-neo4j)"

# 4. API logs
docker logs seedcore-api --tail 20
```

### Test Endpoints

```bash
# API health
curl http://localhost:80/health

# Salience health
curl http://localhost:80/salience/health

# Ray dashboard
curl http://localhost:8265/api/version
```

## Best Practices

1. **Always use `./start-cluster.sh`** for starting services
2. **Avoid individual service restarts** unless you understand the dependencies
3. **Check system health** before attempting any restarts
4. **Monitor logs** for connection errors and dependency issues
5. **Use full cluster restart** when in doubt

## When Individual Restarts Are Safe

Individual service restarts may work if:

1. **Ray head is healthy** and cluster state is consistent
2. **All databases are healthy** and accessible
3. **No recent cluster state changes** have occurred
4. **You're only restarting stateless services** (not API or Ray head)

## Troubleshooting Checklist

- [ ] Ray head container is running and healthy
- [ ] Ray cluster status shows correct worker and actor state
- [ ] All databases are healthy and accessible
- [ ] API logs show successful Ray client initialization
- [ ] No recent cluster state changes or restarts

If any item fails, use full cluster restart.

## Related Documentation

- **[Service Dependencies and Restart Behavior](./service-dependencies-and-restart-behavior.md)** - Detailed technical explanation
- **[Ray Serve Troubleshooting](./ray_serve_troubleshooting.md)** - Ray Serve specific issues
- **[Docker Setup Guide](./docker-setup-guide.md)** - Complete setup instructions

---

**Remember**: When in doubt, restart the entire cluster using `./start-cluster.sh`. This ensures all services start in the correct order with proper dependency management. 