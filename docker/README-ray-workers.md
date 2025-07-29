# Ray Workers Configuration

This directory contains the configuration for managing Ray worker nodes independently from the main SeedCore services.

## Files

- `ray-workers.yml` - Docker Compose configuration for Ray worker nodes
- `ray-workers.sh` - Management script for Ray workers
- `README-ray-workers.md` - This documentation file

## Architecture

The Ray cluster is now split into two parts:

1. **Main Services** (`docker-compose.yml`):
   - Ray Head Node (orchestrator)
   - SeedCore API
   - Databases (PostgreSQL, MySQL, Neo4j)
   - Monitoring (Prometheus, Grafana)

2. **Ray Workers** (`ray-workers.yml`):
   - Multiple Ray worker nodes
   - Independently scalable
   - Connect to the Ray head node

## Usage

### Using the Management Script

The `ray-workers.sh` script provides easy management of Ray workers:

```bash
# Make the script executable
chmod +x ray-workers.sh

# Start 5 Ray workers
./ray-workers.sh start 5

# Stop all Ray workers
./ray-workers.sh stop

# Scale to 3 workers
./ray-workers.sh scale 3

# Check status
./ray-workers.sh status

# View logs
./ray-workers.sh logs

# Show help
./ray-workers.sh help
```

### Using Docker Compose Directly

```bash
# Start 4 workers (default)
docker compose -f ray-workers.yml up -d

# Start specific number of workers
docker compose -f ray-workers.yml up -d --scale ray-worker-1=3

# Stop workers
docker compose -f ray-workers.yml down

# View logs
docker compose -f ray-workers.yml logs -f
```

## Configuration

### Worker Configuration

Each worker node is configured with:
- **CPU**: 1 CPU core per worker
- **Memory**: 2GB shared memory
- **Network**: Connects to `seedcore-network`
- **Dependencies**: Waits for Ray head node to start

### Environment Variables

All workers use the same environment configuration:
- `PYTHONPATH`: Set to include the SeedCore source code
- `RAY_*`: Ray-specific configuration for logging and monitoring
- `RAY_GRAFANA_IFRAME_HOST`: Uses hostname `grafana:3000` (no hardcoded IPs)

### Scaling

To scale the number of workers:

1. **Using the script** (recommended):
   ```bash
   ./ray-workers.sh scale 10
   ```

2. **Manual approach**:
   - Edit `ray-workers.yml` to add/remove worker services
   - Or use Docker Compose scaling:
   ```bash
   docker compose -f ray-workers.yml up -d --scale ray-worker-1=10
   ```

## Benefits

### Separation of Concerns
- Main services and workers are managed independently
- Easier to scale workers without affecting core services
- Cleaner configuration files

### Flexibility
- Start/stop workers without affecting the main system
- Scale workers based on workload
- Different worker configurations possible

### Maintainability
- No hardcoded IP addresses
- Uses Docker hostnames for internal communication
- Easy to modify worker configurations

## Monitoring

### Ray Dashboard
- Access at: http://localhost:8265
- Shows all connected workers
- Real-time cluster status

### Grafana Dashboards
- Ray cluster overview
- Worker performance metrics
- Resource utilization

### Logs
```bash
# All workers
./ray-workers.sh logs

# Specific worker
docker logs ray-worker-1

# Follow logs
docker logs -f ray-worker-1
```

## Troubleshooting

### Workers Not Connecting
1. Ensure Ray head node is running:
   ```bash
   docker compose ps ray-head
   ```

2. Check network connectivity:
   ```bash
   docker network ls
   docker network inspect docker_seedcore-network
   ```

3. Verify worker logs:
   ```bash
   ./ray-workers.sh logs
   ```

### Scaling Issues
1. Check available resources:
   ```bash
   docker stats
   ```

2. Monitor Ray dashboard for cluster status

3. Restart workers if needed:
   ```bash
   ./ray-workers.sh restart
   ```

## Best Practices

1. **Start with main services first**:
   ```bash
   docker compose up -d
   ```

2. **Then start workers**:
   ```bash
   ./ray-workers.sh start 5
   ```

3. **Monitor cluster health**:
   - Check Ray dashboard
   - Monitor Grafana metrics
   - Watch worker logs

4. **Scale based on workload**:
   - Monitor CPU/memory usage
   - Scale up during peak loads
   - Scale down during quiet periods

5. **Use the management script**:
   - Consistent operations
   - Built-in error checking
   - Easy to automate 