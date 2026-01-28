# ✅ Task Routing Payload Reference (TaskPayload v2.5)

This reference details the `TaskPayload` model, explaining how the `Task` row carries routing inputs, cognitive metadata, chat envelopes, interaction state, execution telemetry, and **multimodal media references**—**without schema migrations**.

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
* **Evolution:** New envelopes (e.g., `graph`, `planning`, `multimodal`) can be added without table locks.
* **Multimodal:** Voice and Vision inputs are stored as metadata in `params.multimodal` while embeddings are stored in the dedicated `task_multimodal_embeddings` table (direct FK) for fast "Living System" response times. Graph embeddings use separate tables (`graph_embeddings_128`/`graph_embeddings_1024`) via `graph_node_map` for structural memory.

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
    "tools": ["iot.read", "policy.lookup"]
  }
}
```

### Field Semantics

* **`required_specialization`** (String, Optional): **HARD Constraint.** The target Organ *must* match this specialization.
* **`specialization`** (String, Optional): **SOFT Hint.** The router prefers this specialization but may fallback.
* **`skills`** (Dict[str, float]): Required skill levels (0.0 - 1.0). Used for scoring agents within an Organ.
* **`hints`** (Dict): Metadata for scheduling (priority, deadlines, TTL).
* **`tools`** (List[str]): Tool identifiers the agent must be able to execute (RBAC/scoring).

**Precedence rule:** instance `params.routing.*` overrides task-type defaults, which override organ defaults. When a hard constraint is sourced from defaults, the router should include that provenance in `_router.reason`.

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

**Rule:** if `_router.is_high_stakes != risk.is_high_stakes`, `_router.reason` should explain why.

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
* The ContextBuilder should never merge both unless explicitly requested.

---

## 5.5 Tool Calls (`params.tool_calls`)

Execution-time tool call requests live outside the router inbox.

```json
{
  "tool_calls": [
    {"name": "iot.read", "args": {"sensor": "thermostat", "room": 401}}
  ]
}
```

**Rule:** `params.routing.tools` is for *required tool capabilities*, not executable call objects.

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

## 8. Multimodal Envelope (`params.multimodal`) ⭐ v2.5

**New in v2.5.** Stores metadata for voice and vision inputs without requiring schema migrations. The actual media files are stored externally (e.g., S3), and embeddings are stored in the dedicated `task_multimodal_embeddings` table with direct foreign key to `tasks.id` for fast "Living System" response times. Graph embeddings (for knowledge graph tasks) are stored separately in `graph_embeddings_128` or `graph_embeddings_1024` via the `graph_node_map` indirection.

### TaskType Mapping for Multimodal

| Input Type | TaskType | Description |
| :--- | :--- | :--- |
| **Voice Command** | `CHAT` | Transcribed voice commands (e.g., "Turn off the lights") |
| **Security Camera Detection** | `ACTION` | Visual events requiring immediate action (e.g., "Person detected near Room 101") |
| **Automated Face Recognition** | `QUERY` | Visual queries for identification or verification |
| **Visual Scene Analysis** | `QUERY` | Deep reasoning about visual content |

### Voice Example

```json
{
  "type": "chat",
  "description": "Turn off the lights in the lobby",
  "params": {
    "multimodal": {
      "source": "voice",
      "media_uri": "s3://hotel-assets/audio/clip_99.wav",
      "transcription_engine": "whisper-v3",
      "transcription": "Turn off the lights in the lobby",
      "confidence": 0.98,
      "duration_seconds": 3.2,
      "language": "en-US",
      "location_context": "lobby_area_01",
      "is_real_time": true,
      "ttl_seconds": 300
    },
    "chat": {
      "message": "Turn off the lights in the lobby"
    }
  }
}
```

### Vision Example

```json
{
  "type": "action",
  "description": "Person detected near Room 101",
  "params": {
    "multimodal": {
      "source": "vision",
      "media_uri": "s3://hotel-assets/video/camera_101_20251125_143022.mp4",
      "scene_description": "Person detected near Room 101",
      "detection_engine": "yolo-v8",
      "confidence": 0.92,
      "detected_objects": [
        {
          "class": "person",
          "confidence": 0.92,
          "bbox": [100, 200, 150, 300],
          "attributes": {
            "estimated_age": "adult",
            "clothing_color": "dark"
          }
        },
        {
          "class": "door",
          "confidence": 0.87,
          "bbox": [50, 100, 200, 400]
        }
      ],
      "timestamp": "2025-11-25T14:30:22Z",
      "camera_id": "camera_101",
      "location_context": "room_101_corridor",
      "is_real_time": true,
      "ttl_seconds": 60,
      "parent_stream_id": "stream_camera_101_20251125"
    }
  }
}
```

### Field Semantics

* **`source`** (String, Required): `"voice"` or `"vision"` — identifies the media type.
* **`media_uri`** (String, Required): URI to the media file (S3, GCS, or local path). The system does not store the binary in the database.
* **`transcription_engine`** (String, Optional, Voice only): Engine used for transcription (e.g., `"whisper-v3"`, `"google-speech"`).
* **`transcription`** (String, Optional, Voice only): The transcribed text (also stored in `description` for compatibility).
* **`scene_description`** (String, Optional, Vision only): High-level description of the visual scene (also stored in `description`).
* **`detection_engine`** (String, Optional, Vision only): Object detection model used (e.g., `"yolo-v8"`, `"detr"`).
* **`detected_objects`** (List, Optional, Vision only): Array of detected objects with bounding boxes and confidence scores.
* **`confidence`** (Float, Optional): Overall confidence score (0.0 - 1.0) for the perception result.
* **`duration_seconds`** (Float, Optional, Voice only): Audio duration in seconds.
* **`language`** (String, Optional, Voice only): Detected or specified language code (e.g., `"en-US"`).
* **`timestamp`** (String, Optional, Vision only): ISO 8601 timestamp when the visual event occurred.
* **`camera_id`** (String, Optional, Vision only): Identifier for the camera/sensor that captured the image.
* **`location_context`** (String, Optional): Physical location context (e.g., `"lobby_area_01"`, `"room_101_corridor"`). **Critical:** This field should match the `label` or `node_id` in your Domain Knowledge Graph for instant entity lookups.
* **`is_real_time`** (Boolean, Optional): If `true`, the Coordinator should prioritize this task in the Kafka queue. Defaults to `false`.
* **`ttl_seconds`** (Integer, Optional): Time-to-live in seconds. For transient visual events (e.g., person passing by), the data may only be relevant for 60 seconds. Helps with automatic memory pruning. If not set, uses default task TTL.
* **`parent_stream_id`** (String, Optional, Vision only): For video streams, links individual task "frames" to a continuous stream ID for temporal reasoning. Enables tracking events across multiple frames.

### Embedding Storage Strategy

**Critical:** The `tasks` table stores **metadata only**. Embeddings are stored in separate tables with different architectures:

| Table | Purpose | Architecture | Link |
| :--- | :--- | :--- | :--- |
| **tasks** | Stores task metadata, `params.multimodal` envelope | Primary key: `id` (UUID) | - |
| **task_multimodal_embeddings** | Multimodal embeddings (voice, vision, sensor) | **Direct FK** to `tasks.id` | `task_id` → `tasks.id` |
| **graph_embeddings_128** | Graph structure embeddings (HGNN routing) | **Indirect** via `graph_node_map` | `node_id` (BIGINT) → `graph_node_map` → `tasks.id` |
| **graph_embeddings_1024** | Deep semantic embeddings (knowledge graph) | **Indirect** via `graph_node_map` | `node_id` (BIGINT) → `graph_node_map` → `tasks.id` |

**Architecture Distinction:**

* **Multimodal Embeddings** (`task_multimodal_embeddings`): 
  * Direct foreign key to `tasks(id)` for fast "Living System" response times
  * Used for perception events (voice commands, vision frames, sensor readings)
  * HNSW index for ultra-fast similarity search
  * Supports multiple modalities per task (`PRIMARY KEY (task_id, source_modality)`)

* **Graph Embeddings** (`graph_embeddings_128/1024`):
  * Linked through `graph_node_map` table (BIGINT node_id mapping)
  * Used for graph structure similarity (HGNN) and knowledge base queries
  * IVFFlat indexes for approximate nearest neighbor search
  * Part of the heterogeneous graph neural network (HGNN) architecture

**Unified Memory View for PKG/Coordinator:**

The system provides a unified view (`v_unified_cortex_memory`) that merges all three memory tiers:

```sql
-- Query the unified memory view (created by migration 017)
SELECT 
    id,
    category,
    content,
    memory_tier,  -- 'event_working' or 'knowledge_base'
    vector,
    metadata
