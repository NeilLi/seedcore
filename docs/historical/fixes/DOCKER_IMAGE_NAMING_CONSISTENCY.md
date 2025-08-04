# Docker Image Naming Consistency

## Overview

Updated Docker Compose configuration to use consistent image naming without the `docker-` prefix that was automatically added by Docker Compose.

## Problem

Docker Compose was automatically naming built images with the `docker-` prefix:
- `seedcore-ray-head:latest`
- `seedcore-ray-worker:latest`
- `seedcore-api:latest`
- `seedcore-db-seed:latest`

This created inconsistency with other images that don't have the prefix.

## Solution

Added explicit `image:` tags to all services in Docker Compose files to ensure consistent naming:

### Updated Files

#### `docker/docker-compose.yml`
```yaml
# Before (automatic naming with docker- prefix)
db-seed:
  build:
    context: ..
    dockerfile: docker/Dockerfile

# After (explicit naming)
db-seed:
  build:
    context: ..
    dockerfile: docker/Dockerfile
  image: seedcore-db-seed:latest
```

#### `docker/ray-workers.yml`
```yaml
# Before (automatic naming with docker- prefix)
ray-worker:
  build:
    context: ..
    dockerfile: docker/Dockerfile.ray

# After (explicit naming)
ray-worker:
  build:
    context: ..
    dockerfile: docker/Dockerfile.ray
  image: ray-worker:latest
```

## New Image Names

| Service | Old Name | New Name |
|---------|----------|----------|
| Ray Head | `seedcore-ray-head:latest` | `seedcore-ray-head:latest` |
| Ray Worker | `seedcore-ray-worker:latest` | `seedcore-ray-worker:latest` |
| SeedCore API | `seedcore-api:latest` | `seedcore-api:latest` |
| DB Seed | `seedcore-db-seed:latest` | `seedcore-db-seed:latest` |

## Migration Steps

### 1. Rebuild Images
```bash
# Use the provided script
./scripts/rebuild-docker-images.sh

# Or manually:
cd docker
docker compose down
docker compose -f ray-workers.yml down

# Remove old images
docker rmi seedcore-ray-head:latest seedcore-ray-worker:latest seedcore-api:latest seedcore-db-seed:latest

# Build new images
docker compose build
docker compose -f ray-workers.yml build
```

### 2. Start Services
```bash
cd docker
docker compose up -d
./ray-workers.sh start 3
```

### 3. Verify
```bash
docker images | grep -E "(seedcore|ray)" | grep -v "docker-"
```

## Benefits

1. **Consistent Naming**: All custom images follow the same naming pattern
2. **Cleaner Output**: `docker images` output is more organized
3. **Easier Management**: No confusion between prefixed and non-prefixed images
4. **Professional Appearance**: Consistent with Docker best practices

## Scripts

### `scripts/rebuild-docker-images.sh`
Automated script to:
- Stop all containers
- Remove old images with `docker-` prefix
- Build new images with consistent naming
- Show the new image list

## Verification

After migration, your `docker images` output should show:
```
REPOSITORY            TAG       IMAGE ID       CREATED         SIZE
seedcore-ray-head     latest    [new-id]       [timestamp]     [size]
seedcore-ray-worker   latest    [new-id]       [timestamp]     [size]
seedcore-api          latest    [new-id]       [timestamp]     [size]
seedcore-db-seed      latest    [new-id]       [timestamp]     [size]
```

No more `docker-` prefixed images should be present.

---
*Updated: $(date)* 