## Task Routing Payload Reference

This reference explains how `Task` rows and the in-memory `TaskPayload` model carry router inputs, decisions, and execution telemetry without introducing new database columns.

### Keep Data in JSONB

- All router inputs live under `params.routing`. The `Task` ORM already persists `params` as JSONB and exposes a GIN index for querying nested keys.

```params: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment=(
            "Input parameters including fast_eventizer outputs "
            "and Router inbox fields under params.routing"
        ),
    )
```

- Router decisions and execution metrics are recorded under `result.meta`, keeping result metadata versioned and queryable without schema churn.
- No schema migration is required; model helpers already push structured envelopes into `params` and `result`.

### Risk Envelope (`params.risk`)

High-stakes task classification comes from upstream cognitive analysis (Fast Eventizer or LLM Evaluator). The risk envelope is stored under `params.risk` (separate from routing metadata):

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

**Important:** High-stakes detection is **NOT** part of `params.routing` or routing hints. The `priority` field in routing hints is a soft hint for queue ordering and SLA, not a risk indicator.

The router detects high-stakes tasks by checking:
- `params.risk.is_high_stakes` (canonical source)
- `metadata.risk.is_high_stakes` (fallback if passed via metadata)

**Do NOT** use ad-hoc heuristics like `priority >= 8` or `task_info.high_stakes` - these are not part of the canonical TaskPayload contract.

### Interaction Mode (`params.interaction`)

The interaction envelope controls how tasks are routed and executed, particularly for conversational or agent-tunneled workflows:

```json
{
  "interaction": {
    "mode": "agent_tunnel",  // or "one_shot", "coordinator_routed"
    "conversation_id": "conv_123",
    "assigned_agent_id": "agent_xyz"
  }
}
```

**Interaction Modes:**

- `agent_tunnel`: Human ↔ Agent conversation with memory. Tasks are routed directly to the OrganismRouter, bypassing Coordinator for low-latency conversational flows. The assigned agent maintains conversation context.
  - **Cognitive Integration:** When `mode == "agent_tunnel"`, tasks are typically processed using `CognitiveType.CHAT` with `DecisionKind.FAST_PATH` for low-latency conversational responses.
  - **Conversation Context:** Conversation history should be passed via `params.chat.history` or top-level `conversation_history` field.
  - **Memory Architecture:** 
    - **PersistentAgent is the canonical maintainer of conversation history.** It writes chat history to MwManager (episodic memory) and maintains the conversation state.
    - **CognitiveCore does not persist chat history.** It is stateless and receives conversation history from PersistentAgent.
    - **CognitiveMemoryBridge hydrates chat history** before inference by retrieving episodic memory from MwManager, but PersistentAgent's conversation_history takes precedence when provided.
    - QueryTools must pass both `task_params["chat"]["history"] = conversation_history` and top-level `conversation_history` for ChatSignature compatibility.
  - **Example Payload:**
    ```json
    {
      "type": "chat",
      "task_id": "chat_123",
      "description": "User message here",
      "message": "User message here",
      "conversation_history": [
        {"role": "user", "content": "Previous message"},
        {"role": "assistant", "content": "Previous response"}
      ],
      "params": {
        "interaction": {
          "mode": "agent_tunnel",
          "conversation_id": "conv_123"
        },
        "cognitive": {
          "agent_id": "agent_xyz",
          "cog_type": "chat",
          "decision_kind": "fast"
        },
        "chat": {
          "message": "User message here",
          "history": [...],
          "agent_persona": "...",  // Agent personality/instructions for chat responses
          "style": "concise_conversational"  // Response style preference
        }
      }
    }
    ```
- `one_shot`: Single-turn task execution without conversation context.
- `coordinator_routed`: Default mode. Tasks go through Coordinator for scoring and decision-making before routing.

**Important:** When `mode == "agent_tunnel"`, the router bypasses Coordinator and routes directly to OrganismRouter for faster response times in conversational scenarios. The Cognitive Service will use `CognitiveType.CHAT` for these requests, providing lightweight conversational responses optimized for latency.

### Cognitive Metadata (`params.cognitive`)

The cognitive metadata envelope provides information for the Cognitive Service when tasks are processed through cognitive reasoning:

