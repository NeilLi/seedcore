#!/usr/bin/env python3
"""
SeedCore Task Routing Layer
===========================

This module defines the routing interface used by the Dispatcher to send tasks
into the unified SeedCore execution pipeline. The architecture follows a
"Thick Service, Thin Client" pattern where routers are lightweight clients
that delegate all decision logic to backend services.

Unified Interface Architecture
-------------------------------

The Coordinator Service now uses a **Universal Interface** pattern:
- **Single Business Endpoint**: `/route-and-execute` handles all business operations
- **Type-Based Routing**: Uses `TaskPayload.type` to route internally:
  * `type: "anomaly_triage"` → Anomaly triage pipeline
  * `type: "ml_tune_callback"` → ML tuning callback handler
  * Other types → Standard routing & execution
- **Operational Endpoints**: Health, metrics, and admin endpoints are hidden from schema
  but remain available for Kubernetes/Prometheus

Routers
-------
- CoordinatorHttpRouter:
    Thin client that sends tasks to the Coordinator Service (Tier-0).
    The Coordinator Service handles the complete lifecycle:
    - Type-based routing (anomaly_triage, ml_tune_callback, or standard)
    - Scoring (Surprise Score, PKG evaluation)
    - Routing Decision (FAST_PATH, COGNITIVE, ESCALATED)
    - Delegation (to Cognitive Service or Organism Service)
    - Execution (via downstream services)
    - Persistence (audit trail, telemetry)

    The only client-side optimization is the "agent_tunnel" bypass for
    low-latency chat interactions.

- OrganismRouter:
    Direct client for the Organism Service (Tier-1).
    Executes tasks through Organs → Agents → Tools.
    Handles agent selection, specialization matching, and tool execution.
    May escalate to Cognitive Service if result.decision_kind == "cognitive".

- RouterFactory:
    Factory that creates appropriate router instances based on configuration.

Architecture Overview
--------------------

The routing layer follows a simplified, pass-through pattern:

1. Dispatcher receives a task from the DB queue.

2. CoordinatorHttpRouter (Thin Client):
    - Optionally bypasses Coordinator for "agent_tunnel" mode (chat optimization)
    - Otherwise: POSTs task to Coordinator Service `/route-and-execute`
    - Returns the final result (Coordinator handles all delegation internally)

3. Coordinator Service (Tier-0 - Thick Service):
    - **Type-Based Routing**: Routes internally based on `TaskPayload.type`:
        * `"anomaly_triage"` → Anomaly triage pipeline (ML detection, HGNN escalation)
        * `"ml_tune_callback"` → ML tuning callback handler (energy tracking)
        * Other types → Standard routing & execution
    - Persists task (Inbox Pattern - System of Record)
    - Computes routing decision (Surprise Score + PKG)
    - Executes based on decision:
        * FAST_PATH → Delegates to Organism Service
        * COGNITIVE → Delegates to Cognitive Service for planning
        * ESCALATED → Delegates to Cognitive Service for HGNN reasoning
    - Persists audit trail (proto-plans, telemetry)
    - Returns final execution result

4. Organism Service (Tier-1):
    - Routes to appropriate organ based on task type/specialization
    - Selects agent from organ (with sticky routing for conversations)
    - Executes task via agent tools
    - Returns execution result

5. Cognitive Service (Tier-1):
    - Performs planning, problem-solving, or HGNN reasoning
    - Returns structured cognitive result

Key Design Principles
----------------------

- **Unified Interface**: Single business endpoint (`/route-and-execute`) for all operations
- **Type Polymorphism**: Uses `TaskPayload.type` for internal routing
- **Separation of Concerns**: Routers are thin clients; Services handle logic
- **Single Source of Truth**: Coordinator Service is the authoritative decision maker
- **No Double Delegation**: Client routers don't interpret decision_kind
- **Latency Optimization**: "agent_tunnel" bypass for high-velocity chat
- **Auditability**: All routing decisions and executions are persisted

This architecture ensures:
    * Simplicity: Thin clients are easy to maintain
    * Consistency: All decision logic centralized in Coordinator
    * Performance: Optimized paths for common cases (chat, fast tasks)
    * Observability: Complete audit trail of routing and execution
    * Client Simplicity: Clients only need to know one endpoint
"""

import os
import logging
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

from seedcore.models import TaskPayload
from seedcore.serve.base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from seedcore.models.cognitive import DecisionKind, CognitiveType
from seedcore.models.result_schema import (
    create_cognitive_result,
    create_error_result,
    make_envelope,
    normalize_envelope,
)
from seedcore.serve.cognitive_client import CognitiveServiceClient


