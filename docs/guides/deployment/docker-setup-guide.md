# SeedCore Docker Setup

This directory contains the Docker configuration for the SeedCore Ray Serve cluster, including optimized images and deployment scripts.

## 🚀 Quick Start

```bash
# Start the entire cluster with one command
./start-cluster.sh

# Monitor the cluster
docker compose -p seedcore ps
docker compose -p seedcore logs -f ray-head
```

## 📦 Image Optimization

The Ray images have been optimized for production use:

### Image Size Comparison

| Image | Size | Reduction | Status |
|-------|------|-----------|---------|
| **Original** | 2.21GB | - | ❌ Large |
| **Optimized** | 1.02GB | **54% smaller** | ✅ **Recommended** |

### Key Optimizations

1. **Base Image**: Changed from `rayproject/ray:latest-py310` (~1.4GB) to `python:3.10-slim` (~77MB)
2. **Selective Dependencies**: Only install essential packages used by the codebase
3. **Docker Ignore**: Exclude unnecessary files from build context
4. **Multi-stage Build**: Optimized layer caching and reduced final image size

### Essential Packages Included

- **Ray Core**: `ray[default]==2.48.0`
- **Web Framework**: `fastapi`, `uvicorn`, `pydantic`
- **Database**: `asyncpg`, `psycopg2-binary`, `neo4j`
- **ML Libraries**: `numpy`, `pandas`, `scipy`, `scikit-learn`
- **Utilities**: `pyyaml`, `tqdm`, `prometheus_client`, `aiohttp`, `psutil`

## 🏗️ Architecture

### Services

- **ray-head**: Ray cluster head node with dashboard
- **ray-serve**: Ray Serve application deployment
- **ray-worker**: Ray worker nodes (managed by `ray-workers.sh`)
- **seedcore-api**: FastAPI application server
- **Monitoring**: Prometheus, Grafana, Node Exporter
- **Databases**: PostgreSQL, MySQL, Neo4j

### Network

All services run on the `seedcore-network` external network for proper communication.

## 📁 File Structure

```
docker/
├── Dockerfile.ray              # Optimized Ray image (head, worker, serve)
├── Dockerfile                  # API server image
├── docker-compose.yml          # Main services configuration
├── ray-workers.yml             # Worker services configuration
├── start-cluster.sh            # One-command cluster startup
├── ray-workers.sh              # Worker management script
├── wait_for_head.sh            # Head node readiness check
├── serve_entrypoint.py         # Ray Serve deployment script
├── .dockerignore               # Build context optimization
└── README.md                   # This file
```

## 🔧 Configuration

### Environment Variables

- `RAY_ADDRESS`: Ray cluster address (default: `ray://ray-head:10001`)
- `PYTHONPATH`: Python module search path
- `RAY_TMPDIR`: Ray temporary directory
- `RAY_DASHBOARD_HOST`: Dashboard host (default: `0.0.0.0`)
- `RAY_DASHBOARD_PORT`: Dashboard port (default: `8265`)

### Ports

- **8265**: Ray Dashboard
- **8000**: Ray Serve applications
- **80**: SeedCore API
- **9090**: Prometheus
- **3000**: Grafana
- **9100**: Node Exporter

## 🚀 Deployment

### Production Deployment

1. **Build Images**:
   ```bash
   docker build -f Dockerfile.ray -t seedcore-ray:latest ..
   docker build -f Dockerfile -t seedcore-api:latest ..
   ```

2. **Start Cluster**:
   ```bash
   ./start-cluster.sh
   ```

3. **Verify Health**:
   ```bash
   # Check all services
   docker compose -p seedcore ps
   
   # Test API endpoint
   curl http://localhost:80/health
   
   # Check Ray Dashboard
   curl http://localhost:8265/api/version
   ```

### Development

For development with hot reloading:

```bash
# Start only core services
docker compose -p seedcore up -d postgres mysql neo4j ray-head

# Start API with volume mount for development
docker compose -p seedcore up seedcore-api
```

## 🔍 Monitoring

### Ray Dashboard
- **URL**: http://localhost:8265
- **Features**: Cluster status, task monitoring, resource usage

### Prometheus
- **URL**: http://localhost:9090
- **Features**: Metrics collection, alerting

### Grafana
- **URL**: http://localhost:3000
- **Features**: Dashboards, visualization
- **Default Credentials**: admin/admin

## 🛠️ Troubleshooting

### Common Issues

1. **"Head not ready yet"**:
   - Workers use `wait_for_head.sh` to ensure head node readiness
   - Check head node logs: `docker compose -p seedcore logs ray-head`

2. **Image too large**:
   - Use optimized images (1.02GB vs 2.21GB)
   - Check `.dockerignore` excludes unnecessary files

3. **Missing packages**:
   - All essential packages are included in optimized image
   - Verify with: `docker run --rm seedcore-ray:latest pip list`

### Logs

```bash
# View all logs
docker compose -p seedcore logs

# Follow specific service
docker compose -p seedcore logs -f ray-head

# Check worker logs
./ray-workers.sh logs
```

### Health Checks

```bash
# Check service health
docker compose -p seedcore ps

# Test API health
curl http://localhost:80/health

# Test Ray cluster
curl http://localhost:8265/api/version
```

## 🔄 Updates

### Rebuilding Images

```bash
# Rebuild with latest changes
docker build -f Dockerfile.ray -t seedcore-ray:latest --no-cache ..
docker build -f Dockerfile -t seedcore-api:latest --no-cache ..

# Restart services
docker compose -p seedcore restart
```

### Updating Dependencies

1. Update package versions in `Dockerfile.ray`
2. Rebuild images with `--no-cache`
3. Test thoroughly before deployment

## 📊 Performance

### Resource Usage

- **Memory**: ~2-4GB per Ray node (configurable)
- **CPU**: 1-4 cores per worker (configurable)
- **Storage**: Optimized images reduce pull/push time by 54%

### Scaling

- **Workers**: Use `./ray-workers.sh start <num_workers>`
- **API**: Scale with `docker compose -p seedcore up --scale seedcore-api=3`

## 🤝 Contributing

When making changes to Docker configuration:

1. Test image builds locally
2. Verify all services start correctly
3. Update this README if needed
4. Include size optimization considerations

## 📝 Changelog

### v2.0.0 - Image Optimization
- Reduced image size by 54% (2.21GB → 1.02GB)
- Switched to lightweight base image
- Added selective package installation
- Improved build context with `.dockerignore`
- Added comprehensive monitoring stack 