FROM v_unified_cortex_memory
WHERE memory_tier = 'event_working'  -- Fast-path: only perception events
ORDER BY vector <=> '[0.1, 0.2, ...]'::vector  -- Vector similarity search
LIMIT 10;
```

**Memory Tiers:**

* **`event_working`**: Multimodal perception events (voice, vision, sensor) - "The Now"
* **`knowledge_base`**: Knowledge graph tasks and entities - "The Rules" and "The Context"

**Performance Optimization:** As your database reaches 1M+ tasks, the `t.params ? 'multimodal'` filter will become slow. Create a **Partial GIN Index** to make multimodal queries lightning-fast:

```sql
CREATE INDEX idx_tasks_multimodal_fast 
ON tasks USING GIN (params) 
WHERE (params ? 'multimodal');
```

This partial index only indexes rows that contain the `multimodal` key, dramatically reducing index size and improving query performance for multimodal tasks.

### Coordinator Logic Tips

**A. Perception Confidence (`confidence`)**

* **Auto-Escalation:** If `confidence < 0.7`, the Coordinator should automatically set `DecisionKind.COGNITIVE` (Deep Reasoning) rather than `FAST_PATH`.
* **Voice Quality:** For Voice tasks, Whisper's word-level confidence is a great indicator of whether the transcript is "hallucinated." Low confidence may indicate background noise or unclear speech.

**B. Spatial Context (`detected_objects` & `bbox`)**

* **Spatial Reasoning:** The `bbox` (Bounding Box) data enables spatial reasoning. For example, if the Coordinator sees a "Person" and a "Door" in the same frame, the PKG can infer "Entry/Exit" events.
* **Future Enhancement:** Consider adding a `spatial_relation` field in future versions to store relative distance (e.g., `"Person is 0.5m from Door"`).

**C. Location Context (`location_context`)**

* **Relational Glue:** This field should match the `label` or `node_id` in your **Domain Knowledge Graph**. When the Coordinator sees `location_context: "lobby_area_01"`, it can instantly pull the "Light Switch" entity IDs for that specific zone from the Graph.
* **Graph Integration:** Use this field to enrich routing decisions with location-specific policies and device registries.

**D. Real-Time Prioritization (`is_real_time`)**

* **Queue Priority:** When `is_real_time: true`, the Coordinator should prioritize this task in the Kafka queue, potentially bypassing normal scheduling delays.
* **Use Cases:** Security alerts, emergency voice commands, critical sensor readings.

**E. Temporal Reasoning (`parent_stream_id`)**

* **Stream Linking:** For video streams, use `parent_stream_id` to link individual task "frames" to a continuous stream ID. This enables tracking events across multiple frames and building temporal context.
* **Example:** Multiple detections from the same camera stream can be aggregated to understand movement patterns.

### Perception Flow

1. **Ingestion:** Local Kafka receives audio/video from sensors or UI.
2. **Perception (Eventizer):**
   * **Voice:** Transcribes to text using Whisper or similar. Extracts word-level confidence scores.
   * **Vision:** Generates scene description and object detections using YOLO/DETR. Computes bounding boxes and spatial relationships.
3. **Task Creation:** Insert into `tasks` table:
   * **type:** `TaskType.CHAT` (voice commands) or `TaskType.ACTION`/`TaskType.QUERY` (visual events).
   * **description:** The transcript or scene summary.
   * **params.multimodal:** Complete multimodal metadata including confidence scores, spatial data, and stream IDs.
   * **Multimodal Embedding:** Written to `task_multimodal_embeddings` table with direct FK to `tasks.id`:
     ```sql
     INSERT INTO task_multimodal_embeddings (task_id, emb, source_modality, model_version)
     VALUES (:task_id, :embedding_vector, 'voice'|'vision'|'sensor', :model_version);
     ```
   * **Graph Embedding (Optional):** If the task is part of the knowledge graph, also write to `graph_embeddings_1024` via `graph_node_map` for structural memory.
4. **Coordinator Processing:**
   * **Confidence Check:** If `confidence < 0.7`, escalate to `DecisionKind.COGNITIVE`.
   * **Location Enrichment:** Use `location_context` to pull relevant entities from Domain Knowledge Graph.
   * **Spatial Analysis:** Analyze `detected_objects` and `bbox` data for spatial reasoning (e.g., proximity to doors, devices).
   * **Queue Prioritization:** If `is_real_time: true`, prioritize in Kafka queue.
   * **Unified Memory Query:** Use `v_unified_cortex_memory` view for semantic search across all memory tiers.
5. **Routing:** Standard routing logic applies using `params.routing` and other envelopes, enriched with multimodal context.

---

## 9. Result Metadata (`result.meta`)

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

-- Multimodal indexes (v2.5)
CREATE INDEX ix_tasks_params_multimodal_source 
ON tasks USING gin ((params -> 'multimodal' ->> 'source'));

CREATE INDEX ix_tasks_params_multimodal_media_uri 
ON tasks USING gin ((params -> 'multimodal' ->> 'media_uri'));

CREATE INDEX ix_tasks_params_multimodal_location 
ON tasks USING gin ((params -> 'multimodal' ->> 'location_context'));

-- Efficiently find all voice tasks
CREATE INDEX ix_tasks_params_multimodal_voice 
ON tasks USING gin ((params #> '{multimodal,source}')) 
WHERE (params -> 'multimodal' ->> 'source') = 'voice';

-- Efficiently find all vision tasks
CREATE INDEX ix_tasks_params_multimodal_vision 
ON tasks USING gin ((params #> '{multimodal,source}')) 
WHERE (params -> 'multimodal' ->> 'source') = 'vision';

-- Performance optimization: Partial GIN index for multimodal queries (recommended for 1M+ tasks)
CREATE INDEX idx_tasks_multimodal_fast 
ON tasks USING GIN (params) 
WHERE (params ? 'multimodal');
```

