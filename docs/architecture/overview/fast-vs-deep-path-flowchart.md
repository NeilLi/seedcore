# Fast vs Planner Path Flowchart

**Note**: This document describes routing decisions. The routing decision is "planner" (not "deep"). The "deep" term refers to LLM profile metadata for model selection (e.g., GPT-4o vs mini), while "planner" is the routing decision.

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
│  │      → ESCALATE to Planner Path (may use deep LLM profile)            │   │
│  │  ELSE:                                                                  │   │
│  │      → ROUTE to Fast Path                                               │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│      FAST PATH          │    │    PLANNER PATH         │
│    (200ms GNN)          │    │   (20s HGNN, deep LLM)  │
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
│  │  - Fast GNN     │    │    │  │  - Planner HGNN │    │
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
| `S_t > θ` (0.8) | Planner Path | CUSUM threshold exceeded (uses deep LLM profile) |
| `fast_path_ratio < 0.9` | Planner Path | Maintain 90% fast path guarantee (uses deep LLM profile) |
| `sufficiency.coverage < 0.6` | Planner Path | Low retrieval coverage (uses deep LLM profile) |
| `sufficiency.diversity < 0.5` | Planner Path | Low fact diversity (uses deep LLM profile) |
| `sufficiency.conflict_count > 2` | Planner Path | High fact conflicts (uses deep LLM profile) |
| `sufficiency.staleness_ratio > 0.3` | Planner Path | Too many stale facts (uses deep LLM profile) |
| `sufficiency.trust_score < 0.4` | Planner Path | Low trust in facts (uses deep LLM profile) |
| All else | Fast Path | Default to fast processing |

### 2. Performance Targets

| Path | Latency | Success Rate | Throughput | Use Case |
|------|---------|--------------|------------|----------|
| **Fast** | 200ms | 95% | 1000/min | Pattern matching, cache hits |
| **Planner** | 20s | 90% | 10/min | Complex reasoning, high-stakes (uses deep LLM profile) |

### 3. Memory Access Patterns

| Path | Primary Memory | Fallback | Compression |
|------|----------------|----------|-------------|
| **Fast** | Mw (5ms) | M2.5 (20ms) | LZ4 |
| **Planner** | Mlt (50ms) | Mfb (10ms) | LZ4 + Delta |

### 4. Safety Validation

| Path | Validation | Bound | Optional |
|------|------------|-------|----------|
| **Fast** | Basic | L_tot < 0.5 | None |
| **Planner** | Full | L_tot < 0.9 | zk-SNARK, TEE |

## Monitoring Points

### Fast Path Metrics
- **Latency**: Target <200ms, Alert >300ms
- **Success Rate**: Target >95%, Alert <90%
- **Cache Hit Rate**: Target >95%, Alert <90%
- **Throughput**: Monitor for degradation

### Planner Path Metrics
- **Latency**: Target <20s, Alert >30s
- **Success Rate**: Target >90%, Alert <80%
- **Safety Violations**: Alert on any L_tot ≥ 1.0
- **Energy Cost**: Monitor for efficiency
- **LLM Profile**: Tracks "deep" profile usage (model selection metadata)

### OCPS Valve Metrics
- **Fast Path Ratio**: Target ≥90%, Alert <85%
- **CUSUM Statistic**: Monitor trend, Alert >0.8
- **Escalation Rate**: Monitor for patterns
- **Load Balance**: Ensure fair distribution

## Error Handling

### Fast Path Failures
1. **Cache Miss**: Fallback to M2.5
2. **Pattern Match Failure**: Escalate to Planner Path (with deep LLM profile)
3. **Timeout**: Return error, log for analysis

### Planner Path Failures
1. **Safety Validation Failure**: Reject task
2. **Memory Access Failure**: Retry with backoff
3. **Timeout**: Return partial result if possible

### OCPS Valve Failures
1. **Decision Timeout**: Default to Fast Path
2. **Load Check Failure**: Conservative escalation
3. **CUSUM Reset**: Reset to safe state

---

*This flowchart provides a complete visual guide to the OCPS two-tier coordination system, showing decision points, performance targets, and error handling for production operations.*

**Routing Semantics Clarification:**
- **Routing Decision**: Uses "planner" (not "deep") for all escalation paths
- **LLM Profile**: Uses "deep" internally as metadata for model selection (e.g., GPT-4o vs mini)
- **Semantic Bridge**: CognitiveRouter translates planner → deep for downstream cognitive service calls
