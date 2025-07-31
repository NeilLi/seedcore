# Guides Documentation

This directory contains step-by-step guides and operational documentation for the SeedCore system.

## 📚 Available Guides

- **[docker-setup-guide.md](docker-setup-guide.md)** - Complete Docker environment setup guide
- **[ray-workers-guide.md](ray-workers-guide.md)** - Ray workers management and scaling
- **[salience-service-operations.md](salience-service-operations.md)** - Salience scoring service operations
- **[job-analysis-and-management.md](job-analysis-and-management.md)** - Job analysis and management procedures
- **[ray_serve_troubleshooting.md](ray_serve_troubleshooting.md)** - Ray Serve troubleshooting guide
- **[ray_serve_debugging_commands.md](ray_serve_debugging_commands.md)** - Quick reference for Ray Serve debugging commands
- **[RAY_SERVE_PATTERN.md](RAY_SERVE_PATTERN.md)** - Ray Serve deployment patterns and best practices
- **[OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md)** - Docker optimization and performance tuning
- **[service-dependencies-and-restart-behavior.md](service-dependencies-and-restart-behavior.md)** - Service dependencies and restart behavior patterns
- **[SERVICE_DEPENDENCIES_SUMMARY.md](SERVICE_DEPENDENCIES_SUMMARY.md)** - Quick reference for operators

## 🚀 Quick Start Guides

- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Quick reference for common operations
- **[NEXT_STEPS.md](NEXT_STEPS.md)** - Next steps and development roadmap

## 🔧 Ray Serve Operations

The Ray Serve guides cover:

### Troubleshooting
- **"Serve not started" warnings** - Dashboard false positives and solutions
- **Endpoint accessibility** - External access configuration
- **Application deployment** - Proper FastAPI and routing setup
- **Dashboard detection** - API and namespace issues

### Debugging Commands
- Container status and log checking
- Serve API endpoint testing
- Network and port verification
- Application deployment monitoring

### Quick Fixes
- External access configuration with `host: "0.0.0.0"`
- FastAPI with `@serve.ingress` for proper routing
- Namespace management and connection patterns
- Model file handling and fallback strategies

### Deployment Patterns
- **RAY_SERVE_PATTERN.md** - Best practices for Ray Serve deployments
- FastAPI integration patterns
- External access configuration
- Namespace and application management

## 🐳 Docker Operations

### Setup and Configuration
- **docker-setup-guide.md** - Complete Docker environment setup
- **OPTIMIZATION_SUMMARY.md** - Performance tuning and optimization
- Container orchestration and management
- Resource allocation and scaling

### Optimization
- Image size optimization strategies
- Performance tuning techniques
- Resource allocation best practices
- Monitoring and metrics configuration

## 🔗 Service Dependencies

### Understanding System Dependencies
- **[service-dependencies-and-restart-behavior.md](service-dependencies-and-restart-behavior.md)** - Comprehensive guide to service dependencies and restart behavior
- Ray cluster state management
- API dependency on Ray head and databases
- Safe restart procedures and troubleshooting

### Key Concepts
- **Ray Client/Cluster State**: Understanding Ray's stateful nature
- **Actor & Namespace Coupling**: How actors and namespaces affect restarts
- **Service Health Checks**: Docker Compose dependency limitations
- **Ray Networking**: Container network timing sensitivity

### Best Practices
- Full cluster restarts vs. individual service restarts
- Dependency tree understanding
- Diagnostic procedures for dependency issues
- Troubleshooting common restart problems

## 📋 Operational Procedures

The guides documentation covers:
- System setup and configuration
- Service operations and maintenance
- Troubleshooting and debugging
- Performance optimization
- Monitoring and observability
- Best practices and recommendations

## 🔗 Related Documentation

- **API Reference**: See `../api-reference/` for API documentation
- **Architecture**: See `../architecture/` for system design
- **Monitoring**: See `../monitoring/` for monitoring tools
- **Docker Configuration**: See `../../docker/` for Docker files and scripts 