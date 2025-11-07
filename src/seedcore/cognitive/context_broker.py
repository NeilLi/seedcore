"""Context broker utilities for the cognitive core."""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..logging_setup import setup_logging
from ..models.fact import Fact

if TYPE_CHECKING:
    from .cognitive_core import CognitiveTaskType


setup_logging("seedcore.ContextBroker")
logger = logging.getLogger("seedcore.ContextBroker")

__all__ = [
    "ContextBroker",
    "RetrievalSufficiency",
    "_sanitize_fact_text",
    "_fact_is_stale",
    "_fact_to_context_dict",
]


def _sanitize_fact_text(text: str) -> Tuple[str, bool]:
    sanitized = re.sub(r"```[\s\S]*?```", "[CODE_BLOCK_REMOVED]", text)
    sanitized = re.sub(r"`[^`]+`", "[INLINE_CODE_REMOVED]", sanitized)
    sanitized = re.sub(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        "[URL_REMOVED]",
        sanitized,
    )
    sanitized = re.sub(r"@\w+", "[MENTION_REMOVED]", sanitized)
    sanitized = re.sub(r"<script[\s\S]*?</script>", "[SCRIPT_REMOVED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<iframe[\s\S]*?</iframe>", "[IFRAME_REMOVED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    instructions_present = bool(re.search(r"(?:instruction|command|execute|run|do|perform)", sanitized, re.IGNORECASE))
    return sanitized, instructions_present


def _fact_is_stale(fact: Fact, max_age_s: float = 3600) -> bool:
    timestamp = getattr(fact, "timestamp", None)
    if timestamp is None:
        return False
    staleness = getattr(fact, "staleness_s", None)
    if staleness is None:
        staleness = time.time() - timestamp
        fact.staleness_s = staleness  # type: ignore[attr-defined]
    return staleness > max_age_s


def _fact_to_context_dict(fact: Fact) -> Dict[str, Any]:
    fact_to_dict = getattr(fact, "to_dict", None)
    if callable(fact_to_dict):
        try:
            base = fact_to_dict() or {}
        except Exception:
            base = {}
    else:
        base = {}

    base = dict(base)

    def _set(key: str, value: Any, default: Any = None) -> None:
        if value is not None:
            base[key] = value
        elif key not in base and default is not None:
            base[key] = default

    _set("id", getattr(fact, "id", base.get("id")))
    _set("text", getattr(fact, "text", base.get("text")), "")
    _set("sanitized_text", getattr(fact, "sanitized_text", base.get("sanitized_text")), base.get("text"))
    _set("score", getattr(fact, "score", base.get("score")), 0.0)
    _set("source", getattr(fact, "source", base.get("source")))
    _set("source_uri", getattr(fact, "source_uri", base.get("source_uri")))
    _set("timestamp", getattr(fact, "timestamp", base.get("timestamp")))
    _set("trust", getattr(fact, "trust", base.get("trust")), 0.5)
    _set("signature", getattr(fact, "signature", base.get("signature")))
    _set("staleness_s", getattr(fact, "staleness_s", base.get("staleness_s")))
    _set("instructions_present", getattr(fact, "instructions_present", base.get("instructions_present")), False)
    conflict_set = getattr(fact, "conflict_set", base.get("conflict_set")) or []
    base["conflict_set"] = conflict_set
    return base


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
        fresh_facts = [f for f in facts if not _fact_is_stale(f) and getattr(f, "trust", 0.5) > 0.3]
        kept: List[Fact] = []
        current_tokens = 0
        for fact in fresh_facts:
            sanitized = getattr(fact, "sanitized_text", None) or getattr(fact, "text", "")
            tokens = self._estimate_tokens(sanitized)
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
        text = hit.get("text", "") or ""
        namespace = hit.get("namespace") or "default"
        try:
            fact = Fact(text=text, namespace=namespace)
        except TypeError:
            fact = Fact(text=text)

        raw_id = hit.get("id")
        if raw_id is not None:
            try:
                fact.id = uuid.UUID(str(raw_id))  # type: ignore[assignment]
            except (ValueError, TypeError):
                fact.id = raw_id  # type: ignore[assignment]
        elif getattr(fact, "id", None) is None:
            fact.id = uuid.uuid4()

        fact.score = hit.get("score", 0.0)
        fact.source = hit.get("source", source_type)
        fact.source_uri = hit.get("source_uri")
        fact.timestamp = hit.get("timestamp", time.time())
        fact.trust = hit.get("trust", 0.5)
        fact.signature = hit.get("signature")
        fact.conflict_set = hit.get("conflict_set", []) or []
        sanitized_text, instructions_present = _sanitize_fact_text(text)
        fact.sanitized_text = sanitized_text
        fact.instructions_present = instructions_present
        fact.staleness_s = None
        return fact

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
        words1 = set((getattr(fact1, "sanitized_text", None) or getattr(fact1, "text", "")).lower().split())
        words2 = set((getattr(fact2, "sanitized_text", None) or getattr(fact2, "text", "")).lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        return intersection / union if union > 0 else 0.0

    def _calculate_sufficiency(self, facts: List[Fact], query: str) -> RetrievalSufficiency:
        if not facts:
            return RetrievalSufficiency(0.0, 0.0, 0.0, self.token_budget, 0, 0, 0.0, 0.0)
        coverage = sum(1 for f in facts if getattr(f, "score", 0.0) > 0.5) / len(facts)
        if len(facts) <= 1:
            diversity = 1.0
        else:
            similarities: List[float] = []
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    similarities.append(self._similarity(facts[i], facts[j]))
            diversity = 1.0 - (sum(similarities) / len(similarities)) if similarities else 1.0
        conflict_count = sum(len(getattr(f, "conflict_set", []) or []) for f in facts)
        agreement = 1.0 - (conflict_count / len(facts)) if facts else 1.0
        stale_count = sum(1 for f in facts if _fact_is_stale(f))
        staleness_ratio = stale_count / len(facts) if facts else 0.0
        trust_score = sum(getattr(f, "trust", 0.5) for f in facts) / len(facts) if facts else 0.0
        return RetrievalSufficiency(
            coverage=coverage,
            diversity=diversity,
            agreement=agreement,
            token_budget=self.token_budget,
            token_est=sum(self._estimate_tokens((getattr(f, "sanitized_text", None) or getattr(f, "text", ""))) for f in facts),
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
            text = (getattr(fact, "sanitized_text", None) or getattr(fact, "text", ""))
            source = getattr(fact, "source", "unknown")
            trust = getattr(fact, "trust", 0.5)
            keypoints.append(f"{text[:140]} (source: {source}, trust: {trust:.2f})")
        return "Key information includes: " + " • ".join(keypoints)

