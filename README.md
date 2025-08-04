# SeedCore: Dynamic Cognitive Architecture with XGBoost ML Integration

A stateful, interactive cognitive architecture system with persistent organs, agents, energy-based control loops, and integrated XGBoost machine learning capabilities featuring realistic agent collaboration learning.

## 🚀 Quick Start (5 minutes)

### Prerequisites
- Docker and Docker Compose
- 4GB+ RAM available
- Linux/macOS/Windows with Docker support

### 1. Clone and Setup
```bash
git clone <repository-url>
cd seedcore
```

### 2. Start the Cluster
```bash
cd docker
./start-cluster.sh
```

**⚠️ Important**: Always use `./start-cluster.sh` instead of `docker compose up -d` to ensure proper service startup order and dependency management. Individual service restarts may fail due to Ray cluster state dependencies.

### 3. Wait for Initialization
```bash
# Wait 2-3 minutes for full startup
sleep 120

# Check health
curl http://localhost:8000/health
```

### 4. Verify Installation
```bash
# Check Ray dashboard
curl http://localhost:8265/api/version

# Check API health
curl http://localhost:8000/health

# Check energy system
curl http://localhost:8000/healthz/energy

# Test XGBoost integration
docker exec -it seedcore-ray-head python /app/docker/test_xgboost_docker.py
```

### 5. Run the Complete Demo
```bash
# Run the full XGBoost demo
docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py
```

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
- **Distributed Training**: Train XGBoost models across your Ray cluster (1 head + 3 workers)
- **Data Pipeline Integration**: Seamless data loading from various sources (CSV, Parquet, etc.)
- **Model Management**: Save, load, and manage trained models
- **Batch and Real-time Inference**: Support for both single predictions and batch processing
- **REST API**: Full integration with the SeedCore ML service
- **Feature Validation**: Automatic feature consistency checking between training and prediction

## 🏗️ System Architecture

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
│   ├── XGBoost ML Service
│   └── Task Execution
└── Observability Stack
    ├── Prometheus (Metrics)
    ├── Grafana (Visualization)
    └── Ray Dashboard (Monitoring)
```

## 📊 XGBoost Machine Learning

### Quick XGBoost Training
```bash
# Train a model with sample data
curl -X POST http://localhost:8000/xgboost/train \
  -H "Content-Type: application/json" \
  -d '{
    "use_sample_data": true,
    "sample_size": 1000,
    "sample_features": 20,
    "name": "my_first_model",
    "xgb_config": {
      "objective": "binary:logistic",
      "num_boost_round": 10
    }
  }'
```

### Make Predictions
```bash
# Single prediction
curl -X POST http://localhost:8000/xgboost/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
  }'

# Batch prediction
curl -X POST http://localhost:8000/xgboost/batch_predict \
  -H "Content-Type: application/json" \
  -d '{
    "data_source": "/data/test_data.csv",
    "data_format": "csv",
    "feature_columns": ["feature_0", "feature_1", "feature_2"],
    "path": "/data/models/my_model/model.xgb"
  }'
```

### Model Management
```bash
# List all models
curl http://localhost:8000/xgboost/list_models

# Get model info
curl http://localhost:8000/xgboost/model_info

# Delete a model
curl -X DELETE http://localhost:8000/xgboost/delete_model \
  -H "Content-Type: application/json" \
  -d '{"name": "old_model"}'
```

## 🔄 Energy System Operations

### Basic Energy Operations
```bash
# Check current energy state
curl http://localhost:8000/energy/gradient

# Run a realistic two-agent task
curl -X POST http://localhost:8000/actions/run_two_agent_task

# Run a simulation step
curl http://localhost:8000/run_simulation_step

# Reset energy ledger and pair statistics
curl -X POST http://localhost:8000/actions/reset
```

### COA Organism Management
```bash
# Get organism status
curl -X GET "http://localhost:8000/organism/status"

# Execute task on specific organ
curl -X POST "http://localhost:8000/organism/execute/cognitive_organ_1" \
  -H "Content-Type: application/json" \
  -d '{"description": "Analyze the given data and provide insights"}'

# Execute task on random organ
curl -X POST "http://localhost:8000/organism/execute/random" \
  -H "Content-Type: application/json" \
  -d '{"description": "Process the request"}'
```

## 📈 Monitoring and Observability

### Dashboard Access
- **Ray Dashboard**: `http://localhost:8265` - Cluster overview and job status
- **Grafana**: `http://localhost:3000` (admin/seedcore) - Metrics visualization
- **Prometheus**: `http://localhost:9090` - Metrics collection and querying

