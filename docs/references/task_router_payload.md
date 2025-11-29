# ✅ Task Routing Payload Reference (TaskPayload v2)

This reference details the `TaskPayload` model, explaining how the `Task` row carries routing inputs, cognitive metadata, chat envelopes, interaction state, and execution telemetry—**without schema migrations**.

SeedCore leverages PostgreSQL `JSONB` to store high-evolution metadata:

* **Inputs:** `params` (JSONB)
* **Outputs:** `result.meta` (JSONB)

## Data Persistence Strategy

The `Task` ORM persists `params` as a flexible JSONB column.

```python
params: Mapped[Dict[str, Any]] = mapped_column(
    JSONB,
    nullable=False,
    default=dict,
    comment="Input parameters including interaction modes, cognitive flags, and Router inbox.",
)
```

**Architecture Benefits:**

* **Isolation:** Router input (`params.routing`), Router decision (`params._router`), and Cognitive settings (`params.cognitive`) are strictly isolated.
* **Indexing:** GIN indexes allow high-performance querying on nested fields (e.g., finding all tasks requiring specific skills).
* **Evolution:** New envelopes (e.g., `graph`, `planning`) can be added without table locks.

---

## 1. Interaction Envelope (`params.interaction`)

Controls **how** the task flows through the system topology.

```json
{
  "interaction": {
    "mode": "coordinator_routed",
    "conversation_id": "conv_123",
    "assigned_agent_id": null
  }
}
```

### Interaction Modes

| Mode | Behavior |
| :--- | :--- |
| **`coordinator_routed`** | **Default.** Task is sent to the Coordinator, scored, and routed to the best Organ/Agent. |
| **`agent_tunnel`** | **Bypasses Router.** Task is sent directly to `assigned_agent_id`. Used for low-latency chat. |
| **`one_shot`** | Stateless request/response. No memory hydration. |

**Critical Rule:** If `mode == "agent_tunnel"`, the **Router is skipped entirely**. The `params.routing` envelope is ignored.

---

## 2. Router Inbox (`params.routing`)

**Read-Only Input.** These are the signals the Router uses to select an Agent (when not in tunnel mode).

```json
{
  "routing": {
    "required_specialization": "GuestEmpathy",
    "specialization": "GeneralSupport",
    "skills": {
      "empathy": 0.9,
      "service_recovery": 0.7
    },
    "hints": {
      "priority": 5,
      "deadline_at": "2025-11-11T12:00:00Z",
      "ttl_seconds": 900
    },
    "tools": [
      {"name": "iot.read", "args": {"sensor": "thermostat", "room": 401}}
    ]
  }
}
```

### Field Semantics

* **`required_specialization`** (String, Optional): **HARD Constraint.** The target Organ *must* match this specialization.
* **`specialization`** (String, Optional): **SOFT Hint.** The router prefers this specialization but may fallback.
* **`skills`** (Dict[str, float]): Required skill levels (0.0 - 1.0). Used for scoring agents within an Organ.
* **`hints`** (Dict): Metadata for scheduling (priority, deadlines, TTL).
* **`tools`** (List): Definitions of tools the agent must be able to execute.

---

## 3. Router Output (`params._router`)

**Write-Only / System Generated.** The Router populates this after making a decision. Upstream components should not write to this.

```json
{
  "_router": {
    "is_high_stakes": true,
    "agent_id": "agent_GEA_02",
    "organ_id": "organ_guestcare",
    "reason": "Selected based on specialization match and availability"
  }
}
```

### Field Semantics

* `is_high_stakes` — Router's determination of high-stakes status (may differ from `params.risk.is_high_stakes`)
* `agent_id` — Selected agent identifier (also written to `result.meta.routing_decision.selected_agent_id`)
* `organ_id` — Selected organ identifier
* `reason` — Human-readable explanation of routing decision

---

## 4. Cognitive Metadata (`params.cognitive`)

Controls the reasoning engine, LLM selection, and memory I/O barriers.

```json
{
  "cognitive": {
    "agent_id": "agent_xyz",
    "cog_type": "chat",
    "decision_kind": "fast",
    "llm_provider_override": "openai",
    "llm_model_override": "gpt-4o-mini",
    "skip_retrieval": false,
    "disable_memory_write": false
  }
}
```

### Key Flags

* **`cog_type`**: `chat` (low latency), `task_planning` (multi-step), `hgnn` (deep reasoning).
* **`decision_kind`**: `fast` (direct LLM), `planner` (RAG+Plan).
* **`skip_retrieval`**: If `true`, the ContextBuilder skips vector/graph lookups (saving latency).
* **`disable_memory_write`**: If `true`, the interaction is **not** saved to episodic memory (e.g., for PII reasons or trivial chit-chat).

