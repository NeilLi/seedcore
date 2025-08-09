# SeedCore Architecture

## System Overview

SeedCore implements a multi-tier memory system based on the Collective Organic Architecture (COA) specification. The system uses Ray for distributed computing and provides stateful agents with private memory, working memory, long-term memory, and flashbulb memory tiers.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                      │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP/REST
┌─────────────────────▼───────────────────────────────────────┐
│                    FastAPI Server                           │
│              (src/seedcore/telemetry/server.py)            │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                    API Routers                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │   Tier 0 (Ma)   │  │   Tier 3 (Mfb)  │  │   Health    │ │
│  │   Endpoints     │  │   Endpoints     │  │   Checks    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
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

## Component Details

### 1. FastAPI Server Layer

**File**: `src/seedcore/telemetry/server.py`

**Responsibilities**:
- HTTP request handling and routing
- Request validation and response formatting
- Integration with core components
- Health monitoring and status reporting

**Key Features**:
- RESTful API endpoints for all memory tiers
- Automatic request/response serialization
- Error handling and logging
- Health check endpoints

### 2. Ray Agent System (Tier 0: Ma)

**Files**: 
- `src/seedcore/agents/ray_actor.py`
- `src/seedcore/agents/tier0_manager.py`

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Tier0MemoryManager                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Agent Registry  │  │ Heartbeat       │  │ Task        │ │
│  │                 │  │ Collection      │  │ Execution   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │ Ray Remote Calls
┌─────────────────────▼───────────────────────────────────────┐
│                    RayAgent Actors                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Agent 1         │  │ Agent 2         │  │ Agent N     │ │
│  │ - State Vector  │  │ - State Vector  │  │ - State     │ │
│  │ - Performance   │  │ - Performance   │  │   Vector    │ │
│  │ - Memory Util   │  │ - Memory Util   │  │ - ...       │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **Stateful Actors**: Each agent maintains its own private state
- **128-Dimensional State Vectors**: Per COA specification with adaptive T/S/P budgeting and OCPS signals in F-block
- **Performance Tracking**: Success rate, quality score, capability score
- **Memory Utilization**: Tracks agent memory usage
- **Heartbeat System**: Periodic state reporting for monitoring
- **Role Probabilities**: E/S/O role distribution
- **Optional Checkpointing (MySQL)**: Agents can persist/restore their private state via a pluggable MySQL-backed checkpoint store; default behavior remains ephemeral.

### 3. Memory Tier System (Tiers 1-2)

**File**: `src/seedcore/memory/system.py`

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                    SharedMemorySystem                       │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Working Memory  │  │ Long-Term       │                  │
│  │ (Mw)            │  │ Memory (Mlt)    │                  │
│  │ - Fast Access   │  │ - Large Capacity│                  │
│  │ - Small Size    │  │ - Persistent    │                  │
│  │ - Overflow      │  │ - Compression   │                  │
│  └─────────────────┘  └─────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **Working Memory (Mw)**: Fast, small-capacity memory for active data
- **Long-Term Memory (Mlt)**: Larger, persistent storage with compression
- **Automatic Overflow**: Data migration between tiers
- **Hit/Miss Tracking**: Performance monitoring
- **Capacity Management**: Automatic cleanup and optimization

### 4. Flashbulb Memory System (Tier 3: Mfb)

**Files**:
- `src/seedcore/memory/flashbulb_memory.py`
- `src/seedcore/api/routers/mfb_router.py`

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                    FlashbulbMemoryManager                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Log Incident    │  │ Query Incidents │  │ Statistics  │ │
│  │ - High Salience │  │ - Time Range    │  │ - System    │ │
│  │ - JSON Storage  │  │ - Threshold     │  │   Metrics   │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │ SQLAlchemy
┌─────────────────────▼───────────────────────────────────────┐
│                    MySQL Database                           │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ flashbulb_incidents table                               │ │
│  │ - incident_id (UUID)                                    │ │
│  │ - salience_score (FLOAT)                                │ │
│  │ - event_data (JSON)                                     │ │
│  │ - created_at (TIMESTAMP)                                │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **High-Salience Events**: Stores critical system events
- **JSON Data Storage**: Flexible event data structure
- **Salience Scoring**: Importance-based filtering
- **Time-Based Queries**: Historical incident analysis
- **Durable Storage**: MySQL-backed persistence

### 5. Database Layer

**File**: `src/seedcore/database.py`