def _coerce_task_payload(payload: Union[TaskPayload, Dict[str, Any]]) -> TaskPayload:
    """Normalize incoming payloads to TaskPayload instances."""
    if isinstance(payload, TaskPayload):
        return payload

    if isinstance(payload, dict):
        data = dict(payload)
        if "task_id" in data:
            return TaskPayload(**data)
        return TaskPayload.from_db(data)

    raise TypeError(f"Unsupported payload type for routing: {type(payload)}")


def _attach_routing_decision(
    result: Dict[str, Any],
    agent_id: Optional[str],
    score: Optional[float],
) -> None:
    """Add router decision info into result.meta.routing_decision."""
    meta = result.setdefault("meta", {})
    routing_decision = meta.setdefault("routing_decision", {})
    if agent_id:
        routing_decision["selected_agent_id"] = agent_id
    if score is not None:
        routing_decision["router_score"] = score
    routing_decision["routed_at"] = datetime.now(timezone.utc).isoformat()


def _attach_exec_metrics(
    result: Dict[str, Any],
    started_at: datetime,
    attempt: int = 1,
) -> None:
    """Attach execution timing metadata into result.meta.exec."""
    finished_at = datetime.now(timezone.utc)
    latency_ms = int((finished_at - started_at).total_seconds() * 1000)
    meta = result.setdefault("meta", {})
    meta["exec"] = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "latency_ms": latency_ms,
        "attempt": attempt,
    }


def _wrap_cognitive_response(
    *,
    task_data: Dict[str, Any],
    correlation_id: Optional[str],
    cog_res: Dict[str, Any],
    task_id: str,
) -> Dict[str, Any]:
    """
    Normalize CognitiveService responses into canonical envelope format.
    """
    if not isinstance(cog_res, dict):
        raise ValueError("CognitiveService returned non-dict response")

    metadata = cog_res.get("metadata") or {}
    meta_kwargs = metadata if isinstance(metadata, dict) else {}
    if correlation_id:
        meta_kwargs.setdefault("correlation_id", correlation_id)

    agent_id = (
        task_data.get("agent_id")
        or task_data.get("assigned_agent")
        or task_data.get("owner")
        or "router"
    )
    task_type = (
        task_data.get("type")
        or task_data.get("task_type")
        or task_data.get("name")
        or "unknown_task"
    )

    if cog_res.get("success"):
        payload = cog_res.get("result") or {}
        confidence = (
            payload.get("confidence_score") if isinstance(payload, dict) else None
        )

        cognitive_result = create_cognitive_result(
            agent_id=str(agent_id),
            task_type=str(task_type),
            result=payload,
            confidence_score=confidence,
            **meta_kwargs,
        )

        # Extract payload from cognitive result
        result_payload = cognitive_result.model_dump()
        
        return make_envelope(
            task_id=task_id,
            success=True,
            payload=result_payload,
            decision_kind=DecisionKind.COGNITIVE.value,
            meta=meta_kwargs,
            path="cognitive_service",
        )

    # Failure path – wrap as error result while preserving metadata
    error_message = (
        cog_res.get("error") or "CognitiveService returned unsuccessful result"
    )

    error_result = create_error_result(
        error=error_message,
        error_type="cognitive_service_failure",
        original_type=DecisionKind.COGNITIVE.value,
        **meta_kwargs,
    )

    error_payload = error_result.model_dump()
    
    return make_envelope(
        task_id=task_id,
        success=False,
        payload=error_payload,
        error=error_message,
        error_type="cognitive_service_failure",
        decision_kind=DecisionKind.ERROR.value,
        meta=meta_kwargs,
        path="cognitive_service",
    )


logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Config / Base
# -----------------------------------------------------------------------------


@dataclass
class RouterConfig:
    """Configuration for router implementations."""

    timeout: float = 90.0  # Increased from 30s to 90s for long-running tasks
    max_retries: int = 3
    retry_delay: float = 1.0
    circuit_breaker_failures: int = 5
    circuit_breaker_timeout: float = 90.0  # Increased from 30s to 90s to match timeout


