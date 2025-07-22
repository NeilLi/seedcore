# SeedCore Holon Fabric Setup

This directory contains the Docker setup for the SeedCore hierarchical memory fabric using PGVector and Neo4j.

## Architecture

- **PGVector**: Vector store for Mlt (long-term memory) with 768-dimensional embeddings
- **Neo4j**: Graph database for relationship storage and traversal
- **SeedCore API**: FastAPI server with integrated Holon Fabric

## Quick Start

### 1. Start the Services

```bash
cd docker
docker-compose up -d
```

This will start:
- PostgreSQL with PGVector extension on port 5432
- Neo4j on ports 7474 (HTTP) and 7687 (Bolt)
- SeedCore API on port 8000

### 2. Initialize Databases

The databases will be automatically initialized with sample data when the containers start.

### 3. Test the Setup

```bash
# Test the API
curl http://localhost:8000/system/status

# Test RAG endpoint
curl -X POST http://localhost:8000/rag \
  -H "Content-Type: application/json" \
  -d '{"embedding": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8], "k": 5}'

# Get holon statistics
curl http://localhost:8000/holon/stats
```

## Manual Database Setup

If you need to manually initialize the databases:

### PostgreSQL Setup

```bash
# Connect to PostgreSQL
docker exec -it seedcore-postgres psql -U postgres -d postgres

# Run the initialization script
\i /docker-entrypoint-initdb.d/init_pgvector.sql
```

### Neo4j Setup

1. Open Neo4j Browser at http://localhost:7474
2. Login with username `neo4j` and password `password`
3. Run the Cypher commands from `setup/init_neo4j.cypher`

## API Endpoints

### Holon Fabric Endpoints

- `POST /rag` - Fuzzy search with holon expansion
- `POST /holon/insert` - Insert a new holon
- `GET /holon/{uuid}` - Get a specific holon
- `POST /holon/relationship` - Create a relationship between holons
- `GET /holon/stats` - Get fabric statistics

### Legacy Endpoints

- `GET /system/status` - System status
- `GET /energy/gradient` - Energy state
- `POST /actions/run_two_agent_task` - Run agent task
- `GET /run_memory_loop` - Run memory loop
- `GET /run_pgvector_neo4j_experiment` - Run experiment

## Environment Variables

Set these environment variables for the API:

```bash
export PG_DSN="postgresql://postgres:password@localhost:5432/postgres"
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="password"
```

## Running Experiments

### 1. Start the API Server

```bash
# From project root
PYTHONPATH=src uvicorn src.seedcore.telemetry.server:app --reload --host 0.0.0.0 --port 8000
```

### 2. Run Retrieval Traffic Hammer

```bash
python scripts/blast_retrieval.py
```

This will send 50,000 random queries to test the system.

### 3. Run Compression Sweep

```python
# In a Python notebook or script
from src.seedcore.memory.consolidation_worker import run_consolidation_sweep
from src.seedcore.memory.holon_fabric import HolonFabric

# Initialize fabric
fabric = HolonFabric(vec_store, graph)

# Run sweep
tau_values = [0.1, 0.2, 0.4, 0.8]
results = await run_consolidation_sweep(fabric, mw, tau_values)
```

## Monitoring

- **Neo4j Browser**: http://localhost:7474
- **API Documentation**: http://localhost:8000/docs
- **Health Checks**: 
  - PostgreSQL: `docker exec seedcore-postgres pg_isready -U postgres`
  - Neo4j: `curl http://localhost:7474`

## Troubleshooting

### Common Issues

1. **Connection refused**: Make sure all containers are healthy
2. **Import errors**: Check PYTHONPATH and __init__.py files
3. **Database errors**: Check logs with `docker-compose logs`

### Logs

```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs postgres
docker-compose logs neo4j
docker-compose logs seedcore-api
```

### Reset Everything

```bash
# Stop and remove everything
docker-compose down -v

# Rebuild and start
docker-compose up --build -d
```

## Development

### Adding New Endpoints

1. Add the endpoint to `src/seedcore/telemetry/server.py`
2. Test with curl or the API docs
3. Update this README

### Modifying Schemas

1. Update the SQL/Cypher files in `setup/`
2. Rebuild containers: `docker-compose down -v && docker-compose up --build -d`

### Performance Tuning

- **PGVector**: Adjust HNSW index parameters
- **Neo4j**: Tune memory settings in docker-compose.yml
- **API**: Adjust uvicorn workers and timeout settings 