# seedcore/models/task_payload.py

from __future__ import annotations
from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field, field_validator  # pyright: ignore[reportMissingImports]

# ------------ Helper payloads (router inbox) ------------
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
    - All routing inputs → params.routing
    - Chat envelope → params.chat
    - Interaction envelope → params.interaction
    - Cognitive envelope → params.cognitive
    - conversation_history also available at top-level for ChatSignature

    No DB schema changes required. JSONB params absorb all structured metadata.
    """

    # ------------------------------------------------------------------
    # CORE FIELDS
    # ------------------------------------------------------------------
    type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    domain: Optional[str] = None
    drift_score: float = 0.0
    task_id: str

    # ------------------------------------------------------------------
    # ROUTER MIRRORS (convenience fields → packed into params.routing)
    # ------------------------------------------------------------------
    required_specialization: Optional[str] = None
    desired_skills: Dict[str, float] = Field(default_factory=dict)
    tool_calls: List[ToolCallPayload] = Field(default_factory=list)

    min_capability: Optional[float] = None
    max_mem_util: Optional[float] = None
    priority: int = 0
    deadline_at: Optional[str] = None
    ttl_seconds: Optional[int] = None

    # ------------------------------------------------------------------
    # TOP-LEVEL CHAT CONVENIENCE FIELD (for ChatSignature)
    # ------------------------------------------------------------------
    conversation_history: Optional[List[Dict[str, Any]]] = None
    skip_retrieval: Optional[bool] = None

    # ------------------------------------------------------------------
    # CHAT ENVELOPE MIRRORS (→ params.chat.*)
    # ------------------------------------------------------------------
    chat_message: Optional[str] = None
    chat_history: Optional[List[Dict[str, Any]]] = None
    chat_agent_persona: Optional[str] = None
    chat_style: Optional[str] = None

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
    cog_type: Optional[str] = None                    # chat, task_planning, problem_solving, hgnn
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
                import json
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @field_validator("domain", mode="before")
    @classmethod
    def parse_domain(cls, v):
        return v or ""

    # =====================================================================
    #                 PACKING HELPERS → DB STRUCTURE (params JSONB)
    # =====================================================================
    def to_db_params(self) -> Dict[str, Any]:
        """
        Inject structured envelopes under params:
            - routing
            - chat
            - interaction
            - cognitive
        All fields are optional. None values omitted.
        """
        p = dict(self.params or {})

        # ============================================================
        # ROUTING ENVELOPE
        # ============================================================
        routing = p.get("routing", {})
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
        routing = {**routing, **{k: v for k, v in merged_routing.items() if v is not None}}
        p["routing"] = routing

        # ============================================================
        # CHAT ENVELOPE
        # ============================================================
        chat = {
            "message": self.chat_message,
            "history": self.chat_history,
            "agent_persona": self.chat_agent_persona,
            "style": self.chat_style,
        }
        chat_clean = {k: v for k, v in chat.items() if v is not None}
        if chat_clean:
            p["chat"] = chat_clean

        # ============================================================
        # INTERACTION ENVELOPE
        # ============================================================
        interaction = {
            "mode": self.interaction_mode,
            "conversation_id": self.conversation_id,
            "assigned_agent_id": self.assigned_agent_id,
        }
        interaction_clean = {k: v for k, v in interaction.items() if v is not None}
        if interaction_clean:
            p["interaction"] = interaction_clean

        # ============================================================
        # COGNITIVE ENVELOPE
        # ============================================================
        cognitive = {
            "agent_id": self.cognitive_agent_id,
            "cog_type": self.cog_type,
            "decision_kind": self.decision_kind,
            "llm_provider_override": self.llm_provider_override,
            "llm_model_override": self.llm_model_override,
            "force_rag": self.force_rag,
            "force_deep_reasoning": self.force_deep_reasoning,
        }
        cognitive_clean = {k: v for k, v in cognitive.items() if v is not None}
        if cognitive_clean:
            p["cognitive"] = cognitive_clean

        # ============================================================
        # LEGACY top-level conversation_history compatibility
        # ============================================================
        if self.conversation_history:
            p["conversation_history"] = self.conversation_history

        # ------------------------------------------------------------
        # Top-level skip_retrieval flag (↔ QueryTools / CognitiveCore)
        # ------------------------------------------------------------
        if self.skip_retrieval is not None:
            p["skip_retrieval"] = self.skip_retrieval

        return p

    # =====================================================================
    #     ENSURE SERIALIZED PAYLOAD ALWAYS CONTAINS params.routing
    # =====================================================================
    def model_dump(self, *args, **kwargs) -> Dict[str, Any]:  # type: ignore[override]
        as_dict = super().model_dump(*args, **kwargs)
        as_dict["params"] = self.to_db_params()

        # Include top-level conversation_history for ChatSignature / QueryTools
        if self.conversation_history is not None:
            as_dict["conversation_history"] = self.conversation_history

        return as_dict

    # =====================================================================
    #                       DB → TaskPayload LOADER
    # =====================================================================
    @classmethod
    def from_db(cls, row: Dict[str, Any]) -> "TaskPayload":
        params = row.get("params") or {}

        routing = params.get("routing") or {}
        hints = routing.get("hints") or {}

        tool_calls_raw = routing.get("tool_calls") or []
        tool_calls = [
            (tc if isinstance(tc, ToolCallPayload) else ToolCallPayload(**tc))
            for tc in tool_calls_raw
            if isinstance(tc, (dict, ToolCallPayload))
        ]

        # --- Extract chat ---
        chat = params.get("chat") or {}
        chat_message = chat.get("message")
        chat_history = chat.get("history")
        chat_agent_persona = chat.get("agent_persona")
        chat_style = chat.get("style")

        # --- Extract interaction ---
        interaction = params.get("interaction") or {}
        interaction_mode = interaction.get("mode")
        conversation_id = interaction.get("conversation_id")
        assigned_agent_id = interaction.get("assigned_agent_id")

        # --- Extract cognitive metadata ---
        cognitive = params.get("cognitive") or {}
        cognitive_agent_id = cognitive.get("agent_id")
        cog_type = cognitive.get("cog_type")
        decision_kind = cognitive.get("decision_kind")
        llm_provider_override = cognitive.get("llm_provider_override")
        llm_model_override = cognitive.get("llm_model_override")
        force_rag = cognitive.get("force_rag")
        force_deep_reasoning = cognitive.get("force_deep_reasoning")

        # --- Legacy conversation history ---
        conversation_history = params.get("conversation_history")
        skip_retrieval = params.get("skip_retrieval")

        return cls(
            # Core
            type=row.get("type") or row.get("task_type") or "unknown_task",
            params=params,
            description=row.get("description") or "",
            domain=row.get("domain"),
            drift_score=float(row.get("drift_score") or 0.0),
            task_id=str(row.get("id") or row.get("task_id")),

            # Router
            required_specialization=routing.get("required_specialization"),
            desired_skills=routing.get("desired_skills") or {},
            tool_calls=tool_calls,
            min_capability=hints.get("min_capability"),
            max_mem_util=hints.get("max_mem_util"),
            priority=int(hints.get("priority") or 0),
            deadline_at=hints.get("deadline_at"),
            ttl_seconds=hints.get("ttl_seconds"),

            # Chat
            chat_message=chat_message,
            chat_history=chat_history,
            chat_agent_persona=chat_agent_persona,
            chat_style=chat_style,

            # Interaction
            interaction_mode=interaction_mode,
            conversation_id=conversation_id,
            assigned_agent_id=assigned_agent_id,

            # Cognitive
            cognitive_agent_id=cognitive_agent_id,
            cog_type=cog_type,
            decision_kind=decision_kind,
            llm_provider_override=llm_provider_override,
            llm_model_override=llm_model_override,
            force_rag=force_rag,
            force_deep_reasoning=force_deep_reasoning,

            # Compatibility
            conversation_history=conversation_history,
            skip_retrieval=skip_retrieval,
        )