**Note:** The `agent_id` is typically populated after routing (from `params._router.agent_id`).

---

## 5. Chat Envelope (`params.chat`)

Used for all conversational tasks.

```json
{
  "chat": {
    "message": "User message",
    "history": [
      {"role": "user", "content": "Hi"},
      {"role": "assistant", "content": "Hello!"}
    ],
    "agent_persona": "Concierge with empathy",
    "style": "concise_conversational"
  }
}
```

**Note on History:**

* `conversation_history` (Top-Level) is maintained for **ChatSignature** compatibility.
* `params.chat.history` is the **internal windowed context** used by the Cognitive Engine.

---

## 6. Risk Envelope (`params.risk`)

Risk classification from upstream analysis.

**Important:** Risk is **NOT** a routing signal. Routing uses `skills` and `specialization`. Risk is used for audit trails and potentially forcing a "High Stakes" protocol in the Cognitive engine.

```json
{
  "risk": {
    "is_high_stakes": true,
    "score": 0.92,
    "severity": 0.8,
    "user_impact": 0.9,
    "business_criticality": 0.85
  }
}
```

---

## 7. Graph Envelope (`params.graph`)

Used when `TaskType.GRAPH` is active. This envelope dictates specific Graph RAG or maintenance operations.

```json
{
  "graph": {
    "kind": "rag_query",
    "collection": "policy_v2",
    "inputs": {
      "query_text": "check out time"
    },
    "config": {
      "top_k": 5
    }
  }
}
```

### Field Semantics

* **`kind`**: Maps 1:1 to `GraphOperationKind`.
* **`collection`**: The specific vector/graph partition to query.
* **`inputs`**: Payload required by the operation (query text, metadata filters, seed nodes).
* **`config`**: Optional hyperparameters (limits, score thresholds, vector toggles).

The router still honors the other envelopes (`risk`, `routing`, etc.), but when `type == "graph"` the dispatcher opens `params.graph` to identify the graph operation to execute.

---

## 8. Result Metadata (`result.meta`)

The source of truth for execution telemetry and decision provenance.

```json
{
  "routing_decision": {
    "selected_agent_id": "agent_GEA_02",
    "selected_organ_id": "organ_guestcare",
    "router_score": 0.87,
    "routed_at": "2025-11-11T11:11:11Z",
    "shortlist": [
      {"agent_id": "agent_GEA_02", "score": 0.87},
      {"agent_id": "agent_GEA_07", "score": 0.82}
    ]
  },
  "exec": {
    "started_at": "2025-11-11T11:12:00Z",
    "finished_at": "2025-11-11T11:12:35Z",
    "latency_ms": 350,
    "attempt": 1
  },
  "cognitive_trace": {
    "retrieval_scope": {
      "global_holons": ["hospitality_rules"],
      "organ_holons": ["guestcare_policies"],
      "entity_holons": ["guest_44520_profile"]
    },
    "episodic_fragments_used": 3,
    "chosen_model": "gpt-4o-mini",
    "decision_path": "FAST_PATH_CHAT"
  }
}
```

---

## Memory & Retrieval Scoping Rules

Memory behavior is determined by the `agent_id` context and cognitive flags.

| Context | Retrieval Scope | Memory Writes (Episodic) |
| :--- | :--- | :--- |
| **Coordinator** (`agent_id=None`) | **GLOBAL** Holons only | **Disabled** |
| **Agent** (`agent_id!=None`) | **GLOBAL + ORGAN + ENTITY** | **Enabled** (unless `disable_memory_write=true`) |

---

## Querying & Indexing

Your JSONB GIN index supports flexible queries. Recommended path indexes:

```sql
CREATE INDEX ix_tasks_params_routing_spec 
ON tasks USING gin ((params -> 'routing' ->> 'required_specialization'));

CREATE INDEX ix_tasks_params_routing_specialization 
ON tasks USING gin ((params -> 'routing' ->> 'specialization'));

CREATE INDEX ix_tasks_params_routing_skills 
ON tasks USING gin ((params -> 'routing' -> 'skills'));

CREATE INDEX ix_tasks_params_routing_priority 
ON tasks USING gin ((params #> '{routing,hints,priority}'));

CREATE INDEX ix_tasks_params_router_agent 
ON tasks USING gin ((params -> '_router' ->> 'agent_id'));

CREATE INDEX ix_tasks_params_router_high_stakes 
ON tasks USING gin ((params #> '{_router,is_high_stakes}'));

CREATE INDEX ix_tasks_params_risk_high_stakes 
ON tasks USING gin ((params #> '{risk,is_high_stakes}'));

-- Efficiently find all tasks performed by a specific agent
CREATE INDEX ix_tasks_result_selected_agent 
ON tasks USING gin ((result #> '{meta,routing_decision,selected_agent_id}'));

-- Efficiently query latency for SLA or debugging
CREATE INDEX ix_tasks_result_latency 
ON tasks USING gin ((result #> '{meta,exec,latency_ms}'));
```

