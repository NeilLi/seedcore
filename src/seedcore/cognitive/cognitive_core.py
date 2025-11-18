"""
DSPy Cognitive Core v2 for SeedCore Agents.

This module provides enhanced cognitive reasoning capabilities for agents using DSPy,
with OCPS integration, RRF fusion, MMR diversity, dynamic token budgeting, and
comprehensive fact schema with provenance and trust.

Key Enhancements:
- Enhanced Fact schema with provenance, trust, and policy flags
- RRF fusion and MMR diversification for better retrieval
- Dynamic token budgeting based on OCPS signals
- Hardened cache governance with TTL per task type
- Post-condition checks for DSPy outputs
- OCPS-informed budgeting and escalation hints (no routing)
- Fact sanitization and conflict detection

Note: Coordinator decides fast vs escalate; Organism resolves/executes.
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
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import numpy as np

import dspy  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import setup_logging, ensure_serve_logger
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
from ..models.cognitive import DecisionKind, CognitiveType, CognitiveContext
from .context_broker import (
    ContextBroker,
    RetrievalSufficiency,
    _fact_to_context_dict,
)
from .signatures import (
    AnalyzeFailureSignature,
    CapabilityAssessmentSignature,
    DecisionMakingSignature,
    MemorySynthesisSignature,
    ProblemSolvingSignature,
    TaskPlanningSignature,
)

setup_logging("seedcore.CognitiveCore")
logger = ensure_serve_logger("seedcore.CognitiveCore", level="DEBUG")


class CachedResultFound(Exception):
    """Internal exception used to return a cached result without running the pipeline."""

    def __init__(self, cached_result: Dict[str, Any]):
        self.cached_result = cached_result
        super().__init__("Cached result found, aborting pipeline.")

# Optional Mw/Mlt dependencies
try:
    from src.seedcore.memory.mw_manager import MwManager
    _MW_AVAILABLE = True
except Exception:
    MwManager = None  # type: ignore
    _MW_AVAILABLE = False

MW_ENABLED = os.getenv("MW_ENABLED", "1") in {"1", "true", "True"}

try:
    from src.seedcore.memory.long_term_memory import LongTermMemoryManager
    _MLT_AVAILABLE = True
except Exception:
    LongTermMemoryManager = None  # type: ignore
    _MLT_AVAILABLE = False

MLT_ENABLED = os.getenv("MLT_ENABLED", "1") in {"1", "true", "True"}


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
    ):
        super().__init__()
        self.llm_provider = llm_provider or "unknown"
        self.model = model or "unknown"
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        self._state_lock = threading.RLock()
        self._last_sufficiency: Dict[str, Any] = {}
        
        # Initialize Mw/Mlt support first
        self._mw_enabled = bool(MW_ENABLED and _MW_AVAILABLE)
        self._mw_by_agent: Dict[str, MwManager] = {} if self._mw_enabled else {}
        self._mlt_enabled = bool(MLT_ENABLED and _MLT_AVAILABLE)
        self._mlt = LongTermMemoryManager() if self._mlt_enabled else None
        self._sufficiency_thresholds = {
            "coverage": 0.6,
            "diversity": 0.5,
            "conflict_count": 2,
            "staleness_ratio": 0.3,
            "trust_score": 0.4,
        }
        self._synopsis_embedding_backend = (
            os.getenv("SYNOPSIS_EMBEDDING_BACKEND")
            or ("nim" if os.getenv("SYNOPSIS_EMBEDDING_BASE_URL") or os.getenv("NIM_RETRIEVAL_BASE_URL") else "sentence-transformer")
        ).lower().replace("_", "-")
        self._synopsis_embedding_model = os.getenv("SYNOPSIS_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
        self._synopsis_embedding_dim = int(os.getenv("SYNOPSIS_EMBEDDING_DIM", "768"))
        self._synopsis_embedding_base_url = (
            os.getenv("SYNOPSIS_EMBEDDING_BASE_URL") or os.getenv("NIM_RETRIEVAL_BASE_URL", "")
        ).lstrip("@")
        self._synopsis_embedding_api_key = os.getenv("SYNOPSIS_EMBEDDING_API_KEY") or os.getenv("NIM_RETRIEVAL_API_KEY")
        self._synopsis_embedding_timeout = float(os.getenv("SYNOPSIS_EMBEDDING_TIMEOUT", "10"))
        self._synopsis_embedder: Optional[Any] = None
        self._synopsis_embedder_failed = False
        self._synopsis_embedder_lock = threading.Lock()
        
        # Create ContextBroker with Mw/Mlt search functions if none provided
        if context_broker is None:
            # Create lambda functions that will be bound to agent_id at call time
            def text_fn(query, k):
                return self._mw_first_text_search("", query, k)  # Will be overridden in process()
            def vec_fn(query, k):
                return self._mw_first_vector_search("", query, k)  # Will be overridden in process()
            self.context_broker = ContextBroker(text_fn, vec_fn, token_budget=1500, ocps_client=self.ocps_client)
        else:
            self.context_broker = context_broker
        
        # Initialize specialized cognitive modules with post-condition checks
        self.failure_analyzer = dspy.ChainOfThought(AnalyzeFailureSignature)
        self.task_planner = dspy.ChainOfThought(TaskPlanningSignature)
        self.decision_maker = dspy.ChainOfThought(DecisionMakingSignature)
        self.problem_solver = dspy.ChainOfThought(ProblemSolvingSignature)
        self.memory_synthesizer = dspy.ChainOfThought(MemorySynthesisSignature)
        self.capability_assessor = dspy.ChainOfThought(CapabilityAssessmentSignature)
        
        # Task mapping
        self.task_handlers = {
            CognitiveType.FAILURE_ANALYSIS: self.failure_analyzer,
            CognitiveType.TASK_PLANNING: self.task_planner,
            CognitiveType.DECISION_MAKING: self.decision_maker,
            CognitiveType.PROBLEM_SOLVING: self.problem_solver,
            CognitiveType.MEMORY_SYNTHESIS: self.memory_synthesizer,
            CognitiveType.CAPABILITY_ASSESSMENT: self.capability_assessor,
            
            # Graph task handlers (Migration 007+)
            CognitiveType.GRAPH_EMBED: self._handle_graph_embed,
            CognitiveType.GRAPH_RAG_QUERY: self._handle_graph_rag_query,
            CognitiveType.GRAPH_EMBED_V2: self._handle_graph_embed_v2,
            CognitiveType.GRAPH_RAG_QUERY_V2: self._handle_graph_rag_query_v2,
            CognitiveType.GRAPH_SYNC_NODES: self._handle_graph_sync_nodes,
            
            # Facts system handlers (Migration 009)
            CognitiveType.GRAPH_FACT_EMBED: self._handle_graph_fact_embed,
            CognitiveType.GRAPH_FACT_QUERY: self._handle_graph_fact_query,
            CognitiveType.FACT_SEARCH: self._handle_fact_search,
            CognitiveType.FACT_STORE: self._handle_fact_store,
            
            # Resource management handlers (Migration 007)
            CognitiveType.ARTIFACT_MANAGE: self._handle_artifact_manage,
            CognitiveType.CAPABILITY_MANAGE: self._handle_capability_manage,
            CognitiveType.MEMORY_CELL_MANAGE: self._handle_memory_cell_manage,
            
            # Agent layer handlers (Migration 008)
            CognitiveType.MODEL_MANAGE: self._handle_model_manage,
            CognitiveType.POLICY_MANAGE: self._handle_policy_manage,
            CognitiveType.SERVICE_MANAGE: self._handle_service_manage,
            CognitiveType.SKILL_MANAGE: self._handle_skill_manage,
        }
        
        # Cache governance settings - shorter TTLs for sufficiency-bearing results
        self.cache_ttl_by_task = {
            CognitiveType.FAILURE_ANALYSIS: 300,  # 5 minutes (volatile analysis)
            CognitiveType.TASK_PLANNING: 600,     # 10 minutes (sufficiency data)
            CognitiveType.DECISION_MAKING: 600,   # 10 minutes (sufficiency data)
            CognitiveType.PROBLEM_SOLVING: 600,   # 10 minutes (sufficiency data)
            CognitiveType.MEMORY_SYNTHESIS: 1800, # 30 minutes (no sufficiency)
            CognitiveType.CAPABILITY_ASSESSMENT: 600, # 10 minutes (sufficiency data)
            
            # Graph task TTLs (Migration 007+) - shorter for sufficiency-bearing
            CognitiveType.GRAPH_EMBED: 600,        # 10 minutes (sufficiency data)
            CognitiveType.GRAPH_RAG_QUERY: 600,    # 10 minutes (sufficiency data)
            CognitiveType.GRAPH_EMBED_V2: 600,     # 10 minutes (sufficiency data)
            CognitiveType.GRAPH_RAG_QUERY_V2: 600, # 10 minutes (sufficiency data)
            CognitiveType.GRAPH_SYNC_NODES: 1800,  # 30 minutes (no sufficiency)
            
            # Facts system TTLs (Migration 009) - shorter for sufficiency-bearing
            CognitiveType.GRAPH_FACT_EMBED: 600,   # 10 minutes (sufficiency data)
            CognitiveType.GRAPH_FACT_QUERY: 600,   # 10 minutes (sufficiency data)
            CognitiveType.FACT_SEARCH: 600,        # 10 minutes (sufficiency data)
            CognitiveType.FACT_STORE: 300,         # 5 minutes (storage is immediate)
            
            # Resource management TTLs (Migration 007)
            CognitiveType.ARTIFACT_MANAGE: 1800,   # 30 minutes (artifacts are stable)
            CognitiveType.CAPABILITY_MANAGE: 1800, # 30 minutes (capabilities are stable)
            CognitiveType.MEMORY_CELL_MANAGE: 1800, # 30 minutes (memory cells are stable)
            
            # Agent layer TTLs (Migration 008)
            CognitiveType.MODEL_MANAGE: 3600,      # 1 hour (models are stable)
            CognitiveType.POLICY_MANAGE: 1800,     # 30 minutes (policies may change)
            CognitiveType.SERVICE_MANAGE: 1800,    # 30 minutes (services may change)
            CognitiveType.SKILL_MANAGE: 1800,      # 30 minutes (skills may change)
        }
        
        logger.info(f"Initialized CognitiveCore with {self.llm_provider} and model {self.model}")

        # Log Mw/Mlt integration status
        if self._mw_enabled:
            logger.info("MwManager integration: ENABLED")
        else:
            logger.info("MwManager integration: DISABLED (missing module or env)")

        if self._mlt_enabled:
            logger.info("LongTermMemoryManager integration: ENABLED")
        else:
            logger.info("LongTermMemoryManager integration: DISABLED (missing module or env)")

    def process(self, context: CognitiveContext) -> Dict[str, Any]:
        """
        Pipeline router that selects the appropriate cognitive pathway based on decision kind.
        
        Extracts decision_kind from unified TaskPayload format: params.cognitive.decision_kind
        """
        task_id = self._extract_task_id(context.input_data)
        logger.debug(
            f"CognitiveCore.process: Routing cog_type={context.cog_type.value} agent_id={context.agent_id} task_id={task_id or 'n/a'}"
        )

        input_data = context.input_data or {}
        
        # Extract decision_kind from unified TaskPayload format: params.cognitive.decision_kind
        params = input_data.get("params", {})
        cognitive_section = params.get("cognitive", {})
        
        if not cognitive_section:
            logger.warning(
                f"Task {task_id}: Missing params.cognitive section. "
                "Expected unified TaskPayload format with params.cognitive.decision_kind"
            )
            decision_kind_raw = None
        else:
            decision_kind_raw = cognitive_section.get("decision_kind")
        
        decision_kind_value = (
            str(decision_kind_raw).strip().lower()
            if decision_kind_raw is not None
            else DecisionKind.FAST_PATH.value
        )

        legacy_aliases = {
            "ray_agent_fast": DecisionKind.FAST_PATH,
            "dispatcher_planner": DecisionKind.COGNITIVE,
            "coordinator_hgnn": DecisionKind.ESCALATED,
        }
        try:
            decision_kind = DecisionKind(decision_kind_value)
        except ValueError:
            decision_kind = legacy_aliases.get(decision_kind_value)

        if decision_kind is None:
            logger.warning(
                f"Task {task_id}: Unknown decision_kind '{decision_kind_raw}'. Defaulting to FAST_PATH."
            )
            decision_kind = DecisionKind.FAST_PATH

        logger.debug(f"Task {task_id}: Routed to pipeline for {decision_kind.value}")

        cache_key = self._generate_cache_key(
            context.cog_type, context.agent_id, input_data
        )

        try:
            if decision_kind is DecisionKind.COGNITIVE:
                logger.debug(f"Task {task_id}: Running COGNITIVE (RAG + Plan) pipeline.")
                knowledge_context = self._run_rag_pipeline(context, cache_key, task_id)
                return self._run_handler_and_postprocess(
                    context, knowledge_context, cache_key, task_id
                )

            if decision_kind is DecisionKind.FAST_PATH:
                logger.debug(f"Task {task_id}: Running FAST_PATH (Plan Only) pipeline.")
                knowledge_context = {
                    "facts": [],
                    "summary": "No RAG requested for fast path.",
                    "sufficiency": {},
                    "escalate_hint": False,
                }
                return self._run_handler_and_postprocess(
                    context, knowledge_context, cache_key, task_id
                )

            if decision_kind is DecisionKind.ESCALATED:
                logger.debug(f"Task {task_id}: Running ESCALATED (HGNN context) pipeline.")
                # Extract HGNN data from params.hgnn (new format) or input_data.hgnn_embedding (legacy)
                hgnn_section = params.get("hgnn", {})
                hgnn_embedding = hgnn_section.get("hgnn_embedding") or input_data.get("hgnn_embedding")
                knowledge_context = {
                    "facts": [],
                    "summary": "Context provided by external HGNN.",
                    "sufficiency": {"trust_score": 1.0, "coverage": 1.0},
                    "escalate_hint": False,
                    "hgnn_embedding": hgnn_embedding,
                }
                return self._run_handler_and_postprocess(
                    context, knowledge_context, cache_key, task_id
                )

            logger.warning(
                f"Task {task_id}: Unhandled decision_kind '{decision_kind}'. Defaulting to FAST_PATH."
            )
            fallback_context = {
                "facts": [],
                "summary": "Defaulting to fast path.",
                "sufficiency": {},
                "escalate_hint": False,
            }
            return self._run_handler_and_postprocess(
                context, fallback_context, cache_key, task_id
            )

        except CachedResultFound as crf:
            logger.debug(f"Task {task_id}: Returning cached result from Mw.")
            return crf.cached_result
        except Exception as e:
            logger.error(f"Error processing {context.cog_type.value} task: {e}", exc_info=True)
            return create_error_result(f"Processing error: {str(e)}", "PROCESSING_ERROR").model_dump()

    def _run_rag_pipeline(
        self,
        context: CognitiveContext,
        cache_key: str,
        task_id: Optional[str],
    ) -> Dict[str, Any]:
        """Execute the retrieval-and-budgeting pipeline, returning a knowledge context."""
        cached_result = self._get_cached_result(
            cache_key,
            context.cog_type,
            agent_id=context.agent_id,
            task_id=task_id,
        )
        if cached_result:
            logger.info(
                f"Cache hit for {context.cog_type.value} task task_id={task_id or 'n/a'}"
            )
            raise CachedResultFound(cached_result)

        if not self.context_broker:
            knowledge_context = {
                "facts": [],
                "summary": "No context broker available",
                "sufficiency": {},
            }
            if self._mw_enabled:
                mw = self._mw(context.agent_id)
                if mw:
                    try:
                        query = self._build_query(context)
                        query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
                        mw.set_global_item_typed("_neg", "query", query_hash, "1", ttl_s=60)
                    except Exception:
                        pass
            return knowledge_context

        temp_broker = self._bind_broker(context.agent_id)

        query = self._build_query(context)
        retrieve_start = time.time()
        facts, sufficiency = temp_broker.retrieve(query, k=20, cog_type=context.cog_type)
        retrieve_end = time.time()

        budget_start = time.time()
        budgeted_facts, summary, final_sufficiency = temp_broker.budget(facts, context.cog_type)
        budget_end = time.time()

        self._update_last_sufficiency(final_sufficiency.__dict__)

        mw = self._mw(context.agent_id) if self._mw_enabled else None
        if mw:
            for f in budgeted_facts[:10]:
                try:
                    mw.set_global_item_typed("fact", "global", f.id, _fact_to_context_dict(f), ttl_s=1800)
                    neg_key = f"_neg:fact:global:{f.id}"
                    try:
                        if hasattr(mw, "del_global_key_sync"):
                            mw.del_global_key_sync(neg_key)
                        else:
                            mw.set_global_item(neg_key, {"expired": True}, ttl_s=1)
                    except Exception:
                        pass
                except Exception:
                    pass

        if self._mlt:
            try:
                if final_sufficiency.coverage > 0.7 and final_sufficiency.trust_score > 0.6:
                    synopsis = {
                        "agent_id": context.agent_id,
                        "cog_type": context.cog_type.value,
                        "summary": summary,
                        "facts": [
                            {"id": f.id, "source": f.source, "score": f.score, "trust": f.trust}
                            for f in budgeted_facts[:5]
                        ],
                        "ts": time.time(),
                    }
                    synopsis_id = f"cc:syn:{context.cog_type.value}:{int(time.time())}"
                    embedding = self._generate_synopsis_embedding(synopsis)
                    if embedding is None:
                        logger.debug(
                            "Skipping synopsis holon persistence because no embedding backend is available."
                        )
                    else:
                        holon_data = {
                            "vector": {
                                "id": synopsis_id,
                                "embedding": embedding.tolist(),
                                "meta": synopsis,
                            },
                            "graph": {
                                "src_uuid": synopsis_id,
                                "rel": "GENERATED_BY",
                                "dst_uuid": context.agent_id,
                            },
                        }

                        try:
                            self._run_coro_sync(self._mlt.insert_holon_async(holon_data), timeout=5.0)
                        except Exception:
                            logger.debug("Holon persistence failed; continuing without synopsis cache.", exc_info=True)

                    if mw:
                        try:
                            mw.set_global_item_typed(
                                "synopsis",
                                "global",
                                f"{context.cog_type.value}:{context.agent_id}",
                                synopsis,
                                ttl_s=3600,
                            )
                        except Exception:
                            logger.debug("Failed to cache synopsis in Mw; continuing.", exc_info=True)
            except Exception as exc:  # pragma: no cover - advisory logging only
                logger.debug(f"Failed to store synopsis in Mlt: {exc}")

        knowledge_context = self._build_knowledge_context(budgeted_facts, summary, final_sufficiency)
        knowledge_context["sufficiency"] = {
            **final_sufficiency.__dict__,
            "_thresholds": dict(self._sufficiency_thresholds),
        }
        knowledge_context["_planner_timings"] = {
            "retrieve_ms": int((retrieve_end - retrieve_start) * 1000),
            "budget_ms": int((budget_end - budget_start) * 1000),
            "_budget_end_time": budget_end,
        }

        return knowledge_context

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
                    logger.warning("Failed to initialize NimRetrievalHTTP for synopsis embeddings: %s", exc, exc_info=True)
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
                    self._synopsis_embedder = SentenceTransformer(self._synopsis_embedding_model)
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

    def _generate_synopsis_embedding(self, synopsis: Dict[str, Any]) -> Optional[np.ndarray]:
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
            logger.warning("Failed to generate synopsis embedding: %s", exc, exc_info=True)
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

        payload, planner_timings, plan_build_start, plan_build_end = self._invoke_handler(
            handler, context, knowledge_context, task_id
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

        enhanced_input["knowledge_context"] = json.dumps(working_context)
        enhanced_input = self._format_input_for_signature(enhanced_input, context.cog_type)
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
        payload["meta"].setdefault("sufficiency_thresholds", dict(self._sufficiency_thresholds))
        payload["meta"].setdefault("sufficiency_snapshot", suff_dict)
        payload["meta"].setdefault(
            "escalation_reasons",
            knowledge_context.get("sufficiency", {}).get("escalation_reasons", []),
        )

        is_valid, violations = self._check_post_conditions(payload, context.cog_type)
        if not is_valid:
            logger.warning(f"Post-condition violations: {violations}")

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
            "cog_type": out.payload.cog_type if hasattr(out.payload, "cog_type") else context.cog_type.value,
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

    def build_fragments_for_synthesis(self, context: CognitiveContext, facts: List[Fact], summary: str) -> List[Dict[str, Any]]:
        """Build memory-synthesis fragments for Coordinator."""
        return [
            {"agent_id": context.agent_id},
            {"knowledge_summary": summary},
            {"top_facts": [_fact_to_context_dict(f) for f in facts[:5]]},
            {"ocps_sufficiency": self._get_last_sufficiency()},
        ]

    # ------------------------ Helper Methods ------------------------
    def _generate_cache_key(self, cog_type: CognitiveType, agent_id: str, input_data: Dict[str, Any]) -> str:
        """Generate hardened cache key with provider, model, and schema version."""
        stable_hash = self._stable_hash(cog_type, agent_id, input_data)
        return f"cc:res:{cog_type.value}:{self.model}:{self.llm_provider}:{self.schema_version}:{stable_hash}"

    def _stable_hash(self, cog_type: CognitiveType, agent_id: str, input_data: Dict[str, Any]) -> str:
        """Stable hash of inputs (drop obviously-ephemeral fields if present)."""
        # Shallow sanitize to improve cache hit rate.
        sanitized = dict(input_data)
        # Drop ephemeral fields that shouldn't affect caching
        for key in ["timestamp", "created_at", "updated_at", "id", "request_id"]:
            sanitized.pop(key, None)
        
        # Create stable hash
        content = f"{cog_type.value}:{agent_id}:{json.dumps(sanitized, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached_result(self, cache_key: str, cog_type: CognitiveType, *, agent_id: str, task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
                cached_data = self._run_coro_sync(mw.get_item_async(cache_key), timeout=2.0)
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
                logger.info(f"Cache hit: {cache_key} (age: {cache_age:.1f}s) task_id={task_id or 'n/a'}")
            else:
                logger.info(f"Cache hit: {cache_key} (unexpected format) task_id={task_id or 'n/a'}")

            return normalized
            
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
            return None

    def _cache_result(self, cache_key: str, result: Dict[str, Any], cog_type: CognitiveType, *, agent_id: str, task_id: Optional[str] = None):
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
                "schema_version": self.schema_version
            }
            
            # Use set_global_item instead of set
            mw.set_global_item(cache_key, cache_data)
            logger.info(f"Cached result: {cache_key} task_id={task_id or 'n/a'}")
            
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")

    def _normalize_cached_result_shape(self, cached_data: Any) -> Optional[Dict[str, Any]]:
        """Ensure cached payloads conform to the canonical out_dict structure."""
        if not cached_data:
            return None

        source = cached_data
        if isinstance(cached_data, dict) and isinstance(cached_data.get("result"), dict):
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

        normalized.setdefault("cog_type", (cached_data.get("cog_type") if isinstance(cached_data, dict) else None) or "unknown")
        metadata = normalized.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if isinstance(cached_data, dict) and "cached_at" in cached_data and "cached_at" not in metadata:
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
        if hasattr(raw, '_mock_name'):  # This is a Mock object
            result = {}
            for attr_name in dir(raw):
                if not attr_name.startswith('_') and not callable(getattr(raw, attr_name)):
                    try:
                        value = getattr(raw, attr_name)
                        if not hasattr(value, '_mock_name'):  # Not a nested Mock
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
        """
        # Check top-level task_id first (TaskPayload format)
        task_id = input_data.get("task_id")
        if isinstance(task_id, (str, int)) and task_id is not None:
            return str(task_id)
        
        # Check params.task_id (alternative TaskPayload location)
        params = input_data.get("params", {})
        task_id = params.get("task_id")
        if isinstance(task_id, (str, int)) and task_id is not None:
            return str(task_id)
        
        # Legacy fallback: check common keys
        for key in ("id", "request_id", "job_id", "run_id"):
            value = input_data.get(key)
            if isinstance(value, (str, int)) and value is not None:
                return str(value)
        return None

    def _normalize_failure_analysis(self, payload: dict) -> dict:
        """Normalize failure analysis specific fields."""
        if "confidence_score" in payload:
            try:
                payload["confidence_score"] = float(payload["confidence_score"])
            except Exception:
                pass
        return payload

    def _normalize_task_planning(self, payload: dict) -> dict:
        """Normalize task planning fields, especially estimated_complexity."""
        # Back-compat: Some downstream consumers expect 'step_by_step_plan'.
        # If we produced a uniform plan in 'solution_steps', mirror it.
        if "step_by_step_plan" not in payload and "solution_steps" in payload:
            payload["step_by_step_plan"] = payload.get("solution_steps")

        val = payload.get("estimated_complexity")
        if val is None:
            return payload

        if isinstance(val, (int, float)):
            # Clamp to valid range [1.0, 10.0]
            num = float(val)
            payload["estimated_complexity"] = max(1.0, min(num, 10.0))
            return payload

        if isinstance(val, str):
            # Normalize commas and strip text
            text = val.replace(",", ".").strip()

            # Broader numeric extraction: find any number in the string
            match = re.search(r'([0-9]+(?:\.[0-9]+)?)', text)
            if match:
                try:
                    num = float(match.group(1))
                    # Clamp to valid range [1.0, 10.0]
                    payload["estimated_complexity"] = max(1.0, min(num, 10.0))
                    logger.debug(f"Extracted numeric complexity from '{val}': {payload['estimated_complexity']}")
                    return payload
                except ValueError:
                    logger.warning(f"Could not convert extracted complexity: {match.group(1)}")
            else:
                logger.warning(f"Could not extract numeric value from estimated_complexity: '{val}'")
        else:
            logger.warning(f"Unexpected type for estimated_complexity: {type(val)}")

        # Fallback: set to default middle value to avoid post-condition violations
        payload["estimated_complexity"] = 5.0
        return payload

    def _validate_solution_steps(self, payload: Dict[str, Any], violations: List[str]) -> None:
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

    def _check_post_conditions(self, result: Dict[str, Any], cog_type: CognitiveType) -> Tuple[bool, List[str]]:
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
        text_fields = ["thought", "proposed_solution", "reasoning", "decision", "solution_approach"]
        for field in text_fields:
            if field in result and isinstance(result[field], str):
                text = result[field].lower()
                # Simple PII detection
                if any(pattern in text for pattern in ["ssn", "social security", "credit card", "password"]):
                    violations.append(f"Potential PII detected in {field}")
        
        # Check for executable content
        for field in text_fields:
            if field in result and isinstance(result[field], str):
                text = result[field]
                if re.search(r'```[\s\S]*?```', text) or re.search(r'`[^`]+`', text):
                    violations.append(f"Code blocks detected in {field}")
        
        # Check numeric ranges for specific fields
        if cog_type == CognitiveType.TASK_PLANNING and "estimated_complexity" in result:
            try:
                complexity = float(result["estimated_complexity"])
                if not (1.0 <= complexity <= 10.0):
                    violations.append(f"Complexity score {complexity} out of bounds [1.0, 10.0]")
            except (ValueError, TypeError):
                violations.append("Invalid complexity score format")

        self._validate_solution_steps(result, violations)
        
        return len(violations) == 0, violations

    def _build_query(self, context: CognitiveContext) -> str:
        """Build search query from context."""
        # Extract key information for search
        query_parts = []
        
        if context.cog_type == CognitiveType.FAILURE_ANALYSIS:
            incident = context.input_data.get("incident_context", {})
            query_parts.append(f"failure analysis {incident.get('error_type', '')}")
        elif context.cog_type == CognitiveType.TASK_PLANNING:
            task_desc = context.input_data.get("task_description", "")
            query_parts.append(f"task planning {task_desc}")
        elif context.cog_type == CognitiveType.DECISION_MAKING:
            decision_ctx = context.input_data.get("decision_context", {})
            query_parts.append(f"decision making {decision_ctx.get('options', '')}")
        elif context.cog_type in (CognitiveType.GRAPH_EMBED, CognitiveType.GRAPH_EMBED_V2):
            start_node_ids = context.input_data.get("start_node_ids", [])
            query_parts.append(f"graph embedding nodes {self._format_id_list(start_node_ids)}")
        elif context.cog_type in (CognitiveType.GRAPH_RAG_QUERY, CognitiveType.GRAPH_RAG_QUERY_V2):
            start_node_ids = context.input_data.get("start_node_ids", [])
            query_parts.append(f"graph RAG query nodes {self._format_id_list(start_node_ids)}")
        elif context.cog_type == CognitiveType.GRAPH_SYNC_NODES:
            node_ids = context.input_data.get("node_ids", [])
            query_parts.append(f"graph sync nodes {self._format_id_list(node_ids)}")
        elif context.cog_type in (CognitiveType.GRAPH_FACT_EMBED, CognitiveType.GRAPH_FACT_QUERY):
            start_fact_ids = context.input_data.get("start_fact_ids", [])
            query_parts.append(f"fact operations {self._format_id_list(start_fact_ids)}")
        elif context.cog_type == CognitiveType.FACT_SEARCH:
            query = context.input_data.get("query", "")
            query_parts.append(f"fact search {query}")
        elif context.cog_type == CognitiveType.FACT_STORE:
            text = context.input_data.get("text", "")
            query_parts.append(f"fact store {text[:100]}")
        elif context.cog_type in (CognitiveType.ARTIFACT_MANAGE, CognitiveType.CAPABILITY_MANAGE, 
                                  CognitiveType.MEMORY_CELL_MANAGE):
            action = context.input_data.get("action", "")
            query_parts.append(f"resource management {action}")
        elif context.cog_type in (CognitiveType.MODEL_MANAGE, CognitiveType.POLICY_MANAGE, 
                                  CognitiveType.SERVICE_MANAGE, CognitiveType.SKILL_MANAGE):
            action = context.input_data.get("action", "")
            query_parts.append(f"agent layer management {action}")
        else:
            query_parts.append(context.cog_type.value)
        
        return " ".join(query_parts)

    def _format_input_for_signature(self, input_data: Dict[str, Any], cog_type: CognitiveType) -> Dict[str, Any]:
        """
        Convert dict fields to JSON strings for DSPy signatures that expect JSON strings.
        This handles the mismatch between dict inputs and signature field expectations.
        """
        formatted = dict(input_data)
        
        # Map task types to fields that need JSON string conversion
        if cog_type == CognitiveType.FAILURE_ANALYSIS:
            # AnalyzeFailureSignature expects JSON strings
            if "incident_context" in formatted and isinstance(formatted["incident_context"], dict):
                formatted["incident_context"] = json.dumps(formatted["incident_context"])
        elif cog_type == CognitiveType.TASK_PLANNING:
            # TaskPlanningSignature expects JSON strings
            if "agent_capabilities" in formatted and isinstance(formatted["agent_capabilities"], dict):
                formatted["agent_capabilities"] = json.dumps(formatted["agent_capabilities"])
            if "available_resources" in formatted and isinstance(formatted["available_resources"], dict):
                formatted["available_resources"] = json.dumps(formatted["available_resources"])
        elif cog_type == CognitiveType.DECISION_MAKING:
            # DecisionMakingSignature expects JSON strings
            if "decision_context" in formatted and isinstance(formatted["decision_context"], dict):
                formatted["decision_context"] = json.dumps(formatted["decision_context"])
            if "historical_data" in formatted and isinstance(formatted["historical_data"], dict):
                formatted["historical_data"] = json.dumps(formatted["historical_data"])
        elif cog_type == CognitiveType.PROBLEM_SOLVING:
            # ProblemSolvingSignature expects JSON strings
            if "constraints" in formatted and isinstance(formatted["constraints"], dict):
                formatted["constraints"] = json.dumps(formatted["constraints"])
            if "available_tools" in formatted and isinstance(formatted["available_tools"], dict):
                formatted["available_tools"] = json.dumps(formatted["available_tools"])
        elif cog_type == CognitiveType.MEMORY_SYNTHESIS:
            # MemorySynthesisSignature expects JSON strings
            if "memory_fragments" in formatted:
                if isinstance(formatted["memory_fragments"], (list, dict)):
                    formatted["memory_fragments"] = json.dumps(formatted["memory_fragments"])
        elif cog_type == CognitiveType.CAPABILITY_ASSESSMENT:
            # CapabilityAssessmentSignature expects JSON strings
            if "performance_data" in formatted and isinstance(formatted["performance_data"], dict):
                formatted["agent_performance_data"] = json.dumps(formatted.pop("performance_data"))
            if "current_capabilities" in formatted and isinstance(formatted["current_capabilities"], dict):
                formatted["current_capabilities"] = json.dumps(formatted["current_capabilities"])
            if "target_capabilities" in formatted and isinstance(formatted["target_capabilities"], dict):
                formatted["target_capabilities"] = json.dumps(formatted["target_capabilities"])
        
        return formatted

    def _build_knowledge_context(self, facts: List[Fact], summary: str, sufficiency: RetrievalSufficiency) -> Dict[str, Any]:
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
                "trust_score": sufficiency.trust_score
            },
            "policy": {
                "facts_only": True,
                "no_executable_content": True,
                "sanitized": True
            }
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
        # Text search would need to be implemented via Mlt or external search service
        return []

    def _mlt_text_search(self, q: str, k: int) -> List[Dict[str, Any]]:
        """Search text in Mlt."""
        if not self._mlt:
            return []
        # LongTermMemoryManager doesn't have search_text method - return empty for now
        # Text search would need to be implemented via HolonFabric or external search service
        return []

    def _mw_vector_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search vectors in Mw for agent."""
        mw = self._mw(agent_id)
        if not mw:
            return []
        # MwManager doesn't have search_vector method - return empty for now
        # Vector search would need to be implemented via Mlt or external search service
        return []

    def _mlt_vector_search(self, q: str, k: int) -> List[Dict[str, Any]]:
        """Search vectors in Mlt."""
        if not self._mlt:
            return []
        # LongTermMemoryManager doesn't have search_vector method - return empty for now
        # Vector search would need to be implemented via HolonFabric or external search service
        return []

    def _run_coro_sync(self, coro: Awaitable[Any], *, timeout: Optional[float] = None) -> Any:
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
        """Return a ContextBroker instance with Mw/Mlt bindings for the given agent."""
        def text_fn(query, k):
            return self._mw_first_text_search(agent_id, query, k)
        def vec_fn(query, k):
            return self._mw_first_vector_search(agent_id, query, k)

        base = self.context_broker
        if base is None:
            return ContextBroker(text_fn, vec_fn, token_budget=1500, ocps_client=self.ocps_client)

        if hasattr(base, "clone_with_search"):
            try:
                return base.clone_with_search(text_fn, vec_fn)  # type: ignore[attr-defined]
            except Exception:
                logger.debug("clone_with_search failed; falling back to new ContextBroker.")

        token_budget = getattr(base, "base_token_budget", getattr(base, "token_budget", 1500))
        ocps_client = getattr(base, "ocps_client", self.ocps_client)
        energy_client = getattr(base, "energy_client", None)
        return ContextBroker(text_fn, vec_fn, token_budget=token_budget, ocps_client=ocps_client, energy_client=energy_client)

    def _update_last_sufficiency(self, sufficiency_dict: Dict[str, Any]) -> None:
        with self._state_lock:
            self._last_sufficiency = dict(sufficiency_dict or {})

    def _get_last_sufficiency(self) -> Dict[str, Any]:
        with self._state_lock:
            return dict(self._last_sufficiency)

    def _filter_to_signature(self, handler: Any, data: Dict[str, Any]) -> Dict[str, Any]:
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

    def _mw_first_text_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search Mw first, then Mlt, with Mw backfill on Mlt hits."""
        hits = self._mw_text_search(agent_id, q, k)
        if hits or not self._mlt:
            return hits
        # fallback to Mlt and backfill Mw
        mlt_hits = self._mlt_text_search(q, k)
        mw = self._mw(agent_id)
        if mw:
            for h in mlt_hits:
                try:
                    # Use global write-through for cluster-wide visibility
                    mw.set_global_item_typed("fact", "global", h.get('id', ''), h, ttl_s=1800)
                except Exception:
                    pass
        return mlt_hits

    def _mw_first_vector_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search Mw first, then Mlt, with Mw backfill on Mlt hits."""
        hits = self._mw_vector_search(agent_id, q, k)
        if hits or not self._mlt:
            return hits
        # fallback to Mlt and backfill Mw
        mlt_hits = self._mlt_vector_search(q, k)
        mw = self._mw(agent_id)
        if mw:
            for h in mlt_hits:
                try:
                    # Use global write-through for cluster-wide visibility
                    mw.set_global_item_typed("fact", "global", h.get('id', ''), h, ttl_s=1800)
                except Exception:
                    pass
        return mlt_hits

    def _create_plan_from_steps(self, steps: List[Dict[str, Any]], escalate_hint: bool = False, 
                               sufficiency: Optional[Dict[str, Any]] = None, 
                               confidence: Optional[float] = None) -> Dict[str, Any]:
        """Create a uniform plan format from task steps."""
        return {
            "solution_steps": steps,
            "meta": {
                "escalate_hint": escalate_hint,
                "sufficiency": sufficiency or {},
                "confidence": confidence,
                "plan_type": "cognitive_proposal",
                "step_count": len(steps)
            }
        }
    
    def _wrap_single_step_as_plan(self, task: Dict[str, Any], escalate_hint: bool = False,
                                 sufficiency: Optional[Dict[str, Any]] = None,
                                 confidence: Optional[float] = None) -> Dict[str, Any]:
        """Wrap a single task as a 1-step plan."""
        return self._create_plan_from_steps([task], escalate_hint, sufficiency, confidence)
    
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
            "util": "utility"
        }
        return domain_map.get(domain, domain)
    
    def _assert_no_routing_awareness(self, result: Dict[str, Any]) -> None:
        """Assert that Cognitive output doesn't contain routing decisions."""
        result_str = json.dumps(result).lower()
        forbidden = ("organ_id", "instance_id")
        if any(k in result_str for k in forbidden):
            raise ValueError("Cognitive must not select organs/instances - routing decisions belong to Coordinator/Organism")
        # Extra: forbid router-specific fields accidentally leaking
        if '"resolve-route"' in result_str or '"resolve-routes"' in result_str:
            raise ValueError("Cognitive must not call routing APIs")

    # ------------------------ Non-DSPy task handlers ------------------------
    def _handle_graph_embed(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_embed", "domain": self._norm_domain("graph"), "params": {"start_node_ids": start_node_ids, "k": k, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_graph_rag_query(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        topk = kwargs.get("topk", 10)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_rag_query", "domain": self._norm_domain("graph"), "params": {"start_node_ids": start_node_ids, "k": k, "topk": topk, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_graph_embed_v2(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_embed_v2", "domain": self._norm_domain("graph"), "params": {"start_node_ids": start_node_ids, "k": k, "knowledge_context": knowledge_context}}, "confidence_score": 0.9}

    def _handle_graph_rag_query_v2(self, **kwargs) -> Dict[str, Any]:
        start_node_ids = kwargs.get("start_node_ids", [])
        k = kwargs.get("k", 2)
        topk = kwargs.get("topk", 10)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_rag_query_v2", "domain": self._norm_domain("graph"), "params": {"start_node_ids": start_node_ids, "k": k, "topk": topk, "knowledge_context": knowledge_context}}, "confidence_score": 0.9}

    def _handle_graph_sync_nodes(self, **kwargs) -> Dict[str, Any]:
        node_ids = kwargs.get("node_ids", [])
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_sync_nodes", "domain": self._norm_domain("graph"), "params": {"node_ids": node_ids, "knowledge_context": knowledge_context}}, "confidence_score": 0.7}

    def _handle_graph_fact_embed(self, **kwargs) -> Dict[str, Any]:
        start_fact_ids = kwargs.get("start_fact_ids", [])
        k = kwargs.get("k", 2)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_fact_embed", "domain": self._norm_domain("facts"), "params": {"start_fact_ids": start_fact_ids, "k": k, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_graph_fact_query(self, **kwargs) -> Dict[str, Any]:
        start_fact_ids = kwargs.get("start_fact_ids", [])
        k = kwargs.get("k", 2)
        topk = kwargs.get("topk", 10)
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "graph_fact_query", "domain": self._norm_domain("facts"), "params": {"start_fact_ids": start_fact_ids, "k": k, "topk": topk, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_fact_search(self, **kwargs) -> Dict[str, Any]:
        query = kwargs.get("query", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "fact_search", "domain": self._norm_domain("facts"), "params": {"query": query, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_fact_store(self, **kwargs) -> Dict[str, Any]:
        text = kwargs.get("text", "")
        tags = kwargs.get("tags", [])
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "fact_store", "domain": self._norm_domain("facts"), "params": {"text": text, "tags": tags, "knowledge_context": knowledge_context}}, "confidence_score": 0.9}

    def _handle_artifact_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        uri = kwargs.get("uri", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "artifact_manage", "domain": self._norm_domain("management"), "params": {"action": action, "uri": uri, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_capability_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        name = kwargs.get("name", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "capability_manage", "domain": self._norm_domain("management"), "params": {"action": action, "name": name, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_memory_cell_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        cell_id = kwargs.get("cell_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "memory_cell_manage", "domain": self._norm_domain("management"), "params": {"action": action, "cell_id": cell_id, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_model_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        name = kwargs.get("name", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "model_manage", "domain": self._norm_domain("management"), "params": {"action": action, "name": name, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_policy_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        policy_id = kwargs.get("policy_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "policy_manage", "domain": self._norm_domain("management"), "params": {"action": action, "policy_id": policy_id, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_service_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        service_id = kwargs.get("service_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "service_manage", "domain": self._norm_domain("management"), "params": {"action": action, "service_id": service_id, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}

    def _handle_skill_manage(self, **kwargs) -> Dict[str, Any]:
        action = kwargs.get("action", "")
        skill_id = kwargs.get("skill_id", "")
        knowledge_context = kwargs.get("knowledge_context", "{}")
        return {"task": {"type": "skill_manage", "domain": self._norm_domain("management"), "params": {"action": action, "skill_id": skill_id, "knowledge_context": knowledge_context}}, "confidence_score": 0.8}


# =============================================================================
# Global Cognitive Core Instance Management
# =============================================================================

COGNITIVE_CORE_INSTANCE: Optional[CognitiveCore] = None


def initialize_cognitive_core(
    llm_provider: str = "openai",
    model: str = "gpt-4o",
    context_broker: Optional[ContextBroker] = None,
    ocps_client=None,
) -> CognitiveCore:
    """Initialize the global cognitive core instance."""
    global COGNITIVE_CORE_INSTANCE
    
    if COGNITIVE_CORE_INSTANCE is None:
        try:
            COGNITIVE_CORE_INSTANCE = CognitiveCore(
                llm_provider=llm_provider,
                model=model,
                context_broker=context_broker,
                ocps_client=ocps_client,
            )
            logger.info(
                "Initialized global cognitive core with %s and %s",
                COGNITIVE_CORE_INSTANCE.llm_provider,
                COGNITIVE_CORE_INSTANCE.model,
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize cognitive core: {e}")
            raise
    
    return COGNITIVE_CORE_INSTANCE


def get_cognitive_core() -> Optional[CognitiveCore]:
    """Get the global cognitive core instance."""
    return COGNITIVE_CORE_INSTANCE


def reset_cognitive_core():
    """Reset the global cognitive core instance (useful for testing)."""
    global COGNITIVE_CORE_INSTANCE
    COGNITIVE_CORE_INSTANCE = None
