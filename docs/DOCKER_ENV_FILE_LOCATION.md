# Docker Environment File Location

## Overview

The `.env` file has been moved from the project root directory to the `docker/` subdirectory for better organization and to keep all Docker-related configuration files together.

## File Location

### Current Location
```
seedcore/
├── docker/
│   ├── .env                    # Environment variables
│   ├── docker-compose.yml      # Main services
│   ├── ray-workers.yml         # Ray workers
│   └── [other docker files]
└── [project files]
```

### Previous Location
```
seedcore/
├── .env                        # ❌ Old location
├── docker/
│   ├── docker-compose.yml
│   └── [other docker files]
└── [project files]
```

## Configuration Changes

### Docker Compose Update
The `docker-compose.yml` file has been updated to reference the new `.env` file location:

```yaml
# Before
seedcore-api:
  env_file:
    - ../.env  # Points to project root

# After
seedcore-api:
  env_file:
    - .env     # Points to docker directory
```

## Benefits

1. **Better Organization**: All Docker-related files are in one directory
2. **Cleaner Root**: Project root is less cluttered
3. **Logical Grouping**: Environment variables are with Docker configuration
4. **Easier Management**: All Docker config in one place

## Usage

### Starting Services
```bash
cd docker
docker compose up -d
```

### Environment Variables
The `.env` file in the `docker/` directory contains:
- Database connection settings
- Ray cluster configuration
- API server settings
- Monitoring configuration

### File Contents
The `.env` file includes variables like:
```bash
# Database Configuration
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password
MYSQL_ROOT_PASSWORD=rootpassword

# Ray Configuration
RAY_HEAD_HOST=ray-head
RAY_HEAD_PORT=10001

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
```

## Migration Notes

If you have existing `.env` files in the root directory:
1. **Copy** the file to `docker/.env`
2. **Remove** the old file from the root directory
3. **Verify** Docker Compose works with the new location

## Verification

To verify the configuration is correct:
```bash
cd docker
docker compose config --quiet
```

This should complete without errors if the `.env` file is properly located and configured.

---
*Updated: $(date)* 