**Architecture**:
```
┌─────────────────────────────────────────────────────────────┐
│                    Database Connections                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ PostgreSQL      │  │ MySQL           │  │ Neo4j       │ │
│  │ - Primary DB    │  │ - Flashbulb     │  │ - Graph     │ │
│  │ - General Data  │  │   Memory        │  │   Relations │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
│  ┌─────────────────┐                                       │
│  │ Redis           │                                       │
│  │ - Cache         │                                       │
│  │ - Pub/Sub       │                                       │
│  └─────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **Multi-Database Support**: PostgreSQL, MySQL, Neo4j, Redis
- **Connection Pooling**: Efficient database connections
- **Session Management**: SQLAlchemy session handling
- **Error Handling**: Robust connection error management
- **Agent Checkpointing (MySQL)**: Optional MySQL-backed store for agent private memory warm restarts

## Data Flow

### 1. Agent Task Execution Flow

```
Client Request → FastAPI → Tier0Manager → RayAgent → Task Execution → Performance Update → Heartbeat
```

1. **Client sends task execution request**
2. **FastAPI validates and routes request**
3. **Tier0Manager selects appropriate agent**
4. **RayAgent executes task and updates performance**
5. **Agent emits heartbeat with updated state**
6. **Response returned to client**

### 2. Memory Write Flow

```
Agent → Memory System → Tier Selection → Data Storage → Hit/Miss Tracking → Response
```

1. **Agent requests memory write**
2. **Memory system determines appropriate tier**
3. **Data stored in selected tier**
4. **Performance metrics updated**
5. **Response with storage confirmation**

### 3. Flashbulb Incident Flow

```
High-Salience Event → FlashbulbManager → MySQL Storage → Incident ID → Response
```

1. **High-salience event detected**
2. **FlashbulbManager processes event**
3. **Event stored in MySQL with salience score**
4. **Unique incident ID generated**
5. **Response with incident details**

## Scalability Considerations

### 1. Ray Cluster Scaling

- **Horizontal Scaling**: Add more Ray worker nodes
- **Load Distribution**: Ray automatically distributes tasks
- **Fault Tolerance**: Ray handles node failures
- **Resource Management**: Ray manages CPU/memory allocation

### 2. Database Scaling

- **PostgreSQL**: Read replicas, connection pooling
- **MySQL**: Master-slave replication for flashbulb memory
- **Neo4j**: Cluster mode for graph operations
- **Redis**: Redis Cluster for high availability

### 3. API Scaling

- **Load Balancing**: Multiple FastAPI instances
- **Caching**: Redis for frequently accessed data
- **Rate Limiting**: Protect against abuse
- **Monitoring**: Health checks and metrics

## Security Considerations

### 1. Authentication & Authorization

- **API Keys**: For external access
- **Role-Based Access**: Different permissions per tier
- **Input Validation**: Sanitize all inputs
- **SQL Injection Protection**: Use parameterized queries

### 2. Data Protection

- **Encryption**: Encrypt sensitive data at rest
- **Network Security**: TLS for all communications
- **Access Logging**: Audit all data access
- **Data Retention**: Automatic cleanup policies

### 3. Infrastructure Security

- **Container Security**: Scan Docker images
- **Network Isolation**: Separate networks per tier
- **Secret Management**: Use environment variables
- **Regular Updates**: Keep dependencies updated

## Monitoring & Observability

### 1. Metrics Collection

- **Agent Performance**: Success rates, capability scores
- **Memory Usage**: Tier utilization, hit rates
- **System Health**: Service status, response times
- **Error Rates**: Failed requests, exceptions

### 2. Logging

- **Structured Logging**: JSON format for parsing
- **Log Levels**: DEBUG, INFO, WARNING, ERROR
- **Centralized Logging**: Aggregate logs from all services
- **Log Retention**: Configurable retention policies

### 3. Alerting

- **Health Checks**: Service availability
- **Performance Thresholds**: Response time alerts
- **Error Rate Alerts**: High failure rates
- **Resource Alerts**: Memory, CPU, disk usage

## Deployment Architecture

### 1. Docker Compose Setup

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ seedcore-api│  │ ray-head    │  │ ray-worker  │         │
│  │ (FastAPI)   │  │             │  │             │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ postgres    │  │ neo4j       │  │ redis       │         │
│  │             │  │             │  │             │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│  ┌─────────────┐                                           │
│  │ mysql       │                                           │
│  │             │                                           │
│  └─────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

### 2. Environment Configuration

- **Environment Variables**: All configuration via .env
- **Service Discovery**: Internal Docker networking
- **Volume Mounts**: Persistent data storage
- **Health Checks**: Automatic service monitoring

## Future Architecture Enhancements

### 1. Microservices Evolution

- **Service Decomposition**: Split into microservices
- **API Gateway**: Centralized routing and authentication
- **Service Mesh**: Istio for service-to-service communication
- **Event-Driven Architecture**: Kafka for event streaming

### 2. Machine Learning Integration

- **Salience Scoring**: ML models for event importance
- **Pattern Recognition**: Anomaly detection
- **Predictive Analytics**: Performance forecasting
- **Auto-scaling**: ML-driven resource allocation

### 3. Advanced Memory Management

- **Adaptive Compression**: Dynamic compression algorithms
- **Intelligent Migration**: ML-driven tier selection
- **Memory Optimization**: Automatic cleanup and defragmentation
- **Cross-Tier Analytics**: Unified memory insights 