# SeedCore Futuristic Reference: Capabilities, Routing, Skills & TaskPayload (Baseline → v2.5+)

This document is the canonical reference for how SeedCore maps **database-defined capabilities** and **task-instance routing signals** into **runtime agent behavior**, including specialization resolution, skill materialization, RBAC tool enforcement, routing tags, multimodal envelopes, and telemetry/provenance.

It merges the SeedCore baseline architecture with the modern **TaskPayload v2.5** envelope design, with a focus on **stable contracts**, **safe migration**, and **future evolution without schema migrations**.

---

## 1) Core Concepts

### 1.1 Capability vs Task Instance

SeedCore uses two complementary layers:

* **Capability definition (type-level):** stored in `pkg_subtask_types.default_params`

  * Declares what a *task type* requires / prefers: specialization, behaviors, tools, routing tags, default skills.
* **TaskPayload (instance-level):** stored in `tasks.params` (JSONB)

  * Declares what a *specific task instance* needs right now: routing constraints, cognitive flags, tool calls, multimodal metadata.

**Key principle:** *Type-level defaults provide guardrails; instance-level payloads provide execution-time intent.*

---

## 2) End-to-End Runtime Flow

```
pkg_subtask_types (Database)
    ↓
CapabilityRegistry (loads + caches, builds canonical task definition)
    ↓
CapabilityMonitor (hash polling, detects changes)
    ↓
SpecializationManager (static enums + runtime dynamic specializations)
    ↓
RoleProfile (skills, behaviors, tools, routing_tags, behavior_config)
    ↓
BaseAgent (materializes skills, initializes behaviors, enforces RBAC)
    ↓
Router / Coordinator (selects best Organ/Agent using routing inbox)
```

### 2.1 RoleProfile as the “runtime contract”

`RoleProfile` is the canonical runtime representation of what an agent can do:

* `default_skills: Dict[str, float]`
* `default_behaviors: List[str]`
* `allowed_tools: Set[str]`
* `routing_tags: Set[str]`
* `behavior_config: Dict[str, Dict]`

---

## 3) Capability Definition (Type-Level): `pkg_subtask_types.default_params`

### 3.1 Canonical Structure

```jsonc
{
  "executor": {
    "specialization": "ENVIRONMENT",
    "behaviors": ["background_loop", "continuous_monitoring"],
    "behavior_config": {
      "background_loop": {"interval_s": 10.0, "method": "tick"}
    },
    "tools": ["sensors.read_all", "iot.write.environment"]
  },
  "routing": {
    "required_specialization": "ENVIRONMENT",
    "specialization": "ENVIRONMENT",
    "skills": {"environment_control": 0.9},
    "tools": ["sensors.read_all"],              // REQUIRED tool *names* (strings)
    "routing_tags": ["environment", "monitoring"],
    "zone_affinity": ["lobby_area_01"],
    "environment_constraints": {}
  },

  // Legacy compatibility (supported during migration only)
  "agent_behavior": ["background_loop", "continuous_monitoring"]
}
```

### 3.2 Dynamic specialization registration

* `executor.specialization` may resolve to:

  * a **static** `Specialization` enum (preferred), or
  * a **DynamicSpecialization** registered at runtime.

---

## 4) TaskPayload v2.5+ (Instance-Level): `tasks.params`

`tasks.params` stores high-evolution metadata using JSONB:

* **Inputs:** `tasks.params` (JSONB)
* **Outputs/telemetry:** `tasks.result.meta` (JSONB)

### 4.1 Envelope Isolation (Non-Negotiable)

* `params.routing` — **Router Inbox** (read-only input)
* `params._router` — **Router Output** (system generated)
* `params.cognitive` — cognitive execution controls
* `params.chat` — chat message window/context
* `params.risk` — upstream classification (audit + protocols)
* `params.graph` — graph ops payload when applicable
* `params.multimodal` — voice/vision metadata (v2.5)
* `params.tool_calls` — executable tool invocations (structured)

---

