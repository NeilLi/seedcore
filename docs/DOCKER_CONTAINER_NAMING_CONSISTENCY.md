# Docker Container Naming Consistency

## Overview

Updated Docker Compose configuration to use consistent container naming with the `seedcore-` prefix for all custom containers.

## Problem

Container names were inconsistent:
- `ray-head` (missing seedcore- prefix)
- `docker-ray-worker-*` (using docker- prefix instead of seedcore-)
- `seedcore-*` (correct format)

## Solution

Updated all container names to use the consistent `seedcore-` prefix:

### Updated Files

#### `docker/docker-compose.yml`
```yaml
# Before
ray-head:
  container_name: ray-head

# After
seedcore-ray-head:
  container_name: seedcore-ray-head
```

#### `docker/ray-workers.yml`
```yaml
# Before
ray-worker:
  # No explicit image name

# After
seedcore-ray-worker:
  image: seedcore-ray-worker:latest
```

## Container Name Changes

| Service | Old Container Name | New Container Name |
|---------|-------------------|-------------------|
| Ray Head | `ray-head` | `seedcore-ray-head` |
| Ray Workers | `docker-ray-worker-*` | `seedcore-ray-worker-*` |
| API | `seedcore-api` | `seedcore-api` (unchanged) |
| DB Seed | `seedcore-db-seed` | `seedcore-db-seed` (unchanged) |

## Image Name Changes

| Service | Old Image Name | New Image Name |
|---------|----------------|----------------|
| Ray Head | `ray-head:latest` | `seedcore-ray-head:latest` |
| Ray Workers | `docker-ray-worker:latest` | `seedcore-ray-worker:latest` |
| API | `seedcore-api:latest` | `seedcore-api:latest` (unchanged) |
| DB Seed | `seedcore-db-seed:latest` | `seedcore-db-seed:latest` (unchanged) |

## Updated References

### Service Dependencies
- All `depends_on` references updated from `ray-head` to `seedcore-ray-head`
- Ray workers now connect to `seedcore-ray-head:6379`

### Network Communication
- API service: `RAY_ADDRESS: ray://seedcore-ray-head:10001`
- Workers: `ray start --address=seedcore-ray-head:6379`

## Migration Steps

### 1. Stop Current Services
```bash
cd docker
docker compose down
docker compose -f ray-workers.yml down
```

### 2. Remove Old Containers and Images
```bash
# Remove old containers
docker rm -f ray-head docker-ray-worker-1 docker-ray-worker-2 docker-ray-worker-3 2>/dev/null || true

# Remove old images
docker rmi ray-head:latest docker-ray-worker:latest 2>/dev/null || true
```

### 3. Rebuild with New Names
```bash
# Use the updated script
../scripts/rebuild-docker-images.sh

# Or manually:
docker compose build
docker compose -f ray-workers.yml build
```

### 4. Start Services
```bash
docker compose up -d
./ray-workers.sh start 3
```

## Verification

After migration, your containers should be named:
```
seedcore-ray-head
seedcore-ray-worker-1
seedcore-ray-worker-2
seedcore-ray-worker-3
seedcore-api
seedcore-db-seed
seedcore-postgres
seedcore-mysql
seedcore-neo4j
seedcore-prometheus
seedcore-grafana
```

## Benefits

1. **Consistent Naming**: All containers follow the same naming pattern
2. **Clear Ownership**: `seedcore-` prefix clearly identifies project containers
3. **Easier Management**: No confusion between different naming conventions
4. **Professional Appearance**: Consistent with Docker best practices

## Scripts Updated

- `scripts/rebuild-docker-images.sh` - Updated to use new service names
- All references to `ray-head` changed to `seedcore-ray-head`
- All references to `ray-worker` changed to `seedcore-ray-worker`

---
*Updated: $(date)* 