# SeedCore Quick Reference

## 🚀 Quick Start Commands

### Start the System
```bash
cd docker
docker-compose up -d
```

### Check System Status
```bash
# Check all services
docker-compose ps

# View logs
docker-compose logs

# Check specific service
docker-compose logs seedcore-api
```

### Stop the System
```bash
docker-compose down
```

## 📊 API Testing Commands

### Tier 0 (Agent Memory) Testing
```bash
# Create an agent
curl -X POST http://localhost/tier0/agents/create \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test_agent", "role_probs": {"E": 0.7, "S": 0.2, "O": 0.1}}'

# Get agent heartbeat
curl http://localhost/tier0/agents/test_agent/heartbeat

# Execute a task
curl -X POST http://localhost/tier0/agents/test_agent/execute \
  -H "Content-Type: application/json" \
  -d '{"task_id": "task_1", "type": "analysis", "complexity": 0.8}'

# Get system summary
curl http://localhost/tier0/summary
```

### Tier 3 (Flashbulb Memory) Testing
```bash
# Log an incident
curl -X POST http://localhost/mfb/incidents \
  -H "Content-Type: application/json" \
  -d '{"event_data": {"type": "alert"}, "salience_score": 0.9}'

# Get statistics
curl http://localhost/mfb/stats
```

## 🔧 Configuration

### Environment Variables (.env)
```bash
# MySQL Configuration
MYSQL_ROOT_PASSWORD=rootpassword
MYSQL_DATABASE=seedcore
MYSQL_USER=seedcore
MYSQL_PASSWORD=password
MYSQL_PORT=3306
MYSQL_HOST=seedcore-mysql

# PostgreSQL Configuration
PG_DSN=postgresql+psycopg2://postgres:password@postgres:5432/postgres

# Ray Configuration
RAY_HEAD_HOST=ray-head
RAY_HEAD_PORT=10001
```

### Service Ports
| Service | Port | Purpose |
|---------|------|---------|
| FastAPI | 80 | Main API server |
| Ray Dashboard | 8265 | Ray cluster monitoring |
| PostgreSQL | 5432 | Primary database |
| Neo4j | 7474 | Graph database |
| Redis | 6379 | Cache and pub/sub |
| MySQL | 3306 | Flashbulb memory |

## 🐛 Troubleshooting

### Common Issues

#### 1. Ray Worker Not Starting
```bash
# Check Ray worker logs
docker-compose logs ray-worker

# Restart Ray services
docker-compose restart ray-head ray-worker

# Check Ray cluster status
curl http://localhost:8265/api/cluster
```

#### 2. Database Connection Issues
```bash
# Test PostgreSQL
docker exec -it seedcore-postgres psql -U postgres -d postgres

# Test MySQL
mysql -h 127.0.0.1 -P 3306 -u seedcore -ppassword seedcore

# Test Neo4j
curl -u neo4j:password http://localhost:7474/db/data/
```

#### 3. API Endpoints Not Responding
```bash
# Check API health
curl http://localhost/health

# Check API logs
docker-compose logs seedcore-api

# Restart API service
docker-compose restart seedcore-api
```

### Debug Commands
```bash
# View all container logs
docker-compose logs -f

# Check container resource usage
docker stats

# Access container shell
docker exec -it seedcore-api bash

# Clean restart (removes volumes)
docker-compose down -v && docker-compose up -d --build
```

## 📁 File Structure Quick Reference

```
seedcore/
├── docker/
│   ├── docker-compose.yml          # Main orchestration
│   ├── setup/init_mysql.sql       # MySQL initialization
│   └── requirements-minimal.txt    # Python dependencies
├── src/seedcore/
│   ├── agents/
│   │   ├── ray_actor.py           # Tier 0 Ray agents
│   │   └── tier0_manager.py       # Agent management
│   ├── memory/
│   │   ├── flashbulb_memory.py    # Tier 3 implementation
│   │   └── system.py              # Tiers 1-2 implementation
│   ├── api/routers/
│   │   └── mfb_router.py          # Flashbulb Memory API
│   ├── database.py                # Database connections
│   └── telemetry/server.py        # FastAPI server
├── examples/
│   ├── tier0_agent_demo.py        # Tier 0 demonstration
│   └── test_tier0_api.py          # API testing
└── docs/                          # Documentation
```

## 🔍 Monitoring & Debugging

### Health Checks
```bash
# System health
curl http://localhost/health

# Ray cluster health
curl http://localhost:8265/api/cluster

# Database health
docker-compose exec postgres pg_isready
docker-compose exec mysql mysqladmin ping
```