## 5) Router Inbox: `params.routing` (Read-Only Input)

### 5.1 Canonical Router Inbox Format

```jsonc
{
  "routing": {
    "required_specialization": "SecurityMonitoring",  // HARD constraint
    "specialization": "SecurityMonitoring",           // SOFT preference
    "skills": {"threat_assessment": 0.9},             // 0.0–1.0
    "tools": ["alerts.raise", "sensors.read_all"],    // REQUIRED tool NAMES (strings)
    "routing_tags": ["security", "monitoring"],
    "hints": {
      "priority": 7,
      "deadline_at": "2025-11-25T14:35:00Z",
      "ttl_seconds": 60
    }
  }
}
```

### 5.2 Semantics

* `required_specialization`: must match (routing fails otherwise)
* `specialization`: prefer, but may fall back
* `skills`: used for scoring and selection within candidates
* `tools`: required capabilities by name (RBAC + selection signals)
* `routing_tags`: tag matching / structured routing intent
* `hints`: scheduling metadata (priority/deadline/TTL)

### 5.3 Critical rule: tunnel mode bypass

If `params.interaction.mode == "agent_tunnel"`, router is skipped and `params.routing` is ignored.

---

## 6) Tool Calls: `params.tool_calls` (Executable Requests)

To avoid conflating **tool permission requirements** with **execution requests**:

* `routing.tools` = list of **required tool names** (strings)
* `tool_calls` = list of **tool invocation objects**

```jsonc
{
  "tool_calls": [
    {"name": "iot.control", "args": {"device": "lights", "location": "lobby", "action": "off"}}
  ]
}
```

---

## 7) Router Output: `params._router` (System Generated)

```jsonc
{
  "_router": {
    "is_high_stakes": true,
    "agent_id": "agent_security_001",
    "organ_id": "organ_security",
    "reason": "Matched required specialization and priority constraints"
  }
}
```

**Write-only rule:** upstream components must never write `_router`.

---

## 8) Cognitive Envelope: `params.cognitive`

Controls inference style, memory I/O, and model routing.

```jsonc
{
  "cognitive": {
    "agent_id": "agent_security_001",
    "cog_type": "task_planning",
    "decision_kind": "planner",
    "llm_provider_override": "openai",
    "llm_model_override": "gpt-4o",
    "skip_retrieval": false,
    "disable_memory_write": false,
    "force_rag": false,
    "force_deep_reasoning": false
  }
}
```

**Key note:** `agent_id` is usually populated after routing, derived from `_router.agent_id`.

---

## 9) Multimodal Envelope (v2.5): `params.multimodal`

Stores metadata only. Media binaries live externally. Embeddings live in dedicated tables.

### 9.1 Voice / Vision Metadata (Example)

```jsonc
{
  "multimodal": {
    "source": "vision",
    "media_uri": "s3://.../camera_101.mp4",
    "scene_description": "Person detected near Room 101",
    "confidence": 0.92,
    "detected_objects": [{"class": "person", "bbox": [100,200,150,300]}],
    "timestamp": "2025-11-25T14:30:22Z",
    "camera_id": "camera_101",
    "location_context": "room_101_corridor",
    "is_real_time": true,
    "ttl_seconds": 60,
    "parent_stream_id": "stream_camera_101_20251125"
  }
}
```

### 9.2 Embedding storage strategy

* `task_multimodal_embeddings`: direct FK to `tasks.id` (fast “Living System” recall)
* `graph_embeddings_128/1024`: indirect via `graph_node_map` (HGNN/structural memory)

---

## 10) Priority Order (Canonical)

### 10.1 Behaviors (highest → lowest)

1. constructor `behaviors`
2. `executor.behaviors` (type-level)
3. legacy `agent_behavior` (type-level)
4. `RoleProfile.default_behaviors` (registries)

### 10.2 Skills (highest → lowest)

1. learned deltas (SkillVector)
2. `routing.skills` (type-level or instance-level routing inbox)
3. `RoleProfile.default_skills` (registries)

### 10.3 Tools

