### Ray cluster operations reference

This document summarizes how the SeedCore Ray cluster is configured and operated using Docker Compose and helper scripts.

## Architecture overview

- **Head node**: `ray-head` (starts Ray, Ray Client Server, Ray Serve, Dashboard)
- **Workers (local)**: `ray-worker` services launched inside the Compose network
- **Workers (remote)**: `ray-worker-remote` services launched via host networking on external machines

## Ray ports in this setup

| Port | Role | Who connects | Notes |
| --- | --- | --- | --- |
| 6380 | GCS (Global Control Store) | Workers, internal cluster RPC | Workers join the cluster using `--address=<head>:6380` |
| 10001 | Ray Client Server | Developer scripts, health checks | Client-mode convenience for apps and tools; not needed by workers |
| 8265 | Ray Dashboard | Browser | Web UI for monitoring |
| 8000 | Ray Serve HTTP | HTTP clients | ML inference endpoints |
| 8076 / 8077 | Object/Node Manager | Internal | Explicit for remote workers (host networking) |
| 11000–11020 | Worker RPC ports | Internal | Port range for worker processes on remote hosts |

## Where things are defined

- `docker/docker-compose.yml`
  - Service `ray-head` (build/image, ports, env, healthcheck)
  - Exposes 8265, 8000, 8080, 6380
- `docker/start-ray-with-serve.sh`
  - Starts the head: `--port=6380`, `--ray-client-server-port=10001`
  - Starts Ray Serve (HTTP on 8000)
- `docker/ray-workers.yml`
  - Anchors for worker environment and base container
  - `ray-worker` (local, on Compose network): joins head via `ray-head:6380`
  - `ray-worker-remote` (host network, external hosts): joins via `${HEAD_IP}:6380`
- `docker/sc-cmd.sh`
  - Cluster lifecycle commands: `up`, `down`, `restart`, `status`, `logs`
  - Scaling: `scale_workers` for local workers
  - Remote workers: `up-worker [num_workers]` with fixed head IP (overridable)

## Commands

- Start full stack (core, ray, api, obs) and scale workers:
  ```bash
  ./docker/sc-cmd.sh up 3
  ```

- Scale local workers later (in-network `ray-worker`):
  ```bash
  docker compose -f docker/docker-compose.yml -f docker/ray-workers.yml -p seedcore up -d --no-deps --scale ray-worker=5 ray-worker
  ```

- Bring up remote workers on a separate host (EC2, etc.):
  ```bash
  # On the remote host that should run workers
  ./docker/sc-cmd.sh up-worker 1
  ```
  - Uses fixed head IP set in `sc-cmd.sh` (defaults to `172.31.17.143`); override with `HEAD_IP_OVERRIDE` if needed.
  - Joins the head via `--address=<HEAD_IP>:6380`.
  - Uses host networking and pins ports (8076/8077, 11000–11020).

- Other operations:
  ```bash
  ./docker/sc-cmd.sh status
  ./docker/sc-cmd.sh logs head
  ./docker/sc-cmd.sh logs workers
  ./docker/sc-cmd.sh restart
  ./docker/sc-cmd.sh down
  ```

## Worker configurations

### Local workers (`ray-worker`)

- Network: `seedcore-network` (Compose)
- Join: `ray start --address=ray-head:6380`
- CPU tuning: `RAY_WORKER_CPUS` (defaults to 1)

### Remote workers (`ray-worker-remote`)

- Network: host
- Join: `ray start --address=${HEAD_IP}:6380`
- Node IP and ports are explicit for stability on host networking:
  - `--node-ip-address=${WORKER_IP}`
  - `--object-manager-port=${RAY_OBJECT_MANAGER_PORT:-8076}`
  - `--node-manager-port=${RAY_NODE_MANAGER_PORT:-8077}`
  - `--min-worker-port=${RAY_MIN_WORKER_PORT:-11000}`
  - `--max-worker-port=${RAY_MAX_WORKER_PORT:-11020}`
- CPU tuning: `RAY_WORKER_CPUS`
- Env variable defaults to avoid compose warnings when unset:
  - `HEAD_IP` defaults to `ray-head` in YAML (real value provided by `sc-cmd.sh` for remote)
  - `WORKER_IP` defaults to `127.0.0.1` in YAML

## Client vs cluster ports (quick guide)

- Use `6380` for cluster join (workers, system components)
- Use `ray://<host>:10001` for client-mode (`RAY_ADDRESS`) in developer tools and services

By default, the head enables client server on 10001, but workers never need it to join.

## Security and networking notes

- Keep 10001 internal unless you explicitly need off-host client-mode access. If needed, add a port mapping to `ray-head` (e.g., `"10001:10001"`) and restrict via security groups/firewall.
- Ensure the head node allows inbound 6380 from worker hosts, and the remote worker hosts allow inbound 8076/8077 and 11000–11020 (host network).

## Troubleshooting

- Ray head healthy but workers not joining:
  - Verify security groups for 6380 and worker host port ranges
  - Check `docker logs seedcore-ray-worker-*`

- Compose warnings about `HEAD_IP`/`WORKER_IP`:
  - Mitigated by defaults in `ray-workers.yml` (`HEAD_IP:-ray-head`, `WORKER_IP:-127.0.0.1`)

- Client-mode connection failures:
  - Confirm the head started with `--ray-client-server-port=10001`
  - From inside containers that use client-mode: `ray.init(address=os.getenv("RAY_ADDRESS"))`

## Notable improvements captured here

- Single source of truth for worker config (`docker/ray-workers.yml`) with YAML anchors
- `ray-worker-remote` added for remote hosts (no adhoc YAML generation)
- `sc-cmd.sh up-worker [num_workers]` uses fixed head IP (`172.31.17.143`), overridable via `HEAD_IP_OVERRIDE`
- Suppressed unset variable warnings with YAML defaults
- `scale_workers` only affects `ray-worker` and avoids unintentionally starting remote workers

## Quick reference

- Start 3 workers locally:
  ```bash
  ./docker/sc-cmd.sh up 3
  ```
- Start 2 remote workers on a separate host:
  ```bash
  ./docker/sc-cmd.sh up-worker 2
  # or target a different head for this invocation
  HEAD_IP_OVERRIDE=172.31.99.50 ./docker/sc-cmd.sh up-worker 2
  ```
- Scale local workers to 5:
  ```bash
  docker compose -f docker/docker-compose.yml -f docker/ray-workers.yml -p seedcore up -d --no-deps --scale ray-worker=5 ray-worker
  ```


