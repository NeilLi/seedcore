from __future__ import annotations
from typing import Any, Dict, Optional, List
from enum import Enum
import json

from pydantic import BaseModel, Field, field_validator, model_validator  # pyright: ignore[reportMissingImports]

# If TaskType is defined elsewhere, keep the import. 
# Otherwise, un-comment the Enum definition below.
from seedcore.models.task import TaskType 

# class TaskType(str, Enum):
#     CHAT = "chat"
#     QUERY = "query"
#     ACTION = "action"
#     GRAPH = "graph"
#     MAINTENANCE = "maintenance"
#     UNKNOWN = "unknown"

class GraphOperationKind(str, Enum):
    EMBED = "embed"               # legacy + v2 graph embedding
    RAG = "rag_query"             # similarity search over embeddings
    FACT_EMBED = "fact_embed"     # embed fact nodes
    FACT_QUERY = "fact_query"     # fact-based similarity search
    NIM_EMBED = "nim_embed"       # NIM retrieval embedding (task texts)
    SYNC_NODES = "sync_nodes"     # maintenance / backfill
    UNKNOWN = "unknown"

# ========================================================================
#                           HELPER MODELS
# ========================================================================

class ToolCallPayload(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class RouterHints(BaseModel):
    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None

class RouterInbox(BaseModel):
    required_specialization: Optional[str] = None
    desired_skills: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)
    hints: RouterHints = Field(default_factory=RouterHints)
    v: int = 1

# ========================================================================
#                           MAIN TaskPayload
# ========================================================================

