# SeedCore Documentation

## Overview

SeedCore is a distributed cognitive computing platform that implements the Cognitive Organism Architecture (COA) using Ray for distributed computing. This documentation provides comprehensive guidance for understanding, deploying, and managing the SeedCore system.

## System Architecture

SeedCore implements a "swarm-of-swarms" model with specialized organs containing intelligent agents:

```
SeedCore Platform
├── Ray Distributed Computing Cluster
│   ├── Ray Head Node (Cluster Management)
│   ├── Ray Workers (Distributed Processing)
│   └── Redis (State Management)
├── Cognitive Organism Architecture (COA)
│   ├── Cognitive Organ (Reasoning & Planning)
│   ├── Actuator Organ (Action Execution)
│   └── Utility Organ (System Management)
├── FastAPI Application Server
│   ├── HTTP Endpoints
│   ├── OrganismManager
│   └── Task Execution
└── Observability Stack
    ├── Prometheus (Metrics)
    ├── Grafana (Visualization)
    └── Ray Dashboard (Monitoring)
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- 4GB+ RAM available
- Linux/macOS/Windows with Docker support

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd seedcore

# Navigate to docker directory
cd docker

# Start the system
docker compose up -d

# Wait for initialization (2-3 minutes)
# Check status
docker compose ps
```

### Verification

```bash
# Check Ray dashboard
curl http://localhost:8265/#/jobs

# Check COA organism status
curl -X GET "http://localhost:8000/organism/status"

# Check API health
curl -X GET "http://localhost:8000/health"
```

## Core Components

### 1. Ray Cluster

The distributed computing backbone:

- **Head Node**: Manages cluster resources and job distribution
- **Workers**: Execute distributed tasks and agent computations
- **Dashboard**: Web UI for monitoring (Port 8265)
- **Redis**: Internal state management (Port 6379)

### 2. Cognitive Organism Architecture (COA)

A biological-inspired computing model:

- **Organs**: Specialized containers for agent pools
- **Agents**: Ray actors with private memory and performance tracking
- **OrganismManager**: Central coordinator for lifecycle management

#### Organ Types

1. **Cognitive Organ**
   - Purpose: Reasoning, planning, complex task decomposition
   - Agents: 1 cognitive agent
   - Specialization: Analytical thinking and problem-solving

2. **Actuator Organ**
   - Purpose: Action execution and external API interactions
   - Agents: 1 actuator agent
   - Specialization: Task execution and system interactions

3. **Utility Organ**
   - Purpose: Memory management, health checks, system tasks
   - Agents: 1 utility agent
   - Specialization: System maintenance and optimization

### 3. FastAPI Application Server

The main application interface:

- **HTTP Endpoints**: RESTful API for external access
- **OrganismManager Integration**: COA lifecycle management
- **Task Execution**: Routes requests to appropriate organs
- **Health Monitoring**: System status and metrics

## Documentation Structure

### 📚 Core Documentation

- **[Ray Cluster Diagnostics](./ray-cluster-diagnostics.md)**
  - Comprehensive guide for diagnosing and analyzing Ray clusters
  - Job scheduling and management procedures
  - Troubleshooting and best practices

- **[COA Implementation Guide](./coa-implementation-guide.md)**
  - Detailed implementation of the Cognitive Organism Architecture
  - Configuration and usage examples
  - Testing and validation procedures

- **[Job Analysis and Management](./job-analysis-and-management.md)**
  - Understanding Ray job types and responsibilities
  - Job lifecycle and scheduling analysis
  - Monitoring and troubleshooting procedures

### 🛠️ Operational Documentation

- **[Docker Compose Configuration](../docker/docker-compose.yml)**
  - Service definitions and networking
  - Resource allocation and dependencies
  - Environment configuration

- **[Configuration Files](../src/seedcore/config/)**
  - System configuration and parameters
  - COA organ definitions
  - Environment-specific settings

### 📁 Documentation Directories

- **[Guides](./guides/)** - Step-by-step guides and operational procedures
  - Docker setup and configuration
  - Ray workers management
  - Salience service operations
  - **Ray Serve troubleshooting and debugging**
  - Ray Serve deployment patterns
  - Docker optimization and performance tuning
  - Job analysis and management

- **[Monitoring](./monitoring/)** - Monitoring, diagnostics, and analysis tools
  - Ray cluster diagnostic reports
  - Dashboard fixes and configurations
  - Monitoring system integration
  - Logging and observability guides

- **[API Reference](./api-reference/)** - Complete API documentation
  - Endpoint specifications
  - Request/response examples
  - Authentication and authorization

- **[Architecture](./architecture/)** - System design and architecture
  - Component diagrams
  - Data flow documentation
  - Design decisions and rationale

## Key Features

### 🧠 Cognitive Computing

- **Distributed Intelligence**: Ray-based distributed computing
- **Biological Inspiration**: COA with specialized organs and agents
- **Adaptive Learning**: Agent performance tracking and optimization
- **Scalable Architecture**: Horizontal scaling with Ray workers

### 🔧 System Management

- **Container Orchestration**: Docker Compose for service management
- **Health Monitoring**: Comprehensive observability stack
- **API-First Design**: RESTful endpoints for all operations
- **Configuration Management**: YAML-based configuration system

### 📊 Observability

- **Ray Dashboard**: Real-time cluster monitoring
- **Grafana**: Metrics visualization and dashboards
- **Prometheus**: Metrics collection and storage
- **Structured Logging**: Comprehensive logging system