### Health Checks
```bash
# System health
curl http://localhost:8000/health

# Ray cluster status
curl http://localhost:8000/ray/status

# Energy system health
curl http://localhost:8000/healthz/energy
```

## 🛠️ Development

### Local Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up development environment
cp env.example .env
# Edit .env with your configuration

# Start development services
cd docker
docker compose up -d postgres mysql neo4j
```

### Testing
```bash
# Test energy model
docker compose exec seedcore-api python -m scripts.test_energy_model

# Run energy calibration
docker compose exec seedcore-api python -m scripts.test_energy_calibration

# Test XGBoost integration
docker exec -it seedcore-ray-head python /app/docker/test_xgboost_docker.py

# Run the complete demo
docker exec -it seedcore-ray-head python /app/docker/xgboost_docker_demo.py
```

## 🔧 Configuration

### XGBoost Configuration
```json
{
  "xgb_config": {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "eta": 0.1,
    "max_depth": 5,
    "tree_method": "hist",
    "num_boost_round": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8
  },
  "training_config": {
    "num_workers": 3,
    "use_gpu": false,
    "cpu_per_worker": 1,
    "memory_per_worker": 2000000000
  }
}
```

### Environment Variables
```bash
# Copy and edit the example environment file
cp env.example .env

# Key variables to configure:
RAY_ADDRESS=ray://localhost:10001
PYTHONPATH=/app:/app/src
```

## 🚨 Troubleshooting

### Common Issues

1. **Service Dependencies**
   ```bash
   # Always use the cluster script for reliable operation
   cd docker
   ./start-cluster.sh restart
   
   # Don't restart individual services - they may fail due to dependencies
   ```

2. **Ray Cluster Issues**
   ```bash
   # Check Ray dashboard
   curl http://localhost:8265/api/version
   
   # Check container status
   docker ps | grep seedcore
   
   # Check Ray logs
   docker logs seedcore-ray-head
   ```

3. **XGBoost Feature Mismatch**
   ```bash
   # Ensure feature count matches between training and prediction
   # Check model metadata for expected features
   curl http://localhost:8000/xgboost/model_info
   ```

4. **Memory Issues**
   ```bash
   # Reduce memory usage in training config
   "memory_per_worker": 1000000000  # 1GB instead of 2GB
   ```

### Diagnostic Tools
```bash
# Comprehensive job analysis
docker cp comprehensive_job_analysis.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/comprehensive_job_analysis.py

# COA testing
docker cp test_organism.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/test_organism.py

# System cleanup
docker cp cleanup_organs.py seedcore-api:/tmp/
docker exec -it seedcore-api python3 /tmp/cleanup_organs.py
```

## 📚 Documentation

### Core Documentation
- **[XGBoost Quick Start](docs/xgboost_quickstart.md)** - Get started with XGBoost in 5 minutes
- **[XGBoost Integration Guide](docs/xgboost_integration.md)** - Complete XGBoost API reference
- **[XGBoost Daily Reference](docs/xgboost_daily_reference.md)** - Common operations and troubleshooting
- **[Main Documentation](docs/README.md)** - Comprehensive system documentation

### API Reference
- **Core Endpoints**: `/health`, `/organism/*`, `/energy/*`
- **XGBoost Endpoints**: `/xgboost/train`, `/xgboost/predict`, `/xgboost/batch_predict`
- **Model Management**: `/xgboost/list_models`, `/xgboost/model_info`, `/xgboost/delete_model`

## 🎯 Performance Considerations

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

## 🔒 Security

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

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📞 Support

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

## 📄 License

This project is licensed under the [MIT License](LICENSE).

## 🙏 Acknowledgments

- Ray team for the distributed computing framework
- XGBoost team for the gradient boosting library
- FastAPI team for the web framework
- Docker team for containerization technology
- The open-source community for contributions

---

## 🎉 Recent Updates

### Latest Fixes (2025-08-04)
- ✅ **Fixed XGBoost batch prediction feature mismatch** - Resolved TypeError and ReadTimeoutError
- ✅ **Enhanced feature validation** - Added automatic feature consistency checking
- ✅ **Improved error handling** - Better timeout management and error messages
- ✅ **Performance optimization** - Reduced batch sizes and increased timeouts
- ✅ **Defensive coding** - Added comprehensive feature validation and metadata storage

### Key Improvements
- **Feature Consistency**: Automatic validation between training and prediction features
- **Better Error Messages**: Detailed debugging information for feature mismatches
- **Increased Timeouts**: Extended from 60s to 180s for batch prediction
- **Metadata Storage**: Feature columns stored in model metadata for validation
- **Performance Tuning**: Optimized batch sizes and processing parameters

For more information, visit the [project repository](https://github.com/your-org/seedcore) or contact the development team.