---

# 🎉 Final: Comprehensive End-to-End Task Payload Example

This JSON represents a fully populated task moving through the system.

```jsonc
{
  "type": "chat",
  "task_id": "task_20251125_001",
  "description": "Guest requests late checkout",
  "domain": "hospitality.guest",

  // Top-level history for API/Signature compatibility
  "conversation_history": [
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello! How may I help you?"},
    {"role": "user", "content": "Can I check out at 2pm tomorrow?"}
  ],

  "params": {
    // ---------------------------------------------
    // 1. Interaction: Defines the flow topology
    // ---------------------------------------------
    "interaction": {
      "mode": "coordinator_routed", // Router will be engaged
      "conversation_id": "conv_44520",
      "assigned_agent_id": null     // To be determined by Router
    },

    // ---------------------------------------------
    // 2. Router Inbox: Requirements for the Router
    // ---------------------------------------------
    "routing": {
      "required_specialization": "GuestEmpathy", // Hard Constraint
      "specialization": "GuestEmpathy",          // Soft Hint
      "skills": {
        "empathy": 0.95,
        "policy_knowledge": 0.7
      },
      "hints": {
        "priority": 4,
        "deadline_at": "2025-11-26T14:00:00Z",
        "ttl_seconds": 1800
      },
      "tools": [
        { "name": "policy.lookup", "args": {"policy_name": "late_checkout"} }
      ]
    },

    // ---------------------------------------------
    // 3. Router Output (System Generated)
    // ---------------------------------------------
    "_router": {
      "is_high_stakes": false,
      "agent_id": "agent_guestcare_007",
      "organ_id": "organ_guestcare",
      "reason": "Matched required_specialization 'GuestEmpathy' with score 0.912"
    },

    // ---------------------------------------------
    // 4. Cognitive: Execution Parameters
    // ---------------------------------------------
    "cognitive": {
      "agent_id": "agent_guestcare_007", // Populated after routing
      "cog_type": "chat",
      "decision_kind": "fast",
      "llm_provider_override": "openai",
      "llm_model_override": "gpt-4o-mini",
      "skip_retrieval": false,
      "disable_memory_write": false,
      "force_rag": false,
      "force_deep_reasoning": false
    },

    // ---------------------------------------------
    // 5. Chat: Conversational Context
    // ---------------------------------------------
    "chat": {
      "message": "Can I check out at 2pm tomorrow?",
      "history": [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello! How may I help you?"}
      ],
      "agent_persona": "Professional hotel concierge with high empathy.",
      "style": "concise_conversational"
    },

    // ---------------------------------------------
    // 6. Risk: Upstream Classification
    // ---------------------------------------------
    "risk": {
      "is_high_stakes": false,
      "score": 0.31,
      "severity": 0.22,
      "user_impact": 0.35,
      "business_criticality": 0.40
    }
  },

  // ---------------------------------------------
  // 7. Result Metadata: Telemetry & Provenance
  // ---------------------------------------------
  "result": {
    "data": {
      "assistant_reply": "Certainly! Let me check the late checkout policy for your stay."
    },
    "meta": {
      "routing_decision": {
        "selected_agent_id": "agent_guestcare_007",
        "selected_organ_id": "organ_guestcare",
        "router_score": 0.912,
        "routed_at": "2025-11-25T10:11:45Z",
        "shortlist": [
          {"agent_id": "agent_guestcare_007", "score": 0.912},
          {"agent_id": "agent_guestcare_003", "score": 0.855}
        ]
      },
      "exec": {
        "started_at": "2025-11-25T10:11:50Z",
        "finished_at": "2025-11-25T10:11:53Z",
        "latency_ms": 3007,
        "attempt": 1
      },
      "cognitive_trace": {
        "retrieval_scope": {
          "global_holons": ["hospitality_rules"],
          "organ_holons": ["guestcare_policies"],
          "entity_holons": ["guest_44520_profile"]
        },
        "episodic_fragments_used": 3,
        "chosen_model": "gpt-4o-mini",
        "decision_path": "FAST_PATH_CHAT"
      }
    }
  }
}
```
