# Agent Capability and Skills Relationships Summary

## Overview

This document summarizes the relationships between agent capabilities, specializations, skills, and behaviors in the SeedCore baseline system. The architecture connects database-defined task types (`pkg_subtask_types`) to runtime agent capabilities through a multi-layer mapping system.

## Architecture Flow

```
pkg_subtask_types (Database)
    ↓
CapabilityRegistry (Loads & Caches)
    ↓
CapabilityMonitor (Detects Changes & Registers Dynamic Specializations)
    ↓
SpecializationManager (Manages Static + Dynamic Specializations)
    ↓
RoleProfile (Defines Skills, Behaviors, Tools, Routing Tags)
    ↓
BaseAgent (Materializes Skills, Initializes Behaviors)
```

## Key Components

### 1. Task Types (`pkg_subtask_types`)

Task types are stored in the database with the following structure:

```sql
CREATE TABLE pkg_subtask_types (
    id UUID PRIMARY KEY,
    snapshot_id INT,
    name TEXT,
    default_params JSONB,  -- Contains executor, routing, agent_behavior
    created_at TIMESTAMP
);
```

**Current Task Types (from baseline):**
1. `adjust_zone_environment` - Zone environment control
2. `adjust_zone_hvac` - HVAC system control
3. `control_zone_access` - Access control
4. `route_elevator_to_zone` - Elevator routing
5. `monitor_zone_safety` - Safety monitoring
6. `optimize_zone_energy` - Energy optimization
7. `notify_zone_operator` - Operator notifications
8. `activate_zone_emergency` - Emergency activation
9. `generate_precision_mockups` - 3D rendering/mockups
10. `sync_unified_memory` - Memory synchronization

### 2. Capability Definition Structure

Each task type's `default_params` follows this structure:

```json
{
  "executor": {
    "specialization": "specialization_name",  // Maps to Specialization enum or DynamicSpecialization
    "agent_class": "BaseAgent",              // Optional: agent class name
    "kind": "agent",                         // Optional: executor kind
    "behaviors": ["behavior1", "behavior2"], // Behavior Plugin System
    "behavior_config": {                     // Behavior-specific configuration
      "behavior1": {"config": "value"}
    },
    "tools": ["tool1", "tool2"]             // Required tools
  },
  "routing": {
    "required_specialization": "specialization_name",  // HARD constraint
    "specialization": "specialization_name",            // SOFT hint
    "skills": {                                        // Skill requirements
      "skill_name": 0.8,  // 0.0-1.0 proficiency level
      "another_skill": 0.6
    },
    "tools": ["tool1", "tool2"],                       // Routing-level tools
    "routing_tags": ["tag1", "tag2"],                  // Routing tags
    "zone_affinity": ["zone1", "zone2"],               // Preferred zones
    "environment_constraints": {}                      // Physical constraints
  },
  "agent_behavior": ["behavior1", "behavior2"]  // Legacy format (still supported)
}
```

### 3. Specializations

**Static Specializations** (defined in `Specialization` enum):
- `USER_LIAISON` - User interface and chat
- `ENVIRONMENT` - Environment sensing/digital twin
- `ANOMALY_DETECTOR` - Anomaly detection
- `DEVICE_ORCHESTRATOR` - Device control
- `CLEANING_ROBOT` - Physical cleaning robots
- `RESULT_VERIFIER` - Result verification
- `CRITIC` - Critical analysis
- `ADAPTIVE_LEARNER` - Learning agents
- `GENERALIST` - Fallback executor
- `OBSERVER` - Cache warmer/proactive observer
- `UTILITY` - Utility functions

**Dynamic Specializations** (registered at runtime):
- Created automatically from `executor.specialization` in `pkg_subtask_types`
- Managed by `SpecializationManager`
- Can have associated `RoleProfile` with skills, behaviors, tools

### 4. Skills

Skills are defined as dictionaries mapping skill names to proficiency levels (0.0-1.0):

