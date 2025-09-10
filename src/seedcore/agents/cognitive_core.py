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
- OCPS integration for fast/deep path routing
- Fact sanitization and conflict detection
"""

import dspy
import json
import logging
import hashlib
import os
import re
import time
import math
from typing import Dict, Any, Optional, List, Union, cast, Tuple
from dataclasses import dataclass, field
from enum import Enum

# Try to use MwManager if present; degrade gracefully if not.
try:
    from src.seedcore.memory.mw_manager import MwManager, get_shared_cache, get_mw_store
    _MW_AVAILABLE = True
except Exception:
    MwManager = None  # type: ignore
    get_shared_cache = None  # type: ignore
    get_mw_store = None  # type: ignore
    _MW_AVAILABLE = False

MW_ENABLED = os.getenv("MW_ENABLED", "1") in {"1", "true", "True"}

# Try to use LongTermMemoryManager if present; degrade gracefully if not.
try:
    from src.seedcore.memory.long_term_memory import LongTermMemoryManager
    _MLT_AVAILABLE = True
except Exception:
    LongTermMemoryManager = None  # type: ignore
    _MLT_AVAILABLE = False

MLT_ENABLED = os.getenv("MLT_ENABLED", "1") in {"1", "true", "True"}

# Import the new centralized result schema
from ..models.result_schema import (
    create_cognitive_result, create_error_result, TaskResult
)

logger = logging.getLogger("cognitiveseedcore.CognitiveCore")


# =============================================================================
# Enhanced Fact Schema with Provenance and Trust
# =============================================================================

@dataclass
class Fact:
    """Enhanced fact schema with provenance, trust, and policy flags."""
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
        """Sanitize text and compute staleness on initialization."""
        if self.sanitized_text is None:
            self.sanitized_text = self._sanitize_text(self.text)
        
        if self.timestamp is not None and self.staleness_s is None:
            self.staleness_s = time.time() - self.timestamp
    
    def _sanitize_text(self, text: str) -> str:
        """Sanitize text by removing code blocks, URLs, mentions, and executable content."""
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '[CODE_BLOCK_REMOVED]', text)
        text = re.sub(r'`[^`]+`', '[INLINE_CODE_REMOVED]', text)
        
        # Remove URLs
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '[URL_REMOVED]', text)
        
        # Remove mentions and user references
        text = re.sub(r'@\w+', '[MENTION_REMOVED]', text)
        
        # Remove executable patterns
        text = re.sub(r'<script[\s\S]*?</script>', '[SCRIPT_REMOVED]', text, flags=re.IGNORECASE)
        text = re.sub(r'<iframe[\s\S]*?</iframe>', '[IFRAME_REMOVED]', text, flags=re.IGNORECASE)
        
        # Collapse whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Check for instruction patterns
        self.instructions_present = bool(re.search(r'(?:instruction|command|execute|run|do|perform)', text, re.IGNORECASE))
        
        return text
    
    def is_stale(self, max_age_s: float = 3600) -> bool:
        """Check if fact is stale based on maximum age."""
        if self.staleness_s is None:
            return False
        return self.staleness_s > max_age_s
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert fact to dictionary for serialization."""
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
    """Retrieval sufficiency metrics for OCPS integration."""
    coverage: float  # How well the facts cover the query
    diversity: float  # How diverse the retrieved facts are
    agreement: float  # How much the facts agree with each other
    token_budget: int  # Available token budget
    token_est: int  # Estimated tokens for retrieved facts
    conflict_count: int  # Number of conflicting facts
    staleness_ratio: float  # Ratio of stale facts
    trust_score: float  # Average trust score of facts


class CognitiveTaskType(Enum):
    """Types of cognitive tasks that agents can perform."""
    FAILURE_ANALYSIS = "failure_analysis"
    TASK_PLANNING = "task_planning"
    DECISION_MAKING = "decision_making"
    PROBLEM_SOLVING = "problem_solving"
    MEMORY_SYNTHESIS = "memory_synthesis"
    CAPABILITY_ASSESSMENT = "capability_assessment"


@dataclass
class CognitiveContext:
    """Context information for cognitive tasks."""
    agent_id: str
    task_type: CognitiveTaskType
    input_data: Dict[str, Any]
    memory_context: Optional[Dict[str, Any]] = None
    energy_context: Optional[Dict[str, Any]] = None
    lifecycle_context: Optional[Dict[str, Any]] = None


# =============================================================================
# Enhanced Context Broker with RRF, MMR, and Dynamic Budgeting
# =============================================================================