---

# 🎉 Final: Comprehensive End-to-End Task Payload Examples

## Example 1: Standard Chat Task (v2.0)

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
      "tools": ["policy.lookup"]
    },

    // ---------------------------------------------
    // 3. Tool Calls: Execution Requests
    // ---------------------------------------------
    "tool_calls": [
      { "name": "policy.lookup", "args": {"policy_name": "late_checkout"} }
    ],

    // ---------------------------------------------
    // 4. Router Output (System Generated)
    // ---------------------------------------------
    "_router": {
      "is_high_stakes": false,
      "agent_id": "agent_guestcare_007",
      "organ_id": "organ_guestcare",
      "reason": "Matched required_specialization 'GuestEmpathy' with score 0.912"
    },

    // ---------------------------------------------
    // 5. Cognitive: Execution Parameters
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
    // 6. Chat: Conversational Context
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
    // 7. Risk: Upstream Classification
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
  // 8. Result Metadata: Telemetry & Provenance
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

---

## Example 2: Voice Command Task (v2.5) ⭐

This example shows a voice command task with multimodal metadata.

```jsonc
{
  "type": "chat",
  "task_id": "task_20251125_002",
  "description": "Turn off the lights in the lobby",
  "domain": "hospitality.guest",

  "conversation_history": [
    {"role": "user", "content": "Turn off the lights in the lobby"}
  ],

  "params": {
    // ---------------------------------------------
    // 1. Interaction: Defines the flow topology
    // ---------------------------------------------
    "interaction": {
      "mode": "coordinator_routed",
      "conversation_id": "conv_44520",
      "assigned_agent_id": null
    },

    // ---------------------------------------------
    // 2. Router Inbox: Requirements for the Router
    // ---------------------------------------------
    "routing": {
      "required_specialization": "IoTControl",
      "specialization": "IoTControl",
      "skills": {
        "iot_control": 0.9,
        "voice_understanding": 0.85
      },
      "hints": {
        "priority": 3,
        "ttl_seconds": 300
      },
      "tools": ["iot.control"]
    },

    // ---------------------------------------------
    // 3. Tool Calls: Execution Requests
    // ---------------------------------------------
    "tool_calls": [
      { "name": "iot.control", "args": {"device": "lights", "location": "lobby", "action": "off"} }
    ],

    // ---------------------------------------------
    // 4. Router Output (System Generated)
    // ---------------------------------------------
    "_router": {
      "is_high_stakes": false,
      "agent_id": "agent_iot_003",
      "organ_id": "organ_facilities",
      "reason": "Matched required_specialization 'IoTControl' with score 0.89"
    },

    // ---------------------------------------------
    // 5. Cognitive: Execution Parameters
    // ---------------------------------------------
    "cognitive": {
      "agent_id": "agent_iot_003",
      "cog_type": "chat",
      "decision_kind": "fast",
      "llm_provider_override": "openai",
      "llm_model_override": "gpt-4o-mini",
      "skip_retrieval": false,
      "disable_memory_write": false
    },

    // ---------------------------------------------
    // 6. Chat: Conversational Context
    // ---------------------------------------------
    "chat": {
      "message": "Turn off the lights in the lobby",
      "history": [],
      "agent_persona": "Efficient facility control assistant.",
      "style": "concise_conversational"
    },

    // ---------------------------------------------
    // 6. Risk: Upstream Classification
    // ---------------------------------------------
    "risk": {
      "is_high_stakes": false,
      "score": 0.15,
      "severity": 0.10,
      "user_impact": 0.20,
      "business_criticality": 0.15
    },

    // ---------------------------------------------
    // 8. Multimodal: Voice Metadata (v2.5)
    // ---------------------------------------------
    "multimodal": {
      "source": "voice",
      "media_uri": "s3://hotel-assets/audio/clip_99.wav",
      "transcription_engine": "whisper-v3",
      "transcription": "Turn off the lights in the lobby",
      "confidence": 0.98,
      "duration_seconds": 3.2,
      "language": "en-US",
      "location_context": "lobby_area_01",
      "is_real_time": true,
      "ttl_seconds": 300
    }
  },

  // ---------------------------------------------
  // 7. Result Metadata: Telemetry & Provenance
  // ---------------------------------------------
  "result": {
    "data": {
      "assistant_reply": "I've turned off the lights in the lobby.",
      "action_executed": {
        "device": "lights",
        "location": "lobby",
        "action": "off",
        "status": "success"
      }
    },
    "meta": {
      "routing_decision": {
        "selected_agent_id": "agent_iot_003",
        "selected_organ_id": "organ_facilities",
        "router_score": 0.89,
        "routed_at": "2025-11-25T10:15:30Z"
      },
      "exec": {
        "started_at": "2025-11-25T10:15:32Z",
        "finished_at": "2025-11-25T10:15:35Z",
        "latency_ms": 3200,
        "attempt": 1
      },
      "cognitive_trace": {
        "retrieval_scope": {
          "global_holons": ["iot_device_registry"],
          "organ_holons": ["facilities_policies"]
        },
        "chosen_model": "gpt-4o-mini",
        "decision_path": "FAST_PATH_CHAT"
      }
    }
  }
}
```