```python
default_skills = {
    "skill_name": 0.8,      # 80% proficiency
    "another_skill": 0.6   # 60% proficiency
}
```

**Common Skills** (from role registries):
- `dialogue`, `empathy`, `compliance` - User interaction
- `data_ingestion`, `state_tracking` - Environment sensing
- `pattern_matching`, `threshold_monitoring` - Anomaly detection
- `iot_protocol`, `device_control` - Device orchestration
- `navigation`, `cleaning_mechanics` - Robot operations
- `tool_usage`, `basic_reasoning` - General capabilities
- `cache_management`, `pattern_detection` - Observer capabilities

**Skills Source Priority:**
1. `RoleProfile.default_skills` (from static registries or dynamic registration)
2. `routing.skills` (from `pkg_subtask_types.default_params.routing.skills`)
3. Agent skill deltas (learned over time, stored in `SkillVector`)

### 5. Agent Behaviors

Behaviors are runtime capabilities that can be dynamically configured:

**Standard Behaviors:**
- `chat_history` - Manages conversation history ring buffer
- `background_loop` - Runs periodic background tasks
- `task_filter` - Filters tasks by type/pattern
- `tool_registration` - Registers tools dynamically
- `dedup` - Manages idempotency cache
- `safety_check` - Performs safety validation
- `continuous_monitoring` - Continuous monitoring mode
- `immediate_execution` - Immediate execution mode
- `energy_optimization` - Energy optimization mode
- `intelligent_routing` - Intelligent routing mode
- `load_balancing` - Load balancing mode
- `security_monitoring` - Security monitoring mode
- `priority_override` - Priority override mode
- `task_filter` - Task filtering

**Behavior Sources (Priority Order):**
1. `executor.behaviors` (from `pkg_subtask_types.default_params.executor.behaviors`)
2. `agent_behavior` (legacy, from `pkg_subtask_types.default_params.agent_behavior`)
3. `RoleProfile.default_behaviors` (from static registries)
4. Constructor arguments (when creating agents)

**Behavior Configuration:**
Behaviors can have configuration dictionaries:
```python
behavior_config = {
    "background_loop": {
        "interval_s": 10.0,
        "method": "sense_environment",
        "max_errors": 3
    },
    "task_filter": {
        "allowed_types": ["env.tick", "environment.tick"]
    }
}
```

### 6. Mapping from Task Types to Agent Capabilities

**Current Baseline Task Types → Behaviors Mapping:**

| Task Type | Agent Behaviors (from default_params) |
|-----------|----------------------------------------|
| `adjust_zone_environment` | `["background_loop", "continuous_monitoring"]` |
| `adjust_zone_hvac` | `["background_loop", "energy_optimization"]` |
| `control_zone_access` | `["immediate_execution", "security_monitoring"]` |
| `route_elevator_to_zone` | `["intelligent_routing", "load_balancing"]` |
| `monitor_zone_safety` | `["continuous_monitoring", "immediate_execution"]` |
| `optimize_zone_energy` | `["background_loop", "energy_optimization"]` |
| `notify_zone_operator` | `["immediate_execution"]` |
| `activate_zone_emergency` | `["immediate_execution", "priority_override"]` |
| `generate_precision_mockups` | `["background_loop", "task_filter"]` |
| `sync_unified_memory` | `["background_loop", "continuous_monitoring"]` |

**Note:** Current baseline task types use `agent_behavior` field (legacy format) rather than `executor.behaviors`. The system supports both formats.

## Relationship Summary

### Capability → Specialization
- **Mapping:** `executor.specialization` → `Specialization` enum or `DynamicSpecialization`
- **Process:** 
  1. `CapabilityRegistry` loads task types from database
  2. `CapabilityMonitor` detects changes and extracts `executor.specialization`
  3. `SpecializationManager` registers dynamic specializations if not already registered
  4. `RoleProfile` is created/updated for the specialization

