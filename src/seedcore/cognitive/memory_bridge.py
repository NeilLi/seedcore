"""
Cognitive Memory Bridge — SeedCore / CognitiveCore v2

This module implements the Memory Bridge *inside the Cognitive Core*, aligning with the
Holon Fabric architecture and the Editor‑in‑Chief responsibility model.

Responsibilities (high‑level):
  • PRE‑EXECUTION hydration (server‑side):
      - Resolve scopes & entity_ids via ScopeResolver / Organism policy
      - Retrieve semantic context via Cognitive Retrieval (RRF, MMR hooks)
      - Retrieve episodic context via MwManager (short‑term)
      - Apply OCPS‑informed dynamic token budgeting
      - Produce a compact `hydrated_task` payload for DSPy

  • POST‑EXECUTION consolidation:
      - Build a structured MemoryEvent with provenance & trust
      - Fact sanitization, conflict checks (hooks)
      - Cache governance (TTL per task type) via MwManager
      - Editor‑in‑Chief promotion decision to Holon Fabric (policy + signals)
      - Persist long‑term facts/holons (graph + vector via HolonClient)

Notes:
  • This module intentionally contains *no* model invocation logic.
  • DSPy pipelines (prompts/modules) run outside and call into this bridge.
  • OCPS (Observability / Control / Policy / Signals) is passed in & recorded;
    budgeting/promotion decisions should respect OCPS guidance.

The implementation uses lightweight protocols instead of concrete dependencies so it
can integrate cleanly with existing SeedCore services.
"""
from __future__ import annotations

import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Protocol, Tuple, Sequence

# --------------------------------------------------------------------------------------
# Protocols (thin interfaces) — provide concrete implementations in your runtime layer.
# --------------------------------------------------------------------------------------

class ScopeResolver(Protocol):
    def resolve(self, *, agent_id: str, organ_id: Optional[str], task_params: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """Return (scopes, entity_ids). Scopes are Holon scopes like ["GLOBAL", "ORGAN", "ENTITY"]."""


class CognitiveRetrieval(Protocol):
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
        """Return a list of holon dicts suitable for injection into task context.
        Implementations may perform RRF fusion, MMR diversification, trust filtering, etc.
        """


class MwManager(Protocol):
    def set_item(self, key: str, value: str) -> None: ...
    def set_global_item_typed(self, kind: str, scope: str, item_id: str, payload: Any, ttl_s: Optional[int] = None) -> None: ...
    def get_recent_episode(self, *, organ_id: Optional[str], agent_id: str, k: int = 10) -> List[Dict[str, Any]]: ...


class HolonClient(Protocol):
    async def persist_holon(self, *, fact: Dict[str, Any]) -> str:
        """Create or upsert a holon record (graph + vector). Returns holon id."""


# --------------------------------------------------------------------------------------
# Data Schemas
# --------------------------------------------------------------------------------------

@dataclass
class MemoryEvent:
    id: str
    ts: float
    agent_id: str
    organ_id: Optional[str]
    task_type: str
    task_description: str
    task_params: Dict[str, Any]
    result: Any
    success: bool
    quality: float = 0.5
    salience: Optional[float] = None
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)  # who/what/when/how
    trust: Dict[str, Any] = field(default_factory=dict)        # confidence, policy flags
    policy: Dict[str, Any] = field(default_factory=dict)       # TTL hints, scope hints, retention class


@dataclass
class HydrationResult:
    holons: List[Dict[str, Any]]
    chat_history: List[Dict[str, Any]]
    token_budget: int


# --------------------------------------------------------------------------------------
# Utility: RRF Fusion & MMR Diversification (lightweight placeholders)
# --------------------------------------------------------------------------------------

