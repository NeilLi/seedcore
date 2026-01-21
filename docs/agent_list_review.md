# Agent List Review - 2026-01-20

## Summary
**Total Agents: 43** (including Organ actors, Service replicas, and utility actors)

## Expected Agents (from `config/organs.yaml`)

### ✅ All Expected Agents Present

| Organ | Specialization | Expected Count | Found Agent Name | Status |
|-------|---------------|----------------|-------------------|--------|
| `user_experience_organ` | `USER_LIAISON` | 1 | `user_experience_organ_user_liaison_0` | ✅ |
| `environment_intelligence_organ` | `ENVIRONMENT` | 1 | `environment_intelligence_organ_environment_0` | ✅ |
| `environment_intelligence_organ` | `ANOMALY_DETECTOR` | 1 | `environment_intelligence_organ_anomaly_detector_0` | ✅ |
| `orchestration_organ` | `DEVICE_ORCHESTRATOR` | 1 | `orchestration_organ_device_orchestrator_0` | ✅ |
| `robot_execution_organ` | `CLEANING_ROBOT` | 1 | `robot_execution_organ_cleaning_robot_0` | ✅ |
| `verification_organ` | `RESULT_VERIFIER` | 1 | `verification_organ_result_verifier_0` | ✅ |
| `learning_organ` | `CRITIC` | 1 | `learning_organ_critic_0` | ✅ |
| `learning_organ` | `ADAPTIVE_LEARNER` | 1 | `learning_organ_adaptive_learner_0` | ✅ |
| `utility_organ` | `OBSERVER` | 1 | `utility_organ_observer_0` | ✅ |
| `utility_organ` | `UTILITY` | 1 | `utility_organ_utility_0` (UtilityAgent) | ✅ |
| `utility_organ` | `GENERALIST` | 1 | `utility_organ_generalist_0` | ✅ |

**Total Expected BaseAgent/UtilityAgent instances: 11** ✅

## Organ Actors (Expected: 7)

| Organ ID | Found Actor Name | Status |
|----------|------------------|--------|
| `user_experience_organ` | `user_experience_organ` | ✅ |
| `environment_intelligence_organ` | `environment_intelligence_organ` | ✅ |
| `orchestration_organ` | `orchestration_organ` | ✅ |
| `robot_execution_organ` | `robot_execution_organ` | ✅ |
| `verification_organ` | `verification_organ` | ✅ |
| `learning_organ` | `learning_organ` | ✅ |
| `utility_organ` | `utility_organ` | ✅ |

**All 7 Organ actors present** ✅

## New Specializations (Not Yet Spawned)

The following specializations were added to the `Specialization` enum but are **not configured** in `organs.yaml` (count=0 or not present):

| Specialization | Value | Purpose | Status |
|----------------|-------|---------|--------|
| `STUDIO_DIRECTOR` | `studio_director` | Synthesis: Orchestrates creative workflows | ⚠️ Not configured |
| `PRECISION_RENDERER` | `precision_renderer` | Execution: Handles `generate_precision_mockups` subtasks | ⚠️ Not configured |
| `DESIGN_PROMOTER` | `design_promoter` | Synthesis: Orchestrates "Promote → Validate" flow | ⚠️ Not configured |
| `MOCKUP_ENGINEER` | `mockup_engineer` | Execution: Handles `generate_precision_mockups` subtasks | ⚠️ Not configured |
| `ZONE_GUARDIAN` | `zone_guardian` | Observation: High-priority agent for Magic Atelier (KIDS) zone | ⚠️ Not configured |
| `LOGISTICS_ROUTOR` | `logistics_routor` | Execution: Manages `system:elevators_management` facts | ⚠️ Not configured |

**Note:** These agents will be spawned automatically when:
1. A capability in `pkg_subtask_types` references one of these specializations
2. The `CapabilityMonitor` detects the new capability and triggers agent creation
3. Or they are manually added to `organs.yaml` with `count > 0`

## Service Replicas & Infrastructure

### Ray Serve Services (Expected)
- ✅ `CoordinatorService` (coordinator:Coordinator)
- ✅ `OrganismService` (organism:OrganismService)
- ✅ `MLService` (ml_service:MLService)
- ✅ `FactManagerService` (ops:FactManagerService)
- ✅ `EventizerService` (ops:EventizerService)
- ✅ `MCPService` (mcp:MCPService)
- ✅ `CognitiveService` (cognitive:CognitiveService)
- ✅ `StateService` (ops:StateService)
- ✅ `EnergyService` (ops:EnergyService)
- ✅ `OpsGateway` (ops:OpsGateway)

### Utility Actors
- ✅ `Janitor` (seedcore_janitor)
- ✅ `Reaper` (seedcore_reaper)
- ✅ `Dispatcher` (queue_dispatcher_0)
- ✅ `StatusActor` (job_status_actor)
- ✅ `SharedCache` (shared_cache)
- ✅ `SharedCacheShard` (4 shards)
- ✅ `MwStoreShard` (2 shards)

## Naming Convention Verification

All agents follow the expected naming pattern:
```
{organ_id}_{specialization}_{index}
```

Examples:
- ✅ `user_experience_organ_user_liaison_0`
- ✅ `environment_intelligence_organ_environment_0`
- ✅ `utility_organ_generalist_0`

## Consistency Check with Previous Changes

### ✅ Dynamic Specialization Support
- All agents use string-based specialization values (normalized to lowercase)
- Registry (`OrganRegistry`) correctly stores specializations as lowercase strings
- Topology manager normalizes specialization names for consistent lookup

### ✅ Role Profile Updates
- Agents are ready to receive `RoleProfile` updates via `Organ.update_role_registry()`
- `BaseAgent.update_role_profile()` handles dynamic updates including:
  - Behavior reinitialization
  - Tool changes
  - Zone affinity and environment constraints
  - E/S/O probability updates

### ✅ Capability Monitoring Integration
- `CapabilityMonitor` is running (via `CoordinatorService`)
- Agents can be dynamically spawned/updated when `pkg_subtask_types` changes
- Selective broadcasting ensures only relevant organs receive updates

## Recommendations

1. **New Specializations**: If you want to spawn agents for the new specializations (`STUDIO_DIRECTOR`, `PRECISION_RENDERER`, etc.), add them to `config/organs.yaml`:
   ```yaml
   - id: "creative_organ"  # or add to existing organ
     agents:
       - specialization: "STUDIO_DIRECTOR"
         count: 1
       - specialization: "PRECISION_RENDERER"
         count: 1
   ```

2. **Dynamic Spawning**: Alternatively, ensure `pkg_subtask_types` has capabilities that reference these specializations, and the `CapabilityMonitor` will spawn them automatically.

3. **Verification**: The current agent list is **correct** and consistent with the configuration. All expected agents are present and properly named.

## Conclusion

✅ **Agent list is CORRECT** - All configured agents are present and properly named.  
✅ **Naming conventions are consistent** with the new dynamic specialization system.  
✅ **Registry and topology managers** are compatible with the new features.  
⚠️ **New specializations** are defined but not yet spawned (expected behavior - they'll spawn when capabilities reference them).
