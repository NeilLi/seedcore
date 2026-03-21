# Local Host-Mode Helpers

This folder holds host-native SeedCore bring-up scripts for macOS/Linux development.

Use these when you want to run SeedCore directly on your machine without Kubernetes:

- `init-full-db-direct.sh`
- `run-api.sh`
- `run-hal.sh`
- `run-ray-head.sh`
- `run-serve-app.py`
- `run-bootstrap.sh`
- `run-ray-stack.sh`

These scripts are intentionally separate from the main `deploy/` entrypoints because they are:

- localhost-oriented
- best-effort developer workflows
- not the canonical Kubernetes deployment path

## Restart Sequence

### Lean local mode

Start the backing services first:

```bash
brew services start postgresql@17
brew services start redis
```

Initialize the database if needed:

```bash
bash deploy/local/init-full-db-direct.sh
```

Then start the API and HAL in separate terminals:

```bash
bash deploy/local/run-api.sh
```

```bash
bash deploy/local/run-hal.sh
```

Quick checks:

```bash
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/status
```

### Experimental host-Ray mode

Use this only when you need local Ray/Serve/bootstrap behavior.

Start local services:

```bash
brew services start postgresql@17
brew services start redis
```

Start the API and HAL in separate terminals:

```bash
bash deploy/local/run-api.sh
```

```bash
bash deploy/local/run-hal.sh
```

Start the Ray head in a dedicated terminal:

```bash
bash deploy/local/run-ray-head.sh foreground
```

Deploy the organism Serve app in another terminal:

```bash
python deploy/local/run-serve-app.py organism
```

Bootstrap the organism:

```bash
BOOTSTRAP_MODE=organism bash deploy/local/run-bootstrap.sh
```

Bootstrap one dispatcher with graph dispatchers disabled:

```bash
BOOTSTRAP_MODE=dispatchers DISPATCHER_COUNT=1 ENABLE_GRAPH_DISPATCHERS=false SEEDCORE_GRAPH_DISPATCHERS=0 bash deploy/local/run-bootstrap.sh
```

Quick checks:

```bash
curl http://127.0.0.1:8000/organism/health
curl http://127.0.0.1:8000/organism/init-status
```

### Shutdown

Stop the local runtime:

```bash
bash deploy/local/run-ray-head.sh stop
brew services stop postgresql@17
brew services stop redis
```
