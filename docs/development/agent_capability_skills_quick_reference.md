# Agent Capability & Skills Quick Reference

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  pkg_subtask_types (Database)                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ default_params:                                       │  │
│  │   - executor.specialization → Specialization          │  │
│  │   - executor.behaviors → Agent Behaviors             │  │
│  │   - routing.skills → RoleProfile.default_skills      │  │
│  │   - routing.tools → RoleProfile.allowed_tools        │  │
│  │   - routing.routing_tags → RoleProfile.routing_tags  │  │
│  │   - agent_behavior (legacy) → Agent Behaviors        │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  CapabilityRegistry                                         │
│  - Loads & caches task type definitions                    │
│  - Provides build_step_task_from_subtask()                 │
│  - Extracts executor/routing hints                          │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  CapabilityMonitor                                          │
│  - Polls for changes (hash-based detection)                 │
│  - Registers dynamic specializations                        │
│  - Creates/updates RoleProfiles                             │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  SpecializationManager                                      │
│  - Manages static (Enum) + dynamic specializations         │
│  - Registers RoleProfiles                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  RoleProfile                                                │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ - default_skills: Dict[str, float]                    │ │
│  │ - default_behaviors: List[str]                       │ │
│  │ - allowed_tools: Set[str]                             │ │
│  │ - routing_tags: Set[str]                              │ │
│  │ - behavior_config: Dict[str, Dict]                   │ │
│  └───────────────────────────────────────────────────────┘ │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  BaseAgent                                                  │
│  - Materializes skills (base + deltas)                     │
│  - Initializes behaviors from RoleProfile                   │
│  - Enforces RBAC via allowed_tools                          │
│  - Uses routing_tags for task matching                      │
└─────────────────────────────────────────────────────────────┘
```

## Key Mappings

### 1. Specialization Mapping
```
executor.specialization (string)
    ↓
SpecializationManager.get(value)
    ↓
Specialization enum OR DynamicSpecialization
    ↓
RoleProfile.name
```

### 2. Skills Mapping
```
routing.skills (Dict[str, float])
    ↓
RoleProfile.default_skills
    ↓
Agent.materialize_skills(deltas)
    ↓
Final Skills Dict[str, float] (0.0-1.0)
```

### 3. Behaviors Mapping
```
executor.behaviors OR agent_behavior (List[str])
    ↓
RoleProfile.default_behaviors
    ↓
Agent constructor behaviors parameter
    ↓
BehaviorRegistry.initialize_behaviors()
```

### 4. Tools Mapping
```
executor.tools + routing.tools (List[str])
    ↓
RoleProfile.allowed_tools (Set[str])
    ↓
RbacEnforcer.check_access()
```

### 5. Routing Tags Mapping
```
routing.routing_tags (List[str])
    ↓
RoleProfile.routing_tags (Set[str])
    ↓
Router.select_best(required_tags=...)
```

## Field Priority Order

### Behaviors
1. Constructor `behaviors` parameter (highest priority)
2. `executor.behaviors` from task type
3. `agent_behavior` from task type (legacy)
4. `RoleProfile.default_behaviors` (lowest priority)

### Skills
1. Agent skill deltas (learned over time)
2. `routing.skills` from task type
3. `RoleProfile.default_skills` (baseline)

### Tools
1. `executor.tools` + `routing.tools` (combined)
2. `RoleProfile.allowed_tools` (from static registries)

## Common Behaviors

| Behavior | Purpose | Config Example |
|----------|---------|----------------|
| `background_loop` | Periodic background tasks | `{"interval_s": 10.0, "method": "tick"}` |
| `continuous_monitoring` | Continuous monitoring mode | `{}` |
| `immediate_execution` | Time-sensitive execution | `{}` |
| `task_filter` | Filter tasks by type | `{"allowed_types": ["env.tick"]}` |
| `energy_optimization` | Energy efficiency mode | `{}` |
| `intelligent_routing` | Smart routing decisions | `{}` |
| `load_balancing` | Load distribution | `{}` |
| `security_monitoring` | Security-focused monitoring | `{}` |
| `priority_override` | High-priority execution | `{}` |
| `chat_history` | Conversation history | `{"limit": 50}` |
| `tool_registration` | Dynamic tool registration | `{"tools": ["tool1"]}` |
| `dedup` | Idempotency cache | `{"ttl_s": 60.0}` |
| `safety_check` | Safety validation | `{"enabled": true}` |

## Common Skills (Examples)

| Skill Category | Example Skills |
|----------------|----------------|
| **User Interaction** | `dialogue`, `empathy`, `compliance` |
| **Environment** | `data_ingestion`, `state_tracking`, `sensor_integration` |
| **Monitoring** | `pattern_matching`, `threshold_monitoring`, `anomaly_detection` |
| **Device Control** | `iot_protocol`, `device_control`, `zone_management` |
| **Routing** | `dispatch_planning`, `route_optimization`, `load_balancing` |
| **Security** | `access_policy`, `security_monitoring`, `identity_resolution` |
| **Energy** | `energy_optimization`, `hvac_control` |
| **Graphics** | `rendering`, `three_js`, `graphics_generation` |
| **Memory** | `cache_management`, `data_synchronization`, `memory_management` |

## File Locations

| Component | File Path |
|-----------|-----------|
| Capability Registry | `src/seedcore/ops/pkg/capability_registry.py` |
| Capability Monitor | `src/seedcore/ops/pkg/capability_monitor.py` |
| Specialization System | `src/seedcore/agents/roles/specialization.py` |
| Role Profiles | `src/seedcore/agents/roles/specialization.py` |
| Static Registries | `src/seedcore/agents/roles/generic_defaults.py` |
| Agent Base | `src/seedcore/agents/base.py` |
| Behavior System | `src/seedcore/agents/behaviors/` |

## Quick Checklist

When defining a new task type in `pkg_subtask_types`:

- [ ] Define `executor.specialization` (or use existing)
- [ ] Define `executor.behaviors` (list of behavior names)
- [ ] Define `executor.behavior_config` (optional, behavior-specific configs)
- [ ] Define `routing.skills` (dict of skill_name: proficiency)
- [ ] Define `executor.tools` or `routing.tools` (list of tool names)
- [ ] Define `routing.routing_tags` (list of tags for routing)
- [ ] (Optional) Define `routing.zone_affinity` (preferred zones)
- [ ] (Optional) Define `routing.environment_constraints` (physical constraints)

## Migration Path (Legacy → Modern)

**Legacy Format:**
```json
{
  "agent_behavior": ["background_loop", "continuous_monitoring"]
}
```

**Modern Format:**
```json
{
  "executor": {
    "specialization": "environment_controller",
    "behaviors": ["background_loop", "continuous_monitoring"],
    "behavior_config": {
      "background_loop": {"interval_s": 10.0}
    }
  },
  "routing": {
    "skills": {"environment_control": 0.9},
    "routing_tags": ["environment", "monitoring"]
  }
}
```