class Router(ABC):
    """Abstract base class for task routing implementations."""

    @abstractmethod
    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route and execute a task.

        Args:
            payload: Task payload to route and execute
            correlation_id: Optional correlation ID for tracking

        Returns:
            Task execution result with unified schema (TaskResult-like dict)
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Check router health."""
        pass

    @abstractmethod
    async def close(self):
        """Close router resources."""
        pass


# -----------------------------------------------------------------------------
# OrganismRouter
# -----------------------------------------------------------------------------


class OrganismRouter(Router):
    """
    Fast-path router that calls the Organism service directly.

    Flow:
      1. POST /route-and-execute (canonical endpoint)
         -> Routes and executes task in one call
      2. If execute_result.decision_kind == DecisionKind.COGNITIVE ("cognitive"):
            Delegate to the centralized CognitiveService via the unified client.
         Else:
            Return execute_result directly.

    NOTE:
    - Uses /route-and-execute endpoint (canonical routing+execution API)
    - If execute_result.decision_kind == "fast": that's a normal success, return it.
    - If execute_result.decision_kind == "hgnn": that should already be a fully
      decomposed HGNN-style plan (EscalatedResult). We DO NOT forward again.
    - If execute_result.decision_kind == "error": just return it.
    """

    def __init__(
        self, base_url: Optional[str] = None, config: Optional[RouterConfig] = None
    ):
        self.config = config or RouterConfig()

        # Discover gateway or fallback
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY

                base_url = f"{SERVE_GATEWAY}/organism"
            except Exception:
                base_url = "http://127.0.0.1:8000/organism"

        # Circuit breaker / retry
        circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failures,
            recovery_timeout=self.config.circuit_breaker_timeout,
            expected_exception=(Exception,),
        )
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4,
        )

        self.client = BaseServiceClient(
            service_name="organism",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

        try:
            self.cognitive_client = CognitiveServiceClient()
        except Exception as client_err:
            logger.warning(
                "OrganismRouter failed to initialize CognitiveServiceClient: %s",
                client_err,
            )
            self.cognitive_client = None

        logger.info(f"OrganismRouter initialized with base_url: {base_url}")

    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Unified entrypoint for routing + executing tasks through the OrganismService.

        - Always POSTs to /route-and-execute (canonical endpoint)
        - Lets OrganismCore handle routing, agent selection, execution, escalation
        - Client does NOT need to know organism internals
        """
        started_at = datetime.now(timezone.utc)

        try:
            # 1. Coerce into a proper TaskPayload
            task_payload = _coerce_task_payload(payload)
            task_data = task_payload.model_dump()

            task_id = task_payload.task_id
            logger.debug(f"[OrganismRouter] Routing task {task_id}")

            if correlation_id:
                task_data["correlation_id"] = correlation_id

            # 2. Call the canonical routing+execution endpoint
            response = await self.client.post(
                "/route-and-execute",
                json={"task": task_data},
            )

            # Ensure response is dict (handle case where JSON response is a string or other type)
            if not isinstance(response, dict):
                if isinstance(response, str):
                    # If response is a JSON string, try to parse it
                    try:
                        import json
                        parsed = json.loads(response)
                        if isinstance(parsed, dict):
                            response = parsed
                        else:
                            # Parsed JSON is not a dict (e.g., list, number, string)
                            raise ValueError(f"OrganismService returned non-dict JSON (type={type(parsed).__name__})")
                    except json.JSONDecodeError:
                        # Not valid JSON, treat as error message
                        raise ValueError(f"OrganismService returned non-dict response (string value: {response[:200]})")
                    except Exception as e:
                        raise ValueError(f"OrganismService returned non-dict response: {e}")
                else:
                    raise ValueError(f"OrganismService returned non-dict response (type={type(response).__name__})")

            # Response is now a canonical envelope directly (no OrganismResponse wrapper)
            # Normalize to ensure all required fields are present
            result = normalize_envelope(response, task_id=task_id, path="organism_service")

            # 3. Handle possible cognitive escalation
            decision_kind = result.get("decision_kind")
            if decision_kind == DecisionKind.COGNITIVE.value:
                logger.info(
                    f"[OrganismRouter] Cognitive escalation required for {task_id}; "
                    "delegating to CognitiveService"
                )

                try:
                    if not self.cognitive_client:
                        logger.error(
                            "[OrganismRouter] cognitive_client is not initialized; "
                            "cannot process cognitive escalation"
                        )
                        result["warning"] = "CognitiveServiceClient unavailable"
                    else:
                        cog_res = await self.cognitive_client.execute_async(
                            agent_id=result.get("agent_id", f"planner_{task_id}"),
                            cog_type=CognitiveType.TASK_PLANNING,
                            decision_kind=DecisionKind.COGNITIVE,
                            input_data={
                                "task_description": task_payload.description or "",
                                "agent_capabilities": {},
                                "available_resources": {},
                            },
                            meta={
                                "task_id": task_id,
                                "correlation_id": correlation_id,
                            },
                        )

                        # Replace result payload entirely
                        result = _wrap_cognitive_response(
                            task_data=task_data,
                            correlation_id=correlation_id,
                            cog_res=cog_res,
                            task_id=task_id,
                        )

                except Exception as exc:
                    logger.warning(
                        f"[OrganismRouter] Cognitive escalation failed for {task_id}: {exc}"
                    )
                    result.setdefault("warning", f"Cognitive escalation failed: {exc}")

        except Exception as e:
            # Get task_id safely (might not be defined if exception occurs early)
            safe_task_id = task_payload.task_id if "task_payload" in locals() else "unknown"
            logger.error(
                f"[OrganismRouter] Failed to route task {safe_task_id}: {e}",
                exc_info=True
            )
            result = make_envelope(
                task_id=safe_task_id,
                success=False,
                error=str(e),
                error_type="organism_router_exception",
                decision_kind=DecisionKind.ERROR.value,
                path="organism_router_exception",
            )

        # 4. Attach routing metadata + execution metrics
        selected_agent = result.get("selected_agent_id") or result.get("meta", {}).get(
            "routing_decision", {}
        ).get("selected_agent_id")

        score = result.get("router_score") or result.get("meta", {}).get(
            "routing_decision", {}
        ).get("router_score")

        _attach_routing_decision(result, selected_agent, score)
        _attach_exec_metrics(result, started_at, attempt=1)

        # Ensure result is in canonical format before returning
        return normalize_envelope(result, task_id=task_id, path="organism_router")


# -----------------------------------------------------------------------------
# CoordinatorHttpRouter
# -----------------------------------------------------------------------------


class CoordinatorHttpRouter(Router):
    """
    HTTP-based router that calls Coordinator service.

    The Coordinator Service (Tier-0) now handles the full lifecycle:
    - Scoring (Surprise/PKG)
    - Routing Decision
    - Delegation (to Cognitive or Organism service)
    - Persistence

    This router is a thin client that simply hands off tasks and awaits final results.
    The only client-side optimization is the "agent_tunnel" bypass for low-latency chat.
    """

    def __init__(
        self, base_url: Optional[str] = None, config: Optional[RouterConfig] = None
    ):
        self.config = config or RouterConfig()

        # Discover gateway or fallback
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY

                # Coordinator is fronted under /pipeline
                base_url = f"{SERVE_GATEWAY}/pipeline"
            except Exception:
                base_url = "http://127.0.0.1:8000/pipeline"

        # Circuit breaker / retry for coordinator service
        circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.circuit_breaker_failures,
            recovery_timeout=self.config.circuit_breaker_timeout,
            expected_exception=(Exception,),
        )
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4,
        )

        self.client = BaseServiceClient(
            service_name="coordinator",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

        logger.info(f"CoordinatorHttpRouter initialized with base_url: {base_url}")

    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Route task through Coordinator HTTP API with Client-Side Optimization (Tunnel).
        
        For planning tasks, uses extended timeout to avoid dispatcher timeouts.
        """
        started_at = datetime.now(timezone.utc)

        try:
            # 1. Prepare Payload
            task_payload = _coerce_task_payload(payload)
            task_id = task_payload.task_id
            
            # Check if this is a planning task (needs extended timeout)
            is_planning_task = (
                task_payload.params.get("cognitive", {}).get("cog_type") == "task_planning"
                or task_payload.params.get("cognitive", {}).get("decision_kind") == "planner"
                or task_payload.params.get("cognitive", {}).get("decision_kind") == "cognitive"
            )
            
            # Use extended timeout for planning tasks
            request_timeout = self.config.planning_timeout if is_planning_task else self.config.timeout
            if is_planning_task:
                logger.debug(
                    f"[Router] 🧠 Planning task {task_id} detected - "
                    f"using extended timeout: {request_timeout}s"
                )
            
            # Serialize to dict with JSON-compatible types
            # Use mode='json' if available (Pydantic v2) to handle Enums, datetime, etc.
            # Otherwise use regular model_dump() - httpx will handle JSON serialization
            try:
                task_data = task_payload.model_dump(mode='json', exclude_none=False)
            except (TypeError, ValueError):
                # Fallback for Pydantic v1 or if mode='json' is not supported
                task_data = task_payload.model_dump(exclude_none=False)

            # 2. Standard Coordinator Routing (Unified Endpoint)
            logger.debug(f"[Router] 📡 Routing via Coordinator HTTP: {task_id}")

            # We assume self.client handles network errors and returns Dict
            # For planning tasks, pass extended timeout (BaseServiceClient supports per-request timeout)
            post_kwargs = {}
            if is_planning_task:
                # BaseServiceClient.post() accepts timeout as float and converts to httpx.Timeout
                post_kwargs["timeout"] = request_timeout
            
            raw_result = await self.client.post("/route-and-execute", json=task_data, **post_kwargs)

            # Normalize to canonical envelope format
            result = normalize_envelope(raw_result, task_id=task_id, path="coordinator_service")

        except Exception as e:
            # Get task_id safely (might not be defined if exception occurs early)
            safe_task_id = task_id if "task_id" in locals() else "unknown"
            logger.error(f"[Router] ❌ Routing failed: {e}", exc_info=True)
            result = make_envelope(
                task_id=safe_task_id,
                success=False,
                error=str(e),
                error_type="coordinator_http_error",
                decision_kind=DecisionKind.ERROR.value,
                path="coordinator_http_error",
            )

        # 3. Metrics Attachment (Safe Extraction)
        # Using .get chain with defaults to prevent KeyErrors on partial results
        meta = result.get("meta", {})
        decision = meta.get("routing_decision") or {}

        selected_agent = result.get("selected_agent_id") or decision.get(
            "selected_agent_id"
        )
        score = result.get("router_score") or decision.get("router_score")

        _attach_routing_decision(result, selected_agent, score)
        _attach_exec_metrics(result, started_at, attempt=1)

        # Ensure result is in canonical format before returning
        safe_task_id = result.get("task_id") or (task_id if "task_id" in locals() else "unknown")
        return normalize_envelope(result, task_id=safe_task_id, path="coordinator_router")

    async def health_check(self) -> Dict[str, Any]:
        """Check Coordinator service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "coordinator_http",
            }

    async def close(self):
        """Close HTTP client."""
        await self.client.close()


# -----------------------------------------------------------------------------
# RouterFactory
# -----------------------------------------------------------------------------


class RouterFactory:
    """
    Factory for creating router instances based on configuration.

    Supported router_type values:
      - "coordinator_http"
      - "organism"
      - "auto"
    """

    @staticmethod
    def create_router(
        router_type: Optional[str] = None, config: Optional[RouterConfig] = None
    ) -> Router:
        """
        Create a router instance based on configuration.

        Args:
            router_type:
                Explicit router type to construct.
                If None, we'll read DISPATCHER_ROUTER_TYPE
                (default 'coordinator_http').
            config:
                Router configuration.

        Returns:
            Configured router instance.
        """
        if router_type is None:
            router_type = os.getenv("DISPATCHER_ROUTER_TYPE", "coordinator_http")

        if config is None:
            config = RouterConfig(
                timeout=float(os.getenv("DISPATCHER_ROUTER_TIMEOUT", "90.0")),  # Increased from 30s to 90s for long-running tasks
                planning_timeout=float(os.getenv("DISPATCHER_ROUTER_PLANNING_TIMEOUT", "180.0")),  # 3 minutes for planning tasks
                max_retries=int(os.getenv("DISPATCHER_ROUTER_MAX_RETRIES", "3")),
                retry_delay=float(os.getenv("DISPATCHER_ROUTER_RETRY_DELAY", "1.0")),
                circuit_breaker_failures=int(
                    os.getenv("DISPATCHER_ROUTER_CB_FAILURES", "5")
                ),
                circuit_breaker_timeout=float(
                    os.getenv("DISPATCHER_ROUTER_CB_TIMEOUT", "90.0")  # Increased from 30s to 90s
                ),
            )

        logger.info(f"Creating router of type: {router_type}")

        if router_type == "coordinator_http":
            return CoordinatorHttpRouter(config=config)
        elif router_type == "organism":
            return OrganismRouter(config=config)
        elif router_type == "auto":
            # "auto" prefers organism fast-path if it initializes fine,
            # otherwise fall back to coordinator_http.
            try:
                org_router = OrganismRouter(config=config)
                return org_router
            except Exception:
                logger.warning(
                    "Organism router init failed, falling back to CoordinatorHttpRouter"
                )
                return CoordinatorHttpRouter(config=config)
        else:
            raise ValueError(f"Unknown router type: {router_type}")

    @staticmethod
    async def create_router_with_health_check(
        router_type: Optional[str] = None, config: Optional[RouterConfig] = None
    ) -> Router:
        """
        Create a router and verify it's healthy.
        Raises if unhealthy.
        """
        router = RouterFactory.create_router(router_type, config)

        health = await router.health_check()
        if health.get("status") != "healthy":
            await router.close()
            raise Exception(f"Router health check failed: {health}")

        logger.info(f"Router {router_type} is healthy and ready")
        return router
