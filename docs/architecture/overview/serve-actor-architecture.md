# Serve ↔ Actor Architecture Overview

This document provides a comprehensive overview of the SeedCore system architecture, specifically focusing on the mapping between Ray Serve applications and Ray Actors, and how they work together to form a distributed, intelligent organism.

## Table of Contents

- [System Overview](#system-overview)
- [Serve Applications (Logical Apps)](#serve-applications-logical-apps)
- [Serve Deployments → Ray Actors](#serve-deployments--ray-actors)
- [Control Plane Actors](#control-plane-actors)
- [System Relationships](#system-relationships)
- [Architecture Diagram](#architecture-diagram)
- [Health Indicators](#health-indicators)
- [Scaling and Distribution](#scaling-and-distribution)

## System Overview

SeedCore implements a distributed, intelligent organism architecture using Ray Serve for service orchestration and Ray Actors for distributed computation. The system is designed to be scalable, fault-tolerant, and capable of handling complex cognitive workloads.

The architecture follows a **microservices pattern** where each logical service is deployed as a Ray Serve application, which in turn spawns one or more Ray Actors to handle the actual computation and state management.

## Serve Applications (Logical Apps)

From `serve status`, the system runs 4 main applications:

| Application | Purpose | Status |
|-------------|---------|---------|
| **ml_service** | ML inference and model serving | Running |
| **cognitive** | Reasoning, planning, and cognitive tasks | Running |
| **orchestrator** | System-level orchestration and workflow management | Running |
| **organism** | Organism lifecycle and organ coordination | Running |

Each application represents a logical service namespace that can contain multiple deployments and replicas.

## Serve Deployments → Ray Actors

Every deployment spawns one or more **`ServeReplica` actors**, plus global actors for control and proxying:

### 1. ML Service → MLService

- **ServeDeployment**: `MLService`
- **Actor**: `ServeReplica:ml_service:MLService`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 2
- **Purpose**: Dedicated ML inference service for model serving

### 2. Cognitive → CognitiveService

- **ServeDeployment**: `CognitiveService`
- **Actors**: `ServeReplica:cognitive:CognitiveService`
- **Replicas**: `2 RUNNING`
- **Ray Actor IDs**: Actor 1 and Actor 4
- **Purpose**: Parallel workers for reasoning and planning tasks
- **Distribution**: Replicas are distributed across different Ray nodes for redundancy

### 3. Orchestrator → OpsOrchestrator

- **ServeDeployment**: `OpsOrchestrator`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 5
- **Purpose**: System-level orchestration and external workflow management

### 4. Organism → OrganismManager

- **ServeDeployment**: `OrganismManager`
- **Replicas**: `1 RUNNING`
- **Ray Actor ID**: Actor 8
- **Purpose**: Organism lifecycle management and organ coordination

## Control Plane Actors

Besides service replicas, Serve maintains several control plane actors:

| Actor | Purpose | Status |
|-------|---------|---------|
| **ServeController (Actor 3)** | Central brain of Serve, manages deployments and replicas | Running |
| **ProxyActors (Actor 6 & 7)** | Handle HTTP/GRPC ingress, route to correct deployment | Running |
| **StatusActor (Actor 0)** | Ray Dashboard integration, tracks job/actor status | Running |

## System Relationships

### 1. Serve → Actors Mapping

- Each Serve deployment represents **one logical service**
- It owns **N `ServeReplica` actors** (workers), distributed across Ray nodes
- Scale is reflected in `replica_states.RUNNING`
- Replicas can be scaled independently based on workload requirements

### 2. Actors → Nodes Distribution

- Replicas are distributed between nodes for fault tolerance
- Example: CognitiveService has 2 replicas on different nodes:
  - Actor 1 on node `f7d...`
  - Actor 4 on node `34d...`
- This provides redundancy and parallelism

### 3. Core Service Interactions

#### OrganismManager & CognitiveService
- **OrganismManager** (Actor 8) coordinates organism initialization
- Routes tasks to **organs** (Cognitive, Actuator, Utility)
- **CognitiveService** (Actors 1 & 4) serves as the "Cognitive organ" backing OrganismManager

#### Orchestrator Integration
- Acts as an external workflow/controller service
- Communicates with **OrganismManager** and **CognitiveService**
- Provides system-level orchestration capabilities

#### MLService Integration
- Independent ML-focused endpoint
- Can be called by CognitiveService or Orchestrator for inference workloads
- Supports various ML model types and inference patterns

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Ray Cluster                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐        │
│  │   Serve Proxy   │    │   Serve Proxy   │    │ ServeController │        │
│  │   (Actor 6)     │    │   (Actor 7)     │    │   (Actor 3)     │        │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘        │
│           │                       │                       │                │
│           └───────────────────────┼───────────────────────┘                │
│                                   │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Serve Applications                               │   │
│  │                                                                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│  │  │ ml_service  │  │ cognitive   │  │orchestrator │  │  organism   │ │   │
│  │  │             │  │             │  │             │  │             │ │   │
│  │  │ MLService   │  │CognitiveSvc │  │OpsOrchestr │  │OrganismMgr  │ │   │
│  │  │ (Actor 2)   │  │(Actor 1,4) │  │ (Actor 5)  │  │ (Actor 8)   │ │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Ray Actors                                        │   │
│  │                                                                     │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │   │
│  │  │Actor 0  │ │Actor 1  │ │Actor 2  │ │Actor 3  │ │Actor 4  │     │   │
│  │  │Status   │ │Cognitive│ │MLService│ │ServeCtrl│ │Cognitive│     │   │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │   │
│  │                                                                     │   │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐                               │   │
│  │  │Actor 5  │ │Actor 6  │ │Actor 7  │                               │   │
│  │  │Orchestr │ │Proxy    │ │Proxy    │                               │   │
│  │  └─────────┘ └─────────┘ └─────────┘                               │   │
│  │                                                                     │   │
│  │  ┌─────────┐                                                       │   │
│  │  │Actor 8  │                                                       │   │
│  │  │Organism │                                                       │   │
│  │  │Manager  │                                                       │   │
│  │  └─────────┘                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Health Indicators

The current system shows **healthy** status across all components:

✅ **All deployments are RUNNING**
✅ **Cognitive has 2 replicas** for distributed reasoning
✅ **OrganismManager is alive** and ready to manage organs
✅ **No DEAD actors** left hanging
✅ **Proper replica distribution** across nodes

## Scaling and Distribution

### Horizontal Scaling
- **CognitiveService**: Currently 2 replicas, can scale based on reasoning workload
- **Other services**: Single replica, can be scaled as needed
- **Load balancing**: Automatic across replicas via Serve proxy

### Fault Tolerance
- **Multi-node distribution**: Replicas spread across different Ray nodes
- **Automatic failover**: Serve handles replica failures and restarts
- **State management**: Actor state preserved across failures

### Performance Characteristics
- **Parallel processing**: Multiple CognitiveService replicas handle concurrent reasoning tasks
- **Low latency**: Direct actor-to-actor communication within Ray cluster
- **High throughput**: Distributed processing across multiple nodes

## Monitoring and Observability

### Key Metrics to Monitor
- **Replica health**: All replicas should be in RUNNING state
- **Actor distribution**: Ensure replicas are distributed across nodes
- **Response times**: Monitor service latency and throughput
- **Resource utilization**: CPU, memory, and GPU usage across nodes

### Troubleshooting
- **Actor failures**: Check Ray logs for actor crash details
- **Service unavailability**: Verify Serve proxy routing and deployment status
- **Performance issues**: Monitor replica distribution and resource allocation

## Future Considerations

### Potential Enhancements
- **Auto-scaling**: Implement dynamic replica scaling based on load
- **Multi-region**: Extend to multiple Ray clusters for geographic distribution
- **Advanced routing**: Implement intelligent request routing based on actor load
- **State persistence**: Add persistent state storage for critical actor state

### Integration Points
- **External APIs**: REST/GRPC endpoints for external system integration
- **Event streaming**: Integration with message queues for asynchronous processing
- **Monitoring**: Integration with observability platforms (Prometheus, Grafana)
- **Security**: Authentication and authorization for service-to-service communication

---

*This document provides a comprehensive overview of the SeedCore architecture. For detailed implementation specifics, refer to the individual component documentation in the `docs/architecture/components/` directory.*