### Capability → Skills
- **Mapping:** `routing.skills` → `RoleProfile.default_skills`
- **Process:**
  1. Skills extracted from `default_params.routing.skills` dictionary
  2. Merged into `RoleProfile.default_skills` when creating dynamic role profiles
  3. Agents materialize skills: `base_skills + skill_deltas` (clamped to 0.0-1.0)
  4. Skills can be learned over time via `SkillLearner`

### Capability → Behaviors
- **Mapping:** `executor.behaviors` or `agent_behavior` → `RoleProfile.default_behaviors`
- **Process:**
  1. Behaviors extracted from `executor.behaviors` (preferred) or `agent_behavior` (legacy)
  2. Merged into `RoleProfile.default_behaviors` when creating dynamic role profiles
  3. Agent constructor merges: `RoleProfile.default_behaviors` + constructor args
  4. Behaviors initialized via `BehaviorRegistry` at agent startup

### Capability → Tools
- **Mapping:** `executor.tools` + `routing.tools` → `RoleProfile.allowed_tools`
- **Process:**
  1. Tools extracted from both `executor.tools` and `routing.tools`
  2. Combined into `RoleProfile.allowed_tools` set
  3. Used for RBAC enforcement via `RbacEnforcer`

### Capability → Routing Tags
- **Mapping:** `routing.routing_tags` → `RoleProfile.routing_tags`
- **Process:**
  1. Routing tags extracted from `routing.routing_tags`
  2. Added to `RoleProfile.routing_tags` set
  3. Used for task routing and agent selection

## Dynamic Registration Flow

When a new capability is added to `pkg_subtask_types`:

1. **CapabilityMonitor** detects change (hash-based comparison)
2. **CapabilityRegistry** refreshes capability definitions
3. **SpecializationManager** registers dynamic specialization (if `executor.specialization` exists)
4. **RoleProfile** is created from:
   - `routing.skills` → `default_skills`
   - `executor.behaviors` or `agent_behavior` → `default_behaviors`
   - `executor.behavior_config` → `behavior_config`
   - `executor.tools` + `routing.tools` → `allowed_tools`
   - `routing.routing_tags` → `routing_tags`
5. **Agents** can be spawned/updated with new role profiles (JIT spawning)

## Key Files

- **Capability Registry:** `src/seedcore/ops/pkg/capability_registry.py`
- **Capability Monitor:** `src/seedcore/ops/pkg/capability_monitor.py`
- **Specialization System:** `src/seedcore/agents/roles/specialization.py`
- **Role Profiles:** `src/seedcore/agents/roles/specialization.py` (RoleProfile class)
- **Static Role Registries:** 
  - `src/seedcore/agents/roles/generic_defaults.py`
  - `src/seedcore/agents/roles/role_registry_hospitality.py`
- **Agent Base:** `src/seedcore/agents/base.py`

## Current Baseline Observations

1. **Task Types Use Legacy Format:** Most task types use `agent_behavior` field instead of `executor.behaviors`
2. **No Explicit Skills:** Current task types don't define `routing.skills` - skills come from static role registries
3. **No Explicit Specializations:** Current task types don't define `executor.specialization` - would need dynamic registration
4. **Behavior Patterns:** Common behavior patterns:
   - `background_loop` + `continuous_monitoring` - For monitoring tasks
   - `background_loop` + `energy_optimization` - For optimization tasks
   - `immediate_execution` - For time-sensitive tasks
   - `intelligent_routing` + `load_balancing` - For routing tasks

## Recommendations

1. **Migrate to Modern Format:** Update task types to use `executor.behaviors` instead of `agent_behavior`
2. **Add Skills:** Define `routing.skills` for each task type to enable skill-based routing
3. **Add Specializations:** Define `executor.specialization` for each task type to enable dynamic specialization registration
4. **Add Tools:** Define required tools in `executor.tools` or `routing.tools` for RBAC enforcement
5. **Add Routing Tags:** Define `routing.routing_tags` for better task routing
