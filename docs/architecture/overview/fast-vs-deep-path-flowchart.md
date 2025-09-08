# Fast vs Deep Path Flowchart

## OCPS Two-Tier Coordination System

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Task Arrival                                         │
│                    (External API, Orchestrator, etc.)                         │
└─────────────────────────────┬───────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        OCPS Valve                                              │
│                    (OrganismManager + CUSUM)                                   │
│                                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐            │
│  │   Task Analysis │    │  CUSUM Update   │    │  Load Check     │            │
│  │   - Complexity  │    │  S_t = max(0,   │    │  - Current Load │            │
│  │   - Type        │    │      S_{t-1} +  │    │  - Fast Path %  │            │
│  │   - Priority    │    │      deviation) │    │  - Threshold θ  │            │
│  │   - Sufficiency │    │  - Energy State │    │  - Queue Health │            │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘            │
│                               │                                               │
│                               ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                    Decision Logic                                      │   │
│  │                                                                         │   │
│  │  IF S_t > θ OR fast_path_ratio < 0.9 OR sufficiency_low:              │   │
│  │      → ESCALATE to Deep Path                                           │   │
│  │  ELSE:                                                                  │   │
│  │      → ROUTE to Fast Path                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│      FAST PATH          │    │      DEEP PATH          │
│    (200ms GNN)          │    │     (20s HGNN)          │
│                         │    │                         │
│  ┌─────────────────┐    │    │  ┌─────────────────┐    │
│  │  Context Broker │    │    │  │  Context Broker │    │
│  │  - RRF Fusion   │    │    │  │  - RRF Fusion   │    │
│  │  - MMR Diversity│    │    │  │  - MMR Diversity│    │
│  │  - Token Budget │    │    │  │  - Full Context │    │
│  └─────────────────┘    │    │  └─────────────────┘    │
│           │             │    │           │             │
│           ▼             │    │           ▼             │
│  ┌─────────────────┐    │    │  ┌─────────────────┐    │
│  │  Memory Lookup  │    │    │  │  Enhanced       │    │
│  │  - Mw (5ms)     │    │    │  │  Processing     │    │
│  │  - Cache hit    │    │    │  │  - Post-conds   │    │
│  │  - Quick result │    │    │  │  - Self-consist │    │
│  └─────────────────┘    │    │  └─────────────────┘    │
│           │             │    │           │             │
│           ▼             │    │           ▼             │
│  ┌─────────────────┐    │    │  ┌─────────────────┐    │
│  │  DSPy           │    │    │  │  DSPy           │    │
│  │  Processing     │    │    │  │  Processing     │    │
│  │  - Fast GNN     │    │    │  │  - Deep HGNN    │    │
│  │  - Post-conds   │    │    │  │  - Full valid   │    │
│  │  - Quick return │    │    │  │  - Safety check │    │
│  └─────────────────┘    │    │  └─────────────────┘    │
│           │             │    │           │             │
│           ▼             │    │           ▼             │
│  ┌─────────────────┐    │    │  ┌─────────────────┐    │
│  │  Cache          │    │    │  │  Cache          │    │
│  │  Management     │    │    │  │  Management     │    │
│  │  - TTL update   │    │    │  │  - TTL update   │    │
│  │  - Hit tracking │    │    │  │  - Hit tracking │    │
│  │  - Metadata     │    │    │  │  - Metadata     │    │
│  └─────────────────┘    │    │  └─────────────────┘    │
└─────────────────────────┘    └─────────────────────────┘
           │                                     │
           ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Response Return                                      │
│                    (Success, Latency, Confidence)                             │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Key Decision Points

### 1. OCPS Valve Decision Matrix

| Condition | Action | Rationale |
|-----------|--------|-----------|
| `S_t > θ` (0.8) | Deep Path | CUSUM threshold exceeded |
| `fast_path_ratio < 0.9` | Deep Path | Maintain 90% fast path guarantee |
| `sufficiency.coverage < 0.6` | Deep Path | Low retrieval coverage |
| `sufficiency.diversity < 0.5` | Deep Path | Low fact diversity |
| `sufficiency.conflict_count > 2` | Deep Path | High fact conflicts |
| `sufficiency.staleness_ratio > 0.3` | Deep Path | Too many stale facts |
| `sufficiency.trust_score < 0.4` | Deep Path | Low trust in facts |
| All else | Fast Path | Default to fast processing |

### 2. Performance Targets

| Path | Latency | Success Rate | Throughput | Use Case |
|------|---------|--------------|------------|----------|
| **Fast** | 200ms | 95% | 1000/min | Pattern matching, cache hits |
| **Deep** | 20s | 90% | 10/min | Complex reasoning, high-stakes |

### 3. Memory Access Patterns

| Path | Primary Memory | Fallback | Compression |
|------|----------------|----------|-------------|
| **Fast** | Mw (5ms) | M2.5 (20ms) | LZ4 |
| **Deep** | Mlt (50ms) | Mfb (10ms) | LZ4 + Delta |

### 4. Safety Validation

| Path | Validation | Bound | Optional |
|------|------------|-------|----------|
| **Fast** | Basic | L_tot < 0.5 | None |
| **Deep** | Full | L_tot < 0.9 | zk-SNARK, TEE |

## Monitoring Points

### Fast Path Metrics
- **Latency**: Target <200ms, Alert >300ms
- **Success Rate**: Target >95%, Alert <90%
- **Cache Hit Rate**: Target >95%, Alert <90%
- **Throughput**: Monitor for degradation

### Deep Path Metrics
- **Latency**: Target <20s, Alert >30s
- **Success Rate**: Target >90%, Alert <80%
- **Safety Violations**: Alert on any L_tot ≥ 1.0
- **Energy Cost**: Monitor for efficiency

### OCPS Valve Metrics
- **Fast Path Ratio**: Target ≥90%, Alert <85%
- **CUSUM Statistic**: Monitor trend, Alert >0.8
- **Escalation Rate**: Monitor for patterns
- **Load Balance**: Ensure fair distribution

## Error Handling

### Fast Path Failures
1. **Cache Miss**: Fallback to M2.5
2. **Pattern Match Failure**: Escalate to Deep Path
3. **Timeout**: Return error, log for analysis

### Deep Path Failures
1. **Safety Validation Failure**: Reject task
2. **Memory Access Failure**: Retry with backoff
3. **Timeout**: Return partial result if possible

### OCPS Valve Failures
1. **Decision Timeout**: Default to Fast Path
2. **Load Check Failure**: Conservative escalation
3. **CUSUM Reset**: Reset to safe state

---

*This flowchart provides a complete visual guide to the OCPS two-tier coordination system, showing decision points, performance targets, and error handling for production operations.*