```json
{
  "cognitive": {
    "agent_id": "agent_xyz",
    "cog_type": "chat",  // or "task_planning", "problem_solving", etc.
    "decision_kind": "fast",  // or "planner", "hgnn"
    "llm_provider_override": "openai",  // optional
    "llm_model_override": "gpt-4o"  // optional
  }
}
```

**Cognitive Types (`cog_type`):**
- `chat`: Lightweight conversational path for agent-tunneled interactions
  - Automatically chosen when `params.interaction.mode == "agent_tunnel"`, but QueryTools may override when `force_deep_reasoning` or `force_rag` are set
  - **Retrieval behavior:** CHAT mode defaults to `skip_retrieval=True` for latency optimization, unless `force_rag=true` or `force_deep_reasoning=true` are set
  - **Memory hydration:** Uses only ORGAN-scope holons + episodic chat history (no GLOBAL holons unless in coordinator mode)
- `task_planning`: Decompose complex tasks into structured plans
- `problem_solving`: Generate multi-step solution plans
- `failure_analysis`: Analyze failures and propose solutions
- `decision_making`: Evaluate options and select best choice
- `memory_synthesis`: Synthesize insights from memory fragments
- `capability_assessment`: Assess agent capabilities and improvement plans
- Graph and fact operations: `graph_embed`, `graph_rag_query`, `fact_search`, etc.

**Decision Kinds (`decision_kind`):**
- `fast`: Fast path - direct execution without RAG retrieval
- `planner`: Cognitive path - includes RAG retrieval and planning
- `hgnn`: Escalated path - uses HGNN embeddings for deep context

**Important:** The `params.cognitive` namespace is the **standard location** for cognitive metadata. The Cognitive Service extracts `agent_id`, `cog_type`, and `decision_kind` from this namespace. Legacy top-level `meta.decision_kind` is still supported but deprecated.

**CognitiveCore Architecture:**
- **CognitiveCore is stateless.** All state (chat history, episodic traces, holons) comes from MemoryBridge + MwManager + HolonFabric.
- CognitiveCore does not persist conversation history; PersistentAgent maintains chat state.
- CognitiveMemoryBridge hydrates context before inference but does not store it.

### Cognitive Retrieval Scope Rules (MANDATORY)

**Critical:** CognitiveCore determines retrieval scope and memory writing behavior based on `agent_id`:

- **If `agent_id` is `None` (coordinator mode):**
  - Only **GLOBAL** holons are retrieved
  - Memory writing is **disabled** (no MwManager writes, no HolonFabric promotion)
  - No episodic chat history is hydrated
  - Used for coordinator-level tasks that don't belong to a specific agent

- **If `agent_id` is provided (agent mode):**
  - **ORGAN + ENTITY + GLOBAL** holons are retrieved (scoped retrieval via CognitiveMemoryBridge)
  - **Episodic chat history** is hydrated from MwManager
  - **Memory writing is enabled:**
    - MwManager writes episodic traces
    - HolonFabric promotion for long-term memory
    - MemoryEvent creation for provenance tracking
  - Used for agent-tunneled conversations and agent-specific cognitive tasks

**Architecture Note:** This scope-based retrieval ensures that agents only access memory scoped to their organ/entity, while coordinator tasks operate on global knowledge only. Memory writes only occur in agent mode to maintain proper attribution and scoping.

### Router Inbox (`params.routing`)

Populate the router-facing inputs as a structured subdocument:

