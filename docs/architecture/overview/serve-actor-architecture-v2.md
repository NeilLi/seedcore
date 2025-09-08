# Serve ↔ Actor Architecture v2: OCPS-Enabled Distributed Intelligence

This document provides the enhanced v2 architecture for the SeedCore system, implementing OCPS (Organism Control and Performance System) with fast-path guarantees, unified state-energy bus, hardened memory fabric, and safety overlays for production-grade distributed intelligence.

## Table of Contents

- [System Overview](#system-overview)
- [OCPS Fast-Path Architecture](#ocps-fast-path-architecture)
- [Serve Applications v2](#serve-applications-v2)
- [Unified State + Energy Bus](#unified-state--energy-bus)
- [Memory Fabric Hardening](#memory-fabric-hardening)
- [Placement & Scaling Strategy](#placement--scaling-strategy)
- [Safety Overlays](#safety-overlays)
- [API Contracts & SLOs](#api-contracts--slos)
- [Architecture Diagram v2](#architecture-diagram-v2)
- [Operational Runbook](#operational-runbook)

## System Overview

SeedCore v2 implements a **two-tier coordination system** with OCPS (Organism Control and Performance System) that guarantees ≥90% of requests stay on the fast path (200ms GNN) while escalating only critical tasks to deep reasoning (20s HGNN). The architecture maintains global Lipschitz bound L_tot < 1 through safety overlays and provides production-grade observability.

### Key v2 Enhancements

- **OCPS Valve**: Intelligent routing with CUSUM-based escalation thresholds
- **Unified State-Energy Bus**: Centralized state management with energy gradient decomposition
- **Memory Fabric Hardening**: Tier 2.5 compression with ≤3s freshness guarantees
- **Ray Placement Groups**: PACK for low-latency, SPREAD for compute-intensive workloads
- **Safety Overlays**: GraphMask + optional zk-SNARK + TEE capsules
- **Production SLOs**: Concrete performance guarantees and operational budgets

## OCPS Fast-Path Architecture

### Two-Tier Coordination System

| Tier | Processing | Latency | Use Case | Threshold |
|------|------------|---------|----------|-----------|
| **Fast Path** | Local GNN | 200ms | Routine tasks, pattern matching | Default |
| **Deep Path** | HGNN | 20s | Complex reasoning, high-stakes | CUSUM S_t > θ |

### OCPS Valve Implementation

The OrganismManager implements an OCPS valve that maintains fast-path guarantees:

```python
class OCPSValve:
    def __init__(self, threshold_theta: float = 0.8):
        self.threshold = threshold_theta
        self.cusum_statistic = 0.0
        self.fast_path_ratio = 0.0
        self.escalation_count = 0
    
    def should_escalate(self, task_complexity: float, 
                       current_load: float) -> bool:
        # CUSUM statistic update
        deviation = (task_complexity - 0.5) * current_load
        self.cusum_statistic = max(0, self.cusum_statistic + deviation)
        
        # Escalation decision
        if self.cusum_statistic > self.threshold:
            self.escalation_count += 1
            return True
        
        # Maintain fast-path ratio ≥90%
        if self.fast_path_ratio < 0.9:
            return False
            
        return self.cusum_statistic > (self.threshold * 0.7)
    
    def update_fast_path_ratio(self, fast_path_count: int, total_count: int):
        self.fast_path_ratio = fast_path_count / max(total_count, 1)
```

### Fast vs Deep Path Flow

```
Task Arrival
     ↓
OCPS Valve (OrganismManager)
     ├─ Fast Path (200ms GNN) ← 90%+ requests
     │   ├─ Local pattern matching
     │   ├─ Cache lookup (Mw)
     │   └─ Quick response
     │
     └─ Deep Path (20s HGNN) ← CUSUM S_t > θ
         ├─ Complex reasoning
         ├─ Memory synthesis (Mlt + Mfb)
         ├─ Safety validation
         └─ Escalated response
```

## Serve Applications v2

### Enhanced Application Architecture

| Application | Purpose | Replicas | Placement | SLO |
|-------------|---------|----------|-----------|-----|
| **organism** | OCPS valve + meta-scheduler | 1 | PACK | 200ms fast path |
| **cognitive** | Enhanced reasoning with RRF/MMR | 2+ | PACK/SPREAD | 200ms/20s |
| **ml_service** | Model inference | 1+ | PACK | 100ms inference |
| **state** | Unified state bus | 1 | SPREAD | 50ms aggregation |
| **energy** | Energy gradient API | 1 | SPREAD | 100ms gradient |
| **orchestrator** | External workflows | 1 | PACK | 500ms orchestration |

### Enhanced Cognitive Core v2

The cognitive service now implements advanced retrieval and reasoning capabilities:

```python
class CognitiveCoreV2(dspy.Module):
    """Enhanced cognitive core with OCPS integration and advanced retrieval."""
    
    def __init__(self, llm_provider: str, model: str, ocps_client=None, energy_client=None):
        # Enhanced fact schema with provenance and trust
        self.fact_schema = FactSchema()
        
        # RRF fusion + MMR diversity for better retrieval
        self.context_broker = ContextBroker(
            text_search_func=seedcore_text_search,
            vector_search_func=seedcore_vector_search,
            ocps_client=ocps_client,
            energy_client=energy_client
        )
        
        # Dynamic token budgeting based on system state
        self.base_token_budget = 2000
        self.token_budget = self.base_token_budget
        
        # Hardened cache governance with TTL per task type
        self.cache_ttl_by_task = {
            CognitiveTaskType.FAILURE_ANALYSIS: 300,  # 5 minutes
            CognitiveTaskType.TASK_PLANNING: 1800,    # 30 minutes
            CognitiveTaskType.DECISION_MAKING: 600,   # 10 minutes
            CognitiveTaskType.PROBLEM_SOLVING: 1200,  # 20 minutes
            CognitiveTaskType.MEMORY_SYNTHESIS: 3600, # 1 hour
            CognitiveTaskType.CAPABILITY_ASSESSMENT: 1800, # 30 minutes
        }
    
    def process(self, context: CognitiveContext) -> TaskResult:
        """Enhanced processing with OCPS integration and retrieval sufficiency."""
        # 1. Cache lookup with hardened keys
        cache_key = self._generate_cache_key(context.task_type, context.agent_id, context.input_data)
        cached_result = self._get_cached_result(cache_key, context.task_type)
        if cached_result:
            return cached_result
        
        # 2. Enhanced fact retrieval with RRF + MMR
        query = self._build_query(context)
        facts, summary, sufficiency = self.context_broker.retrieve(query, k=20)
        
        # 3. OCPS escalation decision
        if self._should_escalate_to_deep_path(sufficiency, context.task_type):
            return self._process_deep_path(context, facts, summary, sufficiency)
        else:
            return self._process_fast_path(context, facts, summary, sufficiency)
```

### OCPS-Enhanced OrganismManager

```python
@serve.deployment(
    num_replicas=1,
    ray_actor_options={
        "placement_group": "ocps_pack_group",
        "num_cpus": 1.0,
        "memory": 2 * 1024**3  # 2GB
    }
)
class OrganismManagerV2:
    def __init__(self):
        self.ocps_valve = OCPSValve(threshold_theta=0.8)
        self.state_bus = StateBusClient()
        self.energy_bus = EnergyBusClient()
        self.safety_overlay = SafetyOverlay()
    
    async def route_task(self, task: Task) -> TaskResult:
        # OCPS valve decision
        if self.ocps_valve.should_escalate(task.complexity, self.current_load):
            return await self._deep_path_processing(task)
        else:
            return await self._fast_path_processing(task)
    
    async def _fast_path_processing(self, task: Task) -> TaskResult:
        # 200ms GNN processing
        start_time = time.time()
        
        # Local pattern matching
        pattern_result = await self.cognitive_service.fast_pattern_match(task)
        
        # Cache lookup
        cache_result = await self.state_bus.get_cached_result(task.id)
        
        if cache_result and pattern_result.confidence > 0.8:
            return TaskResult(
                success=True,
                latency=time.time() - start_time,
                path="fast",
                confidence=pattern_result.confidence
            )
        
        # Fallback to cognitive service
        return await self.cognitive_service.process_fast(task)
    
    async def _deep_path_processing(self, task: Task) -> TaskResult:
        # 20s HGNN processing with safety validation
        start_time = time.time()
        
        # Safety overlay validation
        if not await self.safety_overlay.validate_task(task):
            raise SafetyViolationError("Task failed safety validation")
        
        # Deep reasoning
        result = await self.cognitive_service.process_deep(task)
        
        # Energy gradient update
        await self.energy_bus.update_gradient(task.id, result.energy_cost)
        
        return TaskResult(
            success=True,
            latency=time.time() - start_time,
            path="deep",
            confidence=result.confidence,
            energy_cost=result.energy_cost
        )
```

## Unified State + Energy Bus

### StateService as Source of Truth

The StateService remains the authoritative source for UnifiedState, providing:

```python
class UnifiedState:
    agents: Dict[str, AgentSnapshot]
    organs: Dict[str, OrganState] 
    system: SystemState
    memory: MemoryState
    
    def get_agent_state(self, agent_id: str) -> AgentSnapshot:
        return self.agents.get(agent_id)
    
    def get_organ_state(self, organ_id: str) -> OrganState:
        return self.organs.get(organ_id)
    
    def get_system_metrics(self) -> SystemMetrics:
        return self.system.metrics
```

### Energy Gradient API

The EnergyService exposes energy decomposition for routing and promotion gates:

```python
@serve.deployment(
    num_replicas=1,
    ray_actor_options={
        "placement_group": "energy_spread_group",
        "num_cpus": 0.5,
        "memory": 1 * 1024**3  # 1GB
    }
)
class EnergyServiceV2:
    def __init__(self):
        self.energy_state = EnergyState()
        self.gradient_cache = {}
    
    @app.get("/energy/gradient")
    async def get_energy_gradient(self, state_vector: List[float]) -> EnergyGradient:
        """Decompose E(s_t) into terms for routing and promotion gates"""
        
        # Calculate energy components
        kinetic_energy = self._calculate_kinetic(state_vector)
        potential_energy = self._calculate_potential(state_vector)
        thermal_energy = self._calculate_thermal(state_vector)
        
        # Gradient components
        gradient = EnergyGradient(
            kinetic_grad=self._gradient_kinetic(kinetic_energy),
            potential_grad=self._gradient_potential(potential_energy),
            thermal_grad=self._gradient_thermal(thermal_energy),
            total_energy=kinetic_energy + potential_energy + thermal_energy,
            timestamp=time.time()
        )
        
        return gradient
    
    def _calculate_kinetic(self, state_vector: List[float]) -> float:
        """Kinetic energy from agent velocity/capability changes"""
        return sum(v**2 for v in state_vector) * 0.5
    
    def _calculate_potential(self, state_vector: List[float]) -> float:
        """Potential energy from system configuration"""
        return sum(abs(v) for v in state_vector) * 0.3
    
    def _calculate_thermal(self, state_vector: List[float]) -> float:
        """Thermal energy from system entropy"""
        entropy = -sum(p * math.log(p) if p > 0 else 0 for p in state_vector)
        return entropy * 0.2
```

## Memory Fabric Hardening

### Enhanced Memory Tiers

| Tier | Name | Latency | Capacity | Compression | Hit Rate Target |
|------|------|---------|----------|-------------|-----------------|
| **Ma** | Agent Private | 1ms | 128-D vector | None | N/A |
| **Mw** | Working Memory | 5ms | 1GB | LZ4 | >95% |
| **Mlt** | Long-Term | 50ms | 100GB | LZ4 + Quantization | >80% |
| **Mfb** | Flashbulb | 10ms | 1GB | None | >99% |
| **M2.5** | Tier 2.5 | 20ms | 10GB | LZ4 + Delta | >90% |

### Tier 2.5 Compression Layer

```python
class Tier25Memory:
    """Compression layer between Mw and Mlt for ≤3s freshness"""
    
    def __init__(self, max_freshness_s: float = 3.0):
        self.max_freshness = max_freshness_s
        self.compression_engine = LZ4Compressor()
        self.delta_engine = DeltaCompressor()
        self.freshness_tracker = {}
    
    async def store(self, key: str, data: Any, priority: int = 1) -> bool:
        """Store with compression and freshness tracking"""
        
        # Compress data
        compressed = self.compression_engine.compress(data)
        
        # Delta compression if previous version exists
        if key in self.freshness_tracker:
            delta = self.delta_engine.compute_delta(
                self.freshness_tracker[key], compressed
            )
            compressed = delta
        
        # Store with timestamp
        success = await self._store_compressed(key, compressed, priority)
        
        if success:
            self.freshness_tracker[key] = {
                'timestamp': time.time(),
                'size': len(compressed),
                'priority': priority
            }
        
        return success
    
    async def retrieve(self, key: str) -> Optional[Any]:
        """Retrieve with freshness validation"""
        
        if key not in self.freshness_tracker:
            return None
        
        # Check freshness
        age = time.time() - self.freshness_tracker[key]['timestamp']
        if age > self.max_freshness:
            return None  # Stale data
        
        # Retrieve and decompress
        compressed = await self._retrieve_compressed(key)
        if compressed is None:
            return None
        
        # Decompress
        data = self.compression_engine.decompress(compressed)
        
        # Apply delta if needed
        if self.freshness_tracker[key].get('is_delta', False):
            data = self.delta_engine.apply_delta(data, compressed)
        
        return data
```

### Memory Performance Targets

```python
class MemorySLOs:
    """Memory fabric performance targets"""
    
    TARGETS = {
        'mw_hit_rate': 0.95,      # 95% cache hit rate
        'mlt_hit_rate': 0.80,      # 80% long-term hit rate
        'mfb_hit_rate': 0.99,      # 99% flashbulb hit rate
        'tier25_hit_rate': 0.90,   # 90% compression hit rate
        'max_freshness_s': 3.0,    # 3s maximum staleness
        'compression_ratio': 0.3,  # 70% compression ratio
        'aggregation_latency_ms': 50,  # 50ms state aggregation
    }
    
    def validate_performance(self, metrics: MemoryMetrics) -> List[str]:
        """Validate memory performance against SLOs"""
        violations = []
        
        if metrics.mw_hit_rate < self.TARGETS['mw_hit_rate']:
            violations.append(f"Mw hit rate {metrics.mw_hit_rate:.2%} < {self.TARGETS['mw_hit_rate']:.2%}")
        
        if metrics.freshness_s > self.TARGETS['max_freshness_s']:
            violations.append(f"Freshness {metrics.freshness_s:.1f}s > {self.TARGETS['max_freshness_s']:.1f}s")
        
        return violations
```

## Placement & Scaling Strategy

### Ray Placement Groups

```yaml
# serve-config-v2.yaml
placement_groups:
  - name: "ocps_pack_group"
    strategy: "PACK"
    bundles:
      - resources: {"CPU": 1.0, "memory": 2 * 1024**3}
        replicas: 1  # OrganismManager
  
  - name: "cognitive_pack_group" 
    strategy: "PACK"
    bundles:
      - resources: {"CPU": 0.5, "memory": 1 * 1024**3}
        replicas: 2  # Fast GNN replicas
  
  - name: "cognitive_spread_group"
    strategy: "SPREAD" 
    bundles:
      - resources: {"CPU": 2.0, "memory": 4 * 1024**3}
        replicas: 1  # Deep HGNN replica
  
  - name: "state_energy_spread_group"
    strategy: "SPREAD"
    bundles:
      - resources: {"CPU": 0.5, "memory": 1 * 1024**3}
        replicas: 2  # State + Energy services
```

### OCPS-Driven Autoscaling

```python
class OCPSAutoscaler:
    """Autoscaler driven by OCPS demand vectors"""
    
    def __init__(self):
        self.demand_history = deque(maxlen=100)
        self.scaling_policies = {
            'cognitive': {'min_replicas': 2, 'max_replicas': 10},
            'ml_service': {'min_replicas': 1, 'max_replicas': 5},
            'state': {'min_replicas': 1, 'max_replicas': 3},
        }
    
    async def update_demand_vector(self, demand: DemandVector):
        """Update demand vector from OCPS valve"""
        self.demand_history.append(demand)
        
        # Calculate scaling decisions
        for service, policy in self.scaling_policies.items():
            current_demand = demand.get_service_demand(service)
            target_replicas = self._calculate_target_replicas(
                service, current_demand, policy
            )
            
            if target_replicas != demand.current_replicas[service]:
                await self._scale_service(service, target_replicas)
    
    def _calculate_target_replicas(self, service: str, demand: float, 
                                 policy: Dict) -> int:
        """Calculate target replicas based on demand"""
        
        # Base calculation: demand / capacity_per_replica
        base_replicas = max(1, int(demand / 0.8))  # 80% utilization target
        
        # Apply min/max constraints
        target = max(policy['min_replicas'], 
                    min(policy['max_replicas'], base_replicas))
        
        return target
```

## Safety Overlays

### GraphMask Integration

```python
class GraphMask:
    """GraphMask for maintaining Lipschitz bound L_tot < 1"""
    
    def __init__(self, max_lipschitz: float = 0.9):
        self.max_lipschitz = max_lipschitz
        self.edge_weights = {}
        self.node_capacities = {}
    
    def validate_lipschitz_bound(self, graph: Graph) -> bool:
        """Validate global Lipschitz bound"""
        total_lipschitz = 0.0
        
        for edge in graph.edges:
            weight = self.edge_weights.get(edge.id, 1.0)
            total_lipschitz += weight
        
        return total_lipschitz < self.max_lipschitz
    
    def apply_mask(self, graph: Graph, task: Task) -> Graph:
        """Apply GraphMask to maintain safety bounds"""
        masked_graph = graph.copy()
        
        # Remove edges that would violate Lipschitz bound
        for edge in list(masked_graph.edges):
            if not self._is_edge_safe(edge, task):
                masked_graph.remove_edge(edge)
        
        return masked_graph
```

### Optional Proof-Carrying Actions (zk-SNARK)

```python
class ProofCarryingActions:
    """Optional zk-SNARK proofs for high-risk operations"""
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.proving_key = None
        self.verification_key = None
        
        if enabled:
            self._setup_zk_snark()
    
    async def generate_proof(self, action: Action, 
                           witness: Witness) -> Optional[Proof]:
        """Generate zk-SNARK proof for action"""
        if not self.enabled:
            return None
        
        # Generate proof that action is safe
        proof = await self._prove_action_safety(action, witness)
        return proof
    
    async def verify_proof(self, action: Action, 
                          proof: Proof) -> bool:
        """Verify zk-SNARK proof"""
        if not self.enabled or proof is None:
            return True  # Skip verification if disabled
        
        return await self._verify_proof(action, proof)
```

### TEE Capsules for High-Risk Operations

```python
class TEECapsule:
    """Trusted Execution Environment for escalated operations"""
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.tee_attestation = None
        
        if enabled:
            self._initialize_tee()
    
    async def execute_in_tee(self, operation: Operation) -> OperationResult:
        """Execute operation in TEE for maximum security"""
        if not self.enabled:
            return await self._execute_normal(operation)
        
        # Attest TEE environment
        attestation = await self._attest_tee()
        
        # Execute in secure enclave
        result = await self._execute_secure(operation, attestation)
        
        return result
```

## API Contracts & SLOs

### Core API Endpoints

| Endpoint | Method | Purpose | SLO | Rate Limit |
|----------|--------|---------|-----|------------|
| `/ocps/status` | GET | OCPS valve status | 50ms | 1000/min |
| `/ocps/route` | POST | Task routing decision | 200ms | 500/min |
| `/energy/gradient` | GET | Energy decomposition | 100ms | 2000/min |
| `/state/unified` | GET | Unified state snapshot | 50ms | 1000/min |
| `/memory/tier25/store` | POST | Tier 2.5 storage | 20ms | 5000/min |
| `/memory/tier25/retrieve` | GET | Tier 2.5 retrieval | 20ms | 10000/min |
| `/safety/validate` | POST | Safety validation | 100ms | 1000/min |

### SLO Definitions

```python
class SLODefinitions:
    """Service Level Objectives for v2 architecture"""
    
    # OCPS Fast Path
    FAST_PATH_LATENCY = 200  # ms
    FAST_PATH_SUCCESS_RATE = 0.95  # 95%
    FAST_PATH_THROUGHPUT = 1000  # requests/min
    
    # OCPS Deep Path  
    DEEP_PATH_LATENCY = 20000  # ms (20s)
    DEEP_PATH_SUCCESS_RATE = 0.90  # 90%
    DEEP_PATH_THROUGHPUT = 10  # requests/min
    
    # Memory Fabric
    MEMORY_FRESHNESS = 3.0  # seconds
    MEMORY_HIT_RATE_MW = 0.95  # 95%
    MEMORY_HIT_RATE_MLT = 0.80  # 80%
    MEMORY_AGGREGATION_LATENCY = 50  # ms
    
    # Energy Bus
    ENERGY_GRADIENT_LATENCY = 100  # ms
    ENERGY_GRADIENT_ACCURACY = 0.99  # 99%
    
    # Safety Overlays
    SAFETY_VALIDATION_LATENCY = 100  # ms
    LIPSCHITZ_BOUND = 0.9  # L_tot < 1
    SAFETY_SUCCESS_RATE = 0.999  # 99.9%
```

### Operational Budgets

```python
class OperationalBudgets:
    """Resource budgets for production operations"""
    
    # CPU Budgets (cores)
    OCPS_CPU_BUDGET = 1.0
    COGNITIVE_CPU_BUDGET = 4.0  # 2 fast + 1 deep + 1 buffer
    STATE_CPU_BUDGET = 1.0
    ENERGY_CPU_BUDGET = 0.5
    ML_SERVICE_CPU_BUDGET = 2.0
    
    # Memory Budgets (GB)
    OCPS_MEMORY_BUDGET = 2.0
    COGNITIVE_MEMORY_BUDGET = 8.0  # 2GB fast + 4GB deep + 2GB buffer
    STATE_MEMORY_BUDGET = 2.0
    ENERGY_MEMORY_BUDGET = 1.0
    ML_SERVICE_MEMORY_BUDGET = 4.0
    
    # Network Budgets (Mbps)
    INTER_SERVICE_BANDWIDTH = 1000  # 1 Gbps
    EXTERNAL_API_BANDWIDTH = 100    # 100 Mbps
    
    # Storage Budgets (GB)
    MEMORY_FABRIC_STORAGE = 120     # 100GB Mlt + 10GB M2.5 + 10GB buffer
    LOG_STORAGE = 50               # 50GB for logs and metrics
```

## Architecture Diagram v2

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SeedCore v2: OCPS-Enabled Architecture                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                            OCPS Valve                                  │   │
│  │                    (OrganismManager + CUSUM)                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │  │Fast Path    │  │Deep Path    │  │Safety       │  │Energy       │   │   │
│  │  │200ms GNN    │  │20s HGNN     │  │Overlay      │  │Gradient     │   │   │
│  │  │≥90% traffic │  │CUSUM S_t>θ  │  │L_tot<1      │  │API          │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Ray Placement Groups                                 │   │
│  │                                                                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │  │PACK Group   │  │PACK Group   │  │SPREAD Group │  │SPREAD Group │   │   │
│  │  │(Low Latency)│  │(Cognitive)  │  │(HGNN/State) │  │(Energy)     │   │   │
│  │  │             │  │             │  │             │  │             │   │   │
│  │  │OrganismMgr  │  │Fast GNN     │  │Deep HGNN    │  │StateService │   │   │
│  │  │MLService    │  │CognitiveSvc │  │StateService │  │EnergyService│   │   │
│  │  │Orchestrator │  │             │  │             │  │             │   │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Hardened Memory Fabric                              │   │
│  │                                                                         │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐     │   │
│  │  │   Ma    │  │   Mw    │  │  M2.5   │  │   Mlt   │  │   Mfb   │     │   │
│  │  │Private  │  │Working  │  │Compress │  │Long-Term│  │Flashbulb│     │   │
│  │  │128-D    │  │Cache    │  │Tier     │  │Storage  │  │Events   │     │   │
│  │  │1ms      │  │5ms      │  │20ms     │  │50ms     │  │10ms     │     │   │
│  │  │>95% hit │  │>95% hit │  │>90% hit │  │>80% hit │  │>99% hit │     │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Safety Overlays                                     │   │
│  │                                                                         │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                    │   │
│  │  │GraphMask    │  │zk-SNARK     │  │TEE Capsules │                    │   │
│  │  │L_tot < 1    │  │Proofs       │  │High-Risk    │                    │   │
│  │  │Lipschitz    │  │(Optional)   │  │Operations   │                    │   │
│  │  │Bound        │  │             │  │(Optional)   │                    │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                    │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Operational Runbook

### Health Monitoring

#### Key Metrics Dashboard

```python
class HealthDashboard:
    """Real-time health monitoring for v2 architecture"""
    
    def get_ocps_metrics(self) -> Dict[str, Any]:
        return {
            "fast_path_ratio": self.ocps_valve.fast_path_ratio,
            "escalation_count": self.ocps_valve.escalation_count,
            "cusum_statistic": self.ocps_valve.cusum_statistic,
            "current_load": self.current_load,
            "slo_compliance": self._check_slo_compliance()
        }
    
    def get_memory_metrics(self) -> Dict[str, Any]:
        return {
            "mw_hit_rate": self.memory_fabric.mw_hit_rate,
            "mlt_hit_rate": self.memory_fabric.mlt_hit_rate,
            "tier25_hit_rate": self.memory_fabric.tier25_hit_rate,
            "freshness_s": self.memory_fabric.avg_freshness,
            "compression_ratio": self.memory_fabric.compression_ratio
        }
    
    def get_energy_metrics(self) -> Dict[str, Any]:
        return {
            "total_energy": self.energy_bus.total_energy,
            "gradient_latency_ms": self.energy_bus.avg_gradient_latency,
            "energy_efficiency": self.energy_bus.efficiency_score,
            "balance_variance": self.energy_bus.balance_variance
        }
```

### Alerting Rules

```yaml
# alerting-rules-v2.yaml
groups:
  - name: seedcore-v2
    rules:
      # OCPS Alerts
      - alert: FastPathRatioLow
        expr: fast_path_ratio < 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Fast path ratio below 90%"
          
      - alert: CUSUMThresholdExceeded
        expr: cusum_statistic > 0.8
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "CUSUM threshold exceeded, deep path escalation"
      
      # Memory Alerts
      - alert: MemoryHitRateLow
        expr: mw_hit_rate < 0.95 or mlt_hit_rate < 0.80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory hit rate below target"
          
      - alert: MemoryFreshnessStale
        expr: avg_freshness_s > 3.0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Memory freshness exceeds 3s threshold"
      
      # Safety Alerts
      - alert: LipschitzBoundViolation
        expr: lipschitz_bound >= 1.0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Lipschitz bound violation detected"
```

### Deployment Checklist

#### Pre-Deployment

- [ ] Validate OCPS valve configuration
- [ ] Verify placement group assignments
- [ ] Test memory fabric performance
- [ ] Validate safety overlay settings
- [ ] Confirm SLO targets are achievable

#### Post-Deployment

- [ ] Monitor fast-path ratio ≥90%
- [ ] Verify memory hit rates meet targets
- [ ] Check energy gradient API responsiveness
- [ ] Validate safety bounds are maintained
- [ ] Confirm autoscaling is working

#### Rollback Criteria

- Fast-path ratio <85% for >10 minutes
- Memory freshness >5s for >5 minutes
- Lipschitz bound ≥1.0 for any duration
- Energy gradient API latency >500ms
- Safety validation failures >1%

---

*This v2 architecture document provides a production-ready blueprint for OCPS-enabled distributed intelligence with concrete SLOs, API contracts, and operational procedures. The design maintains compatibility with your current Serve application layout while adding the sophisticated control and safety mechanisms required for production deployment.*
