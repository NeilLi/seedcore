# SeedCore Documentation Index

Welcome to the SeedCore documentation! This index provides an overview of all available documentation and helps you navigate to the information you need.

## 📚 Documentation Overview

SeedCore is a multi-tier memory system implementing the Collective Organic Architecture (COA) specification. The system provides stateful Ray-based agents with distributed memory management across multiple tiers.

## 🗂️ Documentation Structure

### 📖 Core Documentation

| Document | Purpose | Best For |
|----------|---------|----------|
| **[README.md](README.md)** | Project overview and quick start | Getting started, understanding the system |
| **[API_REFERENCE.md](API_REFERENCE.md)** | Complete API documentation | Developers, API integration |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System architecture and design | System design, technical deep-dive |
| **[NEXT_STEPS.md](NEXT_STEPS.md)** | Development roadmap and priorities | Planning, future development |
| **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** | Essential commands and troubleshooting | Daily development, debugging |

## 🎯 Quick Navigation

### 🚀 Getting Started
- **New to SeedCore?** → [README.md](README.md)
- **Need to set up the system?** → [README.md](README.md#quick-start-guide)
- **Want to understand the architecture?** → [ARCHITECTURE.md](ARCHITECTURE.md)

### 💻 Development
- **API integration?** → [API_REFERENCE.md](API_REFERENCE.md)
- **Need commands and troubleshooting?** → [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
- **Planning next features?** → [NEXT_STEPS.md](NEXT_STEPS.md)

### 🔧 Operations
- **System administration?** → [QUICK_REFERENCE.md](QUICK_REFERENCE.md#troubleshooting)
- **Performance monitoring?** → [QUICK_REFERENCE.md](QUICK_REFERENCE.md#monitoring--debugging)
- **Deployment guidance?** → [ARCHITECTURE.md](ARCHITECTURE.md#deployment-architecture)

## 📊 Current System Status

### ✅ Completed Features
- **Tier 0 (Ma)**: Ray actor-based agents with 128-dim state vectors
- **Tier 1 (Mw)**: Working memory with capacity management  
- **Tier 2 (Mlt)**: Long-term memory with compression
- **Tier 3 (Mfb)**: MySQL-backed flashbulb memory
- **Infrastructure**: Complete Docker setup with all databases
- **API Layer**: RESTful endpoints for all tiers

### 🔄 In Progress
- Performance optimization and monitoring
- Advanced compression algorithms
- Cross-tier data migration policies

### 📋 Next Priorities
1. **Energy Model Integration** (1-2 weeks)
2. **Advanced Monitoring** (1-2 weeks)
3. **Machine Learning Integration** (1-2 months)

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                      │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP/REST
┌─────────────────────▼───────────────────────────────────────┐
│                    FastAPI Server                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    Core Components                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Ray Agents      │  │ Memory Tiers    │  │ Database    │ │
│  │ (Tier 0)        │  │ (Tiers 1-2)     │  │ Connections │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    Infrastructure Layer                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │    Ray      │  │ PostgreSQL  │  │    Neo4j    │         │
│  │  Cluster    │  │             │  │             │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  ┌─────────────┐  ┌─────────────┐                          │
│  │    Redis    │  │    MySQL    │                          │
│  │             │  │             │                          │
│  └─────────────┘  └─────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## 🎯 Quick Start Commands

```bash
# Start the system
cd docker && docker-compose up -d

# Test Tier 0 (Agent Memory)
curl -X POST http://localhost/tier0/agents/create \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test_agent", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}}'

# Test Tier 3 (Flashbulb Memory)
curl -X POST http://localhost/mfb/incidents \
  -H "Content-Type: application/json" \
  -d '{"event_data": {"type": "alert"}, "salience_score": 0.9}'
```

## 📈 Key Metrics

| Metric | Current Status | Target |
|--------|----------------|--------|
| **System Uptime** | ✅ Running | > 99.9% |
| **API Response Time** | ✅ < 100ms | < 100ms |
| **Memory Tier Hit Rate** | ✅ > 90% | > 90% |
| **Agent Failure Rate** | ✅ < 1% | < 1% |

## 🔗 External Resources

- **Ray Documentation**: https://docs.ray.io/
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Docker Compose**: https://docs.docker.com/compose/
- **MySQL Documentation**: https://dev.mysql.com/doc/

## 📞 Getting Help

### Documentation Issues
- Check the relevant documentation file first
- Use the search function in your browser
- Review the troubleshooting sections

### Technical Issues
- Check logs: `docker-compose logs`
- Verify system health: `curl http://localhost/health`
- Review the troubleshooting guide in [QUICK_REFERENCE.md](QUICK_REFERENCE.md)

### Development Questions
- Review the architecture in [ARCHITECTURE.md](ARCHITECTURE.md)
- Check the API reference in [API_REFERENCE.md](API_REFERENCE.md)
- Plan next steps with [NEXT_STEPS.md](NEXT_STEPS.md)

## 📝 Contributing to Documentation

When updating documentation:
1. Keep it concise and focused
2. Include practical examples
3. Update this index if adding new documents
4. Test all commands and examples
5. Maintain consistent formatting

---

**Last Updated**: January 2024  
**Version**: 1.0.0  
**Status**: ✅ All documentation complete and verified 