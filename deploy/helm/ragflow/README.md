# RAGFlow Helm Chart

This Helm chart deploys RAGFlow, a Retrieval-Augmented Generation workflow engine, into your Seedcore Kubernetes cluster.

## Overview

RAGFlow integrates seamlessly with your existing Seedcore data stores:
- **PostgreSQL with pgvector** - for vector storage and similarity search
- **Redis** - for caching and session management
- **Neo4j** - for graph-based knowledge representation

## Features

- **Document Processing**: Supports PDF, DOCX, TXT, MD, and HTML files
- **Vector Search**: Leverages pgvector for efficient similarity search
- **LLM Integration**: Configurable LLM providers (OpenAI, Ollama, etc.)
- **Embedding Models**: Flexible embedding model support
- **API Server**: RESTful API for document ingestion and retrieval
- **Health Monitoring**: Built-in health checks and metrics

## Prerequisites

- Kubernetes cluster with Helm 3.x
- Existing Seedcore data stores (PostgreSQL, Redis, Neo4j)
- Storage class for persistent volumes
- Access to Docker Hub (for pulling RAGFlow image)

## Installation

The RAGFlow chart is automatically deployed when you run:

```bash
./deploy/setup-cores.sh
```

This script deploys all Seedcore cores including RAGFlow with proper integration.

## Manual Installation

To install RAGFlow manually:

```bash
helm upgrade --install ragflow ./helm/ragflow \
  --namespace seedcore-dev \
  --set database.host=postgresql.seedcore-dev.svc.cluster.local \
  --set database.user=postgres \
  --set database.password=password \
  --set redis.host=redis-master.seedcore-dev.svc.cluster.local \
  --set neo4j.uri=bolt://neo4j.seedcore-dev.svc.cluster.local:7687
```

## Configuration

### Image Configuration

The chart uses the official RAGFlow image:
- **Repository**: `infiniflow/ragflow`
- **Tag**: `v0.20.3` (stable version)
- **Alternative tags**: `v0.20.2`, `nightly`, `nightly-slim`

To use a different version, update `values.yaml`:
```yaml
image:
  repository: infiniflow/ragflow
  tag: "v0.20.2"  # or "nightly", "nightly-slim"
```

### Database Settings

```yaml
database:
  host: "postgresql.seedcore-dev.svc.cluster.local"
  port: 5432
  name: "ragflow"
  user: "postgres"
  password: "password"
  sslMode: "disable"
```

### Redis Settings

```yaml
redis:
  host: "redis-master.seedcore-dev.svc.cluster.local"
  port: 6379
  password: ""
  db: 0
```

### Neo4j Settings

```yaml
neo4j:
  uri: "bolt://neo4j.seedcore-dev.svc.cluster.local:7687"
  user: "neo4j"
  password: "password"
  database: "neo4j"
```

### LLM Configuration

```yaml
ragflow:
  llm:
    provider: "openai"  # or "ollama", "azure", etc.
    model: "gpt-3.5-turbo"
    temperature: 0.1
    maxTokens: 2000
```

### Embedding Configuration

```yaml
ragflow:
  embedding:
    provider: "openai"  # or "ollama", "sentence-transformers", etc.
    model: "text-embedding-ada-002"
    batchSize: 32
```

## Usage

### API Endpoints

- **Health Check**: `GET /health`
- **Readiness**: `GET /ready`
- **Document Upload**: `POST /api/v1/documents`
- **Vector Search**: `POST /api/v1/search`
- **RAG Query**: `POST /api/v1/rag`

### Example Usage

```bash
# Check health
curl http://ragflow.seedcore-dev.svc.cluster.local:8080/health

# Port forward for local testing
kubectl port-forward -n seedcore-dev svc/ragflow 8080:8080

# Test API locally
curl http://localhost:8080/health
```

## Integration with Seedcore

RAGFlow is designed to work alongside your existing Seedcore architecture:

1. **Coordinator + Dispatchers**: Add a `RagflowDispatcher` actor to your Seedcore orchestration
2. **Shared Data Stores**: Reuses existing PostgreSQL, Redis, and Neo4j instances
3. **Service Discovery**: Accessible at `ragflow.seedcore-dev.svc.cluster.local:8080`
4. **Modular Design**: Can be easily removed or replaced without affecting core services

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -n seedcore-dev -l app.kubernetes.io/name=ragflow
```

### View Logs

```bash
kubectl logs -n seedcore-dev -l app.kubernetes.io/name=ragflow
```

### Check Service

```bash
kubectl get svc -n seedcore-dev ragflow
```

### Verify Database Connection

```bash
kubectl exec -n seedcore-dev deploy/ragflow -- env | grep DATABASE
```

## Resources

- **CPU**: 200m request, 500m limit
- **Memory**: 512Mi request, 1Gi limit
- **Storage**: 2Gi persistent volume
- **Port**: 8080 (HTTP API)

## Notes

- RAGFlow automatically creates the `ragflow` database in PostgreSQL if it doesn't exist
- Vector dimensions are set to 1536 by default (OpenAI text-embedding-ada-002)
- Health checks are configured with appropriate delays for startup
- The service is exposed as ClusterIP by default; use port-forward or Ingress for external access
