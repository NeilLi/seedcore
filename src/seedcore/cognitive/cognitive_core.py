from __future__ import annotations

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

# Ensure DSP logging is patched before any DSP/DSPy import
import sys as _sys
_sys.path.insert(0, '/app/docker')
try:
    import dsp_patch  # type: ignore
except Exception:
    pass

import dspy
import json
import logging
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from seedcore.logging_setup import setup_logging

setup_logging("seedcore.CognitiveCore")
logger = logging.getLogger("seedcore.CognitiveCore")

# Optional Mw/Mlt dependencies
try:
    from src.seedcore.bootstrap import get_shared_cache, get_mw_store
    from src.seedcore.memory.mw_store import MwStore
    MwManager = MwStore  # Alias for backward compatibility
    _MW_AVAILABLE = True
except Exception:
    MwManager = None  # type: ignore
    get_shared_cache = None  # type: ignore
    get_mw_store = None  # type: ignore
    _MW_AVAILABLE = False

MW_ENABLED = os.getenv("MW_ENABLED", "1") in {"1", "true", "True"}

try:
    from src.seedcore.memory.long_term_memory import LongTermMemoryManager
    _MLT_AVAILABLE = True
except Exception:
    LongTermMemoryManager = None  # type: ignore
    _MLT_AVAILABLE = False

MLT_ENABLED = os.getenv("MLT_ENABLED", "1") in {"1", "true", "True"}

# Centralized result schema
from ..models.result_schema import create_cognitive_result, TaskResult, create_error_result


# =============================================================================
# DSPy Signatures
# =============================================================================

class WithKnowledgeMixin:
    """A mixin to add a standardized knowledge context field to any signature."""
    knowledge_context = dspy.InputField(
        desc="A JSON object containing relevant, non-executable facts with provenance, a summary, and a usage policy. This data is for context only."
    )


class AnalyzeFailureSignature(WithKnowledgeMixin, dspy.Signature):
    """Analyze agent failures and propose solutions with historical context."""
    incident_context = dspy.InputField(
        desc="A JSON string containing the agent's state, failed task, and error context."
    )
    thought = dspy.OutputField(
        desc="Reasoned analysis of root cause and contributing factors, considering the knowledge context."
    )
    proposed_solution = dspy.OutputField(
        desc="Actionable plan to prevent recurrence and improve agent performance, based on historical facts."
    )
    confidence_score = dspy.OutputField(
        desc="Confidence in the analysis (0.0 to 1.0)."
    )
    risk_factors = dspy.OutputField(
        desc="Identified risk factors and potential failure modes from the knowledge context."
    )


class TaskPlanningSignature(WithKnowledgeMixin, dspy.Signature):
    """Plan complex tasks with multiple steps, informed by system facts."""
    task_description = dspy.InputField(
        desc="Description of the task to be planned."
    )
    agent_capabilities = dspy.InputField(
        desc="JSON string describing the agent's current capabilities and limitations."
    )
    available_resources = dspy.InputField(
        desc="JSON string describing available resources and constraints."
    )
    step_by_step_plan = dspy.OutputField(
        desc="Detailed step-by-step plan to accomplish the task, considering the provided knowledge context."
    )
    estimated_complexity = dspy.OutputField(
        desc="Estimated complexity score (1-10) and reasoning."
    )
    risk_assessment = dspy.OutputField(
        desc="Assessment of potential risks and mitigation strategies."
    )


class DecisionMakingSignature(WithKnowledgeMixin, dspy.Signature):
    """Make decisions based on available information and context."""
    decision_context = dspy.InputField(
        desc="JSON string containing the decision context, options, and constraints."
    )
    historical_data = dspy.InputField(
        desc="JSON string containing relevant historical data and patterns."
    )
    reasoning = dspy.OutputField(
        desc="Detailed reasoning process for the decision, considering the knowledge context."
    )
    decision = dspy.OutputField(
        desc="The chosen decision with justification, considering the knowledge context."
    )
    confidence = dspy.OutputField(
        desc="Confidence level in the decision (0.0 to 1.0)."
    )
    alternative_options = dspy.OutputField(
        desc="Alternative options considered and why they were not chosen."
    )


class ProblemSolvingSignature(WithKnowledgeMixin, dspy.Signature):
    """Solve complex problems using systematic reasoning."""
    problem_statement = dspy.InputField(
        desc="Clear statement of the problem to be solved."
    )
    constraints = dspy.InputField(
        desc="JSON string describing constraints and limitations."
    )
    available_tools = dspy.InputField(
        desc="JSON string describing available tools and capabilities."
    )
    solution_approach = dspy.OutputField(
        desc="Systematic approach to solving the problem, considering the knowledge context."
    )
    solution_steps = dspy.OutputField(
        desc="Detailed steps to implement the solution."
    )
    success_metrics = dspy.OutputField(
        desc="Metrics to measure solution success."
    )


class MemorySynthesisSignature(WithKnowledgeMixin, dspy.Signature):
    """Synthesize information from multiple memory sources."""
    memory_fragments = dspy.InputField(
        desc="JSON string containing multiple memory fragments to synthesize."
    )
    synthesis_goal = dspy.InputField(
        desc="Goal of the memory synthesis (e.g., pattern recognition, insight generation)."
    )
    synthesized_insight = dspy.OutputField(
        desc="Synthesized insight or pattern from the memory fragments, considering the knowledge context."
    )
    confidence_level = dspy.OutputField(
        desc="Confidence in the synthesis (0.0 to 1.0)."
    )
    related_patterns = dspy.OutputField(
        desc="Related patterns or insights that emerged during synthesis."
    )


