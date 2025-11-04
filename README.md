# SeedCore: Dynamic Cognitive Architecture with XGBoost ML Integration

[![Run Tests](https://github.com/NeilLi/seedcore/actions/workflows/tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/tests.yml)

A stateful, interactive cognitive architecture system with persistent organs, agents, energy-based control loops, and integrated XGBoost machine learning capabilities featuring realistic agent collaboration learning. Now deployed on Kubernetes with KubeRay, featuring advanced database schema evolution, Ray Serve microservices architecture, and comprehensive runtime registry management.

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
./deploy/init_env.sh
cp docker/env.example docker/.env

# Run complete deployment pipeline
cd deploy
./deploy-seedcore.sh
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
# Initialize database schema and runtime registry (12 migrations)
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

# Check energy system
curl http://localhost:8002/healthz/energy

# Check runtime registry
curl http://localhost:8002/healthz/runtime-registry

# Check Ray Serve services
curl http://localhost:8000/ml/health
curl http://localhost:8000/organism/health
curl http://localhost:8000/cognitive/health
curl http://localhost:8000/ops/state/health
curl http://localhost:8000/ops/energy/health
```

## 🏗️ Architecture Overview

SeedCore implements a distributed, intelligent organism architecture using Ray Serve for service orchestration and Ray Actors for distributed computation. The system features a robust **epoch-based runtime registry** that provides comprehensive actor lifecycle management, cluster coordination, and fault tolerance.

### Key Architectural Components

#### Microservices Architecture
- **Ray Serve Services**: Independent microservices for different capabilities
  - **ML Service** (`/ml`): XGBoost machine learning and model management
  - **Cognitive Service** (`/cognitive`): Advanced reasoning with DSPy integration
  - **State Service** (`/state`): Centralized state aggregation and collection
  - **Energy Service** (`/energy`): Energy calculations and agent optimization
  - **Coordinator Service** (`/pipeline`): Task coordination and orchestration
  - **Organism Service** (`/organism`): Agent and organ lifecycle management

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

### Advanced Database Schema (12 Migrations)

The system includes a comprehensive database schema evolution with 12 migrations:

#### Task Management System (Migrations 001-006)
- **Coordinator-Dispatcher Pattern**: Complete task queue with lease management
- **Retry Logic**: Automatic requeuing with exponential backoff
- **Drift Scoring**: OCPS valve decision making (0.0 = fast path, ≥0.5 = escalation)
- **Performance Indexes**: Optimized for task claiming and status updates

#### HGNN Architecture (Migrations 007-008)
- **Two-Layer Graph**: Task layer and Agent/Organ layer with cross-layer relationships
- **Node Mapping**: Canonical node-id mapping for DGL integration
- **Vector Embeddings**: PgVector integration with IVFFlat indexes for fast similarity search
- **Graph Analytics**: Unified views for complex relationship analysis

#### Facts Management (Migrations 009-010)
- **Full-Text Search**: GIN indexes for efficient text search
- **Tag-Based Categorization**: Array-based tagging system
- **Metadata Support**: JSONB for flexible fact properties
- **Task Integration**: Fact-task relationship mapping

#### Runtime Registry (Migrations 011-012)
- **Instance Management**: Service instance tracking and health monitoring
- **Cluster Coordination**: Epoch-based management preventing split-brain scenarios
- **Heartbeat Monitoring**: Automatic stale instance detection and cleanup
- **Service Discovery**: Active instance views for load balancing

### Detailed Architecture Documentation

For comprehensive architecture details, see:
- **[Architecture Migration Summary](docs/ARCHITECTURE_MIGRATION_SUMMARY.MD)**: Complete system evolution and database schema
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
- **RRF Fusion & MMR Diversity**: Better retrieval and diversification algorithms
- **Dynamic Token Budgeting**: OCPS-informed budgeting and escalation hints
- **Enhanced Fact Schema**: Provenance, trust, and policy flags
- **Post-condition Checks**: DSPy output validation and sanitization
- **Cache Governance**: TTL per task type with hardened cache management

### 🔄 Service Communication Architecture
- **Circuit Breaker Pattern**: Fault tolerance with configurable failure thresholds
- **Exponential Backoff Retry**: Jittered retry logic with configurable delays
- **Resource Management**: Rate limiting and concurrency control
- **Service Discovery**: Automatic endpoint discovery via centralized gateway
- **Centralized Ray Connection**: Single source of truth for all Ray operations

## 🚀 Deployment Options

### 1. Complete Automated Deployment (Recommended)
```bash
# Build Docker image
./build.sh

# Run complete deployment pipeline
cd deploy
./deploy-seedcore.sh
```

### 2. Step-by-Step Manual Deployment
Follow the detailed steps in the [Quick Start](#-quick-start-kubernetes--kuberay) section above for a complete walkthrough.

### 3. Development Environment
```bash
# Quick development setup
make dev

# Or manual setup
./build.sh
cd deploy
./setup-kind-only.sh
./setup-cores.sh
./init-databases.sh
./setup-ray-serve.sh
./bootstrap_organism.sh
./bootstrap_dispatchers.sh
./deploy-seedcore-api.sh
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

#### Cognitive Service (`/cognitive`)
- **Health Check**: `GET /cognitive/health`
- **Agent Management**: `POST /cognitive/agents`, `GET /cognitive/agents`
- **Task Execution**: `POST /cognitive/execute`
- **Reasoning**: `POST /cognitive/reason`

#### State Service (`/ops/state`)
- **Health Check**: `GET /ops/state/health`
- **Unified State**: `GET /ops/state/unified-state`
- **State Collection**: `POST /ops/state/collect`

#### Energy Service (`/ops/energy`)
- **Health Check**: `GET /ops/energy/health`
- **Energy Computation**: `POST /ops/energy/compute-energy`
- **Agent Optimization**: `POST /ops/energy/optimize-agents`

#### Coordinator Service (`/pipeline`)
- **Health Check**: `GET /pipeline/health`
- **Task Coordination**: `POST /pipeline/coordinate`

#### Organism Service (`/organism`)
- **Health Check**: `GET /organism/health`
- **Organ Management**: `GET /organism/organs`
- **Agent Management**: `GET /organism/agents`

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
- ✅ **Complete Database Schema Evolution**: 12 comprehensive migrations for task management, HGNN architecture, facts system, and runtime registry
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

**Note**: This README reflects the current Kubernetes + KubeRay deployment setup. For the previous Docker Compose setup, see [docs/LEGACY/README-DOCKER-SETUP.MD](docs/LEGACY/README-DOCKER-SETUP.MD).
