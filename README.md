# SeedCore: A Neuro-Symbolic Cognitive Architecture

[![Run Tests](https://github.com/NeilLi/seedcore/actions/workflows/tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/tests.yml)

SeedCore is a self-evolving cognitive operating system that fuses distributed computing with biological design principles. It orchestrates a persistent cognitive organism—a living runtime that supports real-time adaptation, deep structural reasoning, and autonomous self-repair.

Built on Kubernetes and Ray, SeedCore replaces monolithic control logic with a Planes of Control architecture that cleanly separates high-level strategy from low-level execution. It integrates System 1 (reflexive) and System 2 (deliberative) pipelines, handling high-velocity events on the fast path while reserving costly reasoning for high-entropy anomalies.

## Core Architecture: Planes of Control

SeedCore is organized into four operational planes, flowing from abstract strategy to concrete computation:

### 🧠 Intelligence Plane (Cognitive Service)

A shared Brain-as-a-Service layer providing neuro-symbolic reasoning and strategic orchestration. It dynamically allocates computational profiles (Fast vs Deep) based on task complexity, guarantees thread-safe execution across concurrent requests, and hydrates context on demand from persistent storage.

This plane bridges vector-space anomalies with semantic graph neighborhoods via Hypergraph Neural Networks (HGNN), enabling LLMs to reason about structural root causes (e.g., "the cluster is fractured") rather than only react to raw logs or text.

### 🎮 Control Plane (Coordinator Service)

The strategic cortex. It ingests stimuli and governs system behavior using an Online Change-Point Sentinel (OCPS) to detect "surprise" via information entropy. It leverages a Policy Knowledge Graph (PKG) for governance and drives the Plan → Execute → Audit loop, decomposing abstract intentions into concrete, executable sub-tasks.

### ⚡ Execution Plane (Organism Service)

The nervous system. A high-performance, distributed runtime managing a workforce of persistent, stateful agents acting as local reflex layers.

Agents:

- React to tasks and execute tool calls
- Enforce RBAC (tools & data scopes)
- Compute local salience scores
- Advertise their specialization and skills

This plane handles dynamic routing, load balancing, sticky session affinity (`agent_tunnel`), and tool execution with millisecond latency. Agents focus on local execution only; global routing, cognitive reasoning, and cross-agent coordination are the responsibility of the Control and Intelligence planes.

### ⚙️ Infrastructure Plane (ML Service)

The computational substrate. It exposes the raw "physics and math" of the organism, hosting:

- XGBoost services for regime detection
- Drift detectors for data distribution shifts
- The HGNN inference engine for structural reasoning

## Key Capabilities

**Tiered Cognition**

Dynamically switches between Fast Path (heuristic/reflexive) and Deep Path (planner/reasoning) execution based on both semantic urgency and measured drift in incoming signals.

**Energy-Driven Dynamics**

Agents and organs operate under a metabolic energy budget (`E_state`), creating feedback loops that naturally dampen runaway processes and reward efficient problem-solving.

**Neuro-Symbolic Bridge**

Combines the speed of neural models (for embedding and pattern matching) with the interpretability of symbolic logic (for planning, constraints, and rule enforcement).

**Config-Driven Perception**

The Eventizer engine converts unstructured inputs into structured semantic signals ("Tags") using deterministic, hot-swappable pattern definitions, ensuring the organism perceives the world consistently across all planes.

## 🚀 Quick Start (Kubernetes + KubeRay)

### Prerequisites
- **Kubernetes Tools**: `kubectl`, `kind`, `helm`
- **Docker**: For building and loading images
- **System Requirements**: 16GB+ RAM, 4+ CPU cores recommended
- **Operating System**: Linux with Docker support

### Option 1: Complete Automated Deployment
```bash
# Clone and setup
git clone https://github.com/NeilLi/seedcore.git
cd seedcore

# Initialize environment variables and configuration
./deploy/init_env.sh
cp docker/env.example docker/.env

# Run complete deployment pipeline
./deploy/deploy-seedcore.sh

# Start port forwarding for accessing cluster services locally
./deploy/port-forward.sh

# Setup and verify the host environment architecture
./setup_host_env.sh

```

### Option 2: Step-by-Step Manual Deployment

#### 1. Clone and Setup
```bash
git clone https://github.com/NeilLi/seedcore.git
cd seedcore
```

#### 2. Build Docker Image
```bash
./build.sh
```

#### 3. Start the Kubernetes Cluster
```bash
cd deploy
./setup-kind-only.sh
```

#### 4. Deploy Core Services
```bash
# Deploy databases (PostgreSQL, MySQL, Redis, Neo4j)
./setup-cores.sh
```

#### 5. Initialize Databases
```bash
# Initialize database schema and runtime registry (19 migrations)
./init-databases.sh
```

#### 6. Deploy Storage and RBAC
```bash
# Deploy persistent volume claims
kubectl apply -f k8s/seedcore-data-pvc.yaml

# Deploy RBAC and service accounts
kubectl apply -f k8s/seedcore-serviceaccount.yaml
kubectl apply -f k8s/seedcore-rolebinding.yaml
kubectl apply -f k8s/allow-api-egress.yaml
kubectl apply -f k8s/allow-api-to-ray-serve.yaml
kubectl apply -f k8s/xgb-pvc.yaml
```

#### 7. Deploy Ray Services
```bash
# Deploy Ray cluster and Ray Serve
./setup-ray-serve.sh

# Deploy stable Ray service for ingress routing
kubectl apply -f ray-stable-svc.yaml
```

#### 8. Bootstrap System Components
```bash
# Bootstrap organism and dispatchers
./bootstrap_organism.sh
./bootstrap_dispatchers.sh
```

#### 9. Deploy SeedCore API
```bash
# Deploy standalone API service
./deploy-seedcore-api.sh
```

#### 10. Deploy Ingress
```bash
# Deploy ingress configuration
./deploy-k8s-ingress.sh
```

#### 11. Setup Port Forwarding
```bash
# Start port forwarding for development access
./port-forward.sh
```

### 12. Verify Installation
```bash
# Check Ray dashboard
curl http://localhost:8265/api/version

# Check API health
curl http://localhost:8002/health


# Check Ray Serve services
curl http://localhost:8000/ml/health
curl http://localhost:8000/pipeline/health
curl http://localhost:8000/organism/health
curl http://localhost:8000/cognitive/health
curl http://localhost:8000/ops/state/health
curl http://localhost:8000/ops/energy/health
```

## 🏗️ Architecture Overview

SeedCore implements a distributed **Control/Execution Plane architecture** using Ray Serve for service orchestration and Ray Actors for distributed computation. The system features a robust **epoch-based runtime registry** that provides comprehensive actor lifecycle management, cluster coordination, and fault tolerance.

### Control/Execution Plane Architecture

SeedCore follows a **"Planes of Control"** architecture with three distinct planes:

#### 1. Control Plane (Coordinator Service)
- **Universal Interface**: Single `POST /route-and-execute` endpoint consolidates all business logic (Triage, Tuning, Execution)
- **Strategic Orchestration**: Implements "Plan-Execute-Audit" loop - decomposes Cognitive Plans into concrete subtasks and dispatches to Organism
- **Semantic Policy Engine**: Fuses Mathematical Drift (ML Service) with Semantic Urgency (Eventizer Tags) for intelligent routing decisions
- **Type-Based Routing**: Uses `TaskPayload.type` for internal routing:
  - `type: "anomaly_triage"` → Anomaly triage pipeline
  - `type: "ml_tune_callback"` → ML tuning callback handler
  - Other types → Standard routing & execution
- **Clean Architecture**: Removed legacy `CoordinatorCore` wrapper and HGNN execution logic

#### 2. Intelligence Plane (Cognitive Service)
- **Server-Side Hydration**: Implements "Data Pull" pattern - `CognitiveCore` hydrates context from `TaskMetadataRepository` using `task_id`, reducing network payload size
- **Neuro-Symbolic Bridge**: `HGNNReasoningSignature` pipeline translates ML vector embeddings (`hgnn_embedding`) into semantic graph neighborhoods for deep reasoning
- **Concurrency Safety**: Replaced global `dspy.settings` with thread-safe `dspy.context` managers
- **Worker Pattern**: `CognitiveCore` is purely data-driven, stripped of routing logic

#### 3. Execution Plane (Organism & API)
- **Thin API Client**: `seedcore-api` acts as "Dumb Pipe" (Ingest & Queue only) - removed local eventizer processing
- **Unified Gateway**: All clients use Organism's canonical `/route-and-execute` endpoint
- **Sticky Sessions**: `agent_tunnel` logic in `OrganismRouter` enables low-latency conversational affinity via Redis

#### 4. Perception (Eventizer & System 1)
- **Config-Driven Logic**: `EventizerService` injects attributes (`target_organ`, `required_skill`) directly from `eventizer_patterns.json` metadata, removing hardcoded Python heuristics
- **Centralization**: Single source of truth for text analysis hosted in Coordinator
- **Schema Validation**: Enforced strict JSON schema validation for pattern files

#### 5. Infrastructure Improvements
- **Fast-Lane Dispatch**: `_enqueue_task_embedding_now` for best-effort immediate indexing
- **Dependency Injection**: Cleaned up session factories and client wiring across all services
- **Interface Hygiene**: Operational endpoints (`/health`, `/metrics`) hidden from public API schemas but available for Kubernetes/Prometheus

### Key Architectural Components

#### Microservices Architecture
- **Ray Serve Services**: Independent microservices for different capabilities
  - **ML Service** (`/ml`): XGBoost machine learning and model management
  - **Cognitive Service** (`/cognitive`): Advanced reasoning with DSPy integration
  - **State Service** (`/ops/state`): Centralized state aggregation and collection
  - **Energy Service** (`/ops/energy`): Energy calculations and agent optimization
  - **Coordinator Service** (`/pipeline`): Control Plane - unified routing and orchestration
  - **Organism Service** (`/organism`): Execution Plane - agent and organ lifecycle management

#### Runtime Registry and Actor Lifecycle
- **Epoch-Based Cluster Management**: Prevents split-brain scenarios with advisory-locked epoch updates
- **Instance Registry**: Tracks all active Ray actors and Serve deployments with health monitoring
- **Jittered Heartbeats**: Reduces synchronization effects with bounded exponential backoff
- **Graceful Shutdown**: Clean actor termination with SIGTERM handling and registry cleanup

#### Service Architecture
- **Ray Head Service**: `seedcore-svc-head-svc` (ClusterIP: None)
  - Ports: 10001 (Ray), 8265 (Dashboard), 6379, 8080, 8000
- **Ray Serve Service**: `seedcore-svc-serve-svc` (ClusterIP)
  - Port: 8000 (HTTP API) - All microservices
- **SeedCore API**: `seedcore-api` (ClusterIP)
  - Port: 8002 (Standalone API)

#### Database Integration
- **PostgreSQL**: Primary database with pgvector extension for embeddings
  - **Task Management**: Coordinator-dispatcher task queue with lease management
  - **HGNN Architecture**: Two-layer heterogeneous graph neural network
  - **Graph Embeddings**: Vector-based similarity search with ANN indexing
  - **Facts Management**: Full-text search and semantic fact storage
  - **Runtime Registry**: Epoch-based cluster state management
- **MySQL**: Secondary database for specific workloads
- **Redis**: Caching and session management with performance optimization
- **Neo4j**: Graph database for complex relationships

### Advanced Database Schema (19 Migrations)

The system includes a comprehensive database schema evolution with 19 migrations:

#### Task Management System (Migrations 001-006)
- **Coordinator-Dispatcher Pattern**: Complete task queue with lease management
- **Retry Logic**: Automatic requeuing with exponential backoff
- **Drift Scoring**: OCPS valve decision making (0.0 = fast path, ≥0.5 = escalation)
- **Performance Indexes**: Optimized for task claiming and status updates
- **Task Outbox**: Transactional outbox pattern with scheduling and retry tracking (Migration 018)

#### HGNN Architecture (Migrations 007-008)
- **Two-Layer Graph**: Task layer and Agent/Organ layer with cross-layer relationships
- **Node Mapping**: Canonical node-id mapping for DGL integration
- **Vector Embeddings**: PgVector integration with IVFFlat indexes for fast similarity search (upgraded to 1024 dimensions in Migration 019)
- **Graph Analytics**: Unified views for complex relationship analysis
- **Multi-Label Embeddings**: Support for multiple embeddings per node with label-based organization (Migration 017)

#### Facts Management (Migrations 009-010, 016)
- **Full-Text Search**: GIN indexes for efficient text search
- **Tag-Based Categorization**: Array-based tagging system
- **Metadata Support**: JSONB for flexible fact properties
- **Task Integration**: Fact-task relationship mapping
- **PKG Integration**: Policy-driven fact management with temporal validity, namespaces, and governance (Migration 016)
- **Temporal Facts**: Time-bound facts with automatic expiration and cleanup

#### Runtime Registry (Migrations 011-012)
- **Instance Management**: Service instance tracking and health monitoring
- **Cluster Coordination**: Epoch-based management preventing split-brain scenarios
- **Heartbeat Monitoring**: Automatic stale instance detection and cleanup
- **Service Discovery**: Active instance views for load balancing

#### PKG Policy Governance System (Migrations 013-015)
- **Policy Snapshots**: Versioned policy governance with environment-based activation
- **Rule Engine**: Policy rules with conditions, emissions, and subtask types
- **Deployment Management**: Canary deployments and targeted rollouts per router/edge class
- **Validation Framework**: Test fixtures and validation runs for policy correctness
- **Promotion Tracking**: Audit trail for policy promotions and rollbacks
- **Device Coverage**: Edge telemetry and version tracking for distributed deployments

#### Embedding Enhancements (Migrations 017, 019)
- **Multi-Label Embeddings**: Support for multiple embeddings per node (e.g., task.primary, task.content)
- **Content Hash Tracking**: SHA256-based staleness detection for embedding refresh
- **1024-Dimensional Vectors**: Upgraded from 128-d to 1024-d for enhanced NIM Retrieval capabilities
- **Staleness Detection**: Views to identify embeddings that need refresh based on content changes

### Detailed Architecture Documentation

For comprehensive architecture details, see:
- **[Architecture Migration Summary](docs/ARCHITECTURE_MIGRATION_SUMMARY.MD)**: Complete system evolution and database schema
- **[Database Migrations Summary](deploy/migrations/MIGRATIONS_SUMMARY.md)**: Detailed migration documentation and schema evolution
- **[Ray Centralization Guide](docs/RAY_CENTRALIZATION_GUIDE.MD)**: Ray configuration and deployment patterns
- **[Configuration Summary](docs/CONFIGURATION-SUMMARY.MD)**: Database and service configuration
- **[Implementation Summary](docs/IMPLEMENTATION_SUMMARY.MD)**: Independent service deployment
- **[Enhancement Summary](docs/ENHANCEMENT_SUMMARY.MD)**: Complete system enhancements

## 🧠 Core Features

### Cognitive Architecture
- **Persistent State Management**: Centralized state management with `OrganRegistry`
- **Persistent Organs & Agents**: System maintains state across API calls
- **Energy Ledger**: Multi-term energy accounting (pair, hyper, entropy, reg, mem)
- **Role Evolution**: Dynamic agent role probability adjustment

### Agent Personality System
- **Personality Vectors**: Each agent has an 8-dimensional personality embedding (`h`)
- **Cosine Similarity**: Calculates compatibility between agent personalities
- **Collaboration Learning**: Tracks historical success rates between agent pairs
- **Adaptive Weights**: Learns which agent combinations work best together

### Control Loops
- **Fast Loop**: Real-time agent selection and task execution
- **Slow Loop**: Energy-aware role evolution with learning rate control
- **Memory Loop**: Adaptive compression and memory utilization control
- **Energy Model Foundation**: Intelligent energy-aware agent selection and optimization

### Runtime Registry and Actor Lifecycle
- **Epoch-Based Cluster Management**: Prevents split-brain scenarios with advisory-locked epoch updates
- **Instance Registry**: Tracks all active Ray actors and Serve deployments with comprehensive metadata
- **Jittered Heartbeats**: Reduces synchronization effects with bounded exponential backoff on failures
- **Graceful Shutdown**: Clean actor termination with SIGTERM handling and registry cleanup
- **Stale Instance Cleanup**: Automatic detection and cleanup of dead instances
- **Health Monitoring**: Real-time actor health status and heartbeat freshness tracking

### 🎯 XGBoost Machine Learning Integration
- **Distributed Training**: Train XGBoost models across your Ray cluster
- **Hyperparameter Tuning**: ✅ **FULLY OPERATIONAL** - Automated hyperparameter optimization using Ray Tune with ASHA scheduler
- **Data Pipeline Integration**: Seamless data loading from various sources (CSV, Parquet, etc.)
- **Model Management**: Save, load, and manage trained models with automatic promotion
- **Batch and Real-time Inference**: Support for both single predictions and batch processing
- **REST API**: Full integration with the SeedCore ML service
- **Feature Validation**: Automatic feature consistency checking between training and prediction
- **Flashbulb Memory Integration**: High-impact tuning events logged to cognitive memory

### 🧠 Advanced Cognitive Intelligence
- **DSPy v2 Integration**: Enhanced cognitive reasoning with OCPS fast/deep path routing
- **Server-Side Hydration**: Data Pull pattern reduces network payload by hydrating context from database using `task_id`
- **Neuro-Symbolic Bridge**: `HGNNReasoningSignature` translates ML vector embeddings into semantic graph neighborhoods
- **Thread-Safe Execution**: Uses `dspy.context` managers instead of global settings for concurrency safety
- **RRF Fusion & MMR Diversity**: Better retrieval and diversification algorithms
- **Dynamic Token Budgeting**: OCPS-informed budgeting and escalation hints
- **Enhanced Fact Schema**: Provenance, trust, and policy flags
- **Post-condition Checks**: DSPy output validation and sanitization
- **Cache Governance**: TTL per task type with hardened cache management

### 🔄 Service Communication Architecture
- **Unified Interface**: Single `POST /route-and-execute` endpoint for all Coordinator operations
- **Thin Client Pattern**: Routers are lightweight clients that delegate all decision logic to backend services
- **Agent Tunnel Optimization**: Low-latency bypass for conversational interactions via Redis sticky sessions
- **Circuit Breaker Pattern**: Fault tolerance with configurable failure thresholds
- **Exponential Backoff Retry**: Jittered retry logic with configurable delays
- **Resource Management**: Rate limiting and concurrency control
- **Service Discovery**: Automatic endpoint discovery via centralized gateway
- **Centralized Ray Connection**: Single source of truth for all Ray operations
- **Fast-Lane Dispatch**: Best-effort immediate task embedding indexing for reduced latency

#### ⚡ Scaling Evolution Path

SeedCore's inter-service communication follows a tiered evolution strategy optimized for the Ray ecosystem:

**Tier-0: HTTP/JSON (Current)**
- **Protocol**: HTTP/1.1 via `httpx` with JSON serialization
- **Use Case**: Universal compatibility, easy debugging, stateless communication
- **Best For**: Development, testing, external integrations, polyglot environments
- **Performance**: Suitable for current workloads (LLM latency dominates network overhead)

**Tier-1: Ray Native Handles (Next Step)**
- **Protocol**: Ray Serve Deployment Handles (`serve.get_app_handle`)
- **Use Case**: Internal cluster communication within Ray ecosystem
- **Benefits**: 
  - Zero-copy serialization via Plasma Object Store (shared memory references)
  - No Protobuf schema maintenance (direct Python method calls)
  - Auto-discovery and routing via Ray
  - Near-gRPC performance without binary protocol complexity
- **When to Adopt**: When internal routing latency becomes a bottleneck (Coordinator ↔ Organism, Cognitive ↔ ML)

**Tier-2: gRPC (Edge/External)**
- **Protocol**: gRPC with Protobuf (`ray.serve.grpc`)
- **Use Case**: External clients (IoT devices, mobile apps), polyglot services (Go/Rust/C++)
- **Benefits**: Binary serialization, strict typing, low-latency edge communication
- **When to Adopt**: External ingress layer, strict latency requirements for edge devices

**Recommendation**: Start with HTTP, upgrade to Ray Handles for internal cluster communication when scaling, reserve gRPC for external edge interfaces.

## 🚀 Deployment Options

### 1. Complete Automated Deployment (Recommended)
```bash
# Clone and setup
git clone https://github.com/NeilLi/seedcore.git
cd seedcore
./deploy/init_env.sh
cp docker/env.example docker/.env

# Run complete deployment pipeline
cd deploy
./deploy-seedcore.sh
```

This matches **Option 1** in the [Quick Start](#-quick-start-kubernetes--kuberay) section.

### 2. Step-by-Step Manual Deployment
Follow the detailed steps in the [Quick Start](#-quick-start-kubernetes--kuberay) section above for a complete walkthrough (steps 1-12).

### 3. Development Environment
```bash
# Quick development setup (if Makefile supports it)
make dev

# Or complete manual setup following Quick Start Option 2
git clone https://github.com/NeilLi/seedcore.git
cd seedcore
./build.sh
cd deploy
./setup-kind-only.sh
./setup-cores.sh
./init-databases.sh

# Deploy storage and RBAC
kubectl apply -f k8s/seedcore-data-pvc.yaml
kubectl apply -f k8s/seedcore-serviceaccount.yaml
kubectl apply -f k8s/seedcore-rolebinding.yaml
kubectl apply -f k8s/allow-api-egress.yaml
kubectl apply -f k8s/allow-api-to-ray-serve.yaml
kubectl apply -f k8s/xgb-pvc.yaml

# Continue with Ray and services
./setup-ray-serve.sh
kubectl apply -f ray-stable-svc.yaml
./bootstrap_organism.sh
./bootstrap_dispatchers.sh
./deploy-seedcore-api.sh
./deploy-k8s-ingress.sh
./port-forward.sh
```

### 4. Using Makefile
```bash
# Development environment
make dev

# Staging environment
make staging

# Production environment
make prod

# Helm-based deployment
make dev-helm
```

### 5. Docker Compose (Legacy)
For local development without Kubernetes:
```bash
cd docker
./sc-cmd.sh up [num_workers]
```

## 🔧 Configuration

### Environment Variables
The system uses Kubernetes ConfigMaps and Secrets for configuration:

```bash
# Core Configuration
SEEDCORE_NS=seedcore-dev
SEEDCORE_STAGE=dev
RAY_ADDRESS=ray://seedcore-svc-head-svc:10001
RAY_NAMESPACE=seedcore-dev

# Database Configuration
POSTGRES_HOST=postgresql
MYSQL_HOST=mysql
REDIS_HOST=redis-master
NEO4J_HOST=neo4j
```

### Ray Configuration
- **Ray Version**: 2.33.0
- **Head Node Resources**: 2 CPU, 8Gi memory (limits)
- **Worker Resources**: 2 CPU, 4Gi memory (limits)
- **Worker Replicas**: Configurable via `WORKER_REPLICAS` environment variable

### Database Configuration
- **PostgreSQL**: `postgresql://postgres:password@postgresql:5432/postgres`
- **MySQL**: `mysql+mysqlconnector://seedcore:password@mysql:3306/seedcore`
- **Redis**: `redis-master:6379` (no authentication)
- **Neo4j**: `bolt://neo4j:7687` (user: neo4j, password: password)

## 📊 Monitoring and Management

### Ray Dashboard
```bash
# Access Ray dashboard
kubectl port-forward svc/seedcore-svc-head-svc 8265:8265 -n seedcore-dev
# Then visit http://localhost:8265
```

### Service Status
```bash
# Check all services
kubectl get svc -n seedcore-dev

# Check all pods
kubectl get pods -n seedcore-dev

# Check RayService status
kubectl get rayservice -n seedcore-dev

# Check RayCluster status
kubectl get raycluster -n seedcore-dev
```

### Logs and Debugging
```bash
# Check Ray head logs
kubectl logs -l ray.io/node-type=head -n seedcore-dev -f

# Check Ray worker logs
kubectl logs -l ray.io/node-type=worker -n seedcore-dev -f

# Check SeedCore API logs
kubectl logs -l app=seedcore-api -n seedcore-dev -f
```

## 🛠️ Development Workflow

### 1. Start Development Environment
```bash
# Build Docker image
./build.sh

cd deploy

# Complete setup
./setup-kind-only.sh
./setup-cores.sh
./init-databases.sh
kubectl apply -f k8s/seedcore-data-pvc.yaml
kubectl apply -f k8s/ingress-routing.yaml
./deploy-k8s-ingress.sh
./setup-ray-serve.sh
./bootstrap_organism.sh
./bootstrap_dispatchers.sh
./deploy-seedcore-api.sh
./port-forward.sh
```

### 2. Make Code Changes
Your project code is mounted at `/project` inside the cluster, so changes are immediately available.

### 3. Test Changes
```bash
# Test via HTTP API
curl http://localhost:8000/ml/health
curl http://localhost:8002/health

# Test runtime registry
curl http://localhost:8002/healthz/runtime-registry

# Test via Ray client
kubectl exec -it $(kubectl get pods -l ray.io/node-type=head -n seedcore-dev -o jsonpath='{.items[0].metadata.name}') -n seedcore-dev -- python -c "import ray; ray.init(); print('Ray connected!')"
```

### 4. Monitor System Health
```bash
# Check Ray dashboard
kubectl port-forward svc/seedcore-svc-head-svc 8265:8265 -n seedcore-dev

# Check runtime registry status
kubectl exec -it $(kubectl get pods -l ray.io/node-type=head -n seedcore-dev -o jsonpath='{.items[0].metadata.name}') -n seedcore-dev -- python -c "
import asyncio
from seedcore.graph.agent_repository import AgentGraphRepository
async def check_registry():
    repo = AgentGraphRepository()
    instances = await repo.list_active_instances()
    print(f'Active instances: {len(instances)}')
    for inst in instances:
        print(f'  {inst.logical_id}: {inst.status} (heartbeat: {inst.last_heartbeat})')
asyncio.run(check_registry())
"
```

### 5. Cleanup
```bash
# Stop port forwarding
pkill -f "kubectl.*port-forward"

# Delete cluster (when done)
kind delete cluster --name seedcore-dev
```

## 🔍 Troubleshooting

### Common Issues

#### Pod Not Starting
```bash
# Check pod events
kubectl describe pod <pod-name> -n seedcore-dev

# Check pod logs
kubectl logs <pod-name> -n seedcore-dev
```

#### Service Not Accessible
```bash
# Check service endpoints
kubectl get endpoints <service-name> -n seedcore-dev

# Check service configuration
kubectl describe svc <service-name> -n seedcore-dev
```

#### Ray Connection Issues
```bash
# Check Ray cluster status
kubectl exec -it $(kubectl get pods -l ray.io/node-type=head -n seedcore-dev -o jsonpath='{.items[0].metadata.name}') -n seedcore-dev -- ray status

# Check RayService status
kubectl get rayservice seedcore-svc -n seedcore-dev -o yaml
```

### Debug Commands
```bash
# Check cluster resources
kubectl top nodes
kubectl top pods -n seedcore-dev

# Check events
kubectl get events -n seedcore-dev --sort-by='.lastTimestamp'

# Check KubeRay operator
kubectl get pods -n kuberay-system
```

## 📚 API Reference

### Ray Serve Microservices (Port 8000)

#### ML Service (`/ml`)
- **Health Check**: `GET /ml/health`
- **Model Training**: `POST /ml/train`
- **Model Prediction**: `POST /ml/predict`
- **Model Management**: `GET /ml/models`, `DELETE /ml/models/{model_id}`
- **Hyperparameter Tuning**: `POST /ml/tune`

#### Cognitive Service (`/cognitive`) - Intelligence Plane
- **Health Check**: `GET /cognitive/health`
- **Task Execution**: `POST /cognitive/execute` - Executes cognitive tasks with server-side hydration
  - Supports Data Pull pattern: hydrates context from `TaskMetadataRepository` using `task_id`
  - Neuro-symbolic bridge: translates ML embeddings into semantic graph neighborhoods
  - Thread-safe execution via `dspy.context` managers
- **Service Info**: `GET /cognitive/info` - Service metadata and configuration

#### State Service (`/ops/state`)
- **Health Check**: `GET /ops/state/health`
- **Unified State**: `GET /ops/state/unified-state`
- **State Collection**: `POST /ops/state/collect`

#### Energy Service (`/ops/energy`)
- **Health Check**: `GET /ops/energy/health`
- **Energy Computation**: `POST /ops/energy/compute-energy`
- **Agent Optimization**: `POST /ops/energy/optimize-agents`

#### Coordinator Service (`/pipeline`) - Control Plane
- **Health Check**: `GET /pipeline/health` (hidden from schema)
- **Unified Interface**: `POST /pipeline/route-and-execute` - Universal entrypoint for all business operations
  - Type-based routing: `type: "anomaly_triage"` → Anomaly triage pipeline
  - Type-based routing: `type: "ml_tune_callback"` → ML tuning callback handler
  - Other types → Standard routing & execution
  - Handles complete lifecycle: routing, scoring, delegation, execution, persistence
- **Metrics**: `GET /pipeline/metrics` (hidden from schema)
- **Predicate Admin**: `GET /pipeline/predicates/status`, `POST /pipeline/predicates/reload` (hidden from schema)

#### Organism Service (`/organism`) - Execution Plane
- **Health Check**: `GET /organism/health`
- **Unified Gateway**: `POST /organism/route-and-execute` - Canonical endpoint for routing and execution
- **Routing Only**: `POST /organism/route-only` - Get routing decision without execution
- **Organ Management**: `GET /organism/organs`
- **Agent Management**: `GET /organism/agents`
- **Sticky Sessions**: Agent tunnel mode for low-latency conversational affinity via Redis

### Standalone API Endpoints (Port 8002)
- **Health Check**: `GET /health`
- **Readiness**: `GET /readyz`
- **Energy System**: `GET /healthz/energy`
- **Runtime Registry**: `GET /healthz/runtime-registry`

## 🚀 Production Deployment

### Production Considerations
- **Resource Limits**: Adjust CPU/memory limits based on workload
- **Scaling**: Use KEDA for auto-scaling based on metrics
- **Monitoring**: Implement Prometheus/Grafana for production monitoring
- **Security**: Use proper RBAC and network policies
- **Backup**: Implement database backup strategies

### KEDA Auto-scaling
```bash
# Apply KEDA scaling configuration
kubectl apply -f deploy/keda/scaledobject-serve.yaml -n seedcore-dev
```

## 📖 Additional Documentation

### Core Architecture
- **[Architecture Migration Summary](docs/ARCHITECTURE_MIGRATION_SUMMARY.MD)**: Complete system evolution and database schema
- **[Ray Centralization Guide](docs/RAY_CENTRALIZATION_GUIDE.MD)**: Ray configuration and deployment patterns
- **[Configuration Summary](docs/CONFIGURATION-SUMMARY.MD)**: Database and service configuration
- **[Implementation Summary](docs/IMPLEMENTATION_SUMMARY.MD)**: Independent service deployment
- **[Enhancement Summary](docs/ENHANCEMENT_SUMMARY.MD)**: Complete system enhancements

### Operational Guides
- **[Operation Manual](docs/OPERATION-MANUAL.MD)**: Complete operational procedures and troubleshooting
- **[Kubernetes Setup](deploy/KIND_CLUSTER_REFERENCE.md)**: KIND cluster reference and setup
- **[Database Tasks](docs/DATABASE_TASKS.MD)**: Database management and migration procedures
- **[Dispatcher Troubleshooting](docs/DISPATCHER_TROUBLESHOOTING.MD)**: Dispatcher-specific troubleshooting

### Advanced Features
- **[Task Lease Fixes](docs/TASK_LEASE_FIXES.MD)**: Task management and lease system
- **[Namespace Fix Summary](docs/NAMESPACE_FIX_SUMMARY.MD)**: Namespace management and fixes
- **[Registry Integration](docs/REGISTRY_INTEGRATION_SUMMARY.MD)**: Runtime registry integration
- **[Predicate System](docs/PREDICATE_SYSTEM_IMPROVEMENTS.MD)**: Predicate system enhancements

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with the Kubernetes setup
5. Submit a pull request

## 📄 License

This project is licensed under the terms specified in the [LICENSE](LICENSE) file.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review the [KIND_CLUSTER_REFERENCE.md](deploy/KIND_CLUSTER_REFERENCE.md)
3. Check the [docs/](docs/) directory for additional guides
4. Open an issue on GitHub

---

## 🎉 Recent Updates

### Latest Enhancements (2025)
- ✅ **Control/Execution Plane Architecture**: Major refactor transitioning to distributed "Planes of Control" architecture
  - **Control Plane**: Universal `/route-and-execute` interface consolidating all business logic (Triage, Tuning, Execution)
  - **Intelligence Plane**: Server-side hydration with Data Pull pattern, neuro-symbolic bridge, thread-safe execution
  - **Execution Plane**: Thin API client pattern, unified gateway, sticky sessions via Redis agent tunnel
  - **Perception**: Config-driven Eventizer with JSON schema validation, centralized text analysis
- ✅ **Semantic Policy Engine**: Fuses Mathematical Drift (ML Service) with Semantic Urgency (Eventizer Tags) for intelligent routing
- ✅ **Plan-Execute-Audit Loop**: Coordinator decomposes Cognitive Plans into concrete subtasks and dispatches to Organism
- ✅ **Complete Database Schema Evolution**: 19 comprehensive migrations for task management, HGNN architecture, facts system, runtime registry, PKG policy governance, and embedding enhancements
- ✅ **Ray Serve Microservices Architecture**: Independent services for ML, Cognitive, State, Energy, Coordinator, and Organism management
- ✅ **Advanced Cognitive Intelligence**: DSPy v2 integration with OCPS fast/deep path routing and enhanced fact management
- ✅ **Service Communication Architecture**: Circuit breaker pattern, exponential backoff retry, and centralized Ray connection management
- ✅ **Automated Deployment Pipeline**: Complete deployment orchestration with `deploy-seedcore.sh`
- ✅ **Performance Optimizations**: Redis caching system with 16.8x to 1000x performance improvements
- ✅ **Production-Ready Features**: Comprehensive health monitoring, fault tolerance, and resource management

### Key Benefits
- **Scalable Architecture**: Microservices with independent scaling and resource allocation
- **Advanced AI/ML**: Graph neural networks, vector search, and intelligent task management
- **Fault Tolerance**: Circuit breakers, retry logic, and graceful degradation
- **Production Ready**: Comprehensive monitoring, health checks, and operational procedures