class CapabilityAssessmentSignature(WithKnowledgeMixin, dspy.Signature):
    """Assess agent capabilities and suggest improvements."""
    agent_performance_data = dspy.InputField(
        desc="JSON string containing agent performance metrics and history."
    )
    current_capabilities = dspy.InputField(
        desc="JSON string describing current agent capabilities."
    )
    target_capabilities = dspy.InputField(
        desc="JSON string describing desired target capabilities."
    )
    capability_gaps = dspy.OutputField(
        desc="Identified gaps between current and target capabilities, considering the knowledge context."
    )
    improvement_plan = dspy.OutputField(
        desc="Detailed plan to improve agent capabilities."
    )
    priority_recommendations = dspy.OutputField(
        desc="Priority recommendations for capability development."
    )


# =============================================================================
# Types
# =============================================================================

@dataclass
class Fact:
    id: str
    text: str
    score: float
    source: str
    source_uri: Optional[str] = None
    timestamp: Optional[float] = None
    trust: float = 0.5
    signature: Optional[str] = None
    staleness_s: Optional[float] = None
    instructions_present: bool = False
    sanitized_text: Optional[str] = None
    conflict_set: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.sanitized_text is None:
            self.sanitized_text = self._sanitize_text(self.text)
        if self.timestamp is not None and self.staleness_s is None:
            self.staleness_s = time.time() - self.timestamp

    def _sanitize_text(self, text: str) -> str:
        text = re.sub(r'```[\s\S]*?```', '[CODE_BLOCK_REMOVED]', text)
        text = re.sub(r'`[^`]+`', '[INLINE_CODE_REMOVED]', text)
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '[URL_REMOVED]', text)
        text = re.sub(r'@\w+', '[MENTION_REMOVED]', text)
        text = re.sub(r'<script[\s\S]*?</script>', '[SCRIPT_REMOVED]', text, flags=re.IGNORECASE)
        text = re.sub(r'<iframe[\s\S]*?</iframe>', '[IFRAME_REMOVED]', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip()
        self.instructions_present = bool(re.search(r'(?:instruction|command|execute|run|do|perform)', text, re.IGNORECASE))
        return text

    def is_stale(self, max_age_s: float = 3600) -> bool:
        if self.staleness_s is None:
            return False
        return self.staleness_s > max_age_s

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'text': self.text,
            'sanitized_text': self.sanitized_text,
            'score': self.score,
            'source': self.source,
            'source_uri': self.source_uri,
            'timestamp': self.timestamp,
            'trust': self.trust,
            'signature': self.signature,
            'staleness_s': self.staleness_s,
            'instructions_present': self.instructions_present,
            'conflict_set': self.conflict_set
        }


@dataclass
class RetrievalSufficiency:
    coverage: float
    diversity: float
    agreement: float
    token_budget: int
    token_est: int
    conflict_count: int
    staleness_ratio: float
    trust_score: float


class CognitiveTaskType(Enum):
    FAILURE_ANALYSIS = "failure_analysis"
    TASK_PLANNING = "task_planning"
    DECISION_MAKING = "decision_making"
    PROBLEM_SOLVING = "problem_solving"
    MEMORY_SYNTHESIS = "memory_synthesis"
    CAPABILITY_ASSESSMENT = "capability_assessment"

    # Graph tasks
    GRAPH_EMBED = "graph_embed"
    GRAPH_RAG_QUERY = "graph_rag_query"
    GRAPH_EMBED_V2 = "graph_embed_v2"
    GRAPH_RAG_QUERY_V2 = "graph_rag_query_v2"
    GRAPH_SYNC_NODES = "graph_sync_nodes"

    # Facts system
    GRAPH_FACT_EMBED = "graph_fact_embed"
    GRAPH_FACT_QUERY = "graph_fact_query"
    FACT_SEARCH = "fact_search"
    FACT_STORE = "fact_store"

    # Resource management
    ARTIFACT_MANAGE = "artifact_manage"
    CAPABILITY_MANAGE = "capability_manage"
    MEMORY_CELL_MANAGE = "memory_cell_manage"

    # Agent layer
    MODEL_MANAGE = "model_manage"
    POLICY_MANAGE = "policy_manage"
    SERVICE_MANAGE = "service_manage"
    SKILL_MANAGE = "skill_manage"


@dataclass
class CognitiveContext:
    agent_id: str
    task_type: CognitiveTaskType
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None


# =============================================================================
# Context Broker
# =============================================================================

