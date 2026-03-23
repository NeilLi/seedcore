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
- `run-task-stack.sh`

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

### Task execution stack

Use this when you want queued tasks to execute locally through `/pipeline/route-and-execute`.

It starts:

- Ray head
- Serve `organism`
- Serve `coordinator`
- organism bootstrap
- one queue dispatcher

Start:

```bash
bash deploy/local/run-task-stack.sh start
```

Status:

```bash
bash deploy/local/run-task-stack.sh status
```

Stop:

```bash
bash deploy/local/run-task-stack.sh stop
```

Quick checks:

```bash
curl http://127.0.0.1:8000/organism/health
curl http://127.0.0.1:8000/organism/init-status
curl http://127.0.0.1:8000/-/routes
```

### Shutdown

Stop the local runtime:

```bash
bash deploy/local/run-ray-head.sh stop
brew services stop postgresql@17
brew services stop redis
```
