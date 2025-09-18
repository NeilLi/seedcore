# Routing System Contracts

This document defines the contracts, SLAs, and failure matrix for the SeedCore routing system.

## Overview

The routing system has been refactored to move routing logic from Coordinator to OrganismManager, with runtime registry integration and bulk resolution capabilities.

## Architecture

- **Coordinator**: Governor role - decides fast vs escalate, calls Organism for routing
- **OrganismManager**: Dispatcher role - owns routing rules and runtime registry
- **Cognitive**: Planner role - produces abstract steps, no routing awareness

## API Contracts

### Single Route Resolution

**Endpoint**: `POST /organism/resolve-route`

**Request**:
```json
{
  "task": {
    "type": "graph_rag_query_v2",
    "domain": "facts",
    "params": {}
  },
  "preferred_logical_id": "graph_dispatcher"  // optional hint
}
```

**Response**:
```json
{
  "logical_id": "graph_dispatcher",           // required for execution
  "resolved_from": "task",                    // "domain"|"task"|"default"|"preferred"|"fallback"
  "epoch": "epoch-1234567890",               // current cluster epoch
  "instance_id": "instance-graph-123",       // telemetry only - don't pin instances
  "cache_hit": false,                        // whether this was a cache hit
  "cache_age_ms": 0.0                        // age of cached data in milliseconds
}
```

**Status Codes**:
- `200 OK`: Always returned (per-item status in response)
- `503 Service Unavailable`: Only if organism is completely down

### Bulk Route Resolution

**Endpoint**: `POST /organism/resolve-routes`

**Request**:
```json
{
  "tasks": [
    {
      "key": "graph_embed|facts",             // for de-duplication
      "type": "graph_embed",
      "domain": "facts",
      "preferred_logical_id": "graph_dispatcher"  // optional
    },
    {
      "key": "fact_search|",
      "type": "fact_search",
      "domain": null,
      "preferred_logical_id": null
    }
  ]
}
```

**Response**:
```json
{
  "epoch": "epoch-1234567890",
  "results": [
    {
      "key": "graph_embed|facts",
      "logical_id": "graph_dispatcher",
      "resolved_from": "task",
      "status": "ok",                         // "ok"|"no_active_instance"|"unknown_type"|"error"
      "epoch": "epoch-1234567890",
      "instance_id": "instance-graph-123",
      "cache_hit": false,
      "cache_age_ms": 0.0
    },
    {
      "key": "fact_search|",
      "logical_id": "utility_organ_1",
      "resolved_from": "default",
      "status": "ok",
      "epoch": "epoch-1234567890",
      "instance_id": "instance-util-456",
      "cache_hit": true,
      "cache_age_ms": 1500.0
    }
  ]
}
```

## Status Values

### `resolved_from` Values
- `"preferred"`: Used the provided preferred_logical_id
- `"domain"`: Matched by (task_type, domain) rule
- `"task"`: Matched by task_type rule
- `"default"`: Used category default
- `"fallback"`: Used utility_organ_1 fallback

### `status` Values
- `"ok"`: Successfully resolved with active instance
- `"no_active_instance"`: Resolved logical_id but no healthy instance
- `"unknown_type"`: No routing rule found for task type
- `"error"`: Exception during resolution

## SLAs and Performance

### Latency Targets
- **Single resolve**: < 50ms (95th percentile)
- **Bulk resolve**: < 100ms (95th percentile)
- **Cache hit**: < 1ms (95th percentile)

### Throughput
- **Single resolve**: 1000+ requests/second
- **Bulk resolve**: 100+ requests/second (10+ items per request)

### Availability
- **Target**: 99.9% availability
- **Fallback**: Static routing when organism unavailable

## Failure Matrix

| Scenario | Coordinator Behavior | Organism Response | Fallback |
|----------|---------------------|-------------------|----------|
| Organism timeout | Use static routing | N/A | ✅ Per-step static |
| Organism circuit open | Use static routing | N/A | ✅ Per-step static |
| No active instance | Use static routing | `status: "no_active_instance"` | ✅ Per-step static |
| Unknown task type | Use static routing | `status: "unknown_type"` | ✅ Per-step static |
| Epoch rotation | Clear cache, continue | New epoch in response | ✅ Cache refresh |
| Registry empty | Use static routing | `status: "no_active_instance"` | ✅ Per-step static |
| Partial bulk failure | Use static for failed items | Per-item status | ✅ Per-item fallback |

## Caching Strategy