---

## Example 3: Vision Detection Task (v2.5) ⭐

This example shows a security camera detection task with vision metadata.

```jsonc
{
  "type": "action",
  "task_id": "task_20251125_003",
  "description": "Person detected near Room 101",
  "domain": "hospitality.security",

  "params": {
    // ---------------------------------------------
    // 1. Interaction: Defines the flow topology
    // ---------------------------------------------
    "interaction": {
      "mode": "coordinator_routed",
      "conversation_id": null,
      "assigned_agent_id": null
    },

    // ---------------------------------------------
    // 2. Router Inbox: Requirements for the Router
    // ---------------------------------------------
    "routing": {
      "required_specialization": "SecurityMonitoring",
      "specialization": "SecurityMonitoring",
      "skills": {
        "threat_assessment": 0.9,
        "visual_analysis": 0.85
      },
      "hints": {
        "priority": 7,
        "deadline_at": "2025-11-25T14:35:00Z",
        "ttl_seconds": 60
      }
    },

    // ---------------------------------------------
    // 3. Router Output (System Generated)
    // ---------------------------------------------
    "_router": {
      "is_high_stakes": true,
      "agent_id": "agent_security_001",
      "organ_id": "organ_security",
      "reason": "High-priority security event requiring immediate attention"
    },

    // ---------------------------------------------
    // 4. Cognitive: Execution Parameters
    // ---------------------------------------------
    "cognitive": {
      "agent_id": "agent_security_001",
      "cog_type": "task_planning",
      "decision_kind": "planner",
      "llm_provider_override": "openai",
      "llm_model_override": "gpt-4o",
      "skip_retrieval": false,
      "disable_memory_write": false
    },

    // ---------------------------------------------
    // 6. Risk: Upstream Classification
    // ---------------------------------------------
    "risk": {
      "is_high_stakes": true,
      "score": 0.85,
      "severity": 0.80,
      "user_impact": 0.90,
      "business_criticality": 0.95
    },

    // ---------------------------------------------
    // 8. Multimodal: Vision Metadata (v2.5)
    // ---------------------------------------------
    "multimodal": {
      "source": "vision",
      "media_uri": "s3://hotel-assets/video/camera_101_20251125_143022.mp4",
      "scene_description": "Person detected near Room 101",
      "detection_engine": "yolo-v8",
      "confidence": 0.92,
      "detected_objects": [
        {
          "class": "person",
          "confidence": 0.92,
          "bbox": [100, 200, 150, 300],
          "attributes": {
            "estimated_age": "adult",
            "clothing_color": "dark"
          }
        },
        {
          "class": "door",
          "confidence": 0.87,
          "bbox": [50, 100, 200, 400]
        }
      ],
      "timestamp": "2025-11-25T14:30:22Z",
      "camera_id": "camera_101",
      "location_context": "room_101_corridor"
    }
  },

  // ---------------------------------------------
  // 7. Result Metadata: Telemetry & Provenance
  // ---------------------------------------------
  "result": {
    "data": {
      "action_taken": "alert_sent",
      "alert_recipients": ["security_team", "front_desk"],
      "assessment": "Non-threatening individual, likely guest. Monitoring continued."
    },
    "meta": {
      "routing_decision": {
        "selected_agent_id": "agent_security_001",
        "selected_organ_id": "organ_security",
        "router_score": 0.95,
        "routed_at": "2025-11-25T14:30:25Z"
      },
      "exec": {
        "started_at": "2025-11-25T14:30:26Z",
        "finished_at": "2025-11-25T14:30:42Z",
        "latency_ms": 16000,
        "attempt": 1
      },
      "cognitive_trace": {
        "retrieval_scope": {
          "global_holons": ["security_protocols"],
          "organ_holons": ["security_policies"],
          "entity_holons": ["room_101_access_log"]
        },
        "episodic_fragments_used": 5,
        "chosen_model": "gpt-4o",
        "decision_path": "PLANNER_PATH_TASK_PLANNING"
      }
    }
  }
}
```