1. `executor.tools + routing.tools` (union)
2. static registry `RoleProfile.allowed_tools`

**Note:** execution requests live in `params.tool_calls` and are not part of RBAC/scoring.

---

## 11) Precedence Rules: Task Instance vs Task Type

When resolving routing inputs, apply:

1. **Task instance (`tasks.params.routing`)** overrides all defaults
2. Else **task type (`pkg_subtask_types.default_params`)** provides defaults
3. Else **organ defaults / generalist fallback**

**Operational recommendation:** `_router.reason` must state whether constraints came from instance vs type.

---

## 12) Result Provenance: `result.meta` (Source of Truth)

Store:

* routing decision snapshot (selected agent/organ, score, shortlist)
* execution telemetry (latency, attempts, timestamps)
* cognitive trace (retrieval scope, model, decision path)

```jsonc
{
  "routing_decision": {
    "selected_agent_id": "agent_security_001",
    "selected_organ_id": "organ_security",
    "router_score": 0.95,
    "routed_at": "2025-11-25T14:30:25Z"
  },
  "exec": {"latency_ms": 16000, "attempt": 1},
  "cognitive_trace": {"chosen_model": "gpt-4o", "decision_path": "PLANNER_PATH"}
}
```

---

## 13) Operational Checklists

### 13.1 New Task Type Checklist (`pkg_subtask_types`)

* [ ] `executor.specialization`
* [ ] `executor.behaviors`
* [ ] `executor.behavior_config` (optional)
* [ ] `routing.skills`
* [ ] `executor.tools` and/or `routing.tools` (**strings**)
* [ ] `routing.routing_tags`
* [ ] optional: `zone_affinity`, `environment_constraints`
* [ ] legacy: `agent_behavior` only if required during migration

### 13.2 New Task Instance Checklist (`tasks.params`)

* [ ] `interaction.mode` set correctly
* [ ] `routing.*` (only when not tunneling)
* [ ] `tool_calls` for execution requests (structured)
* [ ] `cognitive` flags consistent with risk + urgency
* [ ] `multimodal` metadata present when applicable
* [ ] do not write `_router`
* [ ] do not use legacy `params.tools`

---

## 14) Recommended Next Steps (Future-Proofing)

1. **Schema validation + linter**

   * Validate skill ranges, behavior names, tool name strings, tag conventions.
   * Block structured tool calls inside `routing.tools`.

2. **Specialization policy guardrails**

   * Avoid accidental hard constraints by requiring explicit `required_specialization`.
   * Track source (instance vs type) in `_router.reason`.

3. **Tool taxonomy registry**

   * Canonical naming (`domain.action.scope`) to unify RBAC, router scoring, and agent execution.

4. **Observability + replay**

   * Persist shortlist + scoring inputs.
   * Ability to replay a routing decision deterministically.

5. **Partial indexes for scale**

   * Keep `params.multimodal` partial index once multimodal volume grows (1M+ tasks).

---

## Appendix A: Minimal “Gold Standard” TaskPayload Example

```jsonc
{
  "type": "action",
  "description": "Person detected near Room 101",
  "params": {
    "interaction": {"mode": "coordinator_routed"},
    "routing": {
      "required_specialization": "SecurityMonitoring",
      "skills": {"threat_assessment": 0.9},
      "tools": ["alerts.raise", "sensors.read_all"],
      "routing_tags": ["security", "monitoring"],
      "hints": {"priority": 7, "ttl_seconds": 60}
    },
    "multimodal": {
      "source": "vision",
      "media_uri": "s3://.../camera_101.mp4",
      "confidence": 0.92,
      "location_context": "room_101_corridor"
    },
    "tool_calls": [
      {"name": "alerts.raise", "args": {"channel": "security_team", "msg": "Person near Room 101"}}
    ]
  }
}
```

---

**This is the living contract.** Extend it by adding new envelopes under `params.*` (e.g., `planning`, `policy`, `simulation`) while preserving isolation, precedence rules, and provenance.