```json
{
  "routing": {
    "required_specialization": "GuestEmpathy",
    "desired_skills": { "empathy": 0.9, "service_recovery": 0.7 },
    "tool_calls": [
      {"name": "iot.read", "args": {"sensor": "thermostat", "room": 401}},
      {"name": "iot.write", "args": {"device": "thermostat", "room": 401, "setpoint": 22.0}}
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

Suggested keys:

- `required_specialization` (`str`)
- `desired_skills` (`dict[str, float]`)
- `tool_calls` (`list[{name, args}]`)
- `hints` (`min_capability`, `max_mem_util`, `priority`, `deadline_at`, `ttl_seconds`)

### Router Decision (`result.meta.routing_decision`)

Persist router outcomes alongside the task result payload:

```json
{
  "meta": {
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
}
```

### Execution Metrics (`result.meta.exec`)

Track execution timing and attempt data without extra columns:

```json
{
  "meta": {
    "exec": {
      "started_at": "2025-11-11T11:12:00Z",
      "finished_at": "2025-11-11T11:12:35Z",
      "latency_ms": 350,
      "attempt": 1
    }
  }
}
```

### TaskPayload Helpers

`TaskPayload` exposes validators and helpers that normalize JSON inputs, unpack router envelopes, and guarantee that serialized payloads include the router structure.

**Chat Interaction Notes:**
- For chat interactions, `task_params.chat.*` is passed through TaskPayload unchanged.
- **TaskPayload does NOT manage conversation_history;** PersistentAgent maintains conversation state independently.
- The router layer is pure dispatch and does not write memory; only agents and CognitiveCore perform memory operations.

```72:104:src/seedcore/models/task_payload.py
    def to_db_params(self) -> Dict[str, Any]:
        """Return params with routing envelope injected under params['routing']."""
        p = dict(self.params or {})
        routing = p.get("routing", {})

        # Merge: top-level convenience -> routing envelope
        merged = {
            "required_specialization": self.required_specialization,
            "desired_skills": self.desired_skills or {},
            "tool_calls": [tc.model_dump() if isinstance(tc, ToolCallPayload) else tc for tc in self.tool_calls],
            "hints": {
                "min_capability": self.min_capability,
                "max_mem_util": self.max_mem_util,
                "priority": self.priority,
                "deadline_at": self.deadline_at,
                "ttl_seconds": self.ttl_seconds,
            },
            "v": 1,
        }

        # Keep any pre-existing keys (but top-level mirrors override)
        routing = {**routing, **{k: v for k, v in merged.items() if v is not None}}
        p["routing"] = routing
        return p
```

When writing back to the database call `model_dump()` (or `to_db_params()` / `to_db_row()` helpers) so that updated routing details are baked into `params`.

### Querying & Indexing

The base model already defines a broad JSONB GIN index. Add targeted path indexes for hot filters as needed.

```167:178:src/seedcore/models/task.py
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_tasks_attempts_nonneg"),
        Index("ix_tasks_status_runafter", "status", "run_after"),
        Index("ix_tasks_created_at_desc", "created_at"),
        Index("ix_tasks_type", "type"),
        Index("ix_tasks_domain", "domain"),
        Index("ix_tasks_params_gin", "params", postgresql_using="gin"),
        # Optional JSONB path indexes defined in migration 007_task_schema_enhancements.sql:
        #   ix_tasks_params_routing_spec
        #   ix_tasks_params_routing_priority
        #   ix_tasks_params_routing_deadline
    )
```

Recommended additions:

```sql
CREATE INDEX ix_tasks_params_routing_spec ON tasks
USING GIN ((params -> 'routing' ->> 'required_specialization'));

CREATE INDEX ix_tasks_params_routing_priority ON tasks
USING GIN ((params #> '{routing,hints,priority}'));

CREATE INDEX ix_tasks_params_routing_deadline ON tasks
USING GIN ((params #> '{routing,hints,deadline_at}'));

CREATE INDEX ix_tasks_params_skill_empathy ON tasks
USING GIN ((params #> '{routing,desired_skills,empathy}'));

CREATE INDEX ix_tasks_params_risk_high_stakes ON tasks
USING GIN ((params #> '{risk,is_high_stakes}'));

CREATE INDEX ix_tasks_params_risk_score ON tasks
USING GIN ((params #> '{risk,score}'));
```

### Workflow Summary

- **Upstream Cognitive Stage** (Fast Eventizer/LLM Evaluator) analyzes task and writes risk envelope to `params.risk`.
- Dispatcher constructs a `TaskPayload`, setting router fields on the model.
- Serialization pushes router information into `params.routing`; no extra columns.
- Router reads `params.routing` for agent selection, reads `params.risk.is_high_stakes` for high-stakes routing.
- Router writes decisions into `result.meta.routing_decision`.
- Agents/Coordinator record execution metrics under `result.meta.exec`.

### When to Consider Columns

Add dedicated columns only if query workloads demand it (for example ultra-hot filters on `selected_agent_id` or `latency_ms`). Until then, keep the schema lean and leverage JSONB path indexes for flexible evolution.

