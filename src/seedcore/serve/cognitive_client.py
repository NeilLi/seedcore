#!/usr/bin/env python3
"""
Cognitive Service Client for SeedCore (Updated)

This client provides a clean interface to the deployed cognitive service
supporting multi-provider & dual-profile (FAST/DEEP) requests.
"""

import os
import logging
from typing import Dict, Any, Optional, List, Sequence

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)


def _normalize_list(val: Optional[str]) -> List[str]:
    return [x.strip().lower() for x in (val or "").split(",") if x.strip()]


class CognitiveServiceClient(BaseServiceClient):
    """
    Client for the deployed cognitive service that handles:
    - Problem solving
    - Decision making
    - Memory synthesis
    - Capability assessment
    - Task planning (FAST/DEEP, multi-provider)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = None,
    ):
        # Centralized gateway discovery (env -> ray_utils -> localhost)
        if base_url is None:
            base_url = os.getenv("COG_BASE_URL")
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import COG
                base_url = COG  # already includes /cognitive
            except Exception:
                base_url = "http://127.0.0.1:8000/cognitive"

        # Resolve effective timeout (fallback to env or sensible default)
        if timeout is None:
            try:
                timeout = float(os.getenv("COG_CLIENT_TIMEOUT", "75"))
            except Exception:
                timeout = 75.0

        # Retry tuning (env override)
        try:
            retries = int(os.getenv("COG_CLIENT_RETRIES", "1"))
        except Exception:
            retries = 1

        # Circuit breaker tuned for service calls
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,),
        )

        # Lightweight retries (idempotent reads / safe posts)
        retry_config = RetryConfig(
            max_attempts=max(1, retries),
            base_delay=1.0,
            max_delay=5.0,
        )

        super().__init__(
            service_name="cognitive_service",
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

        # Cache per-profile timeout hints (env overrideable)
        # Defaults chosen to stay below common dispatcher windows (e.g., 120s)
        try:
            self.fast_timeout_s = float(os.getenv("COG_CLIENT_TIMEOUT_FAST", str(min(timeout, 35.0))))
        except Exception:
            self.fast_timeout_s = min(timeout, 35.0)
        try:
            self.deep_timeout_s = float(os.getenv("COG_CLIENT_TIMEOUT_DEEP", str(min(90.0, max(timeout, 60.0)))))
        except Exception:
            self.deep_timeout_s = min(90.0, max(timeout, 60.0))

    def _timeout_for_depth(self, depth: Optional[str]) -> float:
        d = (depth or "").lower()
        if d == "deep":
            return float(self.deep_timeout_s)
        # default fast
        return float(self.fast_timeout_s)

    # ---------------------------
    # Helpers
    # ---------------------------

    async def _post_first_available(
        self,
        candidate_paths: Sequence[str],
        json: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Try a list of endpoint paths in order, returning the first success.
        Useful for smooth migrations (e.g., /plan vs /plan-task).
        """
        last_exc: Optional[Exception] = None
        for p in candidate_paths:
            try:
                return await self.post(p, json=json, **kwargs)
            except Exception as e:
                last_exc = e
                logger.debug("POST %s failed: %s; trying next candidate", p, e)
        # If all failed, raise final exception
        if last_exc:
            raise last_exc
        return {"success": False, "error": "No candidate path attempted"}

    def _provider_hints(self) -> List[str]:
        """
        Collect multi-provider hints from env to send with requests.
        Server can use this to route FAST requests or escalations.
        """
        # Prefer registry (if present) to parse LLM_PROVIDERS; otherwise parse here.
        try:
            from seedcore.utils.llm_registry import get_active_providers  # type: ignore
            provs = get_active_providers()
            if provs:
                return [p.lower() for p in provs]
        except Exception:
            pass
        return _normalize_list(os.getenv("LLM_PROVIDERS"))

    # ---------------------------
    # Task Planning
    # ---------------------------

    async def plan(
        self,
        agent_id: str,
        task_description: str,
        *,
        depth: str = "fast",                 # "fast" | "deep"
        provider: Optional[str] = None,      # optional override (e.g., "anthropic")
        model: Optional[str] = None,         # optional override (e.g., "claude-3-5-sonnet")
        current_capabilities: Optional[str] = None,
        available_tools: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Plan a task with explicit FAST/DEEP profile and optional provider/model override.
        Tries /plan first; falls back to /plan-task for older deployments.
        """
        body = {
            "agent_id": agent_id,
            "task_description": task_description,
            "current_capabilities": current_capabilities or "",
            "available_tools": available_tools or {},
            # Hints for the service:
            "profile": depth.lower(),                     # "fast" | "deep"
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,  # multi-provider pool hint
            "meta": extra_meta or {},
        }
        # Clean out None fields to keep payload tidy
        body = {k: v for k, v in body.items() if v is not None}

        # New route -> legacy route compatibility
        eff_timeout = self._timeout_for_depth(depth)
        return await self._post_first_available(
            candidate_paths=("/plan", "/plan-task"),
            json=body,
            timeout=eff_timeout,
        )

    async def plan_with_escalation(
        self,
        agent_id: str,
        task_description: str,
        *,
        current_capabilities: Optional[Dict[str, Any]] = None,
        available_tools: Optional[Dict[str, Any]] = None,
        preferred_order: Optional[List[str]] = None,  # e.g., ["openai","anthropic","nim"]
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Plan with automatic escalation (FAST -> DEEP). You can pass a preferred provider order.
        """
        providers = preferred_order or self._provider_hints()
        body = {
            "agent_id": agent_id,
            "task_description": task_description,
            "current_capabilities": current_capabilities or {},
            "available_tools": available_tools or {},
            "providers": providers or None,  # server will default if None
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        return await self.post("/plan-with-escalation", json=body)

    # ---------------------------
    # Problem Solving
    # ---------------------------

    async def solve_problem(
        self,
        agent_id: str,
        problem_statement: str,
        *,
        depth: Optional[str] = None,               # optional "fast" | "deep"
        provider: Optional[str] = None,
        model: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None,
        available_tools: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Solve a problem; optional profile/provider/model hints are passed through.
        """
        body = {
            "agent_id": agent_id,
            "problem_statement": problem_statement,
            "constraints": constraints or {},
            "available_tools": available_tools or {},
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/solve-problem", json=body, timeout=eff_timeout)

    # ---------------------------
    # Decision Making
    # ---------------------------

    async def make_decision(
        self,
        agent_id: str,
        decision_context: Dict[str, Any],
        *,
        depth: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        historical_data: Optional[Dict[str, Any]] = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "decision_context": decision_context,
            "historical_data": historical_data or {},
            "knowledge_context": knowledge_context or {},
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/make-decision", json=body, timeout=eff_timeout)

    # ---------------------------
    # Memory Synthesis
    # ---------------------------

    async def synthesize_memory(
        self,
        agent_id: str,
        memory_fragments: List[Dict[str, Any]],
        synthesis_goal: str,
        *,
        depth: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "memory_fragments": memory_fragments,
            "synthesis_goal": synthesis_goal,
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/synthesize-memory", json=body, timeout=eff_timeout)

    # ---------------------------
    # Capability Assessment
    # ---------------------------

    async def assess_capabilities(
        self,
        agent_id: str,
        performance_data: Dict[str, Any],
        current_capabilities: Dict[str, Any],
        target_capabilities: Dict[str, Any],
        *,
        depth: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "performance_data": performance_data,
            "current_capabilities": current_capabilities,
            "target_capabilities": target_capabilities,
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/assess-capabilities", json=body, timeout=eff_timeout)

    # ---------------------------
    # Failure Analysis
    # ---------------------------

    async def reason_about_failure(
        self,
        agent_id: str,
        incident_context: Dict[str, Any],
        *,
        depth: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = {
            "agent_id": agent_id,
            "incident_context": incident_context,
            "knowledge_context": knowledge_context or {},
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/reason-about-failure", json=body, timeout=eff_timeout)

    # ---------------------------
    # Generic forward
    # ---------------------------

    async def forward(
        self,
        agent_id: str,
        task_type: str,
        input_data: Dict[str, Any],
        *,
        depth: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        energy_context: Optional[Dict[str, Any]] = None,
        lifecycle_context: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generic forward for any cognitive task type with profile/provider hints.
        """
        body = {
            "agent_id": agent_id,
            "task_type": task_type,
            "input_data": input_data,
            "memory_context": memory_context or {},
            "energy_context": energy_context or {},
            "lifecycle_context": lifecycle_context or {},
            "profile": depth.lower() if depth else None,
            "llm_provider_override": (provider or "").lower() or None,
            "llm_model_override": model or None,
            "providers": self._provider_hints() or None,
            "meta": extra_meta or {},
        }
        body = {k: v for k, v in body.items() if v is not None}
        eff_timeout = self._timeout_for_depth(depth)
        return await self.post("/forward", json=body, timeout=eff_timeout)

    # ---------------------------
    # Service info / health
    # ---------------------------

    async def get_service_info(self) -> Dict[str, Any]:
        return await self.get("/info")

    async def health_check(self) -> Dict[str, Any]:
        return await self.get("/health")

    async def is_healthy(self) -> bool:
        try:
            health = await self.health_check()
            return str(health.get("status", "")).lower() == "healthy"
        except Exception:
            return False

    # ---------------------------
    # Sync wrappers for sync callers
    # ---------------------------

    def plan_sync(
        self,
        agent_id: str,
        task_description: str,
        *,
        depth: str = "fast",
        provider: Optional[str] = None,
        model: Optional[str] = None,
        current_capabilities: Optional[str] = None,
        available_tools: Optional[Dict[str, Any]] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sync wrapper for plan() – safe in or out of a running event loop.
        Enforces timeout inside the event loop to avoid hanging threads.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        # Resolve an effective timeout (use your attribute name here)
        base_timeout = getattr(self, "timeout", 8.0)
        eff_timeout = float(base_timeout) * (4.0 if str(depth).lower() == "deep" else 1.0)

        async def _call_plan():
            return await self.plan(
                agent_id=agent_id,
                task_description=task_description,
                depth=depth,
                provider=provider,
                model=model,
                current_capabilities=current_capabilities,
                available_tools=available_tools,
                extra_meta=extra_meta,
            )

        async def _runner():
            # Enforce timeout INSIDE the event loop
            return await asyncio.wait_for(_call_plan(), timeout=eff_timeout)

        try:
            # Are we already inside an event loop? (Ray/Serve/FastAPI/Notebook)
            asyncio.get_running_loop()
            # Run in a worker thread with its own fresh loop
            with ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(lambda: asyncio.run(_runner())).result()
        except RuntimeError:
            # No running loop -> safe to run directly
            return asyncio.run(_runner())
