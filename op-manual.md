# SeedCore Application Operation Manual

This manual provides instructions for operating the `seedcore` application stack using the primary control script, `sc-cmd.sh`. This script is the main entry point for starting, stopping, and managing all the services.

-----

## 🏗️ System Architecture

The application stack is managed by Docker Compose and is composed of several key service groups, defined by profiles in the `docker-compose.yml` file:

* **Core Services (`--profile core`):** The foundational databases that store the application's data.
    * `postgres`: SQL database with pgvector for vector embeddings.
    * `mysql`: General-purpose SQL database.
    * `neo4j`: Graph database for relationship data.
* **Ray Cluster (`--profile ray`):** The distributed computing backbone for processing tasks.
    * `ray-head`: The master node that manages the Ray cluster, runs Ray Serve for model deployment, and hosts the Ray Dashboard.
    * `ray-worker`: Scalable worker nodes that execute distributed tasks. These are defined in `ray-workers.yml`.
* **API Service (`--profile api`):** The main application interface.
    * `seedcore-api`: A FastAPI application that serves the primary API, interacts with the databases, and submits jobs to the Ray cluster.
* **Observability Stack (`--profile obs`):** Tools for monitoring and logging.
    * `prometheus`: Collects metrics from the Ray cluster and other services.
    * `grafana`: Provides dashboards for visualizing metrics.
    * `node-exporter`: Exports system-level metrics from the host machine.

-----

## 🚀 Main Commands (`./sc-cmd.sh`)

All operations are performed using the `sc-cmd.sh` script. Below are the available commands.

### **Start Cluster (`up`)**

This command builds and starts the entire application stack, including the databases, Ray cluster, and API.

* **Usage:**
  ```bash
  ./sc-cmd.sh up [num_workers]
  ```
* **Description:**
    * Starts all services defined in `docker-compose.yml` (core, ray, api, and obs profiles).
    * Waits for the `ray-head` container to become fully operational and for the internal Ray Serve applications to be ready. This can take a few minutes.
    * Scales the `ray-worker` service to the specified number of replicas.
* **Arguments:**
    * `[num_workers]` (Optional): The number of `ray-worker` containers to start. **Defaults to 3.**

### **Stop Cluster (`down`)**

This command stops and removes all containers, networks, and volumes associated with the project.

* **Usage:**
  ```bash
  ./sc-cmd.sh down
  ```
* **Description:** This is a complete teardown. It will stop and delete all running services, including the databases.

### **Restart Application (`restart`)**

This command performs a "hot reload" of the application layer, restarting the Ray cluster and API while leaving the databases running.

* **Usage:**
  ```bash
  ./sc-cmd.sh restart
  ```
* **Description:** This is the preferred way to apply changes to the application code without losing database state.
  1.  Stops and removes the existing `ray-worker`s.
  2.  Restarts the application services: `ray-head`, `seedcore-api`, `prometheus`, `grafana`, and `node-exporter`.
  3.  Waits for `ray-head` to become healthy again.
  4.  Starts the same number of `ray-worker`s that were running before the restart.

### **Restart API Only (`restart-api`)**

This command performs a quick restart of only the `seedcore-api` service.

* **Usage:**
  ```bash
  ./sc-cmd.sh restart-api
  ```
* **Description:** Useful during development for quickly applying changes made only to the API code without restarting the entire Ray cluster.

### **Check Status (`status`)**

Displays the current status of all running containers in the stack.

* **Usage:**
  ```bash
  ./sc-cmd.sh status
  ```
* **Description:** It provides two sections: one for the main services (`docker-compose.yml`) and one for the `ray-worker`s (`ray-workers.yml`).

### **View Logs (`logs`)**

Tails the logs for specific services. You must specify which service group you want to see.

* **Usage:**
  ```bash
  ./sc-cmd.sh logs {head|api|workers}
  ```
* **Arguments:**
    * `head`: Shows logs for the `ray-head` container.
    * `api`: Shows logs for the `seedcore-api` container.
    * `workers`: Shows aggregated logs for all running `ray-worker` containers.

-----

## 🌐 Accessing Services

Once the stack is running with `up`, the following services are available at these endpoints:

| Service | URL | Description |
| :--- | :--- | :--- |
| **SeedCore API** | `http://localhost:8002` | The main application API. |
| **Ray Dashboard** | `http://localhost:8265` | UI for monitoring the Ray cluster, jobs, and actors. |
| **Grafana** | `http://localhost:3000` | Dashboards for observing system metrics. (Default login: `admin`/`seedcore`) |
| **Prometheus** | `http://localhost:9090` | Direct access to the metrics collection server. |
| **PostgreSQL** | `localhost:5432` | Direct connection to the Postgres database. |
| **MySQL** | `localhost:3306` | Direct connection to the MySQL database. |
| **Neo4j Browser** | `http://localhost:7474` | Web interface for the Neo4j graph database. |

-----

## 🔧 Energy System Monitoring

The SeedCore energy system provides real-time monitoring through dedicated endpoints:

| Endpoint | URL | Description |
| :--- | :--- | :--- |
| **Energy Gradient** | `http://localhost:8002/energy/gradient` | Real-time energy telemetry with slopes and trends |
| **Current Energy** | `http://localhost:8002/energy/current` | Current energy values without slopes |
| **Energy Stats** | `http://localhost:8002/energy/stats` | Energy statistics and validation metrics |
| **Energy History** | `http://localhost:8002/energy/history/{term}` | Historical energy data for specific terms |

### Energy System Commands

```bash
# Get real-time energy gradient
curl http://localhost:8002/energy/gradient

# Reset energy ledger
curl -X POST http://localhost:8002/energy/reset

# Get energy statistics
curl http://localhost:8002/energy/stats
```

-----

## 🧪 Experimental Validation

