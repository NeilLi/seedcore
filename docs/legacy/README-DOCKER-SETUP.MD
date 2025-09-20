# Docker Setup Guide for SeedCore Local Development

This guide explains how to set up and run SeedCore services using Docker Compose with your locally built images and the `seedcore-network`.

## 🚀 Quick Start

### 1. Setup Docker Network

```bash
# Create the required Docker network
./docker/setup-network.sh

# Or manually:
docker network create --driver bridge seedcore-network
```

### 2. Build Local Images

```bash
# Build Ray head node
docker build -f docker/Dockerfile.ray -t seedcore-ray-head:latest .

# Build API service
docker build -f docker/Dockerfile -t seedcore-api:latest .

# Build Ray workers
docker build -f docker/Dockerfile.ray -t seedcore-ray-worker:latest .
```

### 3. Start Services

```bash
# Start core data stores (PostgreSQL, MySQL, Redis, Neo4j)
docker compose --profile core up -d

# Start Ray cluster
docker compose --profile ray up -d

# Start API service
docker compose --profile api up -d

# Start observability stack (Prometheus, Grafana)
docker compose --profile obs up -d

# Or start everything at once
docker compose --profile core --profile ray --profile api --profile obs up -d
```

## 🌐 Network Configuration

The `seedcore-network` is configured as an **external network** in both:
- `docker-compose.yml` (main services)
- `ray-workers.yml` (Ray worker scaling)

This ensures all services can communicate using container names as hostnames.

## 📦 Service Profiles

### Core Services (`--profile core`)
- **PostgreSQL** with pgvector extension
- **MySQL** 8.0
- **Redis** 7.2 Alpine
- **Neo4j** 5.15
- **PgBouncer** connection pooling

### Ray Services (`--profile ray`)
- **Ray Head Node** with Ray Serve
- **Ray Workers** (scalable)

### API Services (`--profile api`)
- **SeedCore API** service

### Observability (`--profile obs`)
- **Prometheus** metrics collection
- **Grafana** dashboards
- **Node Exporter** system metrics

## 🔧 Configuration Files

### Environment Variables
Copy and customize the environment file:
```bash
cp docker/env.example docker/.env
# Edit docker/.env with your specific values
```

### Database Connection Strings
The services are pre-configured to use these connection strings:
```bash
# PostgreSQL (via PgBouncer)
PG_DSN=postgresql://postgres:password@postgres:5432/postgres

# MySQL
MYSQL_DATABASE_URL=mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# Neo4j
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
```

## 🐳 Container Communication

All services communicate using container names within the `seedcore-network`:

- **Ray Head**: `ray-head:10001` (Ray), `ray-head:8000` (Serve)
- **API Service**: `seedcore-api:8002`
- **Databases**: `postgres:5432`, `mysql:3306`, `redis:6379`, `neo4j:7687`
- **PgBouncer**: `postgresql-pgbouncer:6432`

## 📊 Monitoring & Health Checks

### Service Health
```bash
# Check all service statuses
docker compose ps

# Check specific service logs
docker compose logs ray-head
docker compose logs seedcore-api
docker compose logs postgres
```

### Ray Dashboard
- **URL**: http://localhost:8265
- **Ray Serve**: http://localhost:8000
- **Metrics**: http://localhost:8080

### Grafana Dashboard
- **URL**: http://localhost:3000
- **Default**: `admin/seedcore`

## 🔄 Scaling Ray Workers

### Local Workers (within compose network)
```bash
# Scale to 3 workers
docker compose --profile ray up -d --scale ray-worker=3
```

### Remote Workers (external hosts)
```bash
# Use the provided script
./docker/sc-cmd.sh up-worker --head-ip=<HEAD_IP> --worker-ip=<WORKER_IP>
```

## 🧹 Cleanup

### Stop Services
```bash
# Stop all services
docker compose down

# Stop specific profiles
docker compose --profile core down
docker compose --profile ray down
```

### Remove Network
```bash
# Clean up the network (stops all containers first)
./docker/cleanup-network.sh
```

## 🐛 Troubleshooting

### Common Issues

#### 1. Network Not Found
```bash
Error: network "seedcore-network" not found
```
**Solution**: Run `./docker/setup-network.sh`

#### 2. Port Conflicts
```bash
Error: port is already allocated
```
**Solution**: Check for existing containers or services using the ports

#### 3. Image Not Found
```bash
Error: manifest for seedcore-ray-head:latest not found
```
**Solution**: Build the images first using the build commands above

#### 4. Database Connection Issues
```bash
# Check if databases are healthy
docker compose ps | grep -E "(postgres|mysql|redis|neo4j)"

# Check database logs
docker compose logs postgres
docker compose logs mysql
```

### Debug Commands

```bash
# Inspect network
docker network inspect seedcore-network

# Check container connectivity
docker exec seedcore-api ping postgres
docker exec seedcore-api ping ray-head

# View service endpoints
docker compose exec seedcore-api env | grep -E "(PG_DSN|MYSQL|REDIS|NEO4J)"
```

## 📋 Service Dependencies

The services start in this order due to health checks:
1. **Core databases** (PostgreSQL, MySQL, Redis, Neo4j)
2. **Ray Head** (waits for databases)
3. **API Service** (waits for Ray Head and databases)
4. **Observability** (waits for API and Ray Head)

## 🔐 Security Notes

- All services run within the `seedcore-network` (not exposed to host)
- Only necessary ports are exposed to host (8000, 8002, 8265, 3000, 9090)
- Database passwords are set in environment variables
- Consider using Docker secrets for production deployments

## 🚀 Production Considerations

For production use:
1. Use proper secrets management
2. Configure persistent volumes for data
3. Set up proper monitoring and alerting
4. Use external load balancers
5. Configure backup strategies for databases
6. Set resource limits and requests
7. Use multi-stage builds for smaller images

## 📚 Additional Resources

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Ray Documentation](https://docs.ray.io/)
- [PostgreSQL with pgvector](https://github.com/pgvector/pgvector)
- [Neo4j Docker](https://neo4j.com/developer/docker/)