class ContextBroker:
    def __init__(self, text_search_func, vector_search_func, token_budget: int = 1500, ocps_client=None, energy_client=None):
        self.text_search = text_search_func
        self.vector_search = vector_search_func
        self.base_token_budget = token_budget
        self.token_budget = token_budget
        self.ocps_client = ocps_client
        self.energy_client = energy_client
        self.schema_version = "v2.0"
        logger.info(f"ContextBroker v2 initialized with base token budget of {token_budget}.")

    def retrieve(self, query: str, k: int = 20, task_type: Optional[CognitiveTaskType] = None) -> Tuple[List[Fact], RetrievalSufficiency]:
        expanded_queries = self._expand_query(query)
        text_hits: List[Dict[str, Any]] = []
        vec_hits: List[Dict[str, Any]] = []
        for eq in expanded_queries:
            text_hits.extend(self.text_search(eq, k=k // max(1, len(expanded_queries))))
            vec_hits.extend(self.vector_search(eq, k=k // max(1, len(expanded_queries))))
        text_facts = [self._dict_to_fact(hit, "text") for hit in text_hits]
        vec_facts = [self._dict_to_fact(hit, "vector") for hit in vec_hits]
        fused_facts = self._rrf_fuse(text_facts, vec_facts)
        diversified_facts = self._mmr_diversify(fused_facts, query, k)
        sufficiency = self._calculate_sufficiency(diversified_facts, query)
        return diversified_facts, sufficiency

    def budget(self, facts: List[Fact], task_type: Optional[CognitiveTaskType] = None) -> Tuple[List[Fact], str, RetrievalSufficiency]:
        self._update_dynamic_budget(task_type)
        fresh_facts = [f for f in facts if not f.is_stale() and f.trust > 0.3]
        kept: List[Fact] = []
        current_tokens = 0
        for fact in fresh_facts:
            tokens = self._estimate_tokens(fact.sanitized_text or fact.text)
            if current_tokens + tokens > self.token_budget:
                logger.warning(f"Token budget of {self.token_budget} reached. Truncating facts.")
                break
            kept.append(fact)
            current_tokens += tokens
        sufficiency = self._calculate_sufficiency(kept, "")
        sufficiency.token_budget = self.token_budget
        sufficiency.token_est = current_tokens
        summary = self._summarize(kept)
        return kept, summary, sufficiency

    def _expand_query(self, query: str) -> List[str]:
        expanded = [query]
        synonyms = {
            "error": ["failure", "issue", "problem", "bug"],
            "performance": ["speed", "efficiency", "throughput"],
            "memory": ["storage", "cache", "buffer"],
            "task": ["job", "work", "operation", "process"],
        }
        for term, syns in synonyms.items():
            if term.lower() in query.lower():
                for syn in syns[:2]:
                    expanded.append(query.lower().replace(term.lower(), syn))
        return expanded[:3]

    def _dict_to_fact(self, hit: Dict[str, Any], source_type: str) -> Fact:
        return Fact(
            id=hit.get("id", ""),
            text=hit.get("text", ""),
            score=hit.get("score", 0.0),
            source=hit.get("source", source_type),
            source_uri=hit.get("source_uri"),
            timestamp=hit.get("timestamp", time.time()),
            trust=hit.get("trust", 0.5),
            signature=hit.get("signature"),
        )

    def _rrf_fuse(self, text_facts: List[Fact], vec_facts: List[Fact]) -> List[Fact]:
        text_weight = 0.6
        vec_weight = 0.4
        all_facts: Dict[str, Fact] = {}
        for i, fact in enumerate(text_facts):
            if fact.id not in all_facts:
                all_facts[fact.id] = fact
            all_facts[fact.id].score += text_weight / (i + 60)
        for i, fact in enumerate(vec_facts):
            if fact.id not in all_facts:
                all_facts[fact.id] = fact
            all_facts[fact.id].score += vec_weight / (i + 60)
        return sorted(all_facts.values(), key=lambda x: x.score, reverse=True)

    def _mmr_diversify(self, facts: List[Fact], query: str, k: int) -> List[Fact]:
        if len(facts) <= k:
            return facts
        selected: List[Fact] = []
        remaining = facts.copy()
        if remaining:
            selected.append(remaining.pop(0))
        while len(selected) < k and remaining:
            best_fact: Optional[Fact] = None
            best_score = -1.0
            for fact in remaining:
                relevance = fact.score
                max_sim = max(self._similarity(fact, sel) for sel in selected) if selected else 0
                mmr_score = 0.7 * relevance - 0.3 * max_sim
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_fact = fact
            if best_fact:
                selected.append(best_fact)
                remaining.remove(best_fact)
            else:
                break
        return selected

    def _similarity(self, fact1: Fact, fact2: Fact) -> float:
        words1 = set((fact1.sanitized_text or fact1.text).lower().split())
        words2 = set((fact2.sanitized_text or fact2.text).lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        return intersection / union if union > 0 else 0.0

    def _calculate_sufficiency(self, facts: List[Fact], query: str) -> RetrievalSufficiency:
        if not facts:
            return RetrievalSufficiency(0.0, 0.0, 0.0, self.token_budget, 0, 0, 0.0, 0.0)
        coverage = sum(1 for f in facts if f.score > 0.5) / len(facts)
        if len(facts) <= 1:
            diversity = 1.0
        else:
            similarities: List[float] = []
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    similarities.append(self._similarity(facts[i], facts[j]))
            diversity = 1.0 - (sum(similarities) / len(similarities)) if similarities else 1.0
        conflict_count = sum(len(f.conflict_set) for f in facts)
        agreement = 1.0 - (conflict_count / len(facts)) if facts else 1.0
        stale_count = sum(1 for f in facts if f.is_stale())
        staleness_ratio = stale_count / len(facts) if facts else 0.0
        trust_score = sum(f.trust for f in facts) / len(facts) if facts else 0.0
        return RetrievalSufficiency(
            coverage=coverage,
            diversity=diversity,
            agreement=agreement,
            token_budget=self.token_budget,
            token_est=sum(self._estimate_tokens(f.sanitized_text or f.text) for f in facts),
            conflict_count=conflict_count,
            staleness_ratio=staleness_ratio,
            trust_score=trust_score,
        )

    def _update_dynamic_budget(self, task_type: Optional[CognitiveTaskType] = None):
        base_budget = self.base_token_budget
        if task_type:
            task_multipliers = {
                CognitiveTaskType.FAILURE_ANALYSIS: 1.2,
                CognitiveTaskType.TASK_PLANNING: 1.5,
                CognitiveTaskType.DECISION_MAKING: 1.0,
                CognitiveTaskType.PROBLEM_SOLVING: 1.3,
                CognitiveTaskType.MEMORY_SYNTHESIS: 1.4,
                CognitiveTaskType.CAPABILITY_ASSESSMENT: 1.1,
                CognitiveTaskType.GRAPH_EMBED: 1.2,
                CognitiveTaskType.GRAPH_RAG_QUERY: 1.1,
                CognitiveTaskType.GRAPH_EMBED_V2: 1.2,
                CognitiveTaskType.GRAPH_RAG_QUERY_V2: 1.1,
                CognitiveTaskType.GRAPH_SYNC_NODES: 1.0,
                CognitiveTaskType.GRAPH_FACT_EMBED: 1.3,
                CognitiveTaskType.GRAPH_FACT_QUERY: 1.2,
                CognitiveTaskType.FACT_SEARCH: 1.1,
                CognitiveTaskType.FACT_STORE: 1.0,
                CognitiveTaskType.ARTIFACT_MANAGE: 1.1,
                CognitiveTaskType.CAPABILITY_MANAGE: 1.1,
                CognitiveTaskType.MEMORY_CELL_MANAGE: 1.1,
                CognitiveTaskType.MODEL_MANAGE: 1.1,
                CognitiveTaskType.POLICY_MANAGE: 1.1,
                CognitiveTaskType.SERVICE_MANAGE: 1.1,
                CognitiveTaskType.SKILL_MANAGE: 1.1,
            }
            base_budget *= task_multipliers.get(task_type, 1.0)
        if self.energy_client:
            try:
                energy_state = self.energy_client.get_current_energy()
                if energy_state.get("total_energy", 1.0) < 0.5:
                    base_budget *= 0.8
            except Exception as e:
                logger.warning(f"Failed to get energy state: {e}")
        if self.ocps_client:
            try:
                ocps_status = self.ocps_client.get_status()
                if ocps_status.get("current_load", 0.5) > 0.8:
                    base_budget *= 0.7
            except Exception as e:
                logger.warning(f"Failed to get OCPS status: {e}")
        self.token_budget = max(500, int(base_budget))

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text) / 3.5))

    def _summarize(self, facts: List[Fact]) -> str:
        if not facts:
            return "No relevant facts found."
        keypoints: List[str] = []
        for fact in facts[:5]:
            text = fact.sanitized_text or fact.text
            keypoints.append(f"{text[:140]} (source: {fact.source}, trust: {fact.trust:.2f})")
        return "Key information includes: " + " • ".join(keypoints)


# =============================================================================
# Cognitive Service
# =============================================================================

class CognitiveCore(dspy.Module):
    """
    Enhanced cognitive core with OCPS integration, cache governance, and post-condition checks.
    
    This module integrates with SeedCore's memory, energy, and lifecycle systems
    to provide intelligent reasoning capabilities for agents with OCPS fast/deep path routing.
    """
    
    def __init__(self, llm_provider: str = "openai", model: str = "gpt-4o", 
                 context_broker: Optional[ContextBroker] = None, ocps_client=None):
        super().__init__()
        self.llm_provider = llm_provider
        self.model = model
        self.ocps_client = ocps_client
        self.schema_version = "v2.0"
        
        # Initialize Mw/Mlt support first
        self._mw_enabled = bool(MW_ENABLED and _MW_AVAILABLE)
        self._mw_by_agent: Dict[str, MwManager] = {} if self._mw_enabled else {}
        self._mlt_enabled = bool(MLT_ENABLED and _MLT_AVAILABLE)
        self._mlt = LongTermMemoryManager() if self._mlt_enabled else None
        
        # Create ContextBroker with Mw/Mlt search functions if none provided
        if context_broker is None:
            # Create lambda functions that will be bound to agent_id at call time
            text_fn = lambda query, k: self._mw_first_text_search("", query, k)  # Will be overridden in process()
            vec_fn = lambda query, k: self._mw_first_vector_search("", query, k)  # Will be overridden in process()
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
            CognitiveTaskType.FAILURE_ANALYSIS: self.failure_analyzer,
            CognitiveTaskType.TASK_PLANNING: self.task_planner,
            CognitiveTaskType.DECISION_MAKING: self.decision_maker,
            CognitiveTaskType.PROBLEM_SOLVING: self.problem_solver,
            CognitiveTaskType.MEMORY_SYNTHESIS: self.memory_synthesizer,
            CognitiveTaskType.CAPABILITY_ASSESSMENT: self.capability_assessor,
            
            # Graph task handlers (Migration 007+)
            CognitiveTaskType.GRAPH_EMBED: self._handle_graph_embed,
            CognitiveTaskType.GRAPH_RAG_QUERY: self._handle_graph_rag_query,
            CognitiveTaskType.GRAPH_EMBED_V2: self._handle_graph_embed_v2,
            CognitiveTaskType.GRAPH_RAG_QUERY_V2: self._handle_graph_rag_query_v2,
            CognitiveTaskType.GRAPH_SYNC_NODES: self._handle_graph_sync_nodes,
            
            # Facts system handlers (Migration 009)
            CognitiveTaskType.GRAPH_FACT_EMBED: self._handle_graph_fact_embed,
            CognitiveTaskType.GRAPH_FACT_QUERY: self._handle_graph_fact_query,
            CognitiveTaskType.FACT_SEARCH: self._handle_fact_search,
            CognitiveTaskType.FACT_STORE: self._handle_fact_store,
            
            # Resource management handlers (Migration 007)
            CognitiveTaskType.ARTIFACT_MANAGE: self._handle_artifact_manage,
            CognitiveTaskType.CAPABILITY_MANAGE: self._handle_capability_manage,
            CognitiveTaskType.MEMORY_CELL_MANAGE: self._handle_memory_cell_manage,
            
            # Agent layer handlers (Migration 008)
            CognitiveTaskType.MODEL_MANAGE: self._handle_model_manage,
            CognitiveTaskType.POLICY_MANAGE: self._handle_policy_manage,
            CognitiveTaskType.SERVICE_MANAGE: self._handle_service_manage,
            CognitiveTaskType.SKILL_MANAGE: self._handle_skill_manage,
        }
        
        # Cache governance settings - shorter TTLs for sufficiency-bearing results
        self.cache_ttl_by_task = {
            CognitiveTaskType.FAILURE_ANALYSIS: 300,  # 5 minutes (volatile analysis)
            CognitiveTaskType.TASK_PLANNING: 600,     # 10 minutes (sufficiency data)
            CognitiveTaskType.DECISION_MAKING: 600,   # 10 minutes (sufficiency data)
            CognitiveTaskType.PROBLEM_SOLVING: 600,   # 10 minutes (sufficiency data)
            CognitiveTaskType.MEMORY_SYNTHESIS: 1800, # 30 minutes (no sufficiency)
            CognitiveTaskType.CAPABILITY_ASSESSMENT: 600, # 10 minutes (sufficiency data)
            
            # Graph task TTLs (Migration 007+) - shorter for sufficiency-bearing
            CognitiveTaskType.GRAPH_EMBED: 600,        # 10 minutes (sufficiency data)
            CognitiveTaskType.GRAPH_RAG_QUERY: 600,    # 10 minutes (sufficiency data)
            CognitiveTaskType.GRAPH_EMBED_V2: 600,     # 10 minutes (sufficiency data)
            CognitiveTaskType.GRAPH_RAG_QUERY_V2: 600, # 10 minutes (sufficiency data)
            CognitiveTaskType.GRAPH_SYNC_NODES: 1800,  # 30 minutes (no sufficiency)
            
            # Facts system TTLs (Migration 009) - shorter for sufficiency-bearing
            CognitiveTaskType.GRAPH_FACT_EMBED: 600,   # 10 minutes (sufficiency data)
            CognitiveTaskType.GRAPH_FACT_QUERY: 600,   # 10 minutes (sufficiency data)
            CognitiveTaskType.FACT_SEARCH: 600,        # 10 minutes (sufficiency data)
            CognitiveTaskType.FACT_STORE: 300,         # 5 minutes (storage is immediate)
            
            # Resource management TTLs (Migration 007)
            CognitiveTaskType.ARTIFACT_MANAGE: 1800,   # 30 minutes (artifacts are stable)
            CognitiveTaskType.CAPABILITY_MANAGE: 1800, # 30 minutes (capabilities are stable)
            CognitiveTaskType.MEMORY_CELL_MANAGE: 1800, # 30 minutes (memory cells are stable)
            
            # Agent layer TTLs (Migration 008)
            CognitiveTaskType.MODEL_MANAGE: 3600,      # 1 hour (models are stable)
            CognitiveTaskType.POLICY_MANAGE: 1800,     # 30 minutes (policies may change)
            CognitiveTaskType.SERVICE_MANAGE: 1800,    # 30 minutes (services may change)
            CognitiveTaskType.SKILL_MANAGE: 1800,      # 30 minutes (skills may change)
        }
        
        logger.info(f"Initialized CognitiveCore with {llm_provider} and model {model}")

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
        """Enhanced process method with OCPS integration and cache governance."""
        try:
            # Check cache first
            cache_key = self._generate_cache_key(context.task_type, context.agent_id, context.input_data)
            cached_result = self._get_cached_result(cache_key, context.task_type, agent_id=context.agent_id)
            if cached_result:
                logger.info(f"Cache hit for {context.task_type.value} task")
                return cached_result
            
            # Retrieve and budget facts
            if self.context_broker:
                # Create agent-specific search functions
                text_fn = lambda query, k: self._mw_first_text_search(context.agent_id, query, k)
                vec_fn = lambda query, k: self._mw_first_vector_search(context.agent_id, query, k)
                
                # Create a temporary ContextBroker with agent-specific search functions
                temp_broker = ContextBroker(text_fn, vec_fn, token_budget=1500, ocps_client=self.ocps_client)
                
                query = self._build_query(context)
                retrieve_start = time.time()
                facts, sufficiency = temp_broker.retrieve(query, k=20, task_type=context.task_type)
                retrieve_end = time.time()
                
                budget_start = time.time()
                budgeted_facts, summary, final_sufficiency = temp_broker.budget(facts, context.task_type)
                budget_end = time.time()
                
                # Store sufficiency for fragment helper
                self.last_sufficiency = final_sufficiency.__dict__
                
                # Backfill Mw with curated facts (sanitized) with TTL using global write-through
                if self._mw_enabled:
                    mw = self._mw(context.agent_id)
                    if mw:
                        for f in budgeted_facts[:10]:
                            try:
                                # Use global write-through for cluster-wide visibility
                                mw.set_global_item_typed("fact", "global", f.id, f.to_dict(), ttl_s=1800)
                                # Clear any negative cache for this fact
                                neg_key = f"_neg:fact:global:{f.id}"
                                if hasattr(mw, "del_key_sync"):
                                    mw.del_key_sync(neg_key)
                                elif hasattr(mw, "delete"):
                                    mw.delete(neg_key)
                                else:
                                    # last resort: overwrite with tiny TTL
                                    mw.set(neg_key, {"expired": True}, ttl_s=1)
                            except Exception:
                                pass

                # Optional promote: on high trust & coverage, store a compact synopsis in Mlt
                if self._mlt:
                    try:
                        if final_sufficiency.coverage > 0.7 and final_sufficiency.trust_score > 0.6:
                            synopsis = {
                                "agent_id": context.agent_id,
                                "task_type": context.task_type.value,
                                "summary": summary,
                                "facts": [{"id": f.id, "source": f.source, "score": f.score, "trust": f.trust} for f in budgeted_facts[:5]],
                                "ts": time.time(),
                            }
                            synopsis_id = f"cc:syn:{context.task_type.value}:{int(time.time())}"
                            self._mlt.store_holon(synopsis_id, synopsis)
                            
                            # Also cache synopsis globally for fast access
                            if self._mw_enabled and mw:
                                mw.set_global_item_typed("synopsis", "global", f"{context.task_type.value}:{context.agent_id}", 
                                                       synopsis, ttl_s=3600)
                    except Exception:
                        pass
                
                # Check if should escalate to deep path
                escalate_hint = self._should_escalate_to_deep_path(final_sufficiency, context.task_type)
                if escalate_hint:
                    logger.info(f"Suggesting escalation for {context.task_type.value} due to low sufficiency")
                    # Coordinator will decide whether to escalate based on this hint
                
                # Build knowledge context with escalation hint
                knowledge_context = self._build_knowledge_context(budgeted_facts, summary, final_sufficiency)
                knowledge_context["escalate_hint"] = escalate_hint
            else:
                knowledge_context = {"facts": [], "summary": "No context broker available", "sufficiency": {}, "escalate_hint": False}
                
                # Add negative cache for expensive deep-path misses
                if self._mw_enabled:
                    mw = self._mw(context.agent_id)
                    if mw:
                        try:
                            # Build a simple query for negative caching
                            query = self._build_query(context)
                            query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
                            mw.set_global_item_typed("_neg", "query", query_hash, "1", ttl_s=60)
                        except Exception:
                            pass
            
            # Process with appropriate handler
            handler = self.task_handlers.get(context.task_type)
            if not handler:
                return create_error_result(f"Unknown task type: {context.task_type}", "INVALID_TASK_TYPE")
            
            # Add knowledge context to input data
            enhanced_input = dict(context.input_data)
            enhanced_input["knowledge_context"] = json.dumps(knowledge_context)
            
            # Execute with post-condition checks
            raw = handler(**enhanced_input)
            # Normalize handler output into a dict
            payload = self._to_payload(raw)
            
            # Normalize task-specific fields
            if context.task_type == CognitiveTaskType.FAILURE_ANALYSIS:
                payload = self._normalize_failure_analysis(payload)
            
            # Check if this is a planning-style task that should return a plan
            escalate_hint = knowledge_context.get("escalate_hint", False)
            sufficiency = knowledge_context.get("sufficiency", {})
            confidence = payload.get("confidence_score")
            
            # Add planner timing metrics
            planner_timings = {}
            if 'retrieve_start' in locals() and 'retrieve_end' in locals():
                planner_timings["retrieve_ms"] = int((retrieve_end - retrieve_start) * 1000)
            if 'budget_start' in locals() and 'budget_end' in locals():
                planner_timings["budget_ms"] = int((budget_end - budget_start) * 1000)
            planner_timings["plan_build_ms"] = int((time.time() - (budget_end if 'budget_end' in locals() else time.time())) * 1000)
            
            if "task" in payload:
                # This is a single-step proposal, wrap it as a plan
                plan_result = self._wrap_single_step_as_plan(
                    payload["task"], 
                    escalate_hint, 
                    sufficiency,
                    confidence
                )
                # Update payload to include the plan
                payload["solution_steps"] = plan_result["solution_steps"]
                payload["meta"] = plan_result["meta"]
                payload["meta"]["planner_timings_ms"] = planner_timings
            
            # Validate post-conditions
            is_valid, violations = self._check_post_conditions(payload, context.task_type)
            if not is_valid:
                logger.warning(f"Post-condition violations: {violations}")
                # Could retry or escalate here
            
            out = create_cognitive_result(
                agent_id=context.agent_id,
                task_type=context.task_type.value,
                result=payload,
                confidence_score=payload.get("confidence_score"),
                cache_hit=False,
                sufficiency=final_sufficiency.__dict__ if 'final_sufficiency' in locals() else {},
                post_condition_violations=violations
            )
            # Backward-compat shim: keep 'result' until all tests are updated
            # Convert TaskResult to dict for backward compatibility
            out_dict = {
                "success": out.success,
                "result": out.payload.result if hasattr(out.payload, 'result') else {},
                "payload": out.payload.result if hasattr(out.payload, 'result') else {},
                "error": None,
                "metadata": out.metadata,
                "task_type": out.payload.task_type if hasattr(out.payload, 'task_type') else context.task_type.value,
            }
            
            # Cache the final standardized dict
            self._cache_result(cache_key, out_dict, context.task_type, agent_id=context.agent_id)
            
            # Guardrail: Ensure Cognitive doesn't select organs
            self._assert_no_routing_awareness(out_dict)
            
            return out_dict
            
        except Exception as e:
            logger.error(f"Error processing {context.task_type.value} task: {e}")
            return create_error_result(f"Processing error: {str(e)}", "PROCESSING_ERROR").model_dump()

    def forward(self, context: CognitiveContext) -> Dict[str, Any]:
        """
        Enhanced forward method with OCPS integration and cache governance.
        
        Args:
            context: CognitiveContext containing task information and agent state
            
        Returns:
            Dict containing the cognitive processing result with enhanced metadata
        """
        # Use the enhanced process method
        result = self.process(context)
        
        # Convert TaskResult to dict format for backward compatibility
        # Case 1: real TaskResult object
        if isinstance(result, TaskResult):
            return result.model_dump()

        # Case 2: dict already (shim from process)
        if isinstance(result, dict):
            # make sure keys exist
            return {
                "success": result.get("success", False),
                "result": result.get("result") or result.get("payload", {}),
                "payload": result.get("payload") or result.get("result", {}),
                "task_type": result.get("task_type", context.task_type.value),
                "metadata": result.get("metadata", {}),
                "error": result.get("error"),
            }

        # Case 3: something unexpected
        logger.warning(f"Unexpected result type in forward: {type(result)}")
        return {
            "success": False,
            "result": {},
            "payload": {},
            "task_type": context.task_type.value,
            "metadata": {},
            "error": f"Unsupported result type {type(result)}",
        }

    def build_fragments_for_synthesis(self, context: CognitiveContext, facts: List[Fact], summary: str) -> List[Dict[str, Any]]:
        """Build memory-synthesis fragments for Coordinator."""
        return [
            {"agent_id": context.agent_id},
            {"knowledge_summary": summary},
            {"top_facts": [f.to_dict() for f in facts[:5]]},
            {"ocps_sufficiency": getattr(self, "last_sufficiency", {})},
        ]

    # ------------------------ Helper Methods ------------------------
    def _generate_cache_key(self, task_type: CognitiveTaskType, agent_id: str, input_data: Dict[str, Any]) -> str:
        """Generate hardened cache key with provider, model, and schema version."""
        stable_hash = self._stable_hash(task_type, agent_id, input_data)
        return f"cc:res:{task_type.value}:{self.model}:{self.llm_provider}:{self.schema_version}:{stable_hash}"

    def _stable_hash(self, task_type: CognitiveTaskType, agent_id: str, input_data: Dict[str, Any]) -> str:
        """Stable hash of inputs (drop obviously-ephemeral fields if present)."""
        # Shallow sanitize to improve cache hit rate.
        sanitized = dict(input_data)
        # Drop ephemeral fields that shouldn't affect caching
        for key in ["timestamp", "created_at", "updated_at", "id", "request_id"]:
            sanitized.pop(key, None)
        
        # Create stable hash
        content = f"{task_type.value}:{agent_id}:{json.dumps(sanitized, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached_result(self, cache_key: str, task_type: CognitiveTaskType, *, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get cached result with TTL check."""
        if not self._mw_enabled:
            return None
        try:
            # Get agent-specific cache
            mw = self._mw(agent_id)
            if not mw:
                return None
            
            cached_data = mw.get_item(cache_key)  # Use sync method
            if not cached_data:
                return None
            
            # Check TTL
            ttl = self.cache_ttl_by_task.get(task_type, 600)
            cache_age = time.time() - cached_data.get("cached_at", 0)
            if cache_age > ttl:
                if hasattr(mw, "del_key_sync"):
                    mw.del_key_sync(cache_key)
                elif hasattr(mw, "delete"):
                    mw.delete(cache_key)
                else:
                    # last resort: overwrite with tiny TTL
                    mw.set(cache_key, {"expired": True}, ttl_s=1)
                return None
            
            logger.info(f"Cache hit: {cache_key} (age: {cache_age:.1f}s)")
            return cached_data["result"]  # Return the final dict directly
            
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
            return None

    def _cache_result(self, cache_key: str, result: Dict[str, Any], task_type: CognitiveTaskType, *, agent_id: str):
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
                "task_type": task_type.value,
                "schema_version": self.schema_version
            }
            
            mw.set(cache_key, cache_data)
            logger.info(f"Cached result: {cache_key}")
            
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")

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

    def _normalize_failure_analysis(self, payload: dict) -> dict:
        """Normalize failure analysis specific fields."""
        if "confidence_score" in payload:
            try:
                payload["confidence_score"] = float(payload["confidence_score"])
            except Exception:
                pass
        return payload

    def _check_post_conditions(self, result: Dict[str, Any], task_type: CognitiveTaskType) -> Tuple[bool, List[str]]:
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
        if task_type == CognitiveTaskType.TASK_PLANNING and "estimated_complexity" in result:
            try:
                complexity = float(result["estimated_complexity"])
                if not (1.0 <= complexity <= 10.0):
                    violations.append(f"Complexity score {complexity} out of bounds [1.0, 10.0]")
            except (ValueError, TypeError):
                violations.append("Invalid complexity score format")
        
        return len(violations) == 0, violations

    def _should_escalate_to_deep_path(self, sufficiency: RetrievalSufficiency, task_type: CognitiveTaskType) -> bool:
        """Determine if task should be escalated to deep path based on retrieval sufficiency."""
        if not self.ocps_client:
            return False
        
        # Escalation criteria
        low_coverage = sufficiency.coverage < 0.6
        low_diversity = sufficiency.diversity < 0.5
        high_conflict = sufficiency.conflict_count > 2
        high_staleness = sufficiency.staleness_ratio > 0.3
        low_trust = sufficiency.trust_score < 0.4
        
        # Complex tasks more likely to escalate
        complex_tasks = {CognitiveTaskType.TASK_PLANNING, CognitiveTaskType.PROBLEM_SOLVING, CognitiveTaskType.MEMORY_SYNTHESIS}
        is_complex = task_type in complex_tasks
        
        # Escalate if multiple conditions met
        escalation_score = sum([
            low_coverage, low_diversity, high_conflict, high_staleness, low_trust
        ])
        
        should_escalate = (escalation_score >= 2) or (is_complex and escalation_score >= 1)
        
        if should_escalate:
            logger.info(f"Suggesting escalation for {task_type.value}: coverage={sufficiency.coverage:.2f}, "
                       f"diversity={sufficiency.diversity:.2f}, conflicts={sufficiency.conflict_count}")
        
        return should_escalate

    def _build_query(self, context: CognitiveContext) -> str:
        """Build search query from context."""
        # Extract key information for search
        query_parts = []
        
        if context.task_type == CognitiveTaskType.FAILURE_ANALYSIS:
            incident = context.input_data.get("incident_context", {})
            query_parts.append(f"failure analysis {incident.get('error_type', '')}")
        elif context.task_type == CognitiveTaskType.TASK_PLANNING:
            task_desc = context.input_data.get("task_description", "")
            query_parts.append(f"task planning {task_desc}")
        elif context.task_type == CognitiveTaskType.DECISION_MAKING:
            decision_ctx = context.input_data.get("decision_context", {})
            query_parts.append(f"decision making {decision_ctx.get('options', '')}")
        elif context.task_type in (CognitiveTaskType.GRAPH_EMBED, CognitiveTaskType.GRAPH_EMBED_V2):
            start_node_ids = context.input_data.get("start_node_ids", [])
            query_parts.append(f"graph embedding nodes {start_node_ids}")
        elif context.task_type in (CognitiveTaskType.GRAPH_RAG_QUERY, CognitiveTaskType.GRAPH_RAG_QUERY_V2):
            start_node_ids = context.input_data.get("start_node_ids", [])
            query_parts.append(f"graph RAG query nodes {start_node_ids}")
        elif context.task_type == CognitiveTaskType.GRAPH_SYNC_NODES:
            node_ids = context.input_data.get("node_ids", [])
            query_parts.append(f"graph sync nodes {node_ids}")
        elif context.task_type in (CognitiveTaskType.GRAPH_FACT_EMBED, CognitiveTaskType.GRAPH_FACT_QUERY):
            start_fact_ids = context.input_data.get("start_fact_ids", [])
            query_parts.append(f"fact operations {start_fact_ids}")
        elif context.task_type == CognitiveTaskType.FACT_SEARCH:
            query = context.input_data.get("query", "")
            query_parts.append(f"fact search {query}")
        elif context.task_type == CognitiveTaskType.FACT_STORE:
            text = context.input_data.get("text", "")
            query_parts.append(f"fact store {text[:100]}")
        elif context.task_type in (CognitiveTaskType.ARTIFACT_MANAGE, CognitiveTaskType.CAPABILITY_MANAGE, 
                                  CognitiveTaskType.MEMORY_CELL_MANAGE):
            action = context.input_data.get("action", "")
            query_parts.append(f"resource management {action}")
        elif context.task_type in (CognitiveTaskType.MODEL_MANAGE, CognitiveTaskType.POLICY_MANAGE, 
                                  CognitiveTaskType.SERVICE_MANAGE, CognitiveTaskType.SKILL_MANAGE):
            action = context.input_data.get("action", "")
            query_parts.append(f"agent layer management {action}")
        else:
            query_parts.append(context.task_type.value)
        
        return " ".join(query_parts)

    def _build_knowledge_context(self, facts: List[Fact], summary: str, sufficiency: RetrievalSufficiency) -> Dict[str, Any]:
        """Build knowledge context for DSPy signatures."""
        return {
            "facts": [fact.to_dict() for fact in facts],
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
        mgr = self._mw_by_agent.get(agent_id)
        if mgr is None:
            try:
                mgr = MwManager(agent_id)
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
        # naive example: prefix scan or index lookup if your Mw supports it
        hits = mw.search_text(q, k=k) if hasattr(mw, "search_text") else []
        return hits

    def _mlt_text_search(self, q: str, k: int) -> List[Dict[str, Any]]:
        """Search text in Mlt."""
        if not self._mlt:
            return []
        return self._mlt.search_text(q, k=k) if hasattr(self._mlt, "search_text") else []

    def _mw_vector_search(self, agent_id: str, q: str, k: int) -> List[Dict[str, Any]]:
        """Search vectors in Mw for agent."""
        mw = self._mw(agent_id)
        if not mw:
            return []
        hits = mw.search_vector(q, k=k) if hasattr(mw, "search_vector") else []
        return hits

    def _mlt_vector_search(self, q: str, k: int) -> List[Dict[str, Any]]:
        """Search vectors in Mlt."""
        if not self._mlt:
            return []
        return self._mlt.search_vector(q, k=k) if hasattr(self._mlt, "search_vector") else []

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


def initialize_cognitive_core(llm_provider: str = "openai", model: str = "gpt-4o", context_broker: Optional[ContextBroker] = None, ocps_client=None) -> CognitiveCore:
    """Initialize the global cognitive core instance."""
    global COGNITIVE_CORE_INSTANCE
    
    if COGNITIVE_CORE_INSTANCE is None:
        try:
            # Configure DSPy with the LLM
            if llm_provider == "openai":
                llm = dspy.OpenAI(model=model, max_tokens=1024)
            else:
                # Add support for other providers as needed
                raise ValueError(f"Unsupported LLM provider: {llm_provider}")
            
            dspy.settings.configure(lm=llm)
            COGNITIVE_CORE_INSTANCE = CognitiveCore(llm_provider, model, context_broker, ocps_client=ocps_client)
            logger.info(f"Initialized global cognitive core with {llm_provider} and {model}")
            
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