### Coordinator Cache (Tiny TTL)
- **TTL**: 3 seconds ± 0.5s jitter
- **Key**: `(normalized_type, normalized_domain)`
- **Invalidation**: Epoch rotation, TTL expiry
- **Single-flight**: Prevents dogpiles during cache misses

### Organism Cache (Server-side)
- **TTL**: 3 seconds
- **Key**: `logical_id:epoch`
- **Invalidation**: TTL expiry, manual refresh
- **Single-flight**: Prevents concurrent registry queries

## Security

### Authentication
- **Required**: mTLS or signed service token
- **Headers**: `X-Correlation-ID`, `X-Service`
- **Scope**: All routing and admin endpoints

### Authorization
- **Routing endpoints**: Service-to-service only
- **Admin endpoints**: Restricted to system administrators

## Monitoring and Metrics

### Coordinator Metrics
- `route_cache_hit_total`: Cache hit count
- `route_remote_total`: Remote resolve count
- `route_remote_latency_ms`: Remote resolve latency histogram
- `route_remote_fail_total`: Remote resolve failure count
- `bulk_resolve_items`: Items processed in bulk resolves
- `bulk_resolve_failed_items`: Items that failed in bulk resolves

### Organism Metrics
- `resolve_route_total`: Single resolve count
- `resolve_routes_total`: Bulk resolve count
- `resolve_routes_items`: Items in bulk resolves
- `routing_cache_hit_total`: Server-side cache hits
- `routing_rules_total`: Total routing rules

### Alerts
- **High latency**: > 100ms for 5+ minutes
- **High error rate**: > 5% failures for 2+ minutes
- **Cache miss rate**: > 50% for 5+ minutes
- **Epoch rotation**: When epoch changes

## Feature Flags

### `ROUTING_REMOTE`
- **Default**: `false`
- **Purpose**: Enable remote routing vs static-only
- **Rollout**: Start with `graph_*` types, then expand

### `ROUTING_REMOTE_TYPES`
- **Default**: `"graph_embed,graph_rag_query,graph_embed_v2,graph_rag_query_v2"`
- **Purpose**: Control which task types use remote routing
- **Format**: Comma-separated list

### `ROUTE_CACHE_TTL_S`
- **Default**: `3.0`
- **Purpose**: Coordinator cache TTL in seconds

### `ROUTE_CACHE_JITTER_S`
- **Default**: `0.5`
- **Purpose**: Cache TTL jitter in seconds

## Testing Strategy

### Unit Tests
- Cache operations and expiry
- Single-flight correctness
- De-duplication logic
- Normalization functions
- Fallback routing

### Integration Tests
- End-to-end routing flow
- Bulk resolve with de-duplication
- Epoch rotation handling
- Circuit breaker behavior
- Feature flag functionality

### Chaos Tests
- Epoch rotation during resolution
- Registry temporarily empty
- Partial bulk failures
- Network partitions
- High concurrency scenarios

## Migration Guide

### Phase 1: Deploy with Feature Flag Off
1. Deploy new code with `ROUTING_REMOTE=false`
2. Verify static routing works as before
3. Monitor metrics and logs

### Phase 2: Enable for Graph Tasks
1. Set `ROUTING_REMOTE=true`
2. Set `ROUTING_REMOTE_TYPES="graph_embed,graph_rag_query,graph_embed_v2,graph_rag_query_v2"`
3. Monitor performance and error rates

### Phase 3: Expand Coverage
1. Add more task types to `ROUTING_REMOTE_TYPES`
2. Monitor for any regressions
3. Gradually expand to all task types

### Phase 4: Remove Feature Flag
1. Set `ROUTING_REMOTE=true` globally
2. Remove feature flag code in future release
3. Clean up static routing fallbacks

## Troubleshooting

### Common Issues

**High latency on route resolution**
- Check organism service health
- Verify cache hit rates
- Check for epoch rotation frequency

**Route resolution failures**
- Check organism service logs
- Verify runtime registry connectivity
- Check for circuit breaker trips

**Incorrect routing decisions**
- Check routing rules in organism
- Verify task type normalization
- Check domain-specific overrides

### Debug Commands

```bash
# Check routing rules
curl -H "Authorization: Bearer $TOKEN" \
  http://organism:8000/routing/rules

# Test single resolve
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":{"type":"graph_embed","domain":"facts"}}' \
  http://organism:8000/resolve-route

# Test bulk resolve
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tasks":[{"key":"graph_embed|facts","type":"graph_embed","domain":"facts"}]}' \
  http://organism:8000/resolve-routes

# Refresh cache
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://organism:8000/routing/refresh
```
