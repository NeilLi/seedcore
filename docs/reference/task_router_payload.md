* The **new full TaskPayload v2 envelope model**
* The clarified **chat**, **interaction**, and **cognitive** envelopes
* The distinction between **router inbox vs cognitive envelopes**
* Correct memory semantics
* Correct conversational rules
* AND a **final, comprehensive, end-to-end task payload example** that includes *every field* your system supports.

This is now ready to drop directly into your docs.

---

# ✅ **Task Routing Payload Reference (Updated for TaskPayload v2)**

This reference explains how the `Task` row and the in-memory `TaskPayload` model carry routing inputs, cognitive metadata, chat envelopes, interaction state, and execution telemetry — **all without schema migrations**.

SeedCore stores everything under:

```
params (JSONB)
result.meta (JSONB)
```

This enables high-evolution metadata flows without column churn.

---

# ## Keep Data in JSONB

The `Task` ORM persists `params` as JSONB:

```python
params: Mapped[Dict[str, Any]] = mapped_column(
    JSONB,
    nullable=False,
    default=dict,
    comment="Input parameters including fast_eventizer outputs and Router inbox fields under params.routing",
)
```

### Why JSONB?

* Flexible evolution (new envelopes for chat, cognitive, planning)
* No schema changes when enriching agent metadata
* GIN indexes allow deep nested queries
* Clean isolation: router metadata stays in `params.routing`, cognitive metadata in `params.cognitive`, etc.

Router decisions and execution metrics remain under:

```
result.meta.routing_decision
result.meta.exec
```

---

# ## Risk Envelope (`params.risk`)

Risk classification comes from upstream cognitive analysis:

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

### Key Rules

* **Risk is NOT part of routing.**
  Routing uses: specialization, skills, hints — not risk.

* Router determines high-stakes via:

  * `params.risk.is_high_stakes`
  * or fallback: `metadata.risk.is_high_stakes`

* Priority is **not a risk flag**.
  Do not use `priority >= X` as a proxy.

---

# ## Interaction Envelope (`params.interaction`)

Controls *how* the task flows through the system.

```json
{
  "interaction": {
    "mode": "agent_tunnel",
    "conversation_id": "conv_123",
    "assigned_agent_id": "agent_xyz"
  }
}
```

### Interaction Modes

| Mode                   | Behavior                                                          |
| ---------------------- | ----------------------------------------------------------------- |
| **agent_tunnel**       | Bypasses Coordinator → direct to OrganismRouter, low-latency chat |
| **one_shot**           | Stateless request/response                                        |
| **coordinator_routed** | Goes through Coordinator scoring (default)                        |

### Agent-Tunnel Mode

When `mode == "agent_tunnel"`:

* Router bypassed
* Task routed directly to assigned agent
* Cognitive executes in **CHAT + FAST_PATH** mode
* Retrieval defaults to `skip_retrieval=True`
* PersistentAgent injects conversation history
* MwManager writes episodic memory
* HolonFabric promotes long-term memory where applicable

---

# ## Chat Envelope (`params.chat`)

Used for all conversational tasks:

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

### Notes

* `history` is a **windowed** conversation context (PersistentAgent decides the window size).
* `conversation_history` may also appear **top-level** for ChatSignature compatibility.
* CognitiveCore is stateless — it receives history but does not store it.
* PersistentAgent manages *persistent* episodic chat history.

---

# ## Cognitive Metadata (`params.cognitive`)

Controls the reasoning path and memory rules.

```json
{
  "cognitive": {
    "agent_id": "agent_xyz",
    "cog_type": "chat",
    "decision_kind": "fast",
    "llm_provider_override": "openai",
    "llm_model_override": "gpt-4o-mini",
    "force_rag": false,
    "force_deep_reasoning": false
  }
}
```

### Cognitive Types

* **chat** → low latency, skip retrieval unless overridden
* **task_planning** → decomposes tasks into steps
* **problem_solving** → multi-step reasoning
* **hgnn** → HGNN deep semantic reasoning
* **fact_search**, **graph_rag_query**, **graph_embed** (graph operations)

### Decision Kinds

* **fast** → direct LLM call, no retrieval
* **planner** → RAG + step planning
* **hgnn** → deep HGNN context retrieval + reasoning

---

# ## Cognitive Retrieval Scope Rules (MANDATORY)

Retrieval & memory write rules depend strictly on **agent_id**:

### If `agent_id == None` (Coordinator Mode)

* Retrieve: **GLOBAL** holons only
* Skip episodic hydration
* Memory writes disabled
* Used for global coordinator tasks

### If `agent_id != None` (Agent Mode)

* Retrieve: **ORGAN + ENTITY + GLOBAL** holons
* Hydrate episodic chat history
* Memory writes enabled

  * MwManager episodic writes
  * HolonFabric long-term memory promotion
  * MemoryEvent provenance entries