### Performance Monitoring
```bash
# Check agent performance
curl http://localhost/tier0/summary | jq '.summary'

# Check memory usage
docker stats --no-stream

# Monitor logs in real-time
docker-compose logs -f seedcore-api
```

### Database Queries
```bash
# MySQL - Check flashbulb incidents
docker exec -it seedcore-mysql mysql -u seedcore -ppassword seedcore -e "SELECT COUNT(*) FROM flashbulb_incidents;"

# PostgreSQL - Check general data
docker exec -it seedcore-postgres psql -U postgres -d postgres -c "SELECT version();"

# Neo4j - Check graph data
curl -u neo4j:password http://localhost:7474/db/data/ -H "Accept: application/json"
```

## 🚀 Development Commands

### Code Development
```bash
# Run tests
python -m pytest tests/

# Format code
black src/seedcore/

# Lint code
flake8 src/seedcore/

# Type checking
mypy src/seedcore/
```

### Git Workflow
```bash
# Check status
git status

# Add changes
git add .

# Commit changes
git commit -m "feat: add new feature"

# Push changes
git push origin main
```

## 🎯 Scenarios

### Scenario 1: Collaborative Task with Knowledge Gap

**Purpose**: Demonstrates multi-tier memory system cache miss handling and knowledge retrieval.

```bash
# 1. Check service status
docker-compose ps

# 2. Pre-populate Long-Term Memory (if needed)
docker-compose exec seedcore-api python scripts/populate_mlt.py

# 3. Run the scenario
docker-compose exec seedcore-api python -m scripts.scenario_1_knowledge_gap

# 4. View scenario logs
docker-compose logs ray-head ray-worker | grep -E "(Agent|Querying|Found)"
```

**Expected Behavior**:
- Phase 1: Cache miss in Mw, escalation to Mlt, knowledge retrieval
- Phase 2: Cache hit in Mw (knowledge now cached)
- Phase 3: Collaborative task completion with both agents

**Troubleshooting**:
```bash
# Check Ray agent initialization
docker-compose exec ray-head python -c "import redis, asyncpg, neo4j; print('Dependencies OK')"

# Test memory manager connections
docker-compose exec seedcore-api python -c "from src.seedcore.memory.mw_manager import MwManager; print('MwManager OK')"

# Restart Ray services if needed
docker-compose restart ray-head ray-worker
```

## 📈 Performance Benchmarks

### Expected Performance
- **API Response Time**: < 100ms for 95% of requests
- **Agent Creation**: < 1 second
- **Task Execution**: < 500ms
- **Memory Operations**: < 50ms
- **Database Queries**: < 100ms

### Load Testing
```bash
# Basic load test (requires Apache Bench)
ab -n 1000 -c 10 http://localhost/tier0/summary

# Python load test
python examples/test_tier0_api.py
```

## 🔐 Security Notes

### Current Security Status
- **Authentication**: Not implemented (development mode)
- **Authorization**: Not implemented
- **Encryption**: TLS not configured
- **API Keys**: Not required

### Production Security Checklist
- [ ] Implement API key authentication
- [ ] Add role-based authorization
- [ ] Enable TLS/SSL encryption
- [ ] Configure firewall rules
- [ ] Set up audit logging
- [ ] Implement rate limiting

## 📞 Support & Resources

### Documentation
- **Main README**: `docs/README.md`
- **API Reference**: `docs/API_REFERENCE.md`
- **Architecture**: `docs/ARCHITECTURE.md`
- **Next Steps**: `docs/NEXT_STEPS.md`

### Useful Links
- **Ray Documentation**: https://docs.ray.io/
- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Docker Compose**: https://docs.docker.com/compose/
- **MySQL Documentation**: https://dev.mysql.com/doc/

### Log Locations
- **Application Logs**: `docker-compose logs seedcore-api`
- **Ray Logs**: `docker-compose logs ray-head ray-worker`
- **Database Logs**: `docker-compose logs postgres mysql neo4j redis`

## 🎯 Quick Development Tips

1. **Always check logs first** when troubleshooting
2. **Use `docker-compose down -v`** for clean restarts
3. **Test API endpoints** with curl before writing code
4. **Monitor resource usage** with `docker stats`
5. **Keep documentation updated** as you develop
6. **Use feature branches** for new development
7. **Write tests** for new functionality
8. **Check health endpoints** regularly

This quick reference should help you get up and running quickly with SeedCore development and troubleshooting. 