class TaskPayload(BaseModel):
    """
    Complete in-memory payload for dispatcher, routers, agents, and CognitiveCore.
    
    Design Philosophy:
    - "Lightweight Top-Level": Access key data directly (e.g., task.chat_message, task.graph_inputs).
    - "Structured Storage": Packs everything into specialized JSON envelopes in `params` for DB.
    
    Envelopes managed:
    - params.routing
    - params.chat
    - params.interaction
    - params.cognitive
    - params.graph (NEW)
    """

    # ------------------------------------------------------------------
    # CORE FIELDS
    # ------------------------------------------------------------------
    task_id: str
    type: str
    description: str = ""
    domain: Optional[str] = None
    drift_score: float = 0.0
    
    # The raw params bag (source of truth for DB)
    params: Dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # GRAPH ENVELOPE MIRRORS (→ params.graph.*)
    # ------------------------------------------------------------------
    # The specific operation kind (RAG, EMBED, FACT_QUERY, etc.)
    graph_kind: GraphOperationKind = GraphOperationKind.UNKNOWN
    # The target collection/index (e.g., "hotel_policy", "global_facts")
    graph_collection: Optional[str] = None
    # The input data (e.g., {"query": "...", "chunks": [...]})
    graph_inputs: Dict[str, Any] = Field(default_factory=dict)
    # Configuration (e.g., {"top_k": 5, "threshold": 0.7})
    graph_config: Dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # ROUTER MIRRORS (→ params.routing.*)
    # ------------------------------------------------------------------
    required_specialization: Optional[str] = None
    desired_skills: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)
    
    # Hints
    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None

    # ------------------------------------------------------------------
    # CHAT ENVELOPE MIRRORS (→ params.chat.*)
    # ------------------------------------------------------------------
    chat_message: Optional[str] = None
    chat_history: Optional[List[Dict[str, Any]]] = None
    chat_agent_persona: Optional[str] = None
    chat_style: Optional[str] = None

    # Top-level convenience for ChatSignature
    conversation_history: Optional[List[Dict[str, Any]]] = None
    skip_retrieval: Optional[bool] = None

    # ------------------------------------------------------------------
    # INTERACTION ENVELOPE MIRRORS (→ params.interaction.*)
    # ------------------------------------------------------------------
    interaction_mode: Optional[str] = None            # agent_tunnel, one_shot, coordinator_routed
    conversation_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None

    # ------------------------------------------------------------------
    # COGNITIVE METADATA MIRRORS (→ params.cognitive.*)
    # ------------------------------------------------------------------
    cognitive_agent_id: Optional[str] = None
    cog_type: Optional[str] = None                    # chat, task_planning, problem_solving
    decision_kind: Optional[str] = None               # fast, planner, hgnn

    llm_provider_override: Optional[str] = None
    llm_model_override: Optional[str] = None

    force_rag: Optional[bool] = None
    force_deep_reasoning: Optional[bool] = None

    # =====================================================================
    #                             VALIDATORS
    # =====================================================================

    @field_validator("params", mode="before")
    @classmethod
    def parse_params(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @field_validator("domain", mode="before")
    @classmethod
    def parse_domain(cls, v):
        return v or ""

    @model_validator(mode="after")
    def infer_legacy_graph_types(self):
        """
        Backward compatibility: If graph_kind is UNKNOWN but task type is GRAPH,
        try to guess the operation from legacy fields inside params.
        """
        if self.type != TaskType.GRAPH:
            return self

        if self.graph_kind != GraphOperationKind.UNKNOWN:
            return self

        # Check legacy params keys
        legacy_type = (
            self.params.get("_legacy_type")
            or self.params.get("type")
            or ""
        )
        lt = str(legacy_type).lower()

        if "nim" in lt:
            self.graph_kind = GraphOperationKind.NIM_EMBED
        elif "fact" in lt and "embed" in lt:
            self.graph_kind = GraphOperationKind.FACT_EMBED
        elif "fact" in lt and ("query" in lt or "rag" in lt):
            self.graph_kind = GraphOperationKind.FACT_QUERY
        elif "rag" in lt or "query" in lt:
            self.graph_kind = GraphOperationKind.RAG
        elif "sync" in lt:
            self.graph_kind = GraphOperationKind.SYNC_NODES
        elif "embed" in lt:
            self.graph_kind = GraphOperationKind.EMBED

        return self

    # =====================================================================
    #                 PACKING HELPERS → DB STRUCTURE (params JSONB)
    # =====================================================================
    def to_db_params(self) -> Dict[str, Any]:
        """
        Consolidates all top-level mirror fields into their respective 
        JSON envelopes inside the `params` dictionary.
        """
        # Start with existing params (preserve unrelated keys like 'risk')
        p = dict(self.params or {})

        # 1. GRAPH ENVELOPE
        if self.graph_kind != GraphOperationKind.UNKNOWN:
            graph_env = {
                "kind": self.graph_kind.value,
                "collection": self.graph_collection,
                "inputs": self.graph_inputs,
                "config": self.graph_config
            }
            # Remove None values
            p["graph"] = {k: v for k, v in graph_env.items() if v is not None}

        # 2. ROUTING ENVELOPE
        merged_routing = {
            "required_specialization": self.required_specialization,
            "desired_skills": self.desired_skills or {},
            "tool_calls": [
                tc.model_dump() if isinstance(tc, ToolCallPayload) else tc
                for tc in self.tool_calls
            ],
            "hints": {
                "min_capability": self.min_capability,
                "max_mem_util": self.max_mem_util,
                "priority": self.priority,
                "deadline_at": self.deadline_at,
                "ttl_seconds": self.ttl_seconds,
            },
            "v": 1,
        }
        # Merge with existing routing data if present
        current_routing = p.get("routing", {})
        p["routing"] = {
            **current_routing, 
            **{k: v for k, v in merged_routing.items() if v is not None}
        }

        # 3. CHAT ENVELOPE
        chat_env = {
            "message": self.chat_message,
            "history": self.chat_history,
            "agent_persona": self.chat_agent_persona,
            "style": self.chat_style,
        }
        chat_clean = {k: v for k, v in chat_env.items() if v is not None}
        if chat_clean:
            p["chat"] = chat_clean

        # 4. INTERACTION ENVELOPE
        interaction_env = {
            "mode": self.interaction_mode,
            "conversation_id": self.conversation_id,
            "assigned_agent_id": self.assigned_agent_id,
        }
        interaction_clean = {k: v for k, v in interaction_env.items() if v is not None}
        if interaction_clean:
            p["interaction"] = interaction_clean

        # 5. COGNITIVE ENVELOPE
        cognitive_env = {
            "agent_id": self.cognitive_agent_id,
            "cog_type": self.cog_type,
            "decision_kind": self.decision_kind,
            "llm_provider_override": self.llm_provider_override,
            "llm_model_override": self.llm_model_override,
            "force_rag": self.force_rag,
            "force_deep_reasoning": self.force_deep_reasoning,
        }
        cognitive_clean = {k: v for k, v in cognitive_env.items() if v is not None}
        if cognitive_clean:
            p["cognitive"] = cognitive_clean

        # 6. LEGACY / TOP-LEVEL KEYS
        if self.conversation_history:
            p["conversation_history"] = self.conversation_history
        if self.skip_retrieval is not None:
            p["skip_retrieval"] = self.skip_retrieval

        return p

    # =====================================================================
    #                       DB EXPORTERS
    # =====================================================================
    
    def to_db_row(self) -> Dict[str, Any]:
        """
        [NEW] Creates the exact dictionary required to INSERT/UPDATE into the 'tasks' table.
        Maps the internal 'task_id' back to the DB column 'id' and packs all envelopes into 'params'.
        
        Returns:
            Dict matching columns: id, type, description, domain, drift_score, params
        """
        return {
            "id": self.task_id,
            "type": self.type,
            "description": self.description,
            "domain": self.domain,
            "drift_score": self.drift_score,
            # This is the critical step: Pack all flat fields into the JSONB params
            "params": self.to_db_params() 
        }

    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        """
        API/Internal serialization. 
        Ensures 'params' is fully populated, but keeps top-level convenience fields for REST APIs.
        """
        as_dict = super().model_dump(*args, **kwargs)
        as_dict["params"] = self.to_db_params()
        return as_dict

    # =====================================================================
    #                       DB → TaskPayload LOADER
    # =====================================================================
    @classmethod
    def from_db(cls, row: Dict[str, Any]) -> "TaskPayload":
        """
        Factory method to create a TaskPayload from a raw DB row.
        Unpacks all envelopes from 'params' into top-level fields.
        """
        params = row.get("params") or {}

        # --- Unpack Routing ---
        routing = params.get("routing") or {}
        hints = routing.get("hints") or {}
        tool_calls_raw = routing.get("tool_calls") or []
        tool_calls = [
            (tc if isinstance(tc, ToolCallPayload) else ToolCallPayload(**tc))
            for tc in tool_calls_raw
            if isinstance(tc, (dict, ToolCallPayload))
        ]

        # --- Unpack Graph ---
        graph = params.get("graph") or {}
        # Convert string kind to Enum safe
        g_kind_str = graph.get("kind", "unknown")
        try:
            g_kind = GraphOperationKind(g_kind_str)
        except ValueError:
            g_kind = GraphOperationKind.UNKNOWN

        # --- Unpack Chat ---
        chat = params.get("chat") or {}

        # --- Unpack Interaction ---
        interaction = params.get("interaction") or {}

        # --- Unpack Cognitive ---
        cognitive = params.get("cognitive") or {}

        return cls(
            # Core
            task_id=str(row.get("id") or row.get("task_id")),
            type=row.get("type") or row.get("task_type") or "unknown_task",
            description=row.get("description") or "",
            domain=row.get("domain"),
            drift_score=float(row.get("drift_score") or 0.0),
            params=params,

            # Graph Mirrors
            graph_kind=g_kind,
            graph_collection=graph.get("collection"),
            graph_inputs=graph.get("inputs") or {},
            graph_config=graph.get("config") or {},

            # Router Mirrors
            required_specialization=routing.get("required_specialization"),
            desired_skills=routing.get("desired_skills") or {},
            tool_calls=tool_calls,
            min_capability=hints.get("min_capability"),
            max_mem_util=hints.get("max_mem_util"),
            priority=int(hints.get("priority") or 0),
            deadline_at=hints.get("deadline_at"),
            ttl_seconds=hints.get("ttl_seconds"),

            # Chat Mirrors
            chat_message=chat.get("message"),
            chat_history=chat.get("history"),
            chat_agent_persona=chat.get("agent_persona"),
            chat_style=chat.get("style"),

            # Interaction Mirrors
            interaction_mode=interaction.get("mode"),
            conversation_id=interaction.get("conversation_id"),
            assigned_agent_id=interaction.get("assigned_agent_id"),

            # Cognitive Mirrors
            cognitive_agent_id=cognitive.get("agent_id"),
            cog_type=cognitive.get("cog_type"),
            decision_kind=cognitive.get("decision_kind"),
            llm_provider_override=cognitive.get("llm_provider_override"),
            llm_model_override=cognitive.get("llm_model_override"),
            force_rag=cognitive.get("force_rag"),
            force_deep_reasoning=cognitive.get("force_deep_reasoning"),

            # Legacy / Top-level
            conversation_history=params.get("conversation_history"),
            skip_retrieval=params.get("skip_retrieval"),
        )