This ensures correct **memory scoping** per agent.

---

# ## Router Inbox (`params.routing`)

Router-facing metadata:

```json
{
  "routing": {
    "required_specialization": "GuestEmpathy",
    "desired_skills": {
      "empathy": 0.9,
      "service_recovery": 0.7
    },
    "tool_calls": [
      {"name": "iot.read", "args": {"sensor": "thermostat", "room": 401}}
    ],
    "hints": {
      "min_capability": 0.6,
      "max_mem_util": 0.8,
      "priority": 5,
      "deadline_at": "2025-11-11T12:00:00Z",
      "ttl_seconds": 900
    },
    "v": 1
  }
}
```

These are the **only fields** the router reads.

---

# ## Router Decision (`result.meta.routing_decision`)

```json
{
  "routing_decision": {
    "selected_agent_id": "agent_GEA_02",
    "router_score": 0.87,
    "routed_at": "2025-11-11T11:11:11Z",
    "shortlist": [
      {"agent_id": "agent_GEA_02", "score": 0.87},
      {"agent_id": "agent_GEA_07", "score": 0.82}
    ]
  }
}
```

---

# ## Execution Metrics (`result.meta.exec`)

```json
{
  "exec": {
    "started_at": "2025-11-11T11:12:00Z",
    "finished_at": "2025-11-11T11:12:35Z",
    "latency_ms": 350,
    "attempt": 1
  }
}
```

---

# ## TaskPayload Serialization Rules

* All routing metadata is injected under `params.routing`.
* All chat metadata is injected under `params.chat`.
* All cognitive metadata is injected under `params.cognitive`.
* All interaction metadata is injected under `params.interaction`.
* `conversation_history` may appear both:

  * top-level
  * under `params.chat.history`

---

# ## Querying & Indexing

Your JSONB GIN index supports flexible queries. Recommended path indexes:

```sql
CREATE INDEX ix_tasks_params_routing_spec 
ON tasks USING gin ((params -> 'routing' ->> 'required_specialization'));

CREATE INDEX ix_tasks_params_routing_priority 
ON tasks USING gin ((params #> '{routing,hints,priority}'));

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

# # 🎉 FINAL: Comprehensive End-to-End Task Payload Example

This example includes **EVERY envelope** used by SeedCore:

---

# ✅ **Full Unified Task Payload (Everything Included)**

```jsonc
{
  "type": "chat",
  "task_id": "task_20251125_001",
  "description": "Guest requests late checkout",
  "domain": "hospitality.guest",

  // Top-level convenience for ChatSignature
  "conversation_history": [
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello! How may I help you?"},
    {"role": "user", "content": "Can I check out at 2pm tomorrow?"}
  ],

  "params": {
    // --------------------
    // 1. Risk Envelope
    // --------------------
    "risk": {
      "is_high_stakes": false,
      "score": 0.31,
      "severity": 0.22,
      "user_impact": 0.35,
      "business_criticality": 0.40
    },

    // --------------------
    // 2. Chat Envelope
    // --------------------
    "chat": {
      "message": "Can I check out at 2pm tomorrow?",
      "history": [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello! How may I help you?"},
        {"role": "user", "content": "Can I check out at 2pm tomorrow?"}
      ],
      "agent_persona": "Professional hotel concierge with high empathy.",
      "style": "concise_conversational"
    },

    // --------------------
    // 3. Interaction Envelope
    // --------------------
    "interaction": {
      "mode": "agent_tunnel",
      "conversation_id": "conv_44520",
      "assigned_agent_id": "agent_guestcare_007"
    },

    // --------------------
    // 4. Cognitive Envelope
    // --------------------
    "cognitive": {
      "agent_id": "agent_guestcare_007",
      "cog_type": "chat",
      "decision_kind": "fast",
      "llm_provider_override": "openai",
      "llm_model_override": "gpt-4o-mini",
      "force_rag": false,
      "force_deep_reasoning": false
    },

    // --------------------
    // 5. Router Inbox
    // --------------------
    "routing": {
      "required_specialization": "GuestEmpathy",
      "desired_skills": {
        "empathy": 0.95,
        "policy_knowledge": 0.7
      },
      "tool_calls": [
        {
          "name": "policy.lookup",
          "args": {"policy_name": "late_checkout"}
        }
      ],
      "hints": {
        "min_capability": 0.65,
        "max_mem_util": 0.80,
        "priority": 4,
        "deadline_at": "2025-11-26T14:00:00Z",
        "ttl_seconds": 1800
      },
      "v": 1
    }
  },

  // --------------------
  // 6. Result Metadata
  // --------------------
  "result": {
    "data": {
      "assistant_reply": "Certainly! Let me check the late checkout policy for your stay."
    },
    "meta": {
      "routing_decision": {
        "selected_agent_id": "agent_guestcare_007",
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
