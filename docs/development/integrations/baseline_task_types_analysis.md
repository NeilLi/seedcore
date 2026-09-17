# Baseline Task Types Analysis

## Current Task Types from Database

Based on the `pkg_subtask_types` query results, here are the 10 task types and their current configuration:

### Task Type Breakdown

| ID | Task Type Name | Agent Behaviors | Notes |
|----|---------------|-----------------|-------|
| `aafa308d-3745-49ae-b11b-f774d8766184` | `adjust_zone_environment` | `["background_loop", "continuous_monitoring"]` | Zone environment control |
| `229316c8-c858-4454-acb2-a81239472fe3` | `adjust_zone_hvac` | `["background_loop", "energy_optimization"]` | HVAC system control |
| `6fad7bd5-f6be-495f-90bf-6ee4b7774b50` | `control_zone_access` | `["immediate_execution", "security_monitoring"]` | Access control |
| `51007445-0ec1-4bd5-9584-d394ac5b0015` | `route_elevator_to_zone` | `["intelligent_routing", "load_balancing"]` | Elevator routing |
| `9fc4e214-3dcb-4f69-abde-32271f66fa91` | `monitor_zone_safety` | `["continuous_monitoring", "immediate_execution"]` | Safety monitoring |
| `d39f2642-b2a2-496c-a883-975747a9a69c` | `optimize_zone_energy` | `["background_loop", "energy_optimization"]` | Energy optimization |
| `99d33588-5000-4a09-b752-b5b219ecf1ce` | `notify_zone_operator` | `["immediate_execution"]` | Operator notifications |
| `3c4fb06e-c717-4e57-b573-732fa74355e6` | `activate_zone_emergency` | `["immediate_execution", "priority_override"]` | Emergency activation |
| `0bdc8592-c2c7-4b8a-ae1d-1479ac050ff9` | `generate_precision_mockups` | `["background_loop", "task_filter"]` | 3D rendering/mockups |
| `c888abb6-9b9e-43e7-8bfb-3e9da8455d43` | `sync_unified_memory` | `["background_loop", "continuous_monitoring"]` | Memory synchronization |

## Behavior Pattern Analysis

### Behavior Frequency

| Behavior | Count | Task Types |
|----------|-------|------------|
| `background_loop` | 6 | adjust_zone_environment, adjust_zone_hvac, optimize_zone_energy, generate_precision_mockups, sync_unified_memory |
| `continuous_monitoring` | 3 | adjust_zone_environment, monitor_zone_safety, sync_unified_memory |
| `immediate_execution` | 4 | control_zone_access, monitor_zone_safety, notify_zone_operator, activate_zone_emergency |
| `energy_optimization` | 2 | adjust_zone_hvac, optimize_zone_energy |
| `intelligent_routing` | 1 | route_elevator_to_zone |
| `load_balancing` | 1 | route_elevator_to_zone |
| `security_monitoring` | 1 | control_zone_access |
| `priority_override` | 1 | activate_zone_emergency |
| `task_filter` | 1 | generate_precision_mockups |

### Behavior Categories

**Monitoring & Background Tasks:**
- `background_loop` - Periodic background processing
- `continuous_monitoring` - Continuous monitoring mode
- `task_filter` - Task filtering

**Execution Modes:**
- `immediate_execution` - Time-sensitive execution
- `priority_override` - High-priority execution

**Optimization:**
- `energy_optimization` - Energy efficiency optimization

**Routing:**
- `intelligent_routing` - Smart routing decisions
- `load_balancing` - Load distribution

**Security:**
- `security_monitoring` - Security-focused monitoring

## Current State: Missing Relationships

### ❌ No Explicit Specializations
- None of the task types define `executor.specialization`
- Would need to derive from capability name or use default `GENERALIST`

### ❌ No Explicit Skills
- None of the task types define `routing.skills`
- Skills would come from static role registries only

### ❌ No Explicit Tools
- None of the task types define `executor.tools` or `routing.tools`
- Tools would come from static role registries only

