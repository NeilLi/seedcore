# SeedCore: Dynamic Cognitive Architecture with XGBoost ML Integration

A stateful, interactive cognitive architecture system with persistent organs, agents, energy-based control loops, and integrated XGBoost machine learning capabilities featuring realistic agent collaboration learning, now deployed on Kubernetes with KubeRay.

## 🚀 Quick Start (Kubernetes + KubeRay)

### Prerequisites
- **Kubernetes Tools**: `kubectl`, `kind`, `helm`
- **Docker**: For building and loading images
- **System Requirements**: 8GB+ RAM, 4+ CPU cores recommended
- **Operating System**: Linux/macOS/Windows with Docker support

### 1. Clone and Setup
```bash
git clone <repository-url>
cd seedcore
```

### 2. Start the Kubernetes Cluster
```bash
cd deploy
./setup-kind-only.sh
```

### 3. Deploy Core Services
```bash
# Deploy databases and Ray services
./setup-ray-serve.sh

# Deploy standalone API (optional)
./deploy-seedcore-api.sh

# Initialize databases
./init_databases_k8s.sh
```

### 4. Setup Port Forwarding
```bash
# Start port forwarding for development access
./port-forward.sh
```

### 5. Verify Installation
```bash
# Check Ray dashboard
curl http://localhost:8265/api/version

# Check API health
curl http://localhost:8002/health

# Check energy system
curl http://localhost:8002/healthz/energy
```

## 🏗️ Architecture Overview

### Kubernetes + KubeRay Architecture
```
SeedCore Platform (Kubernetes)
├── Kind Cluster (seedcore-dev)
│   ├── KubeRay Operator (kuberay-system)
│   ├── RayService (seedcore-svc)
│   │   ├── Ray Head Node (Cluster Management)
│   │   ├── Ray Workers (Distributed Processing)
│   │   └── Ray Serve (HTTP API)
│   ├── Database Services (Helm Charts)
│   │   ├── PostgreSQL
│   │   ├── MySQL
│   │   ├── Redis (Master + Replicas)
│   │   └── Neo4j
│   └── SeedCore API (Standalone Service)
```

### Service Architecture
- **Ray Head Service**: `seedcore-svc-head-svc` (ClusterIP: None)
  - Ports: 10001 (Ray), 8265 (Dashboard), 6379, 8080, 8000
- **Ray Serve Service**: `seedcore-svc-serve-svc` (ClusterIP)
  - Port: 8000 (HTTP API)
- **SeedCore API**: `seedcore-api` (ClusterIP)
  - Port: 8002 (Standalone API)

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

### 🎯 XGBoost Machine Learning Integration
- **Distributed Training**: Train XGBoost models across your Ray cluster
- **Hyperparameter Tuning**: ✅ **FULLY OPERATIONAL** - Automated hyperparameter optimization using Ray Tune with ASHA scheduler
- **Data Pipeline Integration**: Seamless data loading from various sources (CSV, Parquet, etc.)
- **Model Management**: Save, load, and manage trained models with automatic promotion
- **Batch and Real-time Inference**: Support for both single predictions and batch processing
- **REST API**: Full integration with the SeedCore ML service
- **Feature Validation**: Automatic feature consistency checking between training and prediction
- **Flashbulb Memory Integration**: High-impact tuning events logged to cognitive memory

## 🚀 Deployment Options

### 1. Complete Setup (Recommended)
```bash
cd deploy
./setup-ray-serve.sh
./deploy-seedcore-api.sh
./init_databases_k8s.sh
./port-forward.sh
```

### 2. Step-by-Step Setup
```bash
# Create Kind cluster
./setup-kind-only.sh

# Deploy databases
./setup-cores.sh

# Deploy Ray services
./setup-ray-serve.sh

# Deploy standalone API
./deploy-seedcore-api.sh

# Initialize databases
./init_databases_k8s.sh

# Setup port forwarding
./port-forward.sh
```

### 3. Using Makefile
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
cd deploy
./setup-kind-only.sh
./setup-ray-serve.sh
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

# Test via Ray client
kubectl exec -it $(kubectl get pods -l ray.io/node-type=head -n seedcore-dev -o jsonpath='{.items[0].metadata.name}') -n seedcore-dev -- python -c "import ray; ray.init(); print('Ray connected!')"
```

### 4. Cleanup
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

### ML Service Endpoints
- **Health Check**: `GET /ml/health`
- **Model Training**: `POST /ml/train`
- **Model Prediction**: `POST /ml/predict`
- **Model Management**: `GET /ml/models`, `DELETE /ml/models/{model_id}`

### Cognitive Service Endpoints
- **Health Check**: `GET /cognitive/health`
- **Agent Management**: `POST /cognitive/agents`, `GET /cognitive/agents`
- **Task Execution**: `POST /cognitive/execute`

### Standalone API Endpoints
- **Health Check**: `GET /health`
- **Readiness**: `GET /readyz`
- **Energy System**: `GET /healthz/energy`

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

- **Kubernetes Setup**: [KIND_CLUSTER_REFERENCE.md](deploy/KIND_CLUSTER_REFERENCE.md)
- **Ray Configuration**: [RAY_CONFIGURATION_PATTERN.md](docs/RAY_CONFIGURATION_PATTERN.md)
- **API Updates**: [README_SEEDCORE_API_UPDATES.md](docs/README_SEEDCORE_API_UPDATES.md)
- **Operation Manual**: [operation-manual.md](docs/operation-manual.md)

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

**Note**: This README reflects the current Kubernetes + KubeRay deployment setup. For the previous Docker Compose setup, see [docs/README-docker-setup.md](docs/README-docker-setup.md).