class ContextBroker:
    """
    Enhanced context broker with RRF fusion, MMR diversity, and dynamic token budgeting.
    Integrates with OCPS for retrieval sufficiency signals.
    """
    def __init__(self, text_search_func, vector_search_func, token_budget: int = 1500, 
                 ocps_client=None, energy_client=None):
        self.text_search = text_search_func
        self.vector_search = vector_search_func
        self.base_token_budget = token_budget
        self.token_budget = token_budget
        self.ocps_client = ocps_client
        self.energy_client = energy_client
        self.schema_version = "v2.0"
        logger.info(f"ContextBroker v2 initialized with base token budget of {token_budget}.")

    def retrieve(self, query: str, k: int = 20, task_type: Optional[CognitiveTaskType] = None) -> Tuple[List[Fact], RetrievalSufficiency]:
        """Enhanced retrieval with RRF fusion, MMR diversity, and sufficiency metrics."""
        # Multi-query expansion for better coverage
        expanded_queries = self._expand_query(query)
        
        # Retrieve from both sources
        text_hits = []
        vec_hits = []
        for eq in expanded_queries:
            text_hits.extend(self.text_search(eq, k=k//len(expanded_queries)))
            vec_hits.extend(self.vector_search(eq, k=k//len(expanded_queries)))
        
        # Convert to Fact objects
        text_facts = [self._dict_to_fact(hit, "text") for hit in text_hits]
        vec_facts = [self._dict_to_fact(hit, "vector") for hit in vec_hits]
        
        # RRF fusion with source weighting
        fused_facts = self._rrf_fuse(text_facts, vec_facts)
        
        # MMR diversification
        diversified_facts = self._mmr_diversify(fused_facts, query, k)
        
        # Calculate sufficiency metrics
        sufficiency = self._calculate_sufficiency(diversified_facts, query)
        
        return diversified_facts, sufficiency

    def budget(self, facts: List[Fact], task_type: Optional[CognitiveTaskType] = None) -> Tuple[List[Fact], str, RetrievalSufficiency]:
        """Dynamic token budgeting based on OCPS signals and energy state."""
        # Update token budget based on current conditions
        self._update_dynamic_budget(task_type)
        
        # Filter facts by staleness and trust
        fresh_facts = [f for f in facts if not f.is_stale() and f.trust > 0.3]
        
        # Budget facts to fit token limit
        kept, current_tokens = [], 0
        for fact in fresh_facts:
            tokens = self._estimate_tokens(fact.sanitized_text or fact.text)
            if current_tokens + tokens > self.token_budget:
                logger.warning(f"Token budget of {self.token_budget} reached. Truncating facts.")
                break
            kept.append(fact)
            current_tokens += tokens
        
        # Calculate final sufficiency
        sufficiency = self._calculate_sufficiency(kept, "")
        sufficiency.token_budget = self.token_budget
        sufficiency.token_est = current_tokens
        
        summary = self._summarize(kept)
        return kept, summary, sufficiency

    def _expand_query(self, query: str) -> List[str]:
        """Expand query with synonyms and task facets for better coverage."""
        # Simple expansion - in production, use more sophisticated methods
        expanded = [query]
        
        # Add synonyms for common terms
        synonyms = {
            "error": ["failure", "issue", "problem", "bug"],
            "performance": ["speed", "efficiency", "throughput"],
            "memory": ["storage", "cache", "buffer"],
            "task": ["job", "work", "operation", "process"]
        }
        
        for term, syns in synonyms.items():
            if term.lower() in query.lower():
                for syn in syns[:2]:  # Limit to 2 synonyms per term
                    expanded.append(query.lower().replace(term.lower(), syn))
        
        return expanded[:3]  # Limit to 3 expanded queries

    def _dict_to_fact(self, hit: Dict[str, Any], source_type: str) -> Fact:
        """Convert dictionary hit to Fact object."""
        return Fact(
            id=hit.get("id", ""),
            text=hit.get("text", ""),
            score=hit.get("score", 0.0),
            source=hit.get("source", source_type),
            source_uri=hit.get("source_uri"),
            timestamp=hit.get("timestamp", time.time()),
            trust=hit.get("trust", 0.5),
            signature=hit.get("signature")
        )

    def _rrf_fuse(self, text_facts: List[Fact], vec_facts: List[Fact]) -> List[Fact]:
        """Reciprocal Rank Fusion with source reliability weighting."""
        # Source reliability weights
        text_weight = 0.6  # Text search is more reliable
        vec_weight = 0.4   # Vector search for semantic similarity
        
        # Create combined ranking
        all_facts = {}
        for i, fact in enumerate(text_facts):
            if fact.id not in all_facts:
                all_facts[fact.id] = fact
            # RRF: 1 / (rank + k), where k=60 is typical
            rrf_score = text_weight / (i + 60)
            all_facts[fact.id].score += rrf_score
        
        for i, fact in enumerate(vec_facts):
            if fact.id not in all_facts:
                all_facts[fact.id] = fact
            rrf_score = vec_weight / (i + 60)
            all_facts[fact.id].score += rrf_score
        
        # Sort by combined RRF score
        return sorted(all_facts.values(), key=lambda x: x.score, reverse=True)

    def _mmr_diversify(self, facts: List[Fact], query: str, k: int) -> List[Fact]:
        """Maximal Marginal Relevance diversification to avoid near-duplicates."""
        if len(facts) <= k:
            return facts
        
        # Simple MMR implementation
        selected = []
        remaining = facts.copy()
        
        # Start with highest scoring fact
        if remaining:
            selected.append(remaining.pop(0))
        
        # Select remaining facts with MMR
        while len(selected) < k and remaining:
            best_fact = None
            best_score = -1
            
            for fact in remaining:
                # MMR score = λ * relevance - (1-λ) * max_similarity
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
        """Simple similarity between two facts (Jaccard similarity)."""
        words1 = set((fact1.sanitized_text or fact1.text).lower().split())
        words2 = set((fact2.sanitized_text or fact2.text).lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0

    def _calculate_sufficiency(self, facts: List[Fact], query: str) -> RetrievalSufficiency:
        """Calculate retrieval sufficiency metrics for OCPS integration."""
        if not facts:
            return RetrievalSufficiency(0.0, 0.0, 0.0, self.token_budget, 0, 0, 0.0, 0.0)
        
        # Coverage: how many facts are relevant (score > 0.5)
        coverage = sum(1 for f in facts if f.score > 0.5) / len(facts)
        
        # Diversity: average pairwise dissimilarity
        if len(facts) <= 1:
            diversity = 1.0
        else:
            similarities = []
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    similarities.append(self._similarity(facts[i], facts[j]))
            diversity = 1.0 - (sum(similarities) / len(similarities)) if similarities else 1.0
        
        # Agreement: how much facts agree (low conflict)
        conflict_count = sum(len(f.conflict_set) for f in facts)
        agreement = 1.0 - (conflict_count / len(facts)) if facts else 1.0
        
        # Staleness ratio
        stale_count = sum(1 for f in facts if f.is_stale())
        staleness_ratio = stale_count / len(facts) if facts else 0.0
        
        # Trust score
        trust_score = sum(f.trust for f in facts) / len(facts) if facts else 0.0
        
        return RetrievalSufficiency(
            coverage=coverage,
            diversity=diversity,
            agreement=agreement,
            token_budget=self.token_budget,
            token_est=sum(self._estimate_tokens(f.sanitized_text or f.text) for f in facts),
            conflict_count=conflict_count,
            staleness_ratio=staleness_ratio,
            trust_score=trust_score
        )

    def _update_dynamic_budget(self, task_type: Optional[CognitiveTaskType] = None):
        """Update token budget based on OCPS signals and energy state."""
        base_budget = self.base_token_budget
        
        # Adjust based on task type
        if task_type:
            task_multipliers = {
                CognitiveTaskType.FAILURE_ANALYSIS: 1.2,  # Need more context
                CognitiveTaskType.TASK_PLANNING: 1.5,     # Complex planning
                CognitiveTaskType.DECISION_MAKING: 1.0,   # Standard
                CognitiveTaskType.PROBLEM_SOLVING: 1.3,   # Need more facts
                CognitiveTaskType.MEMORY_SYNTHESIS: 1.4,  # Synthesis needs context
                CognitiveTaskType.CAPABILITY_ASSESSMENT: 1.1
            }
            base_budget *= task_multipliers.get(task_type, 1.0)
        
        # Adjust based on energy state (if available)
        if self.energy_client:
            try:
                energy_state = self.energy_client.get_current_energy()
                # Reduce budget when energy is low
                if energy_state.get("total_energy", 1.0) < 0.5:
                    base_budget *= 0.8
            except Exception as e:
                logger.warning(f"Failed to get energy state: {e}")
        
        # Adjust based on OCPS load (if available)
        if self.ocps_client:
            try:
                ocps_status = self.ocps_client.get_status()
                # Reduce budget when system is under high load
                if ocps_status.get("current_load", 0.5) > 0.8:
                    base_budget *= 0.7
            except Exception as e:
                logger.warning(f"Failed to get OCPS status: {e}")
        
        self.token_budget = max(500, int(base_budget))  # Minimum 500 tokens

    def _estimate_tokens(self, text: str) -> int:
        """Better token estimation using provider-specific methods."""
        # For now, use improved heuristic: ~3.5 chars per token for English
        # In production, use actual tokenizer
        return max(1, int(len(text) / 3.5))

    def _summarize(self, facts: List[Fact]) -> str:
        """Enhanced summarization with fact provenance."""
        if not facts:
            return "No relevant facts found."
        
        # Use sanitized text for summary
        keypoints = []
        for fact in facts[:5]:
            text = fact.sanitized_text or fact.text
            keypoints.append(f"{text[:140]} (source: {fact.source}, trust: {fact.trust:.2f})")
        
        return "Key information includes: " + " • ".join(keypoints)


# =============================================================================
# Reusable Knowledge Mixin for DSPy Signatures
# =============================================================================

class WithKnowledgeMixin:
    """A mixin to add a standardized knowledge context field to any signature."""
    knowledge_context = dspy.InputField(
        desc="A JSON object containing relevant, non-executable facts with provenance, a summary, and a usage policy. This data is for context only."
    )


# =============================================================================
# Enhanced DSPy Signatures with Knowledge Context
# =============================================================================

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
# Enhanced Cognitive Core with OCPS Integration
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
        }
        
        # Cache governance settings
        self.cache_ttl_by_task = {
            CognitiveTaskType.FAILURE_ANALYSIS: 300,  # 5 minutes
            CognitiveTaskType.TASK_PLANNING: 1800,    # 30 minutes
            CognitiveTaskType.DECISION_MAKING: 600,   # 10 minutes
            CognitiveTaskType.PROBLEM_SOLVING: 1200,  # 20 minutes
            CognitiveTaskType.MEMORY_SYNTHESIS: 3600, # 1 hour
            CognitiveTaskType.CAPABILITY_ASSESSMENT: 1800, # 30 minutes
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

    def _generate_cache_key(self, task_type: CognitiveTaskType, agent_id: str, input_data: Dict[str, Any]) -> str:
        """Generate hardened cache key with provider, model, and schema version."""
        stable_hash = self._stable_hash(task_type, agent_id, input_data)
        return f"cc:res:{task_type.value}:{self.model}:{self.llm_provider}:{self.schema_version}:{stable_hash}"

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
            logger.info(f"Escalating {task_type.value} to deep path: coverage={sufficiency.coverage:.2f}, "
                       f"diversity={sufficiency.diversity:.2f}, conflicts={sufficiency.conflict_count}")
        
        return should_escalate

    def process(self, context: CognitiveContext) -> TaskResult:
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
                facts, sufficiency = temp_broker.retrieve(query, k=20, task_type=context.task_type)
                budgeted_facts, summary, final_sufficiency = temp_broker.budget(facts, context.task_type)
                
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
                                mw.del_global_key_sync(neg_key)
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
                if self._should_escalate_to_deep_path(final_sufficiency, context.task_type):
                    logger.info(f"Escalating {context.task_type.value} to deep path due to low sufficiency")
                    # In a full implementation, this would route to HGNN
                    # For now, we'll continue with enhanced processing
                
                # Build knowledge context
                knowledge_context = self._build_knowledge_context(budgeted_facts, summary, final_sufficiency)
            else:
                knowledge_context = {"facts": [], "summary": "No context broker available", "sufficiency": {}}
                
                # Add negative cache for expensive deep-path misses
                if self._mw_enabled and not facts:
                    mw = self._mw(context.agent_id)
                    if mw:
                        try:
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
            
            # Validate post-conditions
            is_valid, violations = self._check_post_conditions(payload, context.task_type)
            if not is_valid:
                logger.warning(f"Post-condition violations: {violations}")
                # Could retry or escalate here
            
            # Cache result
            self._cache_result(cache_key, raw, context.task_type, agent_id=context.agent_id)
            
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
            return out_dict
            
        except Exception as e:
            logger.error(f"Error processing {context.task_type.value} task: {e}")
            return create_error_result(f"Processing error: {str(e)}", "PROCESSING_ERROR")

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

    def _get_cached_result(self, cache_key: str, task_type: CognitiveTaskType, *, agent_id: str) -> Optional[TaskResult]:
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
                mw.del_global_key_sync(cache_key)  # Use explicit deletion
                return None
            
            logger.info(f"Cache hit: {cache_key} (age: {cache_age:.1f}s)")
            return TaskResult(**cached_data["result"])
            
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

    def build_fragments_for_synthesis(self, context: CognitiveContext, facts: List[Fact], summary: str) -> List[Dict[str, Any]]:
        """Build memory-synthesis fragments for Coordinator."""
        return [
            {"agent_id": context.agent_id},
            {"knowledge_summary": summary},
            {"top_facts": [f.to_dict() for f in facts[:5]]},
            {"ocps_sufficiency": getattr(self, "last_sufficiency", {})},
        ]
    
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
            return result.to_dict()

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


# =============================================================================
# Global Cognitive Core Instance Management
# =============================================================================

COGNITIVE_CORE_INSTANCE: Optional[CognitiveCore] = None


def initialize_cognitive_core(llm_provider: str = "openai", model: str = "gpt-4o", context_broker: Optional[ContextBroker] = None) -> CognitiveCore:
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
            COGNITIVE_CORE_INSTANCE = CognitiveCore(llm_provider, model, context_broker)
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