## API Reference

### Core Endpoints

#### Organism Management

```bash
# Get organism status
GET /organism/status

# Execute task on specific organ
POST /organism/execute/{organ_id}
{
  "description": "Task description",
  "parameters": {"key": "value"}
}

# Execute task on random organ
POST /organism/execute/random
{
  "description": "Task description"
}

# Get organism summary
GET /organism/summary

# Initialize organism
POST /organism/initialize

# Shutdown organism
POST /organism/shutdown
```

#### System Health

```bash
# Health check
GET /health

# Ray cluster status
GET /ray/status

# System metrics
GET /metrics
```

### Example Usage

```bash
# Check system health
curl -X GET "http://localhost:8000/health"

# Get COA organism status
curl -X GET "http://localhost:8000/organism/status"

# Execute a cognitive task
curl -X POST "http://localhost:8000/organism/execute/cognitive_organ_1" \
  -H "Content-Type: application/json" \
  -d '{"description": "Analyze the given data and provide insights"}'

# Execute a random task
curl -X POST "http://localhost:8000/organism/execute/random" \
  -H "Content-Type: application/json" \
  -d '{"description": "Process the request"}'
```

## Monitoring and Diagnostics

### Dashboard Access

- **Ray Dashboard**: `http://localhost:8265`
  - Cluster overview and job status
  - Resource utilization
  - Actor and task monitoring

- **Grafana**: `http://localhost:3000`
  - Metrics visualization
  - Performance dashboards
  - Alert management

- **Prometheus**: `http://localhost:9090`
  - Metrics collection
  - Query interface
  - Alert rules

### Diagnostic Tools

#### Quick Health Check

```bash
# Copy diagnostic script
docker cp comprehensive_job_analysis.py seedcore-api:/tmp/

# Run analysis
docker exec -it seedcore-api python3 /tmp/comprehensive_job_analysis.py
```

#### COA Testing

```bash
# Copy test script
docker cp test_organism.py seedcore-api:/tmp/

# Run tests
docker exec -it seedcore-api python3 /tmp/test_organism.py
```

#### System Cleanup

```bash
# Copy cleanup script
docker cp cleanup_organs.py seedcore-api:/tmp/

# Execute cleanup
docker exec -it seedcore-api python3 /tmp/cleanup_organs.py
```

## Troubleshooting

### Common Issues

1. **Ray Cluster Issues**
   - Check Ray dashboard for job status
   - Verify container connectivity
   - Review Ray logs

2. **COA Initialization Problems**
   - Check organism status endpoint
   - Verify configuration file syntax
   - Review OrganismManager logs

3. **API Endpoint Issues**
   - Check FastAPI server status
   - Verify port accessibility
   - Review application logs

### Diagnostic Procedures

1. **System Health Check**
   ```bash
   docker compose ps
   curl -X GET "http://localhost:8000/health"
   ```

2. **Ray Cluster Analysis**
   ```bash
   docker exec -it seedcore-api python3 -c "
   import ray
   ray.init(address='ray://ray-head:10001', namespace='seedcore')
   print('Ray Status:', ray.is_initialized())
   print('Cluster Resources:', ray.cluster_resources())
   "
   ```

3. **COA Status Verification**
   ```bash
   curl -X GET "http://localhost:8000/organism/status"
   curl -X GET "http://localhost:8000/organism/summary"
   ```

## Development

### Local Development Setup

```bash
# Clone repository
git clone <repository-url>
cd seedcore

# Install dependencies
pip install -r requirements.txt

# Set up development environment
cp .env.example .env
# Edit .env with your configuration

# Start development services
cd docker
docker compose up -d postgres mysql neo4j
```

### Testing

```bash
# Run unit tests
python -m pytest tests/

# Run integration tests
python -m pytest tests/integration/

# Run COA tests
python test_organism.py
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## Performance Considerations

### Resource Requirements

- **Minimum**: 4GB RAM, 2 CPU cores
- **Recommended**: 8GB RAM, 4 CPU cores
- **Production**: 16GB+ RAM, 8+ CPU cores

### Scaling

- **Horizontal Scaling**: Add Ray workers via `ray-workers.yml`
- **Vertical Scaling**: Increase container resource limits
- **Load Balancing**: Implement external load balancer

### Optimization

- **Memory Management**: Monitor agent memory usage
- **CPU Utilization**: Balance workload across workers
- **Network Performance**: Optimize container networking

## Security

### Best Practices

1. **Container Security**
   - Use non-root users in containers
   - Regularly update base images
   - Implement resource limits

2. **Network Security**
   - Use internal networks for inter-service communication
   - Implement proper firewall rules
   - Secure external API access

3. **Data Security**
   - Encrypt sensitive data
   - Implement proper access controls
   - Regular security audits

## Support

### Getting Help

1. **Documentation**: Review this documentation thoroughly
2. **Issues**: Check existing GitHub issues
3. **Community**: Join the community discussions
4. **Support**: Contact support team for critical issues

### Reporting Issues

When reporting issues, please include:

- System configuration and environment
- Detailed error messages and logs
- Steps to reproduce the issue
- Expected vs actual behavior

## License

This project is licensed under the [MIT License](../LICENSE).

## Acknowledgments

- Ray team for the distributed computing framework
- FastAPI team for the web framework
- Docker team for containerization technology
- The open-source community for contributions

---

For more information, visit the [project repository](https://github.com/your-org/seedcore) or contact the development team. 