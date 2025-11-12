#!/usr/bin/env python3
"""
Task Router Interface for SeedCore Dispatcher

Routers:
- CoordinatorHttpRouter (entry point)
- OrganismRouter (fast-path execution)
- RouterFactory (creates routers)

Routing policy (aligned with seedcore.models.cognitive.DecisionKind):
- Coordinator inspects .kind from Coordinator service response:
    - kind == "fast"   -> delegate to fast router (default: OrganismRouter)
    - kind == "cognitive"   -> delegate to CognitiveService orchestration
    - else (incl. "hgnn", "error") -> return Coordinator's result
- Organism executes fast path, then inspects its own result:
    - kind == "cognitive"   -> delegate to CognitiveService orchestration
    - else (fast / hgnn / error) -> return Organism result
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
from seedcore.models.result_schema import create_cognitive_result, create_error_result
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
) -> Dict[str, Any]:
    """
    Normalize CognitiveService responses back into TaskResult-shaped envelopes.
    """
    if not isinstance(cog_res, dict):
        raise ValueError("CognitiveService returned non-dict response")

    metadata = cog_res.get("metadata") or {}
    meta_kwargs = metadata if isinstance(metadata, dict) else {}

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
            payload.get("confidence_score")
            if isinstance(payload, dict)
            else None
        )

        cognitive_result = create_cognitive_result(
            agent_id=str(agent_id),
            task_type=str(task_type),
            result=payload,
            confidence_score=confidence,
            **meta_kwargs,
        )

        result_dict = cognitive_result.model_dump()

        merged_meta = dict(result_dict.get("metadata") or {})
        merged_meta.update(meta_kwargs)
        if correlation_id:
            merged_meta.setdefault("correlation_id", correlation_id)
        result_dict["metadata"] = merged_meta

        payload_dict = result_dict.get("payload") or {}
        if isinstance(payload_dict, dict):
            payload_meta = dict(payload_dict.get("metadata") or {})
            payload_meta.update(meta_kwargs)
            if correlation_id:
                payload_meta.setdefault("correlation_id", correlation_id)
            payload_dict["metadata"] = payload_meta
            result_dict["payload"] = payload_dict

        result_dict["success"] = True
        result_dict["error"] = None
        return result_dict

    # Failure path – wrap as error result while preserving metadata
    error_message = cog_res.get("error") or "CognitiveService returned unsuccessful result"

    error_result = create_error_result(
        error=error_message,
        error_type="cognitive_service_failure",
        original_type=DecisionKind.COGNITIVE.value,
        **meta_kwargs,
    )

    err_dict = error_result.model_dump()

    merged_meta = dict(err_dict.get("metadata") or {})
    merged_meta.update(meta_kwargs)
    if correlation_id:
        merged_meta.setdefault("correlation_id", correlation_id)
    err_dict["metadata"] = merged_meta

    payload_dict = err_dict.get("payload")
    if isinstance(payload_dict, dict):
        payload_meta = dict(payload_dict.get("metadata") or {})
        payload_meta.update(meta_kwargs)
        if correlation_id:
            payload_meta.setdefault("correlation_id", correlation_id)
        payload_dict["metadata"] = payload_meta
        payload_dict["error"] = error_message
        payload_dict["original_type"] = DecisionKind.COGNITIVE.value
        err_dict["payload"] = payload_dict

    err_dict["success"] = False
    err_dict["error"] = error_message
    return err_dict

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Config / Base
# -----------------------------------------------------------------------------

@dataclass
class RouterConfig:
    """Configuration for router implementations."""
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    circuit_breaker_failures: int = 5
    circuit_breaker_timeout: float = 30.0


class Router(ABC):
    """Abstract base class for task routing implementations."""

    @abstractmethod
    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None
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
      1. /resolve-route        -> which organ handles this?
      2. /execute-on-organ     -> run task on that organ
      3. If execute_result.kind == DecisionKind.COGNITIVE ("cognitive"):
            Delegate to the centralized CognitiveService via the unified client.
         Else:
            Return execute_result directly.

    NOTE:
    - If execute_result.kind == "fast": that's a normal success, return it.
    - If execute_result.kind == "hgnn": that should already be a fully
      decomposed HGNN-style plan (EscalatedResult). We DO NOT forward again.
    - If execute_result.kind == "error": just return it.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        config: Optional[RouterConfig] = None
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
            expected_exception=(Exception,)
        )
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4
        )

        self.client = BaseServiceClient(
            service_name="organism",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
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
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Route task through Organism service for fast-path execution."""
        try:
            task_payload = _coerce_task_payload(payload)
            task_data = task_payload.model_dump()
            if correlation_id:
                task_data["correlation_id"] = correlation_id

            started_at = datetime.now(timezone.utc)

            task_id = task_payload.task_id
            logger.debug(f"Routing task via Organism: {task_id}")

            # Step 1: resolve which organ should handle this task
            route_result = await self.client.post(
                "/resolve-route",
                json={"task": task_data},
            )

            if isinstance(route_result, dict) and route_result.get("error"):
                return {
                    "kind": DecisionKind.ERROR.value,
                    "success": False,
                    "error": f"Route resolution failed: {route_result.get('error')}",
                    "path": "organism_route_error"
                }

            organ_id = route_result.get("organ_id") or route_result.get("logical_id")
            if not organ_id:
                return {
                    "kind": DecisionKind.ERROR.value,
                    "success": False,
                    "error": "No organ ID returned from route resolution",
                    "path": "organism_no_organ"
                }

            # Step 2: execute on that organ
            execute_payload = {
                "organ_id": organ_id,
                "task": task_data
            }
            execute_result = await self.client.post(
                "/execute-on-organ",
                json=execute_payload,
            )

            logger.debug(f"Organism execute result: {execute_result}")

            decision_kind = execute_result.get("kind")

            # 3. COGNITIVE → delegate directly to CognitiveService (planner path)
            if decision_kind == DecisionKind.COGNITIVE.value:
                logger.info(
                    f"Task {task_id}: Cognitive planning requested; delegating to CognitiveService (RAG + Plan)."
                )
                try:
                    if not self.cognitive_client:
                        logger.error(
                            f"Task {task_id}: CognitiveServiceClient is not initialized. Cannot delegate."
                        )
                        execute_result["warning"] = "CognitiveServiceClient not available"
                        return execute_result

                    input_data = {
                        "task_description": task_payload.description or "No description provided.",
                        "agent_capabilities": {},
                        "available_resources": {},
                    }

                    meta = {
                        "task_id": task_id,
                        "correlation_id": correlation_id,
                    }

                    cog_res = await self.cognitive_client.execute_async(
                        agent_id=task_data.get("agent_id", f"dispatcher_planner_{task_id}"),
                        cog_type=CognitiveType.TASK_PLANNING,
                        decision_kind=DecisionKind.COGNITIVE,
                        input_data=input_data,
                        meta=meta,
                    )
                    return _wrap_cognitive_response(
                        task_data=task_data,
                        correlation_id=correlation_id,
                        cog_res=cog_res,
                    )

                except Exception as plan_err:
                    logger.warning(
                        f"Escalation router failed for task {task_id}: {plan_err}"
                    )
                    # Attach warning but still surface organism output
                    execute_result["warning"] = (
                        f"Escalation router failed: {plan_err}"
                    )
                    return execute_result

            # Otherwise:
            # - fast_path → direct success (FastPathResult)
            # - escalated → already decomposed HGNN plan (EscalatedResult)
            # - error     → pass it along
            result = execute_result

        except Exception as e:
            logger.error(f"OrganismRouter failed to route task: {e}")
            result = {
                "kind": DecisionKind.ERROR.value,
                "success": False,
                "error": str(e),
                "path": "organism_error"
            }

        selected_agent = (
            result.get("selected_agent_id")
            or result.get("meta", {}).get("routing_decision", {}).get("selected_agent_id")
        )
        score = (
            result.get("router_score")
            or result.get("meta", {}).get("routing_decision", {}).get("router_score")
        )
        _attach_routing_decision(result, selected_agent, score)
        _attach_exec_metrics(result, started_at, attempt=1)
        return result

    async def health_check(self) -> Dict[str, Any]:
        """Check Organism service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "organism"
            }

    async def close(self):
        """Close HTTP client."""
        await self.client.close()
        if getattr(self, "cognitive_client", None):
            try:
                await self.cognitive_client.close()
            except Exception as close_err:
                logger.debug(
                    "OrganismRouter failed to close CognitiveServiceClient: %s",
                    close_err,
                )
        if getattr(self, "cognitive_client", None):
            try:
                await self.cognitive_client.close()
            except Exception as close_err:
                logger.debug(
                    "CoordinatorHttpRouter failed to close CognitiveServiceClient: %s",
                    close_err,
                )


# -----------------------------------------------------------------------------
# CoordinatorHttpRouter
# -----------------------------------------------------------------------------

class CoordinatorHttpRouter(Router):
    """
    HTTP-based router that calls Coordinator service.

    Flow:
      1. Send task to Coordinator (/route-and-execute).
      2. Inspect Coordinator's result["kind"]:
          - kind == DecisionKind.FAST_PATH ("fast")
                → delegate to fast router (default: OrganismRouter)
          - kind == DecisionKind.COGNITIVE ("cognitive")
                → delegate to CognitiveService for planning
          - else (DecisionKind.ESCALATED "hgnn", DecisionKind.ERROR "error", etc.)
                → return Coordinator's result directly

    Why we do NOT forward "hgnn":
      "hgnn" in the new schema already means we HAVE a decomposed multi-step
      plan (EscalatedResult). There's nothing further to plan.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        config: Optional[RouterConfig] = None
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
            expected_exception=(Exception,)
        )
        retry_config = RetryConfig(
            max_attempts=self.config.max_retries,
            base_delay=self.config.retry_delay,
            max_delay=self.config.retry_delay * 4
        )

        self.client = BaseServiceClient(
            service_name="coordinator",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )

        try:
            self.cognitive_client = CognitiveServiceClient()
        except Exception as client_err:
            logger.warning(
                "CoordinatorHttpRouter failed to initialize CognitiveServiceClient: %s",
                client_err,
            )
            self.cognitive_client = None

        logger.info(f"CoordinatorHttpRouter initialized with base_url: {base_url}")


    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Route task through Coordinator HTTP API and then follow its routing kind."""
        try:
            task_payload = _coerce_task_payload(payload)
            task_data = task_payload.model_dump()
            if correlation_id:
                task_data["correlation_id"] = correlation_id

            started_at = datetime.now(timezone.utc)

            task_id = task_payload.task_id
            logger.info(f"Routing task via Coordinator HTTP: {task_id}")

            # 1. Ask Coordinator to process / decide
            result = await self.client.post("/route-and-execute", json=task_data)
            logger.info(f"Coordinator returned: {result}")

            # Extract correlation_id if Coordinator issued one (trace propagation override)
            # This allows Coordinator to start new trace segments for sub-tasks or cognitive plans
            coordinator_corr = (
                result.get("payload", {}).get("metadata", {}).get("correlation_id")
                or result.get("metadata", {}).get("correlation_id")
                or result.get("correlation_id")
            )
            if coordinator_corr:
                correlation_id = coordinator_corr
                logger.debug(f"Using Coordinator-issued correlation_id: {correlation_id}")

            decision_kind = result.get("kind")

            # 2. FAST_PATH → delegate to fast router (default: OrganismRouter)
            if decision_kind == DecisionKind.FAST_PATH.value:
                logger.info(
                    f"Task {task_id}: Coordinator chose fast_path; delegating."
                )
                try:
                    fast_router = RouterFactory.create_router(
                        router_type="organism",
                        config=self.config
                    )
                    fast_res = await fast_router.route_and_execute(
                        task_data,
                        correlation_id=correlation_id
                    )
                    await fast_router.close()
                    result = fast_res

                except Exception as handoff_err:
                    logger.warning(
                        f"Fast-path delegation failed for task {task_id}: {handoff_err}"
                    )
                    result.setdefault("warnings", []).append(
                        f"Fast-path delegation failed: {handoff_err}"
                    )
            elif decision_kind == DecisionKind.COGNITIVE.value:
                logger.info(
                    f"Task {task_id}: Cognitive planning requested; delegating to CognitiveService (RAG + Plan)."
                )
                try:
                    if not self.cognitive_client:
                        logger.error(
                            f"Task {task_id}: CognitiveServiceClient is not initialized. Cannot delegate."
                        )
                        result.setdefault("warnings", []).append(
                            "CognitiveServiceClient not available"
                        )
                    else:
                        input_data = {
                            "task_description": task_payload.description or "No description provided.",
                            "agent_capabilities": {},
                            "available_resources": {},
                        }

                        meta = {
                            "task_id": task_id,
                            "correlation_id": correlation_id,
                        }

                        cog_res = await self.cognitive_client.execute_async(
                            agent_id=task_data.get("agent_id", f"dispatcher_planner_{task_id}"),
                            cog_type=CognitiveType.TASK_PLANNING,
                            decision_kind=DecisionKind.COGNITIVE,
                            input_data=input_data,
                            meta=meta,
                        )
                        result = _wrap_cognitive_response(
                            task_data=task_data,
                            correlation_id=correlation_id,
                            cog_res=cog_res,
                        )

                except Exception as cog_err:
                    logger.error(
                        f"CognitiveService delegation failed for task {task_id}: {cog_err}",
                        exc_info=True
                    )
                    result.setdefault("warnings", []).append(
                        f"CognitiveService delegation failed: {cog_err}"
                    )
                    result["success"] = False
                    result["error"] = f"CognitiveService delegation failed: {cog_err}"
        except Exception as e:
            logger.error(f"CoordinatorHttpRouter failed to route task: {e}")
            result = {
                "kind": DecisionKind.ERROR.value,
                "success": False,
                "error": str(e),
                "path": "coordinator_http_error"
            }

        selected_agent = (
            result.get("selected_agent_id")
            or result.get("meta", {}).get("routing_decision", {}).get("selected_agent_id")
        )
        score = (
            result.get("router_score")
            or result.get("meta", {}).get("routing_decision", {}).get("router_score")
        )
        _attach_routing_decision(result, selected_agent, score)
        _attach_exec_metrics(result, started_at, attempt=1)
        return result

    async def health_check(self) -> Dict[str, Any]:
        """Check Coordinator service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "coordinator_http"
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
        router_type: Optional[str] = None,
        config: Optional[RouterConfig] = None
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
                timeout=float(os.getenv("DISPATCHER_ROUTER_TIMEOUT", "30.0")),
                max_retries=int(os.getenv("DISPATCHER_ROUTER_MAX_RETRIES", "3")),
                retry_delay=float(os.getenv("DISPATCHER_ROUTER_RETRY_DELAY", "1.0")),
                circuit_breaker_failures=int(os.getenv("DISPATCHER_ROUTER_CB_FAILURES", "5")),
                circuit_breaker_timeout=float(os.getenv("DISPATCHER_ROUTER_CB_TIMEOUT", "30.0"))
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
        router_type: Optional[str] = None,
        config: Optional[RouterConfig] = None
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
