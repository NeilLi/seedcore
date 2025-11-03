#!/usr/bin/env python3
"""
Task Router Interface for SeedCore Dispatcher

Routers:
- CoordinatorHttpRouter (entry point)
- OrganismRouter (fast-path execution)
- CognitiveRouter (planning / escalation)
- RouterFactory (creates routers)

Routing policy (aligned with seedcore.models.result_schema.ResultKind):
- Coordinator inspects .kind from Coordinator service response:
    - kind == "fast_path"   -> delegate to fast router (default: OrganismRouter)
    - kind == "cognitive"   -> delegate to escalation router (default: CognitiveRouter)
    - else (incl. "escalated", "error") -> return Coordinator's result
- Organism executes fast path, then inspects its own result:
    - kind == "cognitive"   -> delegate to escalation router (default: CognitiveRouter)
    - else (fast_path / escalated / error) -> return Organism result
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

from seedcore.models import TaskPayload
from seedcore.serve.base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from seedcore.models.result_schema import ResultKind  # <-- NEW

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
# CognitiveRouter
# -----------------------------------------------------------------------------

class CognitiveRouter(Router):
    """
    Escalation / planning router that calls the Cognitive service.

    Triggered when:
      - Coordinator returns kind == ResultKind.COGNITIVE ("cognitive")
      - Organism returns kind == ResultKind.COGNITIVE ("cognitive")

    It may receive partial reasoning context (proto_plan, surprise, etc.)
    and should forward that context into the cognitive service.

    If the upstream already produced kind == "escalated" or kind == "error",
    we DO NOT call cognitive again. We just passthrough that structure.
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
                base_url = f"{SERVE_GATEWAY}/cognitive"
            except Exception:
                base_url = "http://127.0.0.1:8000/cognitive"

        # Circuit breaker and retry
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
            service_name="cognitive",
            base_url=base_url,
            timeout=self.config.timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )

        logger.info(f"CognitiveRouter initialized with base_url: {base_url}")

    # ------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------

    def _normalize_payload_inbound(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        Normalize caller input into a common structure.

        Returns dict with:
            task_data: dict describing the original task from dispatcher
            prior_result: Optional[dict], TaskResult-like structure from upstream
            upstream_kind: Optional[str], e.g. "cognitive", "escalated", ...
        """
        if isinstance(payload, TaskPayload):
            task_data = payload.model_dump()
            prior_result = None
        elif isinstance(payload, dict) and "task_data" in payload:
            # Typical from CoordinatorHttpRouter or OrganismRouter
            task_data = payload.get("task_data", {}) or {}
            prior_result = payload.get("execute_result")
        else:
            # Assume caller passed raw task_data
            task_data = payload
            prior_result = None

        if correlation_id:
            task_data["correlation_id"] = correlation_id

        # pull upstream kind hint safely
        upstream_kind = None
        if isinstance(prior_result, dict):
            upstream_kind = prior_result.get("kind")
        if upstream_kind is None:
            upstream_kind = task_data.get("kind")

        return {
            "task_data": task_data,
            "prior_result": prior_result,
            "upstream_kind": upstream_kind,
        }

    def _should_passthrough(self, upstream_kind: Optional[str]) -> bool:
        """
        Decide if we should just return the upstream result without invoking /plan.
        We passthrough if upstream already has a final structured result.

        Case 1: upstream_kind == "escalated"
            => already a multi-step decomposition (EscalatedResult).
        Case 2: upstream_kind == "error"
            => we can't improve this by planning.
        """
        if upstream_kind == ResultKind.ESCALATED.value:
            return True
        if upstream_kind == ResultKind.ERROR.value:
            return True
        return False

    def _build_capability_string(self, task_data: Dict[str, Any]) -> str:
        raw_caps = (
            task_data.get("current_capabilities")
            or task_data.get("capabilities")
        )
        if isinstance(raw_caps, dict):
            cap_lines = ["Agent capabilities:"]
            for k, v in raw_caps.items():
                cap_lines.append(f"- {k}: {v}")
            return "\n".join(cap_lines)
        return str(raw_caps or "")

    def _extract_proto_plan(
        self,
        task_data: Dict[str, Any],
        prior_result: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Try to surface any planner hint or proto_plan we got from CoordinatorCore.
        We check:
          - prior_result["payload"]["result"]["proto_plan"]
          - prior_result["payload"]["metadata"]["proto_plan"]
          - task_data["proto_plan"]
        and return a lightweight version to cognitive.
        """
        # Helper to safely walk nested dicts
        def dig(obj, *path):
            cur = obj
            for p in path:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(p)
                if cur is None:
                    return None
            return cur

        # Look for proto_plan in prior_result first
        if isinstance(prior_result, dict):
            # In CognitiveResult payload shape:
            #   payload.result.proto_plan
            pp = dig(prior_result, "payload", "result", "proto_plan")
            if pp is not None:
                return pp

            # In metadata (from coordinator payload_common)
            pp = dig(prior_result, "payload", "metadata", "proto_plan")
            if pp is not None:
                return pp

        # Fall back to task_data
        if "proto_plan" in task_data:
            return task_data.get("proto_plan")

        return None

    # ------------------------------------------------------
    # Public API
    # ------------------------------------------------------

    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        High-level cognitive reasoning / planning entrypoint.

        This will:
          1. Normalize inbound payload.
          2. Decide if cognitive should run, or if we just passthrough.
          3. If cognitive should run:
                - build cog_request
                - call /plan
                - return that TaskResult-like structure.
        """
        try:
            norm = self._normalize_payload_inbound(payload, correlation_id)
            task_data = norm["task_data"]
            prior_result = norm["prior_result"]
            upstream_kind = norm["upstream_kind"]

            # Fast path: if upstream already produced final escalated
            # plan or an error, don't re-plan.
            if self._should_passthrough(upstream_kind):
                logger.info(
                    f"CognitiveRouter passthrough: upstream_kind={upstream_kind}"
                )
                # If we HAVE a prior_result, that's the authoritative object.
                if prior_result is not None:
                    return prior_result
                # Otherwise we just wrap and report what we have.
                return {
                    "kind": upstream_kind or ResultKind.ERROR.value,
                    "success": upstream_kind != ResultKind.ERROR.value,
                    "payload": {"context": task_data},
                    "metadata": {"path": "cognitive_passthrough"},
                }

            # Otherwise we are expected to actually think/plan.
            logger.debug("CognitiveRouter planning invocation starting.")

            caps_str = self._build_capability_string(task_data)
            profile = task_data.get("profile", "deep")
            agent_id = task_data.get("agent_id", "router")
            task_desc = task_data.get("description", "")

            # tool surface
            available_tools = (
                task_data.get("available_tools")
                or task_data.get("tools", {})
            )

            proto_plan_hint = self._extract_proto_plan(task_data, prior_result)

            cog_request = {
                "agent_id": agent_id,
                "task_description": task_desc,
                "current_capabilities": caps_str,
                "available_tools": available_tools,
                "profile": profile,

                # raw info for planner context / chain-of-thought / safety
                "context": task_data,
                "task_id": task_data.get("task_id"),
                "correlation_id": task_data.get("correlation_id"),

                # pass along upstream's draft thought / graph
                "proto_plan": proto_plan_hint,

                # pass along upstream result envelope for richer situational awareness
                # (e.g. coordinator decision signals, surprise score, etc.)
                "prior_result": prior_result,
            }

            logger.debug(
                f"CognitiveRouter /plan request agent_id={agent_id} "
                f"task_id={task_data.get('task_id')} "
                f"upstream_kind={upstream_kind}"
            )

            plan_result = await self.client.post("/plan", json=cog_request)

            logger.debug(
                f"CognitiveRouter /plan response for task_id={task_data.get('task_id')}: {plan_result}"
            )

            # We assume cognitive returns a TaskResult-like dict
            # with kind in {"cognitive","escalated","error"}.
            return plan_result

        except Exception as e:
            logger.error(f"CognitiveRouter failed to plan: {e}")

            # We normalize this into TaskResult-like error shape,
            # using ResultKind.ERROR.
            return {
                "kind": ResultKind.ERROR.value,
                "success": False,
                "payload": {
                    "error": str(e),
                    "error_type": "cognitive_router_exception",
                    "original_type": ResultKind.COGNITIVE.value,
                },
                "metadata": {
                    "path": "cognitive_error",
                },
            }

    async def health_check(self) -> Dict[str, Any]:
        """Check Cognitive service health."""
        try:
            return await self.client.health_check()
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "router_type": "cognitive"
            }

    async def close(self):
        """Close HTTP client."""
        await self.client.close()


# -----------------------------------------------------------------------------
# OrganismRouter
# -----------------------------------------------------------------------------

class OrganismRouter(Router):
    """
    Fast-path router that calls the Organism service directly.

    Flow:
      1. /resolve-route        -> which organ handles this?
      2. /execute-on-organ     -> run task on that organ
      3. If execute_result.kind == ResultKind.COGNITIVE ("cognitive"):
            Delegate to escalation router (default: CognitiveRouter via RouterFactory,
            overridable via env).
         Else:
            Return execute_result directly.

    NOTE:
    - If execute_result.kind == "fast_path": that's a normal success, return it.
    - If execute_result.kind == "escalated": that should already be a fully
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

        logger.info(f"OrganismRouter initialized with base_url: {base_url}")

    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Route task through Organism service for fast-path execution."""
        try:
            # Normalize task_data
            if isinstance(payload, TaskPayload):
                task_data = payload.model_dump()
            else:
                task_data = payload

            if correlation_id:
                task_data["correlation_id"] = correlation_id

            task_id = task_data.get("task_id", "unknown")
            logger.debug(f"Routing task via Organism: {task_id}")

            # Step 1: resolve which organ should handle this task
            route_result = await self.client.post(
                "/resolve-route",
                json={"task": task_data},
            )

            if isinstance(route_result, dict) and route_result.get("error"):
                return {
                    "kind": ResultKind.ERROR.value,
                    "success": False,
                    "error": f"Route resolution failed: {route_result.get('error')}",
                    "path": "organism_route_error"
                }

            organ_id = route_result.get("organ_id") or route_result.get("logical_id")
            if not organ_id:
                return {
                    "kind": ResultKind.ERROR.value,
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

            result_kind = execute_result.get("kind")

            # Step 3: cognitive planning handoff if Organism says this needs cognitive reasoning
            if result_kind == ResultKind.COGNITIVE.value:
                logger.info(
                    f"Task {task_id}: Organism requested cognitive escalation."
                )
                try:
                    cognitive_router = RouterFactory.create_router(
                        router_type="cognitive",
                        config=self.config
                    )

                    cog_payload = {
                        "task_data": task_data,
                        "execute_result": execute_result
                    }
                    plan_res = await cognitive_router.route_and_execute(
                        cog_payload,
                        correlation_id=correlation_id
                    )
                    await cognitive_router.close()
                    return plan_res

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
            return execute_result

        except Exception as e:
            logger.error(f"OrganismRouter failed to route task: {e}")
            return {
                "kind": ResultKind.ERROR.value,
                "success": False,
                "error": str(e),
                "path": "organism_error"
            }

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


# -----------------------------------------------------------------------------
# CoordinatorHttpRouter
# -----------------------------------------------------------------------------

class CoordinatorHttpRouter(Router):
    """
    HTTP-based router that calls Coordinator service.

    Flow:
      1. Send task to Coordinator (/process-task).
      2. Inspect Coordinator's result["kind"]:
          - kind == ResultKind.FAST_PATH ("fast_path")
                → delegate to fast router (default: OrganismRouter)
          - kind == ResultKind.COGNITIVE ("cognitive")
                → delegate to escalation router (default: CognitiveRouter)
          - else (ResultKind.ESCALATED "escalated", ResultKind.ERROR "error", etc.)
                → return Coordinator's result directly

    Why we do NOT forward "escalated":
      "escalated" in the new schema already means we HAVE a decomposed multi-step
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

        logger.info(f"CoordinatorHttpRouter initialized with base_url: {base_url}")

    async def route_and_execute(
        self,
        payload: Union[TaskPayload, Dict[str, Any]],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Route task through Coordinator HTTP API and then follow its routing kind."""
        try:
            # Normalize task_data
            if isinstance(payload, TaskPayload):
                task_data = payload.model_dump()
            else:
                task_data = payload

            if correlation_id:
                task_data["correlation_id"] = correlation_id

            task_id = task_data.get("task_id", "unknown")
            logger.info(f"Routing task via Coordinator HTTP: {task_id}")

            # 1. Ask Coordinator to process / decide
            result = await self.client.post("/process-task", json=task_data)
            logger.info(f"Coordinator returned: {result}")

            result_kind = result.get("kind")

            # 2. FAST_PATH → delegate to fast router (default: OrganismRouter)
            if result_kind == ResultKind.FAST_PATH.value:
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
                    return fast_res

                except Exception as handoff_err:
                    logger.warning(
                        f"Fast-path delegation failed for task {task_id}: {handoff_err}"
                    )
                    result["warning"] = (
                        f"Fast-path delegation failed: {handoff_err}"
                    )
                    return result

            # 3. COGNITIVE → delegate to escalation router (default: CognitiveRouter)
            if result_kind == ResultKind.COGNITIVE.value:
                logger.info(
                    f"Task {task_id}: Coordinator requested cognitive planning; delegating."
                )
                try:
                    cognitive_router = RouterFactory.create_router(
                        router_type="cognitive",
                        config=self.config
                    )
                    cog_payload = {
                        "task_data": task_data,
                        "execute_result": result
                    }
                    cog_res = await cognitive_router.route_and_execute(
                        cog_payload,
                        correlation_id=correlation_id
                    )
                    await cognitive_router.close()
                    return cog_res

                except Exception as cog_err:
                    logger.error(
                        f"Escalation delegation failed for task {task_id}: {cog_err}"
                    )
                    result["warning"] = (
                        f"Escalation delegation failed: {cog_err}"
                    )
                    return result

            # 4. Otherwise: "escalated" (already planned multi-step),
            #               "error", or anything unknown → return as-is.
            return result

        except Exception as e:
            logger.error(f"CoordinatorHttpRouter failed to route task: {e}")
            return {
                "kind": ResultKind.ERROR.value,
                "success": False,
                "error": str(e),
                "path": "coordinator_http_error"
            }

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
      - "cognitive"
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
        elif router_type == "cognitive":
            return CognitiveRouter(config=config)
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