The SeedCore system includes an experimental harness for validating energy descent:

```python
# Run energy validation experiments
from seedcore.experiments.harness import EnergyValidationHarness
from seedcore.organs.organism_manager import organism_manager
from seedcore.energy.api import _ledger

# Create harness and run experiments
harness = EnergyValidationHarness(organism_manager, _ledger)
results = await harness.experiment_A_pair()  # Pair energy validation
results = await harness.experiment_B_hyper()  # Hyper-edge validation
results = await harness.experiment_C_entropy()  # Entropy validation
results = await harness.experiment_D_memory()  # Memory validation

# Get experiment summary
summary = harness.get_experiment_summary()
```

-----

## 📊 Monitoring & Observability

### Grafana Dashboards

Access Grafana at `http://localhost:3000` with credentials `admin`/`seedcore` to view:

* **System Metrics**: CPU, memory, and network usage
* **Ray Cluster**: Worker status, job queues, and performance
* **Energy System**: Real-time energy trends and validation metrics
* **Database Performance**: Query times and connection pools

### Prometheus Metrics

Direct access to metrics at `http://localhost:9090`:

* **Energy Metrics**: `energy_term_value`, `energy_total`, `energy_delta_last_task`
* **Agent Metrics**: `agent_capability`, `agent_success_rate`, `agent_tasks_processed_total`
* **Memory Metrics**: `memory_tier_usage_bytes`, `memory_compression_ratio`
* **API Metrics**: `api_requests_total`, `api_request_duration_seconds`

### Ray Dashboard

Monitor the distributed computing cluster at `http://localhost:8265`:

* **Cluster Status**: Worker nodes and their health
* **Job Monitoring**: Task execution and performance
* **Actor Management**: Agent lifecycle and resource usage
* **Resource Utilization**: CPU, memory, and GPU usage

-----

## 🚨 Troubleshooting

### Common Issues

1. **Ray Head Not Starting**
   ```bash
   # Check Ray head logs
   ./sc-cmd.sh logs head
   
   # Restart Ray cluster
   ./sc-cmd.sh restart
   ```

2. **API Service Unavailable**
   ```bash
   # Check API logs
   ./sc-cmd.sh logs api
   
   # Quick API restart
   ./sc-cmd.sh restart-api
   ```

3. **Worker Nodes Not Joining**
   ```bash
   # Check worker logs
   ./sc-cmd.sh logs workers
   
   # Scale workers down and up
   ./sc-cmd.sh down
   ./sc-cmd.sh up 3
   ```

4. **Database Connection Issues**
   ```bash
   # Check core services status
   ./sc-cmd.sh status
   
   # Restart entire stack
   ./sc-cmd.sh down
   ./sc-cmd.sh up
   ```

### Debug Commands

```bash
# Check all container statuses
docker ps -a

# View detailed service logs
docker-compose logs -f [service_name]

# Check resource usage
docker stats

# Access container shell
docker exec -it [container_name] /bin/bash
```

-----

## 🔄 Development Workflow

### Typical Development Cycle

1. **Start Development Environment**
   ```bash
   ./sc-cmd.sh up 2  # Start with 2 workers for development
   ```

2. **Make Code Changes**
   - Edit source code in `src/seedcore/`
   - Update configuration in `src/seedcore/config/`

3. **Apply Changes**
   ```bash
   # For API changes only
   ./sc-cmd.sh restart-api
   
   # For application changes
   ./sc-cmd.sh restart
   
   # For complete rebuild
   ./sc-cmd.sh down
   ./sc-cmd.sh up
   ```

4. **Monitor Changes**
   ```bash
   # Check service status
   ./sc-cmd.sh status
   
   # Monitor logs
   ./sc-cmd.sh logs api
   ```

5. **Test Energy System**
   ```bash
   # Test energy endpoints
   curl http://localhost:8002/energy/gradient
   
   # Run validation experiments
   python -c "import asyncio; from seedcore.experiments.harness import EnergyValidationHarness; asyncio.run(EnergyValidationHarness().experiment_A_pair())"
   ```

### Production Deployment

1. **Scale for Production**
   ```bash
   ./sc-cmd.sh up 8  # Scale to 8 workers
   ```

2. **Monitor Performance**
   - Check Grafana dashboards
   - Monitor Ray Dashboard
   - Track energy system metrics

3. **Maintenance**
   ```bash
   # Rolling restart for updates
   ./sc-cmd.sh restart
   
   # Scale workers as needed
   docker-compose -f ray-workers.yml up -d --scale ray-worker=10
   ```

-----

## 📋 Quick Reference

### Essential Commands

| Command | Description |
| :--- | :--- |
| `./sc-cmd.sh up [N]` | Start cluster with N workers (default: 3) |
| `./sc-cmd.sh down` | Stop and remove all services |
| `./sc-cmd.sh restart` | Hot reload application layer |
| `./sc-cmd.sh status` | Check service status |
| `./sc-cmd.sh logs [service]` | View service logs |

### Key URLs

| Service | URL | Purpose |
| :--- | :--- | :--- |
| API | `http://localhost:8002` | Main application interface |
| Ray Dashboard | `http://localhost:8265` | Cluster monitoring |
| Grafana | `http://localhost:3000` | Metrics visualization |
| Energy Gradient | `http://localhost:8002/energy/gradient` | Real-time energy telemetry |

### Energy System Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/energy/gradient` | GET | Real-time energy telemetry |
| `/energy/current` | GET | Current energy values |
| `/energy/stats` | GET | Energy statistics |
| `/energy/history/{term}` | GET | Historical energy data |
| `/energy/reset` | POST | Reset energy ledger |

This operation manual provides comprehensive guidance for managing the SeedCore application stack, including the energy system monitoring and experimental validation capabilities. 