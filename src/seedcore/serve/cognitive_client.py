#!/usr/bin/env python3
"""
Cognitive Service Client for SeedCore (Refactored v2)

This client provides a clean, unified interface to the deployed
cognitive service's single /execute endpoint.

The /execute endpoint uses TaskPayload (Pydantic) as the public API
contract for system-wide consistency. This ensures the Router, Coordinator,
Agents, and Cognitive Service all speak the exact same language.

The client accepts TaskPayload (or compatible dict) and injects cognitive
metadata into params.cognitive namespace. The CALLER (e.g., Coordinator)
is responsible for setting the 'cog_type', 'decision_kind', and task data.
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional, Union
from concurrent.futures import ThreadPoolExecutor

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from seedcore.models.cognitive import CognitiveType, DecisionKind
from seedcore.models.task_payload import TaskPayload
from seedcore.models.task import TaskType

logger = logging.getLogger(__name__)

# A single, shared thread pool for all sync calls
_SYNC_EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)


class CognitiveServiceClient(BaseServiceClient):
    """
    Client for the unified /execute cognitive endpoint.

    This client uses TaskPayload as the unified schema, ensuring system-wide
    consistency across Router, Coordinator, Agents, and Cognitive Service.

    The main method 'execute_async' accepts a TaskPayload (or compatible dict)
    and injects cognitive metadata into params.cognitive before sending to
    the server's /execute endpoint.
    """

    # Translation map: Router Intent (TaskType) -> Cognitive Mode (CognitiveType)
    # This decouples the Routing Layer vocabulary from the Cognitive Layer vocabulary
    TASK_TO_COG_MAP = {
        "general_query": "problem_solving",  # General queries usually require problem solving
        "chat": "chat",  # Direct map - chat tasks use CHAT cognitive type
        "execute": "task_planning",  # Execution often implies planning/decomposition
        "test_query": "capability_assessment",  # Test queries assess system capabilities
        "fact_search": "fact_search",  # Direct map (exists in both)
        "unknown_task": "failure_analysis",  # If unknown, analyze why
        # Graph tasks map directly (no translation needed)
        "graph_embed": "graph_embed",
        "graph_rag_query": "graph_rag_query",
        "graph_fact_embed": "graph_fact_embed",
        "graph_fact_query": "graph_fact_query",
        "graph_sync_nodes": "graph_sync_nodes",
    }

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = None,
    ):
        # Centralized gateway discovery
        if base_url is None:
            base_url = os.getenv("COG_BASE_URL")
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import COG

                base_url = COG  # already includes /cognitive
            except Exception:
                base_url = "http://127.0.0.1:8000/cognitive"

        # Resolve effective timeout
        if timeout is None:
            try:
                timeout = float(os.getenv("COG_CLIENT_TIMEOUT", "75.0"))
            except Exception:
                timeout = 75.0

        try:
            retries = int(os.getenv("COG_CLIENT_RETRIES", "1"))
        except Exception:
            retries = 1

        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )

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

    @staticmethod
    def _resolve_cog_type(
        task_type: Union[str, CognitiveType, TaskType],
    ) -> CognitiveType:
        """
        Helper to safely convert a string/Enum to a CognitiveType enum.

        Includes an adapter layer to map TaskTypes to CognitiveTypes, decoupling
        the Routing Layer vocabulary from the Cognitive Layer vocabulary.

        Args:
            task_type: Can be a CognitiveType, TaskType, or string value

        Returns:
            CognitiveType enum instance

        Raises:
            ValueError: If the task_type cannot be resolved to a valid CognitiveType
            TypeError: If the task_type is an unsupported type
        """
        # 1. Fast exit if already correct type
        if isinstance(task_type, CognitiveType):
            return task_type

        # 2. Normalize input string
        if hasattr(task_type, "value"):  # Handle TaskType enum input directly
            raw_str = task_type.value
        else:
            raw_str = str(task_type)

        normalized = raw_str.strip().lower()

        if not normalized:
            raise ValueError("cog_type must not be empty")

        # 3. APPLY MAPPING (The Fix)
        # Check if this is a TaskType that needs translation
        if normalized in CognitiveServiceClient.TASK_TO_COG_MAP:
            normalized = CognitiveServiceClient.TASK_TO_COG_MAP[normalized]

        # 4. Attempt Resolution
        try:
            # Try by Value (e.g., "graph_embed")
            return CognitiveType(normalized)
        except ValueError:
            try:
                # Try by Key (e.g., "GRAPH_EMBED")
                return CognitiveType[normalized.upper()]
            except KeyError as exc:
                raise ValueError(
                    f"Unsupported cog_type '{task_type}'. "
                    f"Ensure it is mapped in TASK_TO_COG_MAP or exists in CognitiveType."
                ) from exc

    async def execute_async(
        self,
        *,
        agent_id: str,
        cog_type: Union[str, CognitiveType],
        decision_kind: DecisionKind,
        task: Union[TaskPayload, Dict[str, Any]],
        timeout: Optional[float] = None,
        llm_provider_override: Optional[str] = None,
        llm_model_override: Optional[str] = None,
        # NEW: coordinator / PKG metadata
        proto_plan: Optional[Dict[str, Any]] = None,
        ocps: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Unified cognitive interface using TaskPayload schema.

        Ensures cognitive jobs consume exactly the same structured inputs
        as the router/agents/organs.

        NEW:
          - proto_plan: Optional PKG- or router-generated DAG / plan scaffold
                        (contains pkg_meta embedded in proto_plan.metadata)
          - ocps:       Optional OCPS / drift state payload
        """
        resolved_type = self._resolve_cog_type(cog_type)

        # ------------------------------------------------------------------
        # 1. Normalize to TaskPayload
        # ------------------------------------------------------------------
        if isinstance(task, TaskPayload):
            payload = task
        else:
            payload = TaskPayload.from_db(dict(task or {}))

        # ------------------------------------------------------------------
        # 2. Prepare Modified Params
        # ------------------------------------------------------------------
        params = dict(payload.params or {})
        cognitive_section = dict(params.get("cognitive", {}))

        # Base cognitive envelope (shared by agents + coordinator)
        cognitive_section.update(
            {
                "agent_id": agent_id,
                "cog_type": resolved_type.value,
                "decision_kind": decision_kind.value,
            }
        )

        if llm_provider_override:
            cognitive_section["llm_provider_override"] = (
                llm_provider_override.strip().lower()
            )
        if llm_model_override:
            cognitive_section["llm_model_override"] = llm_model_override

        # ------------------------------------------------------------------
        # 2b. NEW: Coordinator / PKG-specific metadata
        # ------------------------------------------------------------------
        # Note: pkg_meta is embedded in proto_plan.metadata, no need to pass separately
        if proto_plan is not None:
            cognitive_section["proto_plan"] = proto_plan
        if ocps is not None:
            cognitive_section["ocps"] = ocps
        
        # ------------------------------------------------------------------
        # 2c. Performance flags: Skip RAG for TASK_PLANNING
        # ------------------------------------------------------------------
        # ARCHITECTURAL INVARIANT: TASK_PLANNING must skip RAG to maintain
        # closed-world PKG evaluation guarantees (Case A invariants):
        #
        # 1. Eventizer emits bounded tags + signals
        # 2. PKG evaluates closed-world task_facts (no open-world RAG contamination)
        # 3. PKG emits proto-subtasks (intent only, policy-driven)
        # 4. Execution plane enforces deny-by-default (PKG is authoritative)
        # 5. Snapshot version + provenance logged
        #
        # Mixing RAG (open-world) with PKG (closed-world) would violate these
        # invariants. PKG's proto_plan is the single source of truth for planning.
        if resolved_type == CognitiveType.TASK_PLANNING:
            cognitive_section["skip_retrieval"] = True

        params["cognitive"] = cognitive_section

        # ------------------------------------------------------------------
        # 3. Create Updated Payload
        # ------------------------------------------------------------------
        updated_payload = payload.model_copy(update={"params": params})

        # ------------------------------------------------------------------
        # 4. Execute Service Call
        # ------------------------------------------------------------------
        effective_timeout = timeout if timeout is not None else self.timeout

        logger.debug(
            f"[CognitiveClient] execute_async → agent={agent_id}, "
            f"type={resolved_type.value}, pipeline={decision_kind.value}"
        )

        return await self.post(
            "/execute", json=updated_payload.model_dump(), timeout=effective_timeout
        )

    # ---------------------------
    # Service info / health
    # ---------------------------

    async def get_service_info(self) -> Dict[str, Any]:
        """Wraps the /info endpoint for service discovery."""
        return await self.get("/info")

    async def health_check(self) -> Dict[str, Any]:
        """Wraps the /health endpoint for service monitoring."""
        return await self.get("/health")

    async def is_healthy(self) -> bool:
        """Boolean check against the /health endpoint."""
        try:
            health = await self.health_check()
            return str(health.get("status", "")).lower() == "healthy"
        except Exception:
            return False

    # ---------------------------
    # Sync Wrapper
    # ---------------------------

    def execute_sync(
        self,
        *,
        agent_id: str,
        cog_type: Union[str, CognitiveType],
        decision_kind: DecisionKind,
        task: Union[TaskPayload, Dict[str, Any]],
        timeout: Optional[float] = None,
        llm_provider_override: Optional[str] = None,
        llm_model_override: Optional[str] = None,
        # NEW: coordinator / PKG metadata
        proto_plan: Optional[Dict[str, Any]] = None,
        ocps: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for execute_async.

        This method is safe to call from both sync and async code.
        """

        async def _runner():
            return await self.execute_async(
                agent_id=agent_id,
                cog_type=cog_type,
                decision_kind=decision_kind,
                task=task,
                timeout=timeout,
                llm_provider_override=llm_provider_override,
                llm_model_override=llm_model_override,
                proto_plan=proto_plan,
                ocps=ocps,
            )

        try:
            asyncio.get_running_loop()
            future = _SYNC_EXECUTOR.submit(lambda: asyncio.run(_runner()))
            return future.result(timeout=self.timeout + 5.0)
        except RuntimeError:
            return asyncio.run(_runner())
