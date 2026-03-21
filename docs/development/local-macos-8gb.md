# SeedCore On macOS With 8GB RAM

This is the practical low-memory path for local SeedCore development on macOS.

## What Not To Run

The default local deploy path is too heavy for an 8GB Mac:

- `README.md` recommends **16GB+ RAM** for the full local `kind` + Kubernetes stack.
- `deploy/k8s/rayservice.yaml` requests **4Gi** for the Ray head and **4Gi** for one Ray worker.
- `deploy/helm/postgresql/values.yaml` requests **2Gi** for PostgreSQL.

That means the standard `deploy/deploy-all.sh` flow is not a good fit for an 8GB machine.

## Recommended Local Mode

Run SeedCore in a host-native developer mode:

1. Use local PostgreSQL with pgvector.
2. Use local Redis.
3. Run the FastAPI app directly on macOS.
4. Skip Ray, HAL, Neo4j, MySQL, observability, and optional ML unless you are actively testing them.

This gives you the active API surface with the lowest stable memory footprint.

## Why This Works

- `src/seedcore/main.py` hard-requires PostgreSQL at startup.
- Redis is attempted for some PKG and replay paths, but some startup logic treats Redis failure as non-fatal.
- The API verifies database functions from repo migrations:
  - `ensure_task_node(uuid)`
  - `pkg_active_snapshot_id(pkg_env)`

So the real minimum for smooth local API work is:

- Postgres with the full SeedCore migrations applied
- Redis
- No local Ray cluster by default

## Setup

### 1. Start local services

Use Homebrew or very small containers.

Suggested Homebrew services:

```bash
brew install postgresql@17 redis pgvector
brew services start postgresql@17
brew services start redis
```

If your Postgres does not already have `vector`, install pgvector for that instance first.

### 2. Apply the full SeedCore schema directly

Use the direct init script:

```bash
DB_HOST=127.0.0.1 \
DB_PORT=5432 \
DB_USER=postgres \
DB_PASS=password \
DB_NAME=seedcore \
bash deploy/local/init-full-db-direct.sh
```

### 3. Create a lean Python environment

Keep the install CPU-only and skip optional ML extras.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

### 4. Run the API directly

```bash
export PG_DSN=postgresql://postgres:password@127.0.0.1:5432/seedcore
export REDIS_HOST=127.0.0.1
export REDIS_PORT=6379
export RUN_DDL_ON_STARTUP=true
export PYTHONPATH=/Users/ningli/project/seedcore/src

uvicorn seedcore.main:app --host 127.0.0.1 --port 8002
```

### 5. Verify

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/readyz
curl http://127.0.0.1:8002/api/v1/pkg/status
```

## If You Need Kubernetes Anyway

Treat the Kubernetes path as a separate high-memory workflow.
The old root-level `*-local.sh` Kubernetes helpers have been removed in favor of the host-native flow under `deploy/local/`.
If you need Kind or K8s, use the main scripts in `deploy/` directly and expect to tune them manually for this machine.

## Experimental Host-Ray Mode

If you specifically need Ray + bootstrap on macOS, use the host-mode helpers in `deploy/`.
This is best-effort dev mode, not the default smooth path for 8GB.

Recommended sequence:

```bash
bash deploy/local/run-api.sh
bash deploy/local/run-hal.sh
bash deploy/local/run-ray-head.sh foreground
```

Then, in another terminal:

```bash
python deploy/local/run-serve-app.py organism
```

Then bootstrap the organism and dispatchers:

```bash
BOOTSTRAP_MODE=organism bash deploy/local/run-bootstrap.sh
BOOTSTRAP_MODE=dispatchers DISPATCHER_COUNT=1 ENABLE_GRAPH_DISPATCHERS=false SEEDCORE_GRAPH_DISPATCHERS=0 bash deploy/local/run-bootstrap.sh
```

Health checks:

```bash
curl http://127.0.0.1:8000/organism/health
curl http://127.0.0.1:8000/organism/init-status
```

Notes:

- `deploy/local/run-ray-head.sh start` is an experimental detached launcher.
- `deploy/local/run-ray-head.sh foreground` is the more reliable fallback when detached mode is flaky.
- The host-mode env sets repo-local config paths so Serve workers use `config/organism.yaml` instead of `/app/config/organism.yaml`.

## Apple Silicon Note

This machine is `arm64`. The current build defaults to `linux/amd64` in `build.sh`, which is heavier on Apple Silicon.

If you really need a local image build, prefer:

```bash
PLATFORM=linux/arm64 ENABLE_ML=0 ./build.sh
```

## Summary

For an 8GB Mac, the smooth path is:

- direct local Postgres + Redis
- direct API run on the host
- no Kind cluster
- no Ray unless you are specifically testing distributed execution
- no optional ML stack by default

Treat the full Kubernetes deploy as a CI/demo/high-memory workflow, not the day-to-day local development path.
