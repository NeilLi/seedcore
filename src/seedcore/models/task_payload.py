from __future__ import annotations
from typing import Any, Dict, Optional, List
from enum import Enum
import json
import logging
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)
# from seedcore.models.task import TaskType

# ------------------------------------------------------------------------
# ENUMS & CONSTANTS
# ------------------------------------------------------------------------

class GraphOperationKind(str, Enum):
    EMBED = "embed"
    RAG = "rag_query"
    FACT_EMBED = "fact_embed"
    FACT_QUERY = "fact_query"
    NIM_EMBED = "nim_embed"
    SYNC_NODES = "sync_nodes"
    UNKNOWN = "unknown"

# ------------------------------------------------------------------------
# HELPER MODELS
# ------------------------------------------------------------------------

class ToolCallPayload(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)

class RouterHints(BaseModel):
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None
    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None

# ------------------------------------------------------------------------
# MAIN TaskPayload MODEL
# ------------------------------------------------------------------------

class TaskPayload(BaseModel):
    """
    The definitive TaskPayload v2 model.
    
    Acts as a high-level mirror for the JSONB 'params' column.
    Use .to_db_row() to generate the dict for SQL INSERT/UPDATE.
    Use .from_db(row) to hydrate from SQL.
    """

    # --- CORE FIELDS ---
    task_id: str
    type: str
    description: str = ""
    domain: Optional[str] = None
    drift_score: float = 0.0
    correlation_id: Optional[str] = None
    snapshot_id: Optional[int] = None  # PKG snapshot reference for snapshot-aware operations
    
    # The source-of-truth JSONB container
    params: Dict[str, Any] = Field(default_factory=dict)

    # ====================================================================
    #                        ENVELOPE MIRRORS
    # These fields flatten the nested 'params' structure for easy access.
    # ====================================================================

    # --- 1. INTERACTION ENVELOPE (params.interaction) ---
    interaction_mode: Optional[str] = None          # coordinator_routed, agent_tunnel, one_shot
    conversation_id: Optional[str] = None
    assigned_agent_id: Optional[str] = None         # Pre-assigned agent (e.g. tunnel)

    # --- 2. ROUTER INBOX (params.routing) ---
    required_specialization: Optional[str] = None  # HARD constraint
    specialization: Optional[str] = None           # SOFT hint
    skills: Dict[str, float] = Field(default_factory=dict)
    
    # Hints (flattened)
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None
    
    tools: List[ToolCallPayload] = Field(default_factory=list)

    # --- 3. COGNITIVE METADATA (params.cognitive) ---
    agent_id: Optional[str] = None        # The agent actually executing the task
    cog_type: Optional[str] = None                  # chat, task_planning, hgnn
    decision_kind: Optional[str] = None             # fast, planner
    
    llm_provider_override: Optional[str] = None
    llm_model_override: Optional[str] = None
    
    skip_retrieval: Optional[bool] = None     # Performance flag
    disable_memory_write: Optional[bool] = None # Privacy/Episodic flag
    
    force_rag: Optional[bool] = None
    force_deep_reasoning: Optional[bool] = None
    force_fast: Optional[bool] = None
    
    workflow: Optional[str] = None  # Explicit internal override for workflow execution

    # --- 4. CHAT ENVELOPE (params.chat) ---
    chat_message: Optional[str] = None
    chat_history: Optional[List[Dict[str, Any]]] = None
    chat_agent_persona: Optional[str] = None
    chat_style: Optional[str] = None

    # --- 5. GRAPH ENVELOPE (params.graph) ---
    graph_kind: GraphOperationKind = GraphOperationKind.UNKNOWN
    graph_collection: Optional[str] = None
    graph_inputs: Dict[str, Any] = Field(default_factory=dict)
    graph_config: Dict[str, Any] = Field(default_factory=dict)

    # --- LEGACY / COMPATIBILITY ---
    conversation_history: Optional[List[Dict[str, Any]]] = None # Top-level signature

    # ====================================================================
    #                             VALIDATORS
    # ====================================================================

    @field_validator("params", mode="before")
    @classmethod
    def parse_params(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @model_validator(mode="after")
    def auto_generate_ids(self):
        if not self.correlation_id:
            self.correlation_id = uuid4().hex
        return self

    @model_validator(mode="after")
    def infer_legacy_graph_types(self):
        """Backwards compatibility for older graph tasks without explicit 'kind'."""
        if self.type != "graph": # String comparison safer if Enum missing
            return self
        if self.graph_kind != GraphOperationKind.UNKNOWN:
            return self

        # Heuristic detection from params
        legacy_type = str(self.params.get("_legacy_type") or self.params.get("type") or "").lower()
        
        if "nim" in legacy_type:
            self.graph_kind = GraphOperationKind.NIM_EMBED
        elif "fact" in legacy_type and "embed" in legacy_type:
            self.graph_kind = GraphOperationKind.FACT_EMBED
        elif "fact" in legacy_type:
            self.graph_kind = GraphOperationKind.FACT_QUERY
        elif "rag" in legacy_type or "query" in legacy_type:
            self.graph_kind = GraphOperationKind.RAG
        elif "embed" in legacy_type:
            self.graph_kind = GraphOperationKind.EMBED
            
        return self

    @model_validator(mode="after")
    def sync_cognitive_agent(self):
        """
        Syncs cognitive.agent_id with params._router.agent_id.
        This ensures cognitive.agent_id is always populated after routing.
        """
        router_output = self.params.get("_router") or {}
        router_agent_id = router_output.get("agent_id")
        
        if router_agent_id and not self.agent_id:
            self.agent_id = router_agent_id
        
        return self

    # ====================================================================
    #                       PACKING (Model -> DB)
    # ====================================================================

    def to_db_params(self) -> Dict[str, Any]:
        """
        Constructs the authoritative JSONB structure for the DB.
        Merges existing 'params' with the specific mirrors.
        """
        # Start with existing params to preserve unmapped fields (like 'risk')
        p = dict(self.params or {})

        # 1. INTERACTION
        interaction_env = {
            "mode": self.interaction_mode,
            "conversation_id": self.conversation_id,
            "assigned_agent_id": self.assigned_agent_id,
        }
        # Only write non-nulls to keep JSON clean
        interaction_dict = {k: v for k, v in interaction_env.items() if v is not None}
        if interaction_dict:
            p["interaction"] = interaction_dict
        elif "interaction" in p:
            p.pop("interaction")

        # 2. ROUTING
        # Note: We prioritize specialized fields over generic ones
        routing_env = {
            "required_specialization": self.required_specialization, # Hard
            "specialization": self.specialization,                   # Soft
            "skills": self.skills or {},
            "tools": [
                tc.model_dump() if hasattr(tc, 'model_dump') else tc
                for tc in self.tools
            ],
            "hints": {
                "priority": self.priority,
                "deadline_at": self.deadline_at,
                "ttl_seconds": self.ttl_seconds,
            }
        }
        # Merge carefully to avoid wiping existing routing data not in mirror
        existing_routing = p.get("routing", {})
        # Filter out None values and empty collections
        new_routing_data = {k: v for k, v in routing_env.items() if v is not None}
        # Clean up hints dict - only remove if all values are None (priority=0 is valid)
        if "hints" in new_routing_data:
            hints = new_routing_data["hints"]
            if all(v is None for v in hints.values()):
                new_routing_data.pop("hints")
        # Clean up empty skills dict
        if "skills" in new_routing_data and not new_routing_data["skills"]:
            new_routing_data.pop("skills")
        # Clean up empty tools list
        if "tools" in new_routing_data and not new_routing_data["tools"]:
            new_routing_data.pop("tools")
        
        merged_routing = {**existing_routing, **new_routing_data}
        if merged_routing:
            p["routing"] = merged_routing
        elif "routing" in p:
            p.pop("routing")

        # 3. COGNITIVE
        cognitive_env = {
            "agent_id": self.agent_id,
            "cog_type": self.cog_type,
            "decision_kind": self.decision_kind,
            "llm_provider_override": self.llm_provider_override,
            "llm_model_override": self.llm_model_override,
            "skip_retrieval": self.skip_retrieval,
            "disable_memory_write": self.disable_memory_write,
            "force_rag": self.force_rag,
            "force_deep_reasoning": self.force_deep_reasoning,
            "force_fast": self.force_fast,
            "workflow": self.workflow,
        }
        cognitive_dict = {k: v for k, v in cognitive_env.items() if v is not None}
        if cognitive_dict:
            p["cognitive"] = cognitive_dict
        elif "cognitive" in p:
            p.pop("cognitive")

        # 4. CHAT
        chat_env = {
            "message": self.chat_message,
            "history": self.chat_history,
            "agent_persona": self.chat_agent_persona,
            "style": self.chat_style,
        }
        chat_dict = {k: v for k, v in chat_env.items() if v is not None}
        if chat_dict:
            p["chat"] = chat_dict
        elif "chat" in p:
            p.pop("chat")

        # 5. GRAPH
        if self.graph_kind != GraphOperationKind.UNKNOWN:
            graph_dict = {
                "kind": self.graph_kind.value,
                "collection": self.graph_collection,
                "inputs": self.graph_inputs,
                "config": self.graph_config
            }
            # Remove None values and empty dicts
            graph_dict = {k: v for k, v in graph_dict.items() if v is not None}
            if graph_dict:
                p["graph"] = graph_dict
            elif "graph" in p:
                p.pop("graph")
        elif "graph" in p:
            p.pop("graph")

        # 6. TOP LEVEL COMPATIBILITY
        if self.conversation_history:
            p["conversation_history"] = self.conversation_history

        return p

    def to_db_row(self) -> Dict[str, Any]:
        """
        Returns the exact dict for SQL Alchemy / SQL Insert.
        """
        return {
            "id": self.task_id,
            "type": self.type,
            "description": self.description,
            "domain": self.domain,
            "drift_score": self.drift_score,
            "snapshot_id": self.snapshot_id,
            "params": self.to_db_params() # Pack it up
        }

    # ====================================================================
    #                       UNPACKING (DB -> Model)
    # ====================================================================

    @classmethod
    def from_db(cls, row: Dict[str, Any]) -> "TaskPayload":
        """
        Hydrates the object from a DB row, unpacking JSONB envelopes into mirrors.
        
        This method normalizes types at the DB boundary to handle cases where
        JSONB columns might be returned as strings instead of dicts.
        """
        # ====================================================================
        # DB BOUNDARY NORMALIZATION (Critical Safety Layer)
        # ====================================================================
        # Never assume JSONB columns are already dicts - normalize at the boundary
        raw_params = row.get("params")
        
        # Handle None case
        if raw_params is None:
            logger.warning(
                "Task %s has missing params field, using empty dict",
                row.get("id") or row.get("task_id") or "unknown"
            )
            params = {}
        # Handle string case (JSONB sometimes returned as string by some drivers)
        elif isinstance(raw_params, str):
            logger.debug(
                "Parsing JSON params string for task %s",
                row.get("id") or row.get("task_id") or "unknown"
            )
            try:
                params = json.loads(raw_params)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON in params field for task {row.get('id') or row.get('task_id') or 'unknown'}: {e}"
                ) from e
        # Handle dict case (normal case)
        elif isinstance(raw_params, dict):
            params = raw_params
        # Handle invalid type
        else:
            raise TypeError(
                f"Task params must be dict or JSON string, got {type(raw_params).__name__} "
                f"for task {row.get('id') or row.get('task_id') or 'unknown'}"
            )
        
        # Final validation: ensure params is a dict after normalization
        if not isinstance(params, dict):
            raise TypeError(
                f"Task params must be dict after normalization, got {type(params).__name__} "
                f"for task {row.get('id') or row.get('task_id') or 'unknown'}"
            )
        
        # ====================================================================
        # UNPACK ENVELOPES (existing logic)
        # ====================================================================
        # Unpack Envelopes
        routing = params.get("routing") or {}
        hints = routing.get("hints") or {}
        interaction = params.get("interaction") or {}
        cognitive = params.get("cognitive") or {}
        chat = params.get("chat") or {}
        graph = params.get("graph") or {}
        
        # Safe Enum Conversion
        try:
            g_kind = GraphOperationKind(graph.get("kind", "unknown"))
        except ValueError:
            g_kind = GraphOperationKind.UNKNOWN

        # Tools conversion
        raw_tools = routing.get("tools") or []
        tools_objs = [
            (t if isinstance(t, ToolCallPayload) else ToolCallPayload(**t)) 
            for t in raw_tools if isinstance(t, dict)
        ]

        return cls(
            # Core
            task_id=str(row.get("id") or row.get("task_id")),
            type=row.get("type") or "unknown",
            description=row.get("description") or "",
            domain=row.get("domain"),
            drift_score=float(row.get("drift_score") or 0.0),
            snapshot_id=row.get("snapshot_id"),
            params=params,

            # Interaction
            interaction_mode=interaction.get("mode"),
            conversation_id=interaction.get("conversation_id"),
            assigned_agent_id=interaction.get("assigned_agent_id"),

            # Routing
            required_specialization=routing.get("required_specialization"),
            specialization=routing.get("specialization"),
            skills=routing.get("skills") or {},
            priority=int(hints.get("priority") or 0),
            deadline_at=hints.get("deadline_at"),
            ttl_seconds=hints.get("ttl_seconds"),
            tools=tools_objs,

            # Cognitive
            agent_id=cognitive.get("agent_id"),
            cog_type=cognitive.get("cog_type"),
            decision_kind=cognitive.get("decision_kind"),
            llm_provider_override=cognitive.get("llm_provider_override"),
            llm_model_override=cognitive.get("llm_model_override"),
            skip_retrieval=cognitive.get("skip_retrieval"),
            disable_memory_write=cognitive.get("disable_memory_write"),
            force_rag=cognitive.get("force_rag"),
            force_deep_reasoning=cognitive.get("force_deep_reasoning"),
            force_fast=cognitive.get("force_fast"),
            workflow=cognitive.get("workflow"),

            # Chat
            chat_message=chat.get("message"),
            chat_history=chat.get("history"),
            chat_agent_persona=chat.get("agent_persona"),
            chat_style=chat.get("style"),

            # Graph
            graph_kind=g_kind,
            graph_collection=graph.get("collection"),
            graph_inputs=graph.get("inputs") or {},
            graph_config=graph.get("config") or {},

            # Legacy
            conversation_history=params.get("conversation_history"),
        )
    
    # ====================================================================
    #                       UTILITIES
    # ====================================================================

    def model_copy(self, *, update: Optional[Dict[str, Any]] = None, deep: bool = False) -> "TaskPayload":
        """
        Create a new instance of the TaskPayload with modified data.
        
        This mimics Pydantic V2's model_copy but ensures that our custom
        params packing/unpacking logic is respected.
        
        Args:
            update: A dictionary of fields to change in the new copy.
            deep: If True, performs a deep copy of the original data first.
        """
        # 1. Extract current state
        # We prefer model_dump() if available (Pydantic V2), else dict() (V1)
        if hasattr(self, "model_dump"):
            data = self.model_dump()
        elif hasattr(self, "dict"):
            data = self.dict()
        else:
            # Fallback for standard classes or weird edge cases
            data = self.__dict__.copy()

        # 2. Handle Deep Copy
        # Critical for 'params' which contains nested dicts/lists
        if deep:
            import copy
            data = copy.deepcopy(data)

        # 3. Apply Updates
        if update:
            # Special handling for 'params': 
            # If the user updates a top-level field (e.g. 'interaction_mode'),
            # we rely on the constructor/validators to sync it back to 'params'.
            # If the user updates 'params' directly, it overrides everything.
            data.update(update)

        # 4. Re-instantiate
        # This triggers __init__ and validation, ensuring that if you updated
        # 'params' directly, the mirrors (like self.interaction_mode) get
        # re-populated correctly via the constructor logic (if you used from_db logic)
        # OR if you updated top-level fields, to_db_params will pack them later.
        
        # Note: Since Pydantic models are usually instantiated via keywords,
        # we pass the data dict as kwargs.
        return self.__class__(**data)