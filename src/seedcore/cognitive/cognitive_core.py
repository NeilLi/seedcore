"""
DSPy Cognitive Core v2 for SeedCore Agents.

This module provides enhanced cognitive reasoning capabilities for agents using DSPy,
with OCPS integration, RRF fusion, MMR diversity, dynamic token budgeting, and
comprehensive fact schema with provenance and trust.

Key Features:
- Enhanced Fact schema with provenance, trust, and policy flags
- RRF fusion and MMR diversification for better retrieval
- Dynamic token budgeting based on OCPS signals
- Hardened cache governance with TTL per task type
- Post-condition checks for DSPy outputs
- OCPS-informed budgeting and escalation hints (no routing)
- Fact sanitization and conflict detection
- HGNN (Heterogeneous Graph Neural Network) reasoning support
- Graph operations: embedding, RAG queries, node synchronization
- Fact operations: embedding, querying, search, and storage
- Resource management: artifacts, capabilities, memory cells
- Agent layer management: models, policies, services, skills
- Long-term memory via HolonFabric + CognitiveMemoryBridge (per-agent memory bridges)
- MwManager integration for episodic/working memory operations
- Pre-execution hydration and post-execution memory consolidation
- Server-side hydration support for graph repositories

Memory Architecture:
- Per-agent memory bridges: Each agent gets its own CognitiveMemoryBridge instance
  for scoped retrieval and memory writes (HolonFabric + MwManager)
- Global/coordinator mode: Requests without agent_id skip memory bridge operations
  (no memory writes, no scoped retrieval)
- Personal/agent mode: Requests with agent_id use per-agent memory bridges for:
  - Pre-execution hydration: HolonFabric retrieval + episodic memory + token budgeting
  - Post-execution consolidation: Mw episodic writes + Holon promotion + MemoryEvent creation
- LongTermMemoryManager has been removed and replaced with HolonFabric + CognitiveMemoryBridge

Architecture Notes:
- Coordinator decides fast vs escalate; Organism resolves/executes
- CognitiveCore follows data-driven flow based on input availability
- Supports skip_retrieval mode for fast/chat paths
- HGNN context can be provided directly without RAG pipeline
- Memory bridge initialization is lazy (on-demand per agent)
- ContextBroker is deprecated in favor of CognitiveMemoryBridge + HolonFabricRetrieval
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import hashlib
import os
import re
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import dspy  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.models.holon import Holon, HolonScope
from ..coordinator.utils import normalize_task_payloads

try:
    from ..ml.driver.nim_retrieval import NimRetrievalHTTP  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    NimRetrievalHTTP = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None  # type: ignore

# Centralized result schema
from ..models.result_schema import create_cognitive_result, create_error_result
from ..models.fact import Fact
from ..models.cognitive import CognitiveType, CognitiveContext, DecisionKind
from .context_broker import (
    ContextBroker,
    RetrievalSufficiency,
    _fact_to_context_dict,
)
from .signatures import (
    HGNNReasoningSignature,
    AnalyzeFailureSignature,
    CapabilityAssessmentSignature,
    ChatSignature,
    DecisionMakingSignature,
    MemorySynthesisSignature,
    ProblemSolvingSignature,
    TaskPlanningSignature,
    CausalDecompositionSignature,
)
from .memory_bridge import CognitiveMemoryBridge

setup_logging("seedcore.CognitiveCore")
logger = ensure_serve_logger("seedcore.CognitiveCore", level="DEBUG")


class CachedResultFound(Exception):
    """Internal exception used to return a cached result without running the pipeline."""

    def __init__(self, cached_result: Dict[str, Any]):
        self.cached_result = cached_result
        super().__init__("Cached result found, aborting pipeline.")


# Optional Mw dependencies (episodic memory)
try:
    from src.seedcore.memory.mw_manager import MwManager

    _MW_AVAILABLE = True
except Exception:
    MwManager = None  # type: ignore
    _MW_AVAILABLE = False

MW_ENABLED = os.getenv("MW_ENABLED", "1") in {"1", "true", "True"}

# Database & Repo imports (for Server-Side Hydration)
try:
    from ..graph.task_metadata_repository import TaskMetadataRepository
except ImportError:
    TaskMetadataRepository = None

# Holon Client import (for Memory Bridge)
try:
    from ..memory.holon_client import HolonClient
except ImportError:
    HolonClient = None  # type: ignore


class DefaultScopeResolver:
    """Default implementation of ScopeResolver protocol."""

    def resolve(
        self, *, agent_id: str, organ_id: Optional[str], task_params: Dict[str, Any]
    ) -> Tuple[List[str], List[str]]:
        """Return (scopes, entity_ids). Scopes are Holon scopes like ["GLOBAL", "ORGAN", "ENTITY"]."""
        scopes = ["GLOBAL"]

        if organ_id:
            scopes.append("ORGAN")

        # ENTITY scopes if user passes entity_ids in params
        entity_ids = task_params.get("entity_ids") or []
        if not isinstance(entity_ids, list):
            entity_ids = [entity_ids] if entity_ids else []
        if entity_ids:
            scopes.append("ENTITY")

        return scopes, entity_ids


class HolonFabricRetrieval:
    def __init__(self, fabric: HolonFabric, embedder):
        self.fabric = fabric
        self.embedder = embedder

    async def query_context(
        self,
        *,
        text: str,
        scopes: Sequence[str],
        organ_id: Optional[str],
        entity_ids: Sequence[str],
        limit: int,
        agent_id: Optional[str] = None,
        ocps: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        vec = self.embedder.embed(text)
        holons = await self.fabric.query_context(
            query_vec=vec,
            scopes=[HolonScope(s) for s in scopes],
            organ_id=organ_id,
            entity_ids=list(entity_ids),
            limit=limit,
        )

        return [self._holon_to_dict(h) for h in holons]

    def _holon_to_dict(self, h: Holon):
        return {
            "id": h.id,
            "summary": h.summary,
            "content": h.content,
            "confidence": h.confidence,
            "scope": h.scope.value,
        }


# =============================================================================
# Cognitive Service
# =============================================================================


class CognitiveCore(dspy.Module):
    """
    Enhanced cognitive core with OCPS integration, cache governance, and post-condition checks.

    This module integrates with SeedCore's memory, energy, and lifecycle systems
    to provide intelligent reasoning capabilities for agents with OCPS fast/planner path routing
    (where planner path may use deep profile internally).
    """

    def __init__(
        self,
        llm_provider: Optional[str] = "openai",
        model: Optional[str] = "gpt-4o",
        context_broker: Optional[ContextBroker] = None,
        ocps_client=None,
        # --- NEW: Hydration Dependencies ---
        graph_repo: Optional[Any] = None,
        session_maker: Optional[Any] = None,
        # --- Backward compatibility: profile parameter (ignored) ---
        profile: Optional[Any] = None,  # Deprecated: kept for backward compatibility
    ):
        super().__init__()
        self.llm_provider = llm_provider or "unknown"
        self.model = model or "unknown"
        self.ocps_client = ocps_client
        self.graph_repo = graph_repo
        self.session_maker = session_maker  # Factory for DB sessions
        self.schema_version = "v2.0"
        self._state_lock = threading.RLock()
        self._last_sufficiency: Dict[str, Any] = {}

        # Initialize Mw support (episodic memory)
        self._mw_enabled = bool(MW_ENABLED and _MW_AVAILABLE)
        self._mw_by_agent: Dict[str, MwManager] = {} if self._mw_enabled else {}
        self._sufficiency_thresholds = {
            "coverage": 0.6,
            "diversity": 0.5,
            "conflict_count": 2,
            "staleness_ratio": 0.3,
            "trust_score": 0.4,
        }
        self._synopsis_embedding_backend = (
            (
                os.getenv("SYNOPSIS_EMBEDDING_BACKEND")
                or (
                    "nim"
                    if os.getenv("SYNOPSIS_EMBEDDING_BASE_URL")
                    or os.getenv("NIM_RETRIEVAL_BASE_URL")
                    else "sentence-transformer"
                )
            )
            .lower()
            .replace("_", "-")
        )
        self._synopsis_embedding_model = os.getenv(
            "SYNOPSIS_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"
        )
        self._synopsis_embedding_dim = int(os.getenv("SYNOPSIS_EMBEDDING_DIM", "768"))
        self._synopsis_embedding_base_url = (
            os.getenv("SYNOPSIS_EMBEDDING_BASE_URL")
            or os.getenv("NIM_RETRIEVAL_BASE_URL", "")
        ).lstrip("@")
        self._synopsis_embedding_api_key = os.getenv(
            "SYNOPSIS_EMBEDDING_API_KEY"
        ) or os.getenv("NIM_RETRIEVAL_API_KEY")
        self._synopsis_embedding_timeout = float(
            os.getenv("SYNOPSIS_EMBEDDING_TIMEOUT", "10")
        )
        self._synopsis_embedder: Optional[Any] = None
        self._synopsis_embedder_failed = False
        self._synopsis_embedder_lock = threading.Lock()

        # Create ContextBroker with Mw search functions if none provided
        # NOTE: ContextBroker is deprecated in favor of CognitiveMemoryBridge + HolonFabricRetrieval
        # Kept for backward compatibility with legacy handlers that may still use it
        # Long-term memory uses HolonFabric via CognitiveMemoryBridge
        if context_broker is None:
            # Create lambda functions that will be bound to agent_id at call time
            def text_fn(query, k):
                return self._mw_first_text_search(
                    "", query, k
                )  # Will be overridden in process()

            def vec_fn(query, k):
                return self._mw_first_vector_search(
                    "", query, k
                )  # Will be overridden in process()

            self.context_broker = ContextBroker(
                text_fn, vec_fn, token_budget=1500, ocps_client=self.ocps_client
            )
            logger.debug(
                "ContextBroker initialized (legacy mode - consider migrating to CognitiveMemoryBridge)"
            )
        else:
            self.context_broker = context_broker

        # Initialize specialized cognitive modules with post-condition checks
        self.failure_analyzer = dspy.ChainOfThought(AnalyzeFailureSignature)
        self.task_planner = dspy.ChainOfThought(TaskPlanningSignature)
        self.decision_maker = dspy.ChainOfThought(DecisionMakingSignature)
        self.problem_solver = dspy.ChainOfThought(ProblemSolvingSignature)
        # OPTIMIZATION: Use Predict (Direct) for Chat to ensure low latency
        self.chat_handler = dspy.Predict(ChatSignature)
        self.memory_synthesizer = dspy.ChainOfThought(MemorySynthesisSignature)
        self.capability_assessor = dspy.ChainOfThought(CapabilityAssessmentSignature)
        self.hgnn_reasoner = dspy.ChainOfThought(HGNNReasoningSignature)
        self.causal_decomposer = dspy.ChainOfThought(CausalDecompositionSignature)

        # Task mapping - updated to match CognitiveType enum from cognitive.py
        self.task_handlers = {
            # Core reasoning
            CognitiveType.CHAT: self.chat_handler,
            CognitiveType.PROBLEM_SOLVING: self.problem_solver,
            CognitiveType.TASK_PLANNING: self.task_planner,
            CognitiveType.DECISION_MAKING: self.decision_maker,
            CognitiveType.FAILURE_ANALYSIS: self.failure_analyzer,
            CognitiveType.CAUSAL_DECOMPOSITION: self.causal_decomposer,
            # Memory-based reasoning
            CognitiveType.MEMORY_SYNTHESIS: self.memory_synthesizer,
            CognitiveType.CAPABILITY_ASSESSMENT: self.capability_assessor,
        }

        # Cache governance settings - shorter TTLs for sufficiency-bearing results
        # Updated to match CognitiveType enum from cognitive.py
        self.cache_ttl_by_task = {
            # Core reasoning
            CognitiveType.CHAT: 300,  # 5 minutes (lightweight conversational, volatile)
            CognitiveType.PROBLEM_SOLVING: 600,  # 10 minutes (sufficiency data)
            CognitiveType.TASK_PLANNING: 600,  # 10 minutes (sufficiency data)
            CognitiveType.DECISION_MAKING: 600,  # 10 minutes (sufficiency data)
            CognitiveType.FAILURE_ANALYSIS: 300,  # 5 minutes (volatile analysis)
            CognitiveType.CAUSAL_DECOMPOSITION: 900,  # 15 minutes (structural reasoning output)
            # Memory-based reasoning
            CognitiveType.MEMORY_SYNTHESIS: 1800,  # 30 minutes (no sufficiency)
            CognitiveType.CAPABILITY_ASSESSMENT: 600,  # 10 minutes (sufficiency data)
        }

        logger.info(
            f"Initialized CognitiveCore with {self.llm_provider} and model {self.model}"
        )

        # Log Mw integration status
        if self._mw_enabled:
            logger.info("MwManager integration: ENABLED")
        else:
            logger.info("MwManager integration: DISABLED (missing module or env)")

        # Log synopsis embedding status
        synopsis_enabled = self._synopsis_embedding_backend in {
            "nim",
            "nim-retrieval",
            "sentence-transformer",
        } and (
            self._synopsis_embedding_base_url
            or self._synopsis_embedding_backend == "sentence-transformer"
        )
        if synopsis_enabled:
            logger.info(
                f"Synopsis embedding: ENABLED (backend={self._synopsis_embedding_backend}, "
                f"model={self._synopsis_embedding_model})"
            )
        else:
            logger.info(
                "Synopsis embedding: DISABLED (backend not configured or dependencies unavailable)"
            )

        # Memory bridges (per-agent) - supports multi-agent and global/coordinator modes
        # Global/coordinator requests (no agent_id) don't use memory bridges
        # Personal/agent requests get per-agent bridges for scoped retrieval and memory writes
        self.memory_bridges: Dict[str, CognitiveMemoryBridge] = {}

        # Per-agent memory components (for future multi-agent memory isolation)
        # Currently uses shared instances with fallback to defaults, but prepared for per-agent injection
        self.scope_resolvers: Dict[
            str, Any
        ] = {}  # Dict[str, ScopeResolver] - per-agent scope resolution
        self.cognitive_retrievals: Dict[
            str, Any
        ] = {}  # Dict[str, CognitiveRetrieval] - per-agent retrieval

        # Shared memory components (used by all agents, can be overridden per-agent)
        # These are set externally or lazily initialized
        self.holon_client: Optional[Any] = None  # HolonClient instance
        self.holon_fabric: Optional[Any] = (
            None  # HolonFabric instance (for HolonFabricRetrieval)
        )
        self.scope_resolver: Optional[Any] = None  # Default ScopeResolver (fallback)
        self.cognitive_retrieval: Optional[Any] = (
            None  # Default CognitiveRetrieval (fallback)
        )

    def set_memory_bridge(self, memory_bridge: CognitiveMemoryBridge) -> None:
        """Set the memory bridge instance for a specific agent.

        This should be called when all required dependencies are available:
        - agent_id, organ_id (from context)
        - MwManager (from _mw_by_agent)
        - HolonClient, ScopeResolver, CognitiveRetrieval (provided externally)
        """
        agent_id = memory_bridge.agent_id
        if agent_id in self.memory_bridges:
            logger.warning(
                f"Overwriting existing memory bridge for agent_id={agent_id}"
            )
        self.memory_bridges[agent_id] = memory_bridge
        logger.info(
            f"Memory bridge configured for agent_id={agent_id}, organ_id={memory_bridge.organ_id}"
        )

    def set_scope_resolver(self, agent_id: str, scope_resolver: Any) -> None:
        """Set a per-agent scope resolver.

        If not set, will fall back to shared scope_resolver or DefaultScopeResolver.
        """
        self.scope_resolvers[agent_id] = scope_resolver
        logger.debug(f"Scope resolver configured for agent_id={agent_id}")

    def set_cognitive_retrieval(self, agent_id: str, cognitive_retrieval: Any) -> None:
        """Set a per-agent cognitive retrieval instance.

        If not set, will fall back to shared cognitive_retrieval or attempt to create HolonFabricRetrieval.
        """
        self.cognitive_retrievals[agent_id] = cognitive_retrieval
        logger.debug(f"Cognitive retrieval configured for agent_id={agent_id}")

    def _get_memory_bridge(
        self, agent_id: Optional[str]
    ) -> Optional[CognitiveMemoryBridge]:
        """Get the memory bridge for a specific agent.

        Returns None for global/coordinator requests (no agent_id) or if bridge doesn't exist.
        """
        if not agent_id:
            return None
        return self.memory_bridges.get(agent_id)

    def _try_initialize_memory_bridge(
        self, agent_id: Optional[str], organ_id: Optional[str] = None
    ) -> bool:
        """Attempt to lazily initialize a per-agent memory bridge.

        Returns True if initialization was successful, False otherwise.
        Global/coordinator requests (no agent_id) return False immediately.
        """
        # 0) Global / coordinator requests: skip bridge entirely
        if not agent_id:
            logger.debug(
                "Memory bridge initialization skipped: no agent_id (global/coordinator request)."
            )
            return False

        # Already initialized for this agent
        if agent_id in self.memory_bridges:
            return True

        # 1) MwManager must be enabled and available for this agent
        if not getattr(self, "_mw_enabled", False):
            logger.debug("Memory bridge initialization skipped: MwManager not enabled")
            return False

        mw = self._mw_by_agent.get(agent_id) if hasattr(self, "_mw_by_agent") else None
        if mw is None:
            logger.debug(
                "Memory bridge initialization skipped: "
                f"No MwManager instance for agent_id={agent_id}"
            )
            return False

        # 2) External dependencies: HolonClient, ScopeResolver, CognitiveRetrieval
        # Note: HolonClient from memory.holon_client implements the Protocol from memory_bridge

        # HolonClient: shared across all agents (set externally)
        holon_client = self.holon_client

        # ScopeResolver: per-agent if available, otherwise shared, otherwise default
        scope_resolver = self.scope_resolvers.get(agent_id) or self.scope_resolver
        if scope_resolver is None:
            scope_resolver = DefaultScopeResolver()
            logger.debug(f"Using DefaultScopeResolver for agent_id={agent_id}")

        # CognitiveRetrieval: per-agent if available, otherwise shared, otherwise try to create
        cognitive_retrieval = (
            self.cognitive_retrievals.get(agent_id) or self.cognitive_retrieval
        )
        if cognitive_retrieval is None:
            holon_fabric = self.holon_fabric
            embedder = self._ensure_synopsis_embedder()

            if holon_fabric is not None and embedder is not None:
                cognitive_retrieval = HolonFabricRetrieval(
                    fabric=holon_fabric, embedder=embedder
                )
                logger.debug(f"Using HolonFabricRetrieval for agent_id={agent_id}")
            else:
                missing_components = []
                if holon_fabric is None:
                    missing_components.append("holon_fabric")
                if embedder is None:
                    missing_components.append("embedder (synopsis_embedder)")
                logger.debug(
                    f"Cannot create HolonFabricRetrieval for agent_id={agent_id}: missing {', '.join(missing_components)}"
                )

        missing = []
        if holon_client is None:
            if HolonClient is None:
                missing.append(
                    "HolonClient (module not available - install from memory.holon_client)"
                )
            else:
                missing.append(
                    "HolonClient (self.holon_client - set an instance of memory.holon_client.HolonClient)"
                )
        if cognitive_retrieval is None:
            missing.append(
                "CognitiveRetrieval (self.cognitive_retrieval or set self.holon_fabric + embedder for HolonFabricRetrieval)"
            )

        if missing:
            logger.debug(
                "Memory bridge initialization skipped: missing external dependencies: "
                + ", ".join(missing)
                + ". Use set_memory_bridge() or set these attributes on CognitiveCore."
            )
            return False

        # 3) Construct the CognitiveMemoryBridge for this agent
        try:
            bridge_logger = logger.getChild("memory_bridge")
            memory_bridge = CognitiveMemoryBridge(
                agent_id=agent_id,
                organ_id=organ_id,
                mw=mw,
                holon=holon_client,
                scope_resolver=scope_resolver,
                retrieval=cognitive_retrieval,
                logger=bridge_logger,
            )
            self.memory_bridges[agent_id] = memory_bridge
            logger.info(
                "Lazily initialized CognitiveMemoryBridge for "
                f"agent_id={agent_id}, organ_id={organ_id}"
            )
            return True
        except Exception as e:
            logger.exception(f"Memory bridge initialization failed: {e}")
            return False

    def process(self, context: CognitiveContext) -> Dict[str, Any]:
        """
        Main entry point (Orchestrator).
        Executes the task by coordinating hydration, decision logic, and execution handlers.
        """
        task_id = self._extract_task_id(context.input_data)
        input_data = context.input_data or {}

        logger.debug(
            f"CognitiveCore.process: cog_type={context.cog_type.value} "
            f"decision_kind={context.decision_kind.value} "
            f"agent_id={context.agent_id} task_id={task_id or 'n/a'}"
        )

        cache_key = self._generate_cache_key(
            context.cog_type, context.agent_id, input_data
        )

        try:
            # 1. Configuration & Setup
            params = input_data.get("params") or {}
            cog_flags = self._resolve_cognitive_flags(input_data, params)

            # 2. Hydration (The heavy lifting)
            knowledge_context = self._hydrate_knowledge_context(
                context, input_data, params, cog_flags
            )

            # 3. Decision Branching: HGNN Path
            # v2 semantics: If COGNITIVE path and HGNN embedding exists, shortcut to HGNN pipeline
            # Note: Coordinator now creates DecisionKind.COGNITIVE (not ESCALATED) for escalated tasks
            if (
                context.decision_kind == DecisionKind.COGNITIVE
                and knowledge_context.get("hgnn_embedding") is not None
            ):
                logger.debug(
                    f"Task {task_id}: Cognitive path + HGNN detected. Running HGNN pipeline."
                )
                return self._run_hgnn_pipeline(
                    context=context,
                    hgnn_embedding=knowledge_context["hgnn_embedding"],
                    knowledge_context=knowledge_context,
                )

            # 4. Standard Execution
            return self._run_handler_and_postprocess(
                context,
                knowledge_context,
                cache_key,
                task_id,
            )

        except CachedResultFound as crf:
            return crf.cached_result
        except Exception as e:
            logger.exception(f"Processing error: {e}")
            return create_error_result(str(e), "PROCESSING_ERROR").model_dump()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_cognitive_flags(
        self, input_data: Dict, params: Dict
    ) -> Dict[str, bool]:
        """
        Normalizes flags like 'skip_retrieval' or 'force_rag' from top-level or params.
        """
        cognitive_cfg = params.get("cognitive") or {}

        def _flag(name: str, default: bool = False) -> bool:
            # Prefer top-level, fall back to params.cognitive
            if name in input_data:
                return bool(input_data.get(name))
            return bool(cognitive_cfg.get(name, default))

        return {
            "skip_retrieval": _flag("skip_retrieval", False),
            "force_fast": _flag("force_fast", False),
            "force_deep_reasoning": _flag("force_deep_reasoning", False),
            "force_rag": _flag("force_rag", False),
        }

    def _resolve_initial_chat_history(
        self, context: CognitiveContext, input_data: Dict, params: Dict
    ) -> List[Any]:
        """
        Extracts conversation history from input inputs (PersistentAgent priority) before hydration.
        """
        if context.cog_type != CognitiveType.CHAT:
            return []

        # Priority: top-level conversation_history > params.conversation_history > params.chat.history
        history = (
            input_data.get("conversation_history")
            or params.get("conversation_history")
            or params.get("chat", {}).get("history")
            or []
        )

        if not isinstance(history, list):
            history = []

        logger.debug(f"Chat mode: Extracted initial history ({len(history)} turns)")
        return history

    def _hydrate_knowledge_context(
        self, context: CognitiveContext, input_data: Dict, params: Dict, cog_flags: Dict
    ) -> Dict[str, Any]:
        """
        Handles the logic for Memory Bridge vs Global fallback.
        Returns a standardized knowledge_context dictionary.
        """
        is_personal = bool(context.agent_id)
        initial_chat_history = self._resolve_initial_chat_history(
            context, input_data, params
        )

        # 1. Initialize Bridge (if personal)
        memory_bridge = None
        if is_personal:
            organ_id = input_data.get("organ_id") or params.get("organ_id")
            self._try_initialize_memory_bridge(context.agent_id, organ_id)
            memory_bridge = self._get_memory_bridge(context.agent_id)
        else:
            logger.debug(
                "Global/coordinator request detected: skipping memory bridge init."
            )

        # 2. Execute Hydration Strategy
        if not memory_bridge:
            return self._build_fallback_knowledge_context(
                context,
                params,
                initial_chat_history,
                cog_flags,
                reason="Memory bridge unavailable; retrieval skipped.",
            )

        try:
            # Prepare task for bridge
            base_task = {
                "id": self._extract_task_id(input_data),
                "type": context.cog_type.value,
                "description": input_data.get("description") or "",
                "goal": input_data.get("goal") or "",
                "params": dict(params),
            }
            ocps = input_data.get("ocps")

            # Sync execution of async hydration
            hydrated_task = self._run_coro_sync(
                memory_bridge.hydrate_task(
                    task=base_task,
                    ocps=ocps,
                    skip_retrieval=cog_flags["skip_retrieval"],
                ),
                timeout=10.0,
            )

            # Merge hydration back into input_data (side-effect maintenance for handlers)
            input_data.update(hydrated_task)

            # Construct context
            return self._construct_bridged_knowledge_context(
                context, hydrated_task, initial_chat_history, cog_flags
            )

        except Exception as e:
            logger.exception(f"Memory bridge hydration failed: {e}")
            return self._build_fallback_knowledge_context(
                context,
                params,
                initial_chat_history,
                cog_flags,
                reason="Hydration failed",
            )

    def _construct_bridged_knowledge_context(
        self,
        context: CognitiveContext,
        hydrated_task: Dict,
        initial_chat_history: List,
        cog_flags: Dict,
    ) -> Dict[str, Any]:
        """
        Builds the knowledge context from a successful Memory Bridge response.
        """
        ctx_section = hydrated_task.get("params", {}).get("context", {})
        holons = ctx_section.get("holons", [])
        hydrated_history = ctx_section.get("chat_history", [])
        token_budget = ctx_section.get("token_budget", 0)
        hgnn_embedding = ctx_section.get("hgnn_embedding")

        # Merge Logic: PersistentAgent history overrides hydration history in CHAT mode
        if context.cog_type == CognitiveType.CHAT and initial_chat_history:
            final_chat_history = initial_chat_history
            logger.debug(
                f"Chat mode: Using input history ({len(final_chat_history)} turns) "
                f"over hydration ({len(hydrated_history)} turns)"
            )
        else:
            final_chat_history = hydrated_history

        return {
            "facts": [self._holon_to_fact(h) for h in holons],
            "holons": holons,
            "chat_history": final_chat_history,
            "token_budget": token_budget,
            "summary": "Hydrated via Holon Memory Fabric",
            "sufficiency": {
                "token_budget": token_budget,
                "holon_count": len(holons),
                "chat_turns": len(final_chat_history),
            },
            "bridge_context": ctx_section,
            "memory_context": ctx_section,
            "hgnn_embedding": hgnn_embedding,
            "cognitive_flags": cog_flags,
        }

    def _build_fallback_knowledge_context(
        self,
        context: CognitiveContext,
        params: Dict,
        chat_history: List,
        cog_flags: Dict,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Constructs a minimal context when the bridge is missing or errors out.
        Updates input_data['params'] in place to ensure downstream compatibility.
        """
        params.setdefault("context", {})
        params["context"].update(
            {
                "holons": [],
                "chat_history": chat_history,
                "token_budget": 0,
            }
        )

        # Ensure context.input_data reflects these fallbacks
        if context.input_data:
            context.input_data["params"] = params

        return {
            "facts": [],
            "holons": [],
            "chat_history": chat_history,
            "token_budget": 0,
            "summary": reason,
            "sufficiency": {
                "token_budget": 0,
                "holon_count": 0,
                "chat_turns": len(chat_history),
            },
            "hgnn_embedding": None,
            "cognitive_flags": cog_flags,
        }

    def _run_hgnn_pipeline(
        self, context: CognitiveContext, embedding: List[float]
    ) -> Dict[str, Any]:
        """
        The 'Deep Reasoning' Pipeline: Vector -> Graph -> LLM

        This method implements the Neuro-Symbolic Bridge:
        1. Translates the mathematical vector back into human-readable graph nodes
        2. Uses DSPy to reason about structural relationships
        3. Returns a structured diagnosis and mitigation plan

        Args:
            context: The cognitive context containing task information
            embedding: The HGNN embedding vector from ML Service

        Returns:
            Dictionary with analysis, root_cause, solution_steps, and metadata
        """
        logger.info(f"🧠 Starting HGNN Deep Reasoning for {context.agent_id}")

        # Step A: Vector Translation (Hydration)
        graph_neighbors = []
        if self.graph_repo and self.session_maker:
            # Synchronously run async DB call (using helper)
            async def _fetch():
                async with self.session_maker() as session:
                    return await self.graph_repo.find_hgnn_neighbors(session, embedding)

            try:
                graph_neighbors = self._run_coro_sync(_fetch())
            except Exception as e:
                logger.warning(f"HGNN neighbor fetch failed: {e}")

        context_str = json.dumps(graph_neighbors, indent=2)
        anomaly_desc = str(
            context.input_data.get(
                "description", "Unknown Anomaly detected via system drift."
            )
        )

        # Step B: DSPy Execution
        # Note: No 'with dspy.context' here. The Orchestrator already set the DEEP profile.
        prediction = self.hgnn_reasoner(
            structural_context=context_str, anomaly_description=anomaly_desc
        )

        # Step C: Structuring
        return {
            "success": True,
            "result": {
                "analysis": prediction.structural_analysis,
                "root_cause": prediction.root_cause_hypothesis,
                # Helper to format the text plan into list of steps
                "solution_steps": self._parse_plan_text(prediction.mitigation_plan),
                "meta": {
                    "source": "hgnn_deep_reasoning",
                    "neighbors_found": len(graph_neighbors),
                },
            },
        }

    def _parse_plan_text(self, text: str) -> List[Dict[str, Any]]:
        """Simple helper to convert LLM text block into step list."""
        # Basic heuristic: split by newlines or numbers
        steps = []
        for line in text.split("\n"):
            clean = line.strip()
            if clean and (clean[0].isdigit() or clean.startswith("-")):
                steps.append({"type": "execute", "description": clean})
        return steps or [{"type": "unknown", "description": text}]

    def _ensure_synopsis_embedder(self) -> Optional[Any]:
        if self._synopsis_embedder or self._synopsis_embedder_failed:
            return self._synopsis_embedder

        with self._synopsis_embedder_lock:
            if self._synopsis_embedder or self._synopsis_embedder_failed:
                return self._synopsis_embedder

            backend = self._synopsis_embedding_backend
            if backend in {"nim", "nim-retrieval"}:
                if NimRetrievalHTTP is None:
                    logger.warning(
                        "Synopsis embedding backend configured for NIM but NimRetrievalHTTP dependency is unavailable."
                    )
                    self._synopsis_embedder_failed = True
                    return None
                if not self._synopsis_embedding_base_url:
                    logger.warning(
                        "Synopsis embedding backend configured for NIM but SYNOPSIS_EMBEDDING_BASE_URL/NIM_RETRIEVAL_BASE_URL is not set."
                    )
                    self._synopsis_embedder_failed = True
                    return None
                try:
                    self._synopsis_embedder = NimRetrievalHTTP(
                        base_url=self._synopsis_embedding_base_url,
                        api_key=self._synopsis_embedding_api_key,
                        model=self._synopsis_embedding_model,
                        timeout=int(self._synopsis_embedding_timeout),
                    )
                    logger.debug(
                        "Initialized NimRetrievalHTTP for synopsis embeddings (model=%s).",
                        self._synopsis_embedding_model,
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to initialize NimRetrievalHTTP for synopsis embeddings: %s",
                        exc,
                        exc_info=True,
                    )
                    self._synopsis_embedder_failed = True
            else:
                if SentenceTransformer is None:
                    logger.warning(
                        "SentenceTransformer is not available; synopsis embeddings will be disabled. "
                        "Install sentence-transformers or configure SYNOPSIS_EMBEDDING_BACKEND=nim."
                    )
                    self._synopsis_embedder_failed = True
                    return None
                try:
                    self._synopsis_embedder = SentenceTransformer(
                        self._synopsis_embedding_model
                    )
                    logger.debug(
                        "Loaded SentenceTransformer model '%s' for synopsis embeddings.",
                        self._synopsis_embedding_model,
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to load SentenceTransformer model '%s' for synopsis embeddings: %s",
                        self._synopsis_embedding_model,
                        exc,
                    )
                    self._synopsis_embedder_failed = True

        return self._synopsis_embedder

    def _generate_synopsis_embedding(
        self, synopsis: Dict[str, Any]
    ) -> Optional[np.ndarray]:
        embedder = self._ensure_synopsis_embedder()
        if embedder is None:
            return None

        text_to_embed = json.dumps(synopsis, sort_keys=True)
        try:
            if NimRetrievalHTTP is not None and isinstance(embedder, NimRetrievalHTTP):
                vectors = embedder.embed(text_to_embed, input_type="passage")
                if not vectors:
                    logger.debug("Nim synopsis embedder returned no vectors.")
                    return None
                vector = vectors[0]
            else:
                vector = embedder.encode(  # type: ignore[attr-defined]
                    text_to_embed,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to generate synopsis embedding: %s", exc, exc_info=True
            )
            return None

        vec = np.asarray(vector, dtype=np.float32).reshape(-1)
        target_dim = self._synopsis_embedding_dim
        if vec.size != target_dim:
            logger.debug(
                "Adjusting synopsis embedding dimensionality from %d to %d.",
                vec.size,
                target_dim,
            )
            if vec.size > target_dim:
                vec = vec[:target_dim]
            else:
                vec = np.pad(vec, (0, target_dim - vec.size), mode="constant")

        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm

        return vec.astype(np.float32)

    def _run_handler_and_postprocess(
        self,
        context: CognitiveContext,
        knowledge_context: Dict[str, Any],
        cache_key: str,
        task_id: Optional[str],
    ) -> Dict[str, Any]:
        """Execute the appropriate handler and apply normalization, caching, and guardrails."""
        handler = self.task_handlers.get(context.cog_type)
        if not handler:
            return create_error_result(
                f"Unknown task type: {context.cog_type}", "INVALID_COG_TYPE"
            ).model_dump()

        payload, planner_timings, plan_build_start, plan_build_end = (
            self._invoke_handler(handler, context, knowledge_context, task_id)
        )
        processed_payload, suff_dict, violations = self._apply_post_processing(
            payload=payload,
            context=context,
            knowledge_context=knowledge_context,
            planner_timings=planner_timings,
            plan_build_start=plan_build_start,
            plan_build_end=plan_build_end,
        )
        return self._package_result(
            context=context,
            payload=processed_payload,
            cache_key=cache_key,
            task_id=task_id,
            suff_dict=suff_dict,
            violations=violations,
        )

    def _invoke_handler(
        self,
        handler: Callable[..., Any],
        context: CognitiveContext,
        knowledge_context: Dict[str, Any],
        task_id: Optional[str],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], float, float]:
        """Prepare inputs, invoke the handler, and normalize the raw response."""
        enhanced_input = dict(context.input_data)
        working_context = dict(knowledge_context)

        planner_timings = working_context.pop("_planner_timings", {})
        hgnn_embedding = working_context.pop("hgnn_embedding", None)
        if hgnn_embedding is not None:
            enhanced_input["hgnn_embedding"] = hgnn_embedding

        # For CHAT mode: Ensure message and conversation_history are set correctly
        # ChatSignature expects: message (str) and conversation_history (JSON string)
        if context.cog_type == CognitiveType.CHAT:
            # Extract message from multiple possible locations
            message = (
                enhanced_input.get("message")
                or enhanced_input.get("description")
                or enhanced_input.get("params", {}).get("chat", {}).get("message")
                or ""
            )
            enhanced_input["message"] = message

            # Extract conversation_history from knowledge_context (which was set from input)
            # or fallback to input_data
            chat_history = knowledge_context.get("chat_history", [])
            if not chat_history:
                # Fallback to input_data if not in knowledge_context
                chat_history = (
                    enhanced_input.get("conversation_history")
                    or enhanced_input.get("params", {}).get("conversation_history")
                    or enhanced_input.get("params", {}).get("chat", {}).get("history")
                    or []
                )
            enhanced_input["conversation_history"] = chat_history
        
        # For PROBLEM_SOLVING mode: Extract problem_statement, constraints, and available_tools
        # ProblemSolvingSignature expects these at top level
        elif context.cog_type == CognitiveType.PROBLEM_SOLVING:
            params = enhanced_input.get("params", {})
            
            # Extract problem_statement from multiple possible locations
            problem_statement = (
                enhanced_input.get("problem_statement")
                or enhanced_input.get("description")
                or params.get("query", {}).get("problem_statement")
                or ""
            )
            enhanced_input["problem_statement"] = problem_statement
            
            # Extract constraints from params if not at top level
            if "constraints" not in enhanced_input:
                constraints = params.get("constraints") or {}
                enhanced_input["constraints"] = constraints
            
            # Extract available_tools from params if not at top level
            if "available_tools" not in enhanced_input:
                available_tools = params.get("available_tools") or {}
                enhanced_input["available_tools"] = available_tools

        enhanced_input["knowledge_context"] = json.dumps(working_context)
        enhanced_input = self._format_input_for_signature(
            enhanced_input, context.cog_type
        )
        filtered_input = self._filter_to_signature(handler, enhanced_input)

        logger.debug(
            f"Invoking handler for {context.cog_type.value} task_id={task_id or 'n/a'}"
        )

        plan_build_start = time.time()
        raw = handler(**filtered_input)
        plan_build_end = time.time()

        payload = self._to_payload(raw)
        logger.debug(
            f"Handler completed for {context.cog_type.value} task_id={task_id or 'n/a'} payload_keys={list(payload.keys())}"
        )

        return payload, planner_timings, plan_build_start, plan_build_end

    def _apply_post_processing(
        self,
        payload: Dict[str, Any],
        context: CognitiveContext,
        knowledge_context: Dict[str, Any],
        planner_timings: Dict[str, Any],
        plan_build_start: float,
        plan_build_end: float,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        """Normalize payloads, enrich metadata, and run guardrail checks."""
        if context.cog_type == CognitiveType.FAILURE_ANALYSIS:
            payload = self._normalize_failure_analysis(payload)
        elif context.cog_type == CognitiveType.TASK_PLANNING:
            payload = self._normalize_task_planning(payload)
        elif context.cog_type == CognitiveType.CHAT:
            payload = self._normalize_chat(payload)

        escalate_hint = knowledge_context.get("escalate_hint", False)
        sufficiency = knowledge_context.get("sufficiency", {}) or {}
        suff_dict = sufficiency
        confidence = payload.get("confidence_score")

        if planner_timings:
            budget_end_time = planner_timings.pop("_budget_end_time", None)
            if budget_end_time is not None:
                planner_timings["plan_build_ms"] = int(
                    (plan_build_end - budget_end_time) * 1000
                )
            else:
                planner_timings.setdefault(
                    "plan_build_ms", int((plan_build_end - plan_build_start) * 1000)
                )
        else:
            planner_timings = {
                "plan_build_ms": int((plan_build_end - plan_build_start) * 1000)
            }

        if "task" in payload:
            normalized_task = normalize_task_payloads(payload["task"])
            payload["task"] = normalized_task
            plan_result = self._wrap_single_step_as_plan(
                normalized_task, escalate_hint, sufficiency, confidence
            )
            payload["solution_steps"] = plan_result["solution_steps"]
            payload["meta"] = plan_result["meta"]
            payload["meta"]["planner_timings_ms"] = planner_timings

        if "meta" not in payload:
            payload["meta"] = {}
        payload["meta"].setdefault("planner_timings_ms", planner_timings)
        payload["meta"].setdefault(
            "sufficiency_thresholds", dict(self._sufficiency_thresholds)
        )
        payload["meta"].setdefault("sufficiency_snapshot", suff_dict)
        payload["meta"].setdefault(
            "escalation_reasons",
            knowledge_context.get("sufficiency", {}).get("escalation_reasons", []),
        )

        is_valid, violations = self._check_post_conditions(payload, context.cog_type)
        if not is_valid:
            logger.warning(f"Post-condition violations: {violations}")

        # 🔥 POST-EXECUTION MEMORY CONSOLIDATION
        # Memory Bridge writes episodic memory (Mw), creates MemoryEvent, and promotes to HolonFabric
        # Only run for personal/agent requests (not global/coordinator)
        is_personal = bool(context.agent_id)
        if is_personal:
            memory_bridge = self._get_memory_bridge(context.agent_id)
        else:
            memory_bridge = None

        if memory_bridge:
            try:
                # Extract ocps from context input_data
                ocps = context.input_data.get("ocps") if context.input_data else None

                # Build task dict for memory bridge (matches what was used in hydration)
                # Extract task_id consistently (Issue 4 fix)
                task_id_for_memory = (
                    self._extract_task_id(context.input_data)
                    or payload.get("task_id")
                    or (
                        context.input_data.get("task_id")
                        if context.input_data
                        else None
                    )
                    or f"ad-hoc:{int(time.time() * 1000)}"
                )

                task_dict: Dict[str, Any] = {
                    "id": task_id_for_memory,
                    "type": context.cog_type.value,
                    "description": context.input_data.get("description", "")
                    if context.input_data
                    else "",
                    "goal": context.input_data.get("goal", "")
                    if context.input_data
                    else "",
                    "params": context.input_data.get("params", {})
                    if context.input_data
                    else {},
                }

                # Call memory bridge post-execution consolidation
                memory_event = self._run_coro_sync(
                    memory_bridge.process_post_execution(
                        task=task_dict,
                        result=payload,
                        ocps=ocps,
                    ),
                    timeout=5.0,
                )

                # Store memory event ID in payload metadata for telemetry
                payload.setdefault("meta", {})["memory_event_id"] = memory_event.id
                logger.debug(
                    f"Memory bridge post-execution completed: memory_event_id={memory_event.id}"
                )
            except Exception as e:
                logger.warning(
                    f"Memory bridge post-execution failed: {e}", exc_info=True
                )
                # Continue execution even if memory bridge fails
        elif is_personal:
            # Personal request but no bridge available - log but don't fail
            logger.debug(
                f"Memory bridge post-execution skipped: no bridge for agent_id={context.agent_id}"
            )

        return payload, suff_dict, violations

    def _package_result(
        self,
        context: CognitiveContext,
        payload: Dict[str, Any],
        cache_key: str,
        task_id: Optional[str],
        suff_dict: Dict[str, Any],
        violations: List[str],
    ) -> Dict[str, Any]:
        """Create the final task result, persist cache, and enforce invariants."""
        out = create_cognitive_result(
            agent_id=context.agent_id,
            cog_type=context.cog_type.value,
            result=payload,
            confidence_score=payload.get("confidence_score"),
            cache_hit=False,
            sufficiency=suff_dict,
            post_condition_violations=violations,
        )

        out_dict = {
            "success": out.success,
            "result": out.payload.result if hasattr(out.payload, "result") else {},
            "payload": out.payload.result if hasattr(out.payload, "result") else {},
            "error": None,
            "metadata": out.metadata,
            "cog_type": out.payload.cog_type
            if hasattr(out.payload, "cog_type")
            else context.cog_type.value,
        }

        self._cache_result(
            cache_key,
            out_dict,
            context.cog_type,
            agent_id=context.agent_id,
            task_id=task_id,
        )

        self._assert_no_routing_awareness(out_dict)

        return out_dict

    def forward(self, context: CognitiveContext) -> Dict[str, Any]:
        """Expose the enhanced planning pipeline via the dspy.Module interface."""
        return self.process(context)

    def build_fragments_for_synthesis(
        self, context: CognitiveContext, facts: List[Fact], summary: str
    ) -> List[Dict[str, Any]]:
        """Build memory-synthesis fragments for Coordinator."""
        return [
            {"agent_id": context.agent_id},
            {"knowledge_summary": summary},
            {"top_facts": [_fact_to_context_dict(f) for f in facts[:5]]},
            {"ocps_sufficiency": self._get_last_sufficiency()},
        ]

    # ------------------------ Helper Methods ------------------------
    def _holon_to_fact(self, h: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a Holon dict to a Fact-like dict for backward compatibility with handlers.

        HolonFabric holons have a different structure than RAG facts, so we normalize them
        to match the expected fact schema used by DSPy handlers.

        Args:
            h: Holon dict from HolonFabric with keys: id, summary, content, confidence, scope, etc.

        Returns:
            Fact-like dict with normalized structure
        """
        return {
            "id": h.get("id"),
            "source": "holon",
            "score": h.get("confidence", 1.0),
            "trust": h.get("trust_score", h.get("confidence", 0.7)),
            "summary": h.get("summary", ""),
            "content": h.get("content", {}),
            "scope": h.get("scope"),  # GLOBAL, ORGAN, ENTITY
        }

    def _generate_cache_key(
        self, cog_type: CognitiveType, agent_id: str, input_data: Dict[str, Any]
    ) -> str:
        """Generate hardened cache key with provider, model, and schema version."""
        stable_hash = self._stable_hash(cog_type, agent_id, input_data)
        return f"cc:res:{cog_type.value}:{self.model}:{self.llm_provider}:{self.schema_version}:{stable_hash}"

    def _stable_hash(
        self, cog_type: CognitiveType, agent_id: str, input_data: Dict[str, Any]
    ) -> str:
        """Stable hash of inputs (drop obviously-ephemeral fields if present)."""
        # Shallow sanitize to improve cache hit rate.
        sanitized = dict(input_data)
        # Drop ephemeral fields that shouldn't affect caching
        for key in ["timestamp", "created_at", "updated_at", "id", "request_id"]:
            sanitized.pop(key, None)

        # Create stable hash
        content = f"{cog_type.value}:{agent_id}:{json.dumps(sanitized, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached_result(
        self,
        cache_key: str,
        cog_type: CognitiveType,
        *,
        agent_id: str,
        task_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get cached result with TTL check."""
        if not self._mw_enabled:
            return None
        try:
            # Get agent-specific cache
            mw = self._mw(agent_id)
            if not mw:
                return None

            # Use async get_item_async via helper to avoid nested loop issues
            try:
                cached_data = self._run_coro_sync(
                    mw.get_item_async(cache_key), timeout=2.0
                )
            except Exception:
                cached_data = None

            if not cached_data:
                return None

            normalized = self._normalize_cached_result_shape(cached_data)

            if isinstance(cached_data, dict) and "cached_at" in cached_data:
                ttl = self.cache_ttl_by_task.get(cog_type, 600)
                cache_age = time.time() - cached_data.get("cached_at", 0)
                if cache_age > ttl:
                    # Delete expired cache entry
                    try:
                        if hasattr(mw, "del_global_key_sync"):
                            mw.del_global_key_sync(cache_key)
                        else:
                            # New API: delete via set_global_item with None/expired flag
                            mw.set_global_item(cache_key, {"expired": True}, ttl_s=1)
                    except Exception:
                        pass
                    return None
                logger.info(
                    f"Cache hit: {cache_key} (age: {cache_age:.1f}s) task_id={task_id or 'n/a'}"
                )
            else:
                logger.info(
                    f"Cache hit: {cache_key} (unexpected format) task_id={task_id or 'n/a'}"
                )

            return normalized

        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
            return None

    def _cache_result(
        self,
        cache_key: str,
        result: Dict[str, Any],
        cog_type: CognitiveType,
        *,
        agent_id: str,
        task_id: Optional[str] = None,
    ):
        """Cache result with metadata."""
        if not self._mw_enabled:
            return

        try:
            mw = self._mw(agent_id)
            if not mw:
                return

            cache_data = {
                "result": result,
                "cached_at": time.time(),
                "cog_type": cog_type.value,
                "schema_version": self.schema_version,
            }

            # Use set_global_item instead of set
            mw.set_global_item(cache_key, cache_data)
            logger.info(f"Cached result: {cache_key} task_id={task_id or 'n/a'}")

        except Exception as e:
            logger.warning(f"Cache storage error: {e}")

    def _normalize_cached_result_shape(
        self, cached_data: Any
    ) -> Optional[Dict[str, Any]]:
        """Ensure cached payloads conform to the canonical out_dict structure."""
        if not cached_data:
            return None

        source = cached_data
        if isinstance(cached_data, dict) and isinstance(
            cached_data.get("result"), dict
        ):
            source = cached_data["result"]

        if not isinstance(source, dict):
            return {
                "success": True,
                "result": {"value": source},
                "payload": {"value": source},
                "cog_type": "unknown",
                "metadata": {},
                "error": None,
            }

        normalized = dict(source)
        normalized.setdefault("success", normalized.get("error") is None)
        payload = normalized.get("payload")
        result_field = normalized.get("result")
        if payload is None and isinstance(result_field, dict):
            normalized["payload"] = result_field
        elif result_field is None and isinstance(payload, dict):
            normalized["result"] = payload
        elif payload is None and result_field is None:
            normalized["payload"] = {}
            normalized["result"] = {}

        normalized.setdefault(
            "cog_type",
            (cached_data.get("cog_type") if isinstance(cached_data, dict) else None)
            or "unknown",
        )
        metadata = normalized.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if (
            isinstance(cached_data, dict)
            and "cached_at" in cached_data
            and "cached_at" not in metadata
        ):
            metadata = dict(metadata)
            metadata["cached_at"] = cached_data["cached_at"]
        if metadata:
            normalized["metadata"] = metadata
        else:
            normalized.setdefault("metadata", {})
        normalized.setdefault("error", None)
        return normalized

    def _to_payload(self, raw) -> dict:
        """Normalize any handler output into a dict."""
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        # DSPy predictions often have toDict()
        if hasattr(raw, "toDict") and callable(raw.toDict):
            try:
                result = raw.toDict()
                if isinstance(result, dict):
                    return result or {}
            except Exception:
                pass
        # namedtuple
        if hasattr(raw, "_asdict"):
            try:
                result = raw._asdict()
                if isinstance(result, dict):
                    return result or {}
            except Exception:
                pass
        # Mock objects - extract attributes directly
        if hasattr(raw, "_mock_name"):  # This is a Mock object
            result = {}
            for attr_name in dir(raw):
                if not attr_name.startswith("_") and not callable(
                    getattr(raw, attr_name)
                ):
                    try:
                        value = getattr(raw, attr_name)
                        if not hasattr(value, "_mock_name"):  # Not a nested Mock
                            result[attr_name] = value
                    except Exception:
                        pass
            return result
        # generic object with attributes
        if hasattr(raw, "__dict__"):
            return {k: v for k, v in vars(raw).items() if not k.startswith("_")}
        # fallback
        return {"value": raw}

    def _extract_task_id(self, input_data: Dict[str, Any]) -> Optional[str]:
        """Best-effort extraction of a task id from input data for logging.

        Supports unified TaskPayload format (task_id at top level) and legacy formats.

        Priority order:
        1. Top-level task_id (TaskPayload standard format)
        2. params.task_id (alternative location)
        3. Legacy keys: id, request_id, job_id, run_id

        Args:
            input_data: The input data dictionary, typically from TaskPayload.model_dump()

        Returns:
            Task ID as string, or None if not found
        """
        if not input_data:
            return None

        # 1. Check top-level task_id first (TaskPayload standard format)
        # TaskPayload.model_dump() puts task_id at the top level
        task_id = input_data.get("task_id")
        if task_id is not None:
            # Handle both string and numeric IDs
            if isinstance(task_id, str) and task_id.strip():
                return task_id.strip()
            elif isinstance(task_id, (int, float)) and task_id != 0:
                return str(int(task_id))

        # 2. Check params.task_id (alternative TaskPayload location)
        params = input_data.get("params")
        if isinstance(params, dict):
            task_id = params.get("task_id")
            if task_id is not None:
                if isinstance(task_id, str) and task_id.strip():
                    return task_id.strip()
                elif isinstance(task_id, (int, float)) and task_id != 0:
                    return str(int(task_id))

        # 3. Legacy fallback: check common keys
        for key in ("id", "request_id", "job_id", "run_id"):
            value = input_data.get(key)
            if value is not None:
                if isinstance(value, str) and value.strip():
                    return value.strip()
                elif isinstance(value, (int, float)) and value != 0:
                    return str(int(value))

        return None

    def _normalize_failure_analysis(self, payload: dict) -> dict:
        """
        Normalize failure analysis specific fields.

        Handles:
        - confidence_score: Ensures it's a float in [0.0, 1.0]
        - Nested task structures: Normalizes any TaskPayload-like structures

        Args:
            payload: The raw payload dict from DSPy handler output

        Returns:
            Normalized payload dict
        """
        if not isinstance(payload, dict):
            return payload

        # Normalize confidence_score
        if "confidence_score" in payload:
            try:
                conf = payload["confidence_score"]
                # Handle string values
                if isinstance(conf, str):
                    conf = float(conf.strip())
                elif isinstance(conf, (int, float)):
                    conf = float(conf)
                else:
                    conf = 0.0

                # Clamp to valid range [0.0, 1.0]
                payload["confidence_score"] = max(0.0, min(conf, 1.0))
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Invalid confidence_score '{payload.get('confidence_score')}': {e}. Defaulting to 0.0"
                )
                payload["confidence_score"] = 0.0

        # Normalize nested task structure if present (TaskPayload format)
        if "task" in payload and isinstance(payload["task"], dict):
            payload["task"] = normalize_task_payloads(payload["task"])

        # Normalize solution_steps if present (may contain TaskPayload-like structures)
        if "solution_steps" in payload and isinstance(payload["solution_steps"], list):
            normalized_steps = []
            for step in payload["solution_steps"]:
                if isinstance(step, dict):
                    # Normalize any nested task structures in steps
                    if "task" in step and isinstance(step["task"], dict):
                        step["task"] = normalize_task_payloads(step["task"])
                    normalized_steps.append(step)
                else:
                    normalized_steps.append(step)
            payload["solution_steps"] = normalized_steps

        return payload

    def _normalize_task_planning(self, payload: dict) -> dict:
        """
        Normalize task planning fields, especially estimated_complexity.

        Handles:
        - estimated_complexity: Ensures it's a float in [1.0, 10.0]
        - step_by_step_plan: Backward compatibility alias for solution_steps
        - Nested task structures: Normalizes any TaskPayload-like structures in solution_steps

        Args:
            payload: The raw payload dict from DSPy handler output

        Returns:
            Normalized payload dict
        """
        if not isinstance(payload, dict):
            return payload

        # Back-compat: Some downstream consumers expect 'step_by_step_plan'.
        # If we produced a uniform plan in 'solution_steps', mirror it.
        if "step_by_step_plan" not in payload and "solution_steps" in payload:
            payload["step_by_step_plan"] = payload.get("solution_steps")

        # Normalize estimated_complexity
        val = payload.get("estimated_complexity")
        if val is not None:
            if isinstance(val, (int, float)):
                # Clamp to valid range [1.0, 10.0]
                num = float(val)
                payload["estimated_complexity"] = max(1.0, min(num, 10.0))
            elif isinstance(val, str):
                # Normalize commas and strip text
                text = val.replace(",", ".").strip()

                # Broader numeric extraction: find any number in the string
                match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
                if match:
                    try:
                        num = float(match.group(1))
                        # Clamp to valid range [1.0, 10.0]
                        payload["estimated_complexity"] = max(1.0, min(num, 10.0))
                        logger.debug(
                            f"Extracted numeric complexity from '{val}': {payload['estimated_complexity']}"
                        )
                    except ValueError:
                        logger.warning(
                            f"Could not convert extracted complexity: {match.group(1)}"
                        )
                        payload["estimated_complexity"] = 5.0
                else:
                    logger.warning(
                        f"Could not extract numeric value from estimated_complexity: '{val}'"
                    )
                    payload["estimated_complexity"] = 5.0
            else:
                logger.warning(f"Unexpected type for estimated_complexity: {type(val)}")
                payload["estimated_complexity"] = 5.0

        # Normalize nested task structure if present (TaskPayload format)
        if "task" in payload and isinstance(payload["task"], dict):
            payload["task"] = normalize_task_payloads(payload["task"])

        # Normalize solution_steps - ensure each step follows TaskPayload structure
        if "solution_steps" in payload and isinstance(payload["solution_steps"], list):
            normalized_steps = []
            for idx, step in enumerate(payload["solution_steps"]):
                if isinstance(step, dict):
                    # Ensure step has required TaskPayload-like structure
                    # Each step should have 'type' and 'params' at minimum
                    if "type" not in step:
                        logger.warning(f"solution_steps[{idx}] missing 'type' field")
                        step["type"] = "unknown_task"

                    if "params" not in step:
                        step["params"] = {}

                    # Normalize any nested task structures in steps
                    if "task" in step and isinstance(step["task"], dict):
                        step["task"] = normalize_task_payloads(step["task"])

                    # Normalize params if it contains TaskPayload-like structures
                    if "params" in step and isinstance(step["params"], dict):
                        # Check if params contains nested routing or cognitive sections
                        # that might need normalization
                        if "routing" in step["params"] and isinstance(
                            step["params"]["routing"], dict
                        ):
                            # Already normalized by TaskPayload structure
                            pass

                    normalized_steps.append(step)
                else:
                    logger.warning(
                        f"solution_steps[{idx}] is not a dict, skipping normalization"
                    )
                    normalized_steps.append(step)
            payload["solution_steps"] = normalized_steps

            # Update step_by_step_plan if it was set earlier
            if "step_by_step_plan" in payload:
                payload["step_by_step_plan"] = normalized_steps

        return payload

    def _normalize_chat(self, payload: dict) -> dict:
        """
        Normalize chat-specific fields.

        Handles:
        - confidence: Ensures it's a float in [0.0, 1.0] and maps to confidence_score for consistency
        - response: Ensures it's a string

        Args:
            payload: The raw payload dict from DSPy handler output

        Returns:
            Normalized payload dict
        """
        if not isinstance(payload, dict):
            return payload

        # Normalize confidence field (ChatSignature outputs 'confidence', not 'confidence_score')
        if "confidence" in payload:
            try:
                conf = payload["confidence"]
                # Handle string values
                if isinstance(conf, str):
                    conf = float(conf.strip())
                elif isinstance(conf, (int, float)):
                    conf = float(conf)
                else:
                    conf = 0.0

                # Clamp to valid range [0.0, 1.0]
                conf_normalized = max(0.0, min(conf, 1.0))
                payload["confidence"] = conf_normalized
                # Also set confidence_score for consistency with other cognitive types
                payload["confidence_score"] = conf_normalized
            except (ValueError, TypeError) as e:
                logger.warning(
                    f"Invalid confidence '{payload.get('confidence')}': {e}. Defaulting to 0.0"
                )
                payload["confidence"] = 0.0
                payload["confidence_score"] = 0.0

        # Ensure response is a string
        if "response" in payload and not isinstance(payload["response"], str):
            payload["response"] = str(payload.get("response", ""))

        return payload

    def _validate_solution_steps(
        self, payload: Dict[str, Any], violations: List[str]
    ) -> None:
        steps = payload.get("solution_steps")
        if steps is None:
            return
        if not isinstance(steps, list):
            violations.append("solution_steps must be a list")
            return

        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                violations.append(f"solution_steps[{idx}] must be an object")
                continue
            for required in ("type", "params"):
                if required not in step:
                    violations.append(f"solution_steps[{idx}] missing '{required}'")

    def _check_post_conditions(
        self, result: Dict[str, Any], cog_type: CognitiveType
    ) -> Tuple[bool, List[str]]:
        """Check post-conditions for DSPy outputs to ensure policy compliance."""
        violations = []

        # Check confidence score bounds
        if "confidence_score" in result:
            conf = result["confidence_score"]
            if isinstance(conf, str):
                try:
                    conf = float(conf)
                except ValueError:
                    conf = 0.0
            if not (0.0 <= conf <= 1.0):
                violations.append(f"Confidence score {conf} out of bounds [0.0, 1.0]")

        # Check for PII patterns
        text_fields = [
            "thought",
            "proposed_solution",
            "reasoning",
            "decision",
            "solution_approach",
        ]
        for field in text_fields:
            if field in result and isinstance(result[field], str):
                text = result[field].lower()
                # Simple PII detection
                if any(
                    pattern in text
                    for pattern in ["ssn", "social security", "credit card", "password"]
                ):
                    violations.append(f"Potential PII detected in {field}")

        # Check for executable content
        for field in text_fields:
            if field in result and isinstance(result[field], str):
                text = result[field]
                if re.search(r"```[\s\S]*?```", text) or re.search(r"`[^`]+`", text):
                    violations.append(f"Code blocks detected in {field}")

        # Check numeric ranges for specific fields
        if cog_type == CognitiveType.TASK_PLANNING and "estimated_complexity" in result:
            try:
                complexity = float(result["estimated_complexity"])
                if not (1.0 <= complexity <= 10.0):
                    violations.append(
                        f"Complexity score {complexity} out of bounds [1.0, 10.0]"
                    )
            except (ValueError, TypeError):
                violations.append("Invalid complexity score format")

        self._validate_solution_steps(result, violations)

        return len(violations) == 0, violations

    def _build_query(self, context: CognitiveContext) -> str:
        """
        Build search query from context.
        
        Updated to match CognitiveType enum from cognitive.py:
        - CHAT
        - PROBLEM_SOLVING
        - TASK_PLANNING
        - DECISION_MAKING
        - FAILURE_ANALYSIS
        - CAUSAL_DECOMPOSITION
        - MEMORY_SYNTHESIS
        - CAPABILITY_ASSESSMENT
        """
        # Extract key information for search
        query_parts = []

        if context.cog_type == CognitiveType.CHAT:
            message = context.input_data.get("message", "") or context.input_data.get("chat_message", "")
            query_parts.append(f"chat {message[:100]}")
        elif context.cog_type == CognitiveType.PROBLEM_SOLVING:
            problem = context.input_data.get("problem_description", "") or context.input_data.get("task_description", "")
            query_parts.append(f"problem solving {problem[:100]}")
        elif context.cog_type == CognitiveType.TASK_PLANNING:
            task_desc = context.input_data.get("task_description", "")
            query_parts.append(f"task planning {task_desc[:100]}")
        elif context.cog_type == CognitiveType.DECISION_MAKING:
            decision_ctx = context.input_data.get("decision_context", {})
            options = decision_ctx.get("options", "") if isinstance(decision_ctx, dict) else str(decision_ctx)
            query_parts.append(f"decision making {options[:100]}")
        elif context.cog_type == CognitiveType.FAILURE_ANALYSIS:
            incident = context.input_data.get("incident_context", {}) or context.input_data.get("failure_context", {})
            error_type = incident.get("error_type", "") if isinstance(incident, dict) else str(incident)
            query_parts.append(f"failure analysis {error_type[:100]}")
        elif context.cog_type == CognitiveType.CAUSAL_DECOMPOSITION:
            structural = context.input_data.get("structural_context", "")
            incident = context.input_data.get("incident_report", "") or context.input_data.get("incident_context", "")
            query_parts.append(f"causal decomposition {structural[:80]} {incident[:80]}")
        elif context.cog_type == CognitiveType.MEMORY_SYNTHESIS:
            memory_context = context.input_data.get("memory_context", {}) or context.memory_context or {}
            query = memory_context.get("query", "") if isinstance(memory_context, dict) else str(memory_context)
            query_parts.append(f"memory synthesis {query[:100]}")
        elif context.cog_type == CognitiveType.CAPABILITY_ASSESSMENT:
            capability_context = context.input_data.get("capability_context", {}) or context.input_data.get("assessment_context", {})
            agent_id = capability_context.get("agent_id", "") if isinstance(capability_context, dict) else ""
            task_type = capability_context.get("task_type", "") if isinstance(capability_context, dict) else ""
            query_parts.append(f"capability assessment {agent_id} {task_type}")
        else:
            # Fallback: use the enum value as query
            query_parts.append(context.cog_type.value)

        return " ".join(query_parts).strip()

    def _format_input_for_signature(
        self, input_data: Dict[str, Any], cog_type: CognitiveType
    ) -> Dict[str, Any]:
        """
        Convert dict fields to JSON strings for DSPy signatures that expect JSON strings.
        This handles the mismatch between dict inputs and signature field expectations.
        """
        formatted = dict(input_data)

        # Map task types to fields that need JSON string conversion
        if cog_type == CognitiveType.FAILURE_ANALYSIS:
            # AnalyzeFailureSignature expects JSON strings
            if "incident_context" in formatted and isinstance(
                formatted["incident_context"], dict
            ):
                formatted["incident_context"] = json.dumps(
                    formatted["incident_context"]
                )
        elif cog_type == CognitiveType.TASK_PLANNING:
            # TaskPlanningSignature expects JSON strings
            if "agent_capabilities" in formatted and isinstance(
                formatted["agent_capabilities"], dict
            ):
                formatted["agent_capabilities"] = json.dumps(
                    formatted["agent_capabilities"]
                )
            if "available_resources" in formatted and isinstance(
                formatted["available_resources"], dict
            ):
                formatted["available_resources"] = json.dumps(
                    formatted["available_resources"]
                )
        elif cog_type == CognitiveType.DECISION_MAKING:
            # DecisionMakingSignature expects JSON strings
            if "decision_context" in formatted and isinstance(
                formatted["decision_context"], dict
            ):
                formatted["decision_context"] = json.dumps(
                    formatted["decision_context"]
                )
            if "historical_data" in formatted and isinstance(
                formatted["historical_data"], dict
            ):
                formatted["historical_data"] = json.dumps(formatted["historical_data"])
        elif cog_type == CognitiveType.PROBLEM_SOLVING:
            # ProblemSolvingSignature expects JSON strings
            if "constraints" in formatted and isinstance(
                formatted["constraints"], dict
            ):
                formatted["constraints"] = json.dumps(formatted["constraints"])
            if "available_tools" in formatted and isinstance(
                formatted["available_tools"], dict
            ):
                formatted["available_tools"] = json.dumps(formatted["available_tools"])
        elif cog_type == CognitiveType.CAUSAL_DECOMPOSITION:
            # CausalDecompositionSignature expects structured context blocks
            if "structural_context" in formatted and isinstance(
                formatted["structural_context"], (list, dict)
            ):
                formatted["structural_context"] = json.dumps(
                    formatted["structural_context"]
                )
            if "incident_report" in formatted and isinstance(
                formatted["incident_report"], (list, dict)
            ):
                formatted["incident_report"] = json.dumps(formatted["incident_report"])
        elif cog_type == CognitiveType.CHAT:
            # ChatSignature expects conversation_history as JSON string
            if "conversation_history" in formatted:
                if isinstance(formatted["conversation_history"], (list, dict)):
                    formatted["conversation_history"] = json.dumps(
                        formatted["conversation_history"]
                    )
                elif formatted["conversation_history"] is None:
                    formatted["conversation_history"] = "[]"
        elif cog_type == CognitiveType.MEMORY_SYNTHESIS:
            # MemorySynthesisSignature expects JSON strings
            if "memory_fragments" in formatted:
                if isinstance(formatted["memory_fragments"], (list, dict)):
                    formatted["memory_fragments"] = json.dumps(
                        formatted["memory_fragments"]
                    )
        elif cog_type == CognitiveType.CAPABILITY_ASSESSMENT:
            # CapabilityAssessmentSignature expects JSON strings
            if "performance_data" in formatted and isinstance(
                formatted["performance_data"], dict
            ):
                formatted["agent_performance_data"] = json.dumps(
                    formatted.pop("performance_data")
                )
            if "current_capabilities" in formatted and isinstance(
                formatted["current_capabilities"], dict
            ):
                formatted["current_capabilities"] = json.dumps(
                    formatted["current_capabilities"]
                )
            if "target_capabilities" in formatted and isinstance(
                formatted["target_capabilities"], dict
            ):
                formatted["target_capabilities"] = json.dumps(
                    formatted["target_capabilities"]
                )

        return formatted

    def _build_knowledge_context(
        self, facts: List[Fact], summary: str, sufficiency: RetrievalSufficiency
    ) -> Dict[str, Any]:
        """Build knowledge context for DSPy signatures."""
        return {
            "facts": [_fact_to_context_dict(fact) for fact in facts],
            "summary": summary,
            "sufficiency": {
                "coverage": sufficiency.coverage,
                "diversity": sufficiency.diversity,
                "agreement": sufficiency.agreement,
                "conflict_count": sufficiency.conflict_count,
                "staleness_ratio": sufficiency.staleness_ratio,
                "trust_score": sufficiency.trust_score,
            },
            "policy": {
                "facts_only": True,
                "no_executable_content": True,
                "sanitized": True,
            },
        }

    def _mw(self, agent_id: str) -> Optional[MwManager]:
        """Get or create MwManager for agent."""
        if not self._mw_enabled:
            return None
        with self._state_lock:
            mgr = self._mw_by_agent.get(agent_id)
            if mgr is None:
                try:
                    # MwManager expects organ_id as parameter name
                    mgr = MwManager(organ_id=agent_id)
                    self._mw_by_agent[agent_id] = mgr
                except Exception as e:
                    logger.debug("MwManager unavailable (init failed): %s", e)
                    return None
            return mgr

    def _mw_text_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search text in Mw for agent."""
        mw = self._mw(agent_id)
        if not mw:
            return []
        # MwManager doesn't have search_text method - return empty for now
        # Text search should use CognitiveMemoryBridge + HolonFabricRetrieval instead
        return []

    def _mw_vector_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search vectors in Mw for agent."""
        mw = self._mw(agent_id)
        if not mw:
            return []
        # MwManager doesn't have search_vector method - return empty for now
        # Vector search should use CognitiveMemoryBridge + HolonFabricRetrieval instead
        return []

    def _run_coro_sync(
        self, coro: Awaitable[Any], *, timeout: Optional[float] = None
    ) -> Any:
        """Run an async coroutine from sync context without nesting event loops."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        if not loop.is_running():
            return loop.run_until_complete(coro)

        def _runner() -> Any:
            return asyncio.run(coro)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_runner)
            return future.result(timeout=timeout)

    def _bind_broker(self, agent_id: str) -> ContextBroker:
        """Return a ContextBroker instance with Mw search bindings for the given agent."""

        def text_fn(query, k):
            return self._mw_first_text_search(agent_id, query, k)

        def vec_fn(query, k):
            return self._mw_first_vector_search(agent_id, query, k)

        base = self.context_broker
        if base is None:
            return ContextBroker(
                text_fn, vec_fn, token_budget=1500, ocps_client=self.ocps_client
            )

        if hasattr(base, "clone_with_search"):
            try:
                return base.clone_with_search(text_fn, vec_fn)  # type: ignore[attr-defined]
            except Exception:
                logger.debug(
                    "clone_with_search failed; falling back to new ContextBroker."
                )

        token_budget = getattr(
            base, "base_token_budget", getattr(base, "token_budget", 1500)
        )
        ocps_client = getattr(base, "ocps_client", self.ocps_client)
        energy_client = getattr(base, "energy_client", None)
        return ContextBroker(
            text_fn,
            vec_fn,
            token_budget=token_budget,
            ocps_client=ocps_client,
            energy_client=energy_client,
        )

    def _update_last_sufficiency(self, sufficiency_dict: Dict[str, Any]) -> None:
        with self._state_lock:
            self._last_sufficiency = dict(sufficiency_dict or {})

    def _get_last_sufficiency(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._last_sufficiency)

    def _filter_to_signature(
        self, handler: Any, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Filter kwargs to the declared DSPy signature inputs to avoid unexpected kwargs."""
        signature = getattr(handler, "signature", None)
        if not signature:
            return data

        allowed = getattr(signature, "inputs", None)
        if isinstance(allowed, dict):
            keys = set(allowed.keys())
        elif isinstance(allowed, (list, tuple, set)):
            keys = set(allowed)
        else:
            return data

        return {k: v for k, v in data.items() if k in keys}

    @staticmethod
    def _format_id_list(ids: Any) -> str:
        if isinstance(ids, (list, tuple, set)):
            return ",".join(str(item) for item in ids)
        return str(ids)

    def _mw_first_text_search(
        self, agent_id: str, q: str, k: int
    ) -> List[Dict[str, Any]]:
        """Search Mw for text queries.

        NOTE: This method is deprecated. Use CognitiveMemoryBridge + HolonFabricRetrieval
        for proper scoped retrieval with HolonFabric.
        """
        return self._mw_text_search(agent_id, q, k)

    def _mw_first_vector_search(
        self, agent_id: str, q: str, k: int
    ) -> List[Dict[str, Any]]:
        """Search Mw for vector queries.

        NOTE: This method is deprecated. Use CognitiveMemoryBridge + HolonFabricRetrieval
        for proper scoped vector search with HolonFabric.
        """
        return self._mw_vector_search(agent_id, q, k)

    def _create_plan_from_steps(
        self,
        steps: List[Dict[str, Any]],
        escalate_hint: bool = False,
        sufficiency: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create a uniform plan format from task steps."""
        return {
            "solution_steps": steps,
            "meta": {
                "escalate_hint": escalate_hint,
                "sufficiency": sufficiency or {},
                "confidence": confidence,
                "plan_type": "cognitive_proposal",
                "step_count": len(steps),
            },
        }

    def _wrap_single_step_as_plan(
        self,
        task: Dict[str, Any],
        escalate_hint: bool = False,
        sufficiency: Optional[Dict[str, Any]] = None,
        confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Wrap a single task as a 1-step plan."""
        return self._create_plan_from_steps(
            [task], escalate_hint, sufficiency, confidence
        )

    def _norm_domain(self, domain: Optional[str]) -> Optional[str]:
        """Normalize domain to standard taxonomy."""
        if not domain:
            return None
        domain = domain.strip().lower()
        # Map common variations to standard domains
        domain_map = {
            "fact": "facts",
            "admin": "management",
            "mgmt": "management",
            "util": "utility",
        }
        return domain_map.get(domain, domain)

    def _assert_no_routing_awareness(self, result: Dict[str, Any]) -> None:
        """Assert that Cognitive output doesn't contain routing decisions."""
        result_str = json.dumps(result).lower()
        forbidden = ("organ_id", "instance_id")
        if any(k in result_str for k in forbidden):
            raise ValueError(
                "Cognitive must not select organs/instances - routing decisions belong to Coordinator/Organism"
            )
        # Extra: forbid router-specific fields accidentally leaking
        if '"resolve-route"' in result_str or '"resolve-routes"' in result_str:
            raise ValueError("Cognitive must not call routing APIs")

    # ------------------------ Non-DSPy task handlers ------------------------
    def _handle_graph_embed(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "graph_embed",
                "domain": self._norm_domain("graph"),
                "params": {
                    "start_node_ids": start_node_ids,
                    "k": k,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_graph_rag_query(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        topk = kwargs.get("topk", 10)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "graph_rag_query",
                "domain": self._norm_domain("graph"),
                "params": {
                    "start_node_ids": start_node_ids,
                    "k": k,
                    "topk": topk,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_graph_sync_nodes(self, **kwargs) -> Dict[str, Any]:
        node_ids = kwargs.get("node_ids", [])
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "graph_sync_nodes",
                "domain": self._norm_domain("graph"),
                "params": {
                    "node_ids": node_ids,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.7,
        }

    def _handle_graph_fact_embed(self, **kwargs) -> Dict[str, Any]:
        start_fact_ids = kwargs.get("start_fact_ids", [])
        k = kwargs.get("k", 2)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "graph_fact_embed",
                "domain": self._norm_domain("facts"),
                "params": {
                    "start_fact_ids": start_fact_ids,
                    "k": k,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_graph_fact_query(self, **kwargs) -> Dict[str, Any]:
        start_fact_ids = kwargs.get("start_fact_ids", [])
        k = kwargs.get("k", 2)
        topk = kwargs.get("topk", 10)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "graph_fact_query",
                "domain": self._norm_domain("facts"),
                "params": {
                    "start_fact_ids": start_fact_ids,
                    "k": k,
                    "topk": topk,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_fact_search(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "fact_search",
                "domain": self._norm_domain("facts"),
                "params": {"query": query, "knowledge_context": knowledge_context},
            },
            "confidence_score": 0.8,
        }

    def _handle_fact_store(self, **kwargs) -> Dict[str, Any]:
        text = kwargs.get("text", "")
        tags = kwargs.get("tags", [])
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "fact_store",
                "domain": self._norm_domain("facts"),
                "params": {
                    "text": text,
                    "tags": tags,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.9,
        }

    def _handle_artifact_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        uri = kwargs.get("uri", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "artifact_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "uri": uri,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_capability_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        name = kwargs.get("name", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "capability_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "name": name,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_memory_cell_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        cell_id = kwargs.get("cell_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "memory_cell_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "cell_id": cell_id,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_model_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        name = kwargs.get("name", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "model_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "name": name,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_policy_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        policy_id = kwargs.get("policy_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "policy_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "policy_id": policy_id,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_service_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        service_id = kwargs.get("service_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "service_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "service_id": service_id,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }

    def _handle_skill_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        skill_id = kwargs.get("skill_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {
            "task": {
                "type": "skill_manage",
                "domain": self._norm_domain("management"),
                "params": {
                    "action": action,
                    "skill_id": skill_id,
                    "knowledge_context": knowledge_context,
                },
            },
            "confidence_score": 0.8,
        }


# =============================================================================
# Global Cognitive Core Instance Management
# =============================================================================