### ❌ No Routing Tags
- None of the task types define `routing.routing_tags`
- Routing would rely on specialization matching only

### ✅ Behaviors Defined (Legacy Format)
- All task types use `agent_behavior` field (legacy)
- Should migrate to `executor.behaviors` format

## Recommended Enhancements

### Example: Enhanced `adjust_zone_environment`

**Current:**
```json
{
  "zone": null,
  "humidity": null,
  "lighting": null,
  "temperature": null,
  "agent_behavior": ["background_loop", "continuous_monitoring"]
}
```

**Recommended:**
```json
{
  "zone": null,
  "humidity": null,
  "lighting": null,
  "temperature": null,
  "executor": {
    "specialization": "environment_controller",
    "behaviors": ["background_loop", "continuous_monitoring"],
    "behavior_config": {
      "background_loop": {
        "interval_s": 10.0,
        "method": "adjust_environment",
        "max_errors": 3
      }
    },
    "tools": ["iot.write", "sensors.read_all"]
  },
  "routing": {
    "skills": {
      "environment_control": 0.9,
      "sensor_integration": 0.8,
      "zone_management": 0.85
    },
    "routing_tags": ["environment", "zone_control", "monitoring"]
  }
}
```

## Mapping to Static Role Registries

Since current task types don't define specializations, they would map to:

| Task Type | Likely Specialization | Reason |
|-----------|----------------------|--------|
| `adjust_zone_environment` | `ENVIRONMENT` | Environment sensing/control |
| `adjust_zone_hvac` | `DEVICE_ORCHESTRATOR` | Device control |
| `control_zone_access` | `GENERALIST` | No specific specialization |
| `route_elevator_to_zone` | `DEVICE_ORCHESTRATOR` | Device orchestration |
| `monitor_zone_safety` | `ANOMALY_DETECTOR` | Monitoring/anomaly detection |
| `optimize_zone_energy` | `DEVICE_ORCHESTRATOR` | Device optimization |
| `notify_zone_operator` | `USER_LIAISON` | User communication |
| `activate_zone_emergency` | `GENERALIST` | Emergency handling |
| `generate_precision_mockups` | `GENERALIST` | Rendering/graphics |
| `sync_unified_memory` | `OBSERVER` | Memory/cache management |

## Skills That Would Be Relevant

Based on task types, these skills would be useful:

| Task Type | Relevant Skills |
|-----------|----------------|
| `adjust_zone_environment` | `environment_control`, `sensor_integration`, `zone_management` |
| `adjust_zone_hvac` | `iot_protocol`, `device_control`, `energy_optimization` |
| `control_zone_access` | `access_policy`, `security_monitoring`, `identity_resolution` |
| `route_elevator_to_zone` | `dispatch_planning`, `route_optimization`, `device_control` |
| `monitor_zone_safety` | `pattern_matching`, `threshold_monitoring`, `anomaly_detection` |
| `optimize_zone_energy` | `energy_optimization`, `device_control`, `analytics` |
| `notify_zone_operator` | `communication`, `notification_management`, `urgency_handling` |
| `activate_zone_emergency` | `crisis_management`, `priority_handling`, `emergency_protocols` |
| `generate_precision_mockups` | `rendering`, `three_js`, `graphics_generation` |
| `sync_unified_memory` | `cache_management`, `data_synchronization`, `memory_management` |

## Summary

**Current Baseline State:**
- ✅ Behaviors defined (legacy `agent_behavior` format)
- ❌ No specializations defined
- ❌ No skills defined
- ❌ No tools defined
- ❌ No routing tags defined

**System Capabilities:**
- ✅ Supports dynamic specialization registration
- ✅ Supports skill-based routing
- ✅ Supports behavior configuration
- ✅ Supports tool-based RBAC
- ✅ Supports routing tags

**Gap:**
- Task types need to be enhanced with full capability definitions to leverage all system features
