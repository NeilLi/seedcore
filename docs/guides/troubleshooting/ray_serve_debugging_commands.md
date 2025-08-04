# Ray Serve Debugging Commands Quick Reference

This document provides a quick reference for debugging Ray Serve issues in the SeedCore project.

## Container Status Commands

### Check All Containers
```bash
# List all containers
docker ps

# List containers with specific service
docker ps | grep ray

# Check container status in compose
docker compose -f docker-compose.yml ps
```

### Container Logs
```bash
# Ray head logs
docker logs seedcore-ray-head --tail 50

# Ray serve logs
docker logs seedcore-ray-serve-1 --tail 50

# Follow logs in real-time
docker logs -f seedcore-ray-head

# Search for specific patterns
docker logs seedcore-ray-head | grep -i serve
docker logs seedcore-ray-serve-1 | grep -i error
```

## Ray Serve Status Commands

### Check Serve Applications via API
```bash
# Get all applications
curl -s http://localhost:8265/api/serve/applications/ | jq .

# Get just application names
curl -s http://localhost:8265/api/serve/applications/ | jq '.applications | keys'

# Get specific application details
curl -s http://localhost:8265/api/serve/applications/ | jq '.applications["simple-serve"]'
```

### Check Serve Status via Python
```bash
# Check Serve status from head node
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init(namespace='serve')
print('Serve status:', serve.status())
"

# Check applications in namespace
docker exec seedcore-ray-head python -c "
import ray; from ray import serve
ray.init(namespace='serve')
print('Applications:', serve.status().applications)
"

# Check from serve container
docker exec seedcore-ray-serve-1 python -c "
import ray; from ray import serve
ray.init(address='ray://seedcore-ray-head:10001', namespace='serve')
print('Applications:', serve.status().applications)
"
```

## Endpoint Testing Commands

### Test Basic Endpoints
```bash
# Test simple endpoint
curl http://localhost:8000/

# Test with verbose output
curl -v http://localhost:8000/

# Test with specific headers
curl -H "Content-Type: application/json" http://localhost:8000/
```

### Test ML Endpoints
```bash
# Test salience scoring
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.5, "failure_severity": 0.3}]}'

# Test with different data
curl -X POST http://localhost:8000/score/salience \
  -H "Content-Type: application/json" \
  -d '{"features": [{"task_risk": 0.8, "failure_severity": 0.9}]}'
```

## Network and Port Commands

### Check Port Usage
```bash
# Check what's using port 8000
netstat -tulpn | grep :8000

# Check what's using port 8265
netstat -tulpn | grep :8265

# Check from inside container (if netstat available)
docker exec seedcore-ray-head netstat -tlnp 2>/dev/null | grep 8000 || echo "netstat not available"
```

### Check Container Networking
```bash
# Check container IP
docker inspect seedcore-ray-head | grep IPAddress

# Check port mappings
docker port seedcore-ray-head

# Check network connectivity
docker exec seedcore-ray-head ping -c 1 seedcore-ray-serve-1
```

## Ray Cluster Commands

### Check Ray Status
```bash
# Check Ray version
docker exec seedcore-ray-head python -c "import ray; print('Ray version:', ray.__version__)"

# Check Ray cluster status
docker exec seedcore-ray-head python -c "import ray; ray.init(); print('Ray status:', ray.status())"

# Check Ray dashboard version
curl -s http://localhost:8265/api/version
```

### Check Ray Workers
```bash
# List Ray workers
docker ps | grep ray-worker

# Check worker logs
docker logs seedcore-ray-worker-1 --tail 20

# Check worker connectivity
docker exec seedcore-ray-worker-1 python -c "import ray; ray.init(address='ray://seedcore-ray-head:10001'); print('Connected to cluster')"
```

## Application Deployment Commands

### Deploy Test Application
```bash
# Deploy simple serve application
docker exec seedcore-ray-serve-1 python /app/scripts/deploy_simple_serve.py

# Deploy ML application
docker exec seedcore-ray-serve-1 python /app/scripts/deploy_ml_serve.py
```

### Check Application Deployment
```bash
# Check if application is ready
docker logs seedcore-ray-serve-1 | grep "Application.*ready"

# Check deployment status
docker logs seedcore-ray-serve-1 | grep "Deploying.*Deployment"

# Check replica status
docker logs seedcore-ray-serve-1 | grep "ServeReplica"
```

## Restart and Recovery Commands