def _rrf_fuse(ranked_lists: List[List[Dict[str, Any]]], k: int = 60) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion. Input is multiple ranked lists; each item must carry an 'id'.
    This is a placeholder; plug in your production implementation.
    """
    scores: Dict[str, float] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst, start=1):
            _id = str(item.get("id") or item.get("uuid") or item.get("_id") or json.dumps(item))
            by_id[_id] = item
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank)
    fused = sorted(by_id.items(), key=lambda kv: scores.get(kv[0], 0.0), reverse=True)
    return [by_id[_id] for _id, _ in fused]


def _mmr_diversify(items: List[Dict[str, Any]], *, lambda_weight: float = 0.7, top_k: int = 8) -> List[Dict[str, Any]]:
    """Maximal Marginal Relevance placeholder over text fields 'text'/'content'.
    Replace with embedding‑based MMR. Here we do a naive lexical dissimilarity.
    """
    def _text(it: Dict[str, Any]) -> str:
        return str(it.get("text") or it.get("content") or it.get("summary") or "")

    selected: List[Dict[str, Any]] = []
    while items and len(selected) < top_k:
        if not selected:
            selected.append(items.pop(0))
            continue
        # pick next that maximizes: lambda*relevance - (1-lambda)*similarity
        best_idx = 0
        best_score = -1e9
        for i, cand in enumerate(items):
            rel = cand.get("relevance", 1.0)
            sim = max(_lexical_jaccard(_text(cand), _text(s)) for s in selected) if selected else 0.0
            score = lambda_weight * rel - (1.0 - lambda_weight) * sim
            if score > best_score:
                best_idx, best_score = i, score
        selected.append(items.pop(best_idx))
    return selected


def _lexical_jaccard(a: str, b: str) -> float:
    sa, sb = set(a.lower().split()), set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / float(len(sa | sb))


# --------------------------------------------------------------------------------------
# Cognitive Memory Bridge (lives inside Cognitive Core)
# --------------------------------------------------------------------------------------

class CognitiveMemoryBridge:
    """Editor‑aligned Memory Bridge that runs inside the Cognitive Core.

    This class exposes two main entry points:
      • `hydrate_task(...)`  – pre‑execution server‑side hydration for DSPy
      • `process_post_execution(...)` – consolidate + promote after execution

    It delegates retrieval and promotion semantics to injected services and
    keeps Mw TTL/policy decisions outside (Organism).
    """

    def __init__(
        self,
        *,
        agent_id: str,
        organ_id: Optional[str],
        mw: MwManager,
        holon: HolonClient,
        scope_resolver: ScopeResolver,
        retrieval: CognitiveRetrieval,
        logger: Optional[logging.Logger] = None,
        default_hydration_limit: int = 5,
        default_chat_k: int = 10,
    ) -> None:
        self.agent_id = agent_id
        self.organ_id = organ_id
        self.mw = mw
        self.holon = holon
        self.scope_resolver = scope_resolver
        self.retrieval = retrieval
        self.default_hydration_limit = default_hydration_limit
        self.default_chat_k = default_chat_k
        self.log = logger or logging.getLogger("seedcore.cognitive.memory_bridge")

    # ------------------------------------------------------------------
    # PRE‑EXECUTION
    # ------------------------------------------------------------------
    async def hydrate_task(
        self,
        *,
        task: Dict[str, Any],
        ocps: Optional[Dict[str, Any]] = None,
        skip_retrieval: bool = False,
    ) -> Dict[str, Any]:
        """Return a hydrated copy of `task` with server‑side context injected.

        Injected under `task['params']['context']`:
          - 'holons': curated semantic context (GLOBAL/ORGAN/ENTITY aware)
          - 'chat_history': recent episodic turns
          - 'token_budget': suggested context token allowance
        """
        params = dict(task.get("params") or {})
        description = str(task.get("description") or "")
        goal = str(task.get("goal") or "")

        # Build query text
        query_text = "\n\n".join([t for t in (description, goal) if t]) or description

        # Resolve scopes via policy
        scopes, entity_ids = self.scope_resolver.resolve(
            agent_id=self.agent_id, organ_id=self.organ_id, task_params=params
        )

        holons: List[Dict[str, Any]] = []
        if not skip_retrieval and query_text.strip():
            # Cognitive retrieval; implementers may run RRF + MMR internally
            raw_context = await self.retrieval.query_context(
                text=query_text,
                scopes=scopes,
                organ_id=self.organ_id,
                entity_ids=entity_ids,
                limit=self.default_hydration_limit,
                agent_id=self.agent_id,
                ocps=ocps,
            )
            # Optional outer fusion/diversification hooks (if retrieval returns multiple lists)
            if raw_context and isinstance(raw_context[0], list):
                fused = _rrf_fuse([lst for lst in raw_context if isinstance(lst, list)])
                holons = _mmr_diversify(fused, lambda_weight=0.7, top_k=self.default_hydration_limit)
            else:
                holons = raw_context[: self.default_hydration_limit]

        # Episodic memory (chat history) — CognitiveCore can source from Mw centrally
        chat_history = self._load_recent_chat(k=self.default_chat_k)

        token_budget = self._suggest_token_budget(ocps=ocps, holon_count=len(holons), chat_k=len(chat_history))

        params.setdefault("context", {})
        params["context"].update(
            {
                "holons": holons,
                "chat_history": chat_history,
                "token_budget": token_budget,
            }
        )

        hydrated = dict(task)
        hydrated["params"] = params
        self.log.info(
            f"[CognitiveMemoryBridge] Hydrated context: holons={len(holons)}, chat_k={len(chat_history)}, budget={token_budget}"
        )
        return hydrated

    # ------------------------------------------------------------------
    # POST‑EXECUTION
    # ------------------------------------------------------------------
    async def process_post_execution(
        self,
        *,
        task: Dict[str, Any],
        result: Dict[str, Any],
        ocps: Optional[Dict[str, Any]] = None,
    ) -> MemoryEvent:
        """Consolidate a MemoryEvent, write episodic cache, and promote holons.

        Returns the MemoryEvent for telemetry/reporting.
        """
        task_type = str(task.get("type") or "unknown")
        description = str(task.get("description") or "")
        params = dict(task.get("params") or {})

        task_id = str(result.get("task_id") or params.get("task_id") or f"ad-hoc:{int(time.time()*1000)}")
        artifact_key = f"task:{task_id}"

        event = MemoryEvent(
            id=artifact_key,
            ts=time.time(),
            agent_id=self.agent_id,
            organ_id=self.organ_id,
            task_type=task_type,
            task_description=description,
            task_params=params,
            result=result.get("results"),
            success=bool(result.get("success", False)),
            quality=float(result.get("quality", 0.5) or 0.5),
            salience=self._coerce_optional_float(result.get("salience")),
            error=self._string_or_none(result.get("error")),
            metrics={
                "latency_ms": result.get("latency_ms"),
                "token_usage": result.get("token_usage"),
                "cost": result.get("cost"),
            },
            provenance=self._make_provenance(task=task, result=result, ocps=ocps),
            trust=self._make_trust(task=task, result=result, ocps=ocps),
            policy=self._make_policy(task=task, result=result, ocps=ocps),
        )

        # Episodic write — Mw controls TTL/policy mapping by kind/scope
        self._mw_put_local(artifact_key, asdict(event))
        self._mw_put_global(kind="task_artifact", scope="global", item_id=artifact_key, payload=asdict(event))

        # Fact sanitization & conflict checks — hook points
        sanitized = self._sanitize_event(event)
        if not sanitized:
            self.log.info("MemoryEvent rejected by sanitizer; skipping promotion.")
            return event

        # Editor‑in‑Chief decision: promote to holon?
        if self._should_promote(event):
            await self._promote_to_holon(event)
        else:
            self.log.debug("Promotion not warranted by policy/signals.")

        return event

    # ------------------------------------------------------------------
    # Internals — Policy & Hooks
    # ------------------------------------------------------------------

    def _load_recent_chat(self, *, k: int) -> List[Dict[str, Any]]:
        try:
            return self.mw.get_recent_episode(organ_id=self.organ_id, agent_id=self.agent_id, k=k) or []
        except Exception as e:
            self.log.warning(f"Mw.get_recent_episode failed: {e}")
            return []

    def _suggest_token_budget(self, *, ocps: Optional[Dict[str, Any]], holon_count: int, chat_k: int) -> int:
        # OCPS‑informed budgeting. Fallback heuristic.
        base = int(ocps.get("budget", {}).get("context_tokens", 0)) if ocps else 0
        if base <= 0:
            # Simple heuristic: allocate ~256 for holons and ~128 for chat, scaled.
            base = 128 + 32 * holon_count + 12 * chat_k
        # Clamp to sane range; real impl would respect model constraints
        return max(128, min(base, 4096))

    def _sanitize_event(self, event: MemoryEvent) -> bool:
        # Placeholder for redaction, PII filtering, conflict detection
        # Return False to drop the event.
        return True

    def _should_promote(self, event: MemoryEvent) -> bool:
        # Editor‑in‑Chief policy (simplified):
        #  - promote if success & quality >= 0.8
        #  - or if salience >= 0.7 (even on failure, e.g., novel signal)
        if event.success and event.quality >= 0.8:
            return True
        if event.salience is not None and event.salience >= 0.7:
            return True
        # OCPS override
        return bool(event.policy.get("force_promote", False))

    async def _promote_to_holon(self, event: MemoryEvent) -> None:
        # Construct a Fact/ Holon dict the HolonClient expects. The cognitive
        # layer owns summarization/embedding/graph schema in the client.
        fact = self._event_to_fact(event)
        try:
            holon_id = await self.holon.persist_holon(fact=fact)
            self.log.info(f"Promoted MemoryEvent to holon id={holon_id}")
        except Exception as e:
            self.log.warning(f"Holon promotion failed: {e}")

    def _event_to_fact(self, event: MemoryEvent) -> Dict[str, Any]:
        # Minimal but rich payload; HolonClient should add embeddings/graph.
        return {
            "type": "TASK_EVENT",
            "src": {
                "agent_id": event.agent_id,
                "organ_id": event.organ_id,
            },
            "ts": event.ts,
            "task": {
                "id": event.id,
                "task_type": event.task_type,
                "description": event.task_description,
                "params": event.task_params,
            },
            "outcome": {
                "success": event.success,
                "quality": event.quality,
                "salience": event.salience,
                "error": event.error,
                "result_preview": _preview(event.result, 400),
            },
            "metrics": event.metrics,
            "provenance": event.provenance,
            "trust": event.trust,
            "policy": event.policy,
        }

    def _make_provenance(self, *, task: Dict[str, Any], result: Dict[str, Any], ocps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "coordinator": ocps.get("coordinator") if ocps else None,
            "skills": task.get("skills"),
            "services": task.get("services"),
            "models": task.get("models"),
            "capabilities": task.get("capabilities"),
            "pipeline": task.get("pipeline"),  # DSPy pipeline id/name
            "policy_flags": (ocps or {}).get("policy_flags"),
        }

    def _make_trust(self, *, task: Dict[str, Any], result: Dict[str, Any], ocps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "confidence": result.get("confidence"),
            "verifications": result.get("verifications"),  # post‑conditions passed/failed
            "conflicts": result.get("conflicts"),          # detected contradictions
            "sources": result.get("sources"),              # citations / ids
            "hints": (ocps or {}).get("trust_hints"),
        }

    def _make_policy(self, *, task: Dict[str, Any], result: Dict[str, Any], ocps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # TTL is enforced in Mw / Organism; here we only hint a retention class
        return {
            "retention": task.get("retention") or "ephemeral_task_artifact",
            "scope_hint": task.get("scope_hint"),
            "force_promote": bool(task.get("force_promote", False)),
        }

    # ----------------------------------------------------------------------------------
    # Mw adapters
    # ----------------------------------------------------------------------------------

    def _mw_put_local(self, key: str, payload: Dict[str, Any]) -> None:
        try:
            self.mw.set_item(key, json.dumps(payload))
        except Exception as e:
            self.log.warning(f"Mw.set_item failed: {e}")

    def _mw_put_global(self, *, kind: str, scope: str, item_id: str, payload: Dict[str, Any], ttl_s: Optional[int] = None) -> None:
        try:
            self.mw.set_global_item_typed(kind, scope, item_id, payload, ttl_s=ttl_s)
        except Exception as e:
            self.log.warning(f"Mw.set_global_item_typed failed: {e}")

    # ----------------------------------------------------------------------------------
    # Small helpers
    # ----------------------------------------------------------------------------------

    @staticmethod
    def _coerce_optional_float(v: Any) -> Optional[float]:
        try:
            return None if v is None else float(v)
        except Exception:
            return None

    @staticmethod
    def _string_or_none(v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v)
        return s if s else None


def _preview(obj: Any, n: int) -> Optional[str]:
    if obj is None:
        return None
    s = str(obj)
    return s[:n]