### Restart Services
```bash
# Restart Ray serve container
docker restart seedcore-ray-serve-1

# Restart Ray head container
docker restart seedcore-ray-head

# Restart entire cluster
cd docker && ./stop-all.sh && ./start-cluster.sh
```

### Clean Restart
```bash
# Stop all containers
cd docker && ./stop-all.sh

# Remove containers and networks
docker compose -f docker-compose.yml down --remove-orphans

# Start fresh
./start-cluster.sh
```

## Error Diagnosis Commands

### Check for Errors
```bash
# Search for errors in logs
docker logs seedcore-ray-head 2>&1 | grep -i error
docker logs seedcore-ray-serve-1 2>&1 | grep -i error

# Search for warnings
docker logs seedcore-ray-head 2>&1 | grep -i warning
docker logs seedcore-ray-serve-1 2>&1 | grep -i warning

# Search for specific error patterns
docker logs seedcore-ray-head | grep "Failed to start"
docker logs seedcore-ray-serve-1 | grep "ConnectionError"
```

### Check Configuration Issues
```bash
# Check if Serve is configured for external access
docker logs seedcore-ray-head | grep "ready at.*0.0.0.0"

# Check namespace configuration
docker logs seedcore-ray-serve-1 | grep "namespace.*serve"

# Check HTTP configuration
docker logs seedcore-ray-head | grep "http_options"
```

## Performance Monitoring Commands

### Check Resource Usage
```bash
# Check container resource usage
docker stats seedcore-ray-head seedcore-ray-serve-1

# Check memory usage
docker exec seedcore-ray-head free -h

# Check CPU usage
docker exec seedcore-ray-head top -n 1
```

### Check Application Performance
```bash
# Test endpoint response time
time curl -s http://localhost:8000/ > /dev/null

# Test with load
for i in {1..10}; do curl -s http://localhost:8000/ > /dev/null & done; wait
```

## Quick Diagnostic Script

Create a diagnostic script for quick troubleshooting:

```bash
#!/bin/bash
# ray-serve-diagnostics.sh

echo "=== Ray Serve Diagnostics ==="
echo

echo "1. Container Status:"
docker ps | grep ray
echo

echo "2. Ray Head Logs (last 10 lines):"
docker logs seedcore-ray-head --tail 10
echo

echo "3. Ray Serve Logs (last 10 lines):"
docker logs seedcore-ray-serve-1 --tail 10
echo

echo "4. Serve Applications:"
curl -s http://localhost:8265/api/serve/applications/ | jq '.applications | keys' 2>/dev/null || echo "API not accessible"
echo

echo "5. Endpoint Test:"
curl -s http://localhost:8000/ 2>/dev/null || echo "Endpoint not accessible"
echo

echo "6. Ray Version:"
docker exec seedcore-ray-head python -c "import ray; print(ray.__version__)" 2>/dev/null || echo "Ray not accessible"
echo

echo "=== Diagnostics Complete ==="
```

## Common Error Patterns

### "Serve not started" Warning
```bash
# Check if this is a false positive
docker logs seedcore-ray-head | grep "Application.*ready"
curl -s http://localhost:8265/api/serve/applications/ | jq .
```

### Endpoints Not Responding
```bash
# Check if proxy is running
docker logs seedcore-ray-head | grep "Proxy starting"

# Check external access configuration
docker logs seedcore-ray-head | grep "ready at.*0.0.0.0"

# Test endpoint directly
curl -v http://localhost:8000/
```

### Applications Not in Dashboard
```bash
# Check namespace
docker logs seedcore-ray-serve-1 | grep "namespace"

# Check application deployment
docker logs seedcore-ray-serve-1 | grep "Application.*ready"

# Check API directly
curl -s http://localhost:8265/api/serve/applications/
```

## Useful Aliases

Add these to your shell profile for quick access:

```bash
# Ray Serve aliases
alias ray-logs='docker logs seedcore-ray-head --tail 50'
alias serve-logs='docker logs seedcore-ray-serve-1 --tail 50'
alias ray-status='curl -s http://localhost:8265/api/serve/applications/ | jq .'
alias ray-test='curl http://localhost:8000/'
alias ray-restart='docker restart seedcore-ray-serve-1'
```

## Related Documentation

- [Ray Serve Troubleshooting Guide](ray_serve_troubleshooting.md)
- [Ray Serve Deployment Pattern](../docker/RAY_SERVE_PATTERN.md)
- [Ray Cluster Setup](ray_cluster_setup.md) 