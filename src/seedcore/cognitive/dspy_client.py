from __future__ import annotations

"""
DSpyCognitiveClient — production-ready client for Ray Serve "Cognitive Core".
"""

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import ray
from ray import serve
from ray.exceptions import RayActorError

JSONDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_ns() -> str:
    return os.getenv("SEEDCORE_NS", "seedcore")


def _env_stage() -> str:
    return os.getenv("SEEDCORE_STAGE", "dev")


def _serve_app_name(base: str = "sc_cognitive") -> str:
    # For Ray Serve applications, we don't need namespace/stage prefixes
    # The application is deployed with the base name directly
    return base


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CognitiveClientError(RuntimeError):
    """Base error raised by DSpyCognitiveClient."""


class NotDeployedError(CognitiveClientError):
    """Raised when the Serve application isn't deployed/available."""


class RPCTimeoutError(CognitiveClientError):
    """Raised when an RPC exceeds its timeout."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ClientConfig:
    app_base_name: str = "sc_cognitive"
    # Use RAY_HOST and RAY_PORT environment variables that are set in the API pod
    ray_address: str = os.getenv("RAY_ADDRESS") or f"ray://{os.getenv('RAY_HOST', 'seedcore-svc-head-svc')}:{os.getenv('RAY_PORT', '10001')}"
    default_rpc_timeout_s: float = float(os.getenv("DSPY_CLIENT_RPC_TIMEOUT_S", "30"))
    max_retries: int = int(os.getenv("DSPY_CLIENT_MAX_RETRIES", "2"))
    backoff_base_s: float = 0.25
    backoff_cap_s: float = 2.0
    health_poll_interval_s: float = 0.5


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DSpyCognitiveClient:
    """
    Enhanced, production-ready client for Ray Serve Cognitive Core deployments.
    """

    def __init__(self, app_base_name: str = "sc_cognitive", *, config: Optional[ClientConfig] = None) -> None:
        self.app_name = _serve_app_name(app_base_name)
        self.config = config or ClientConfig(app_base_name=app_base_name)
        self._handle: Optional[Any] = None
        self._is_connected = False
        self._logger = logging.getLogger("dspy.cognitive_client")
        if not self._logger.handlers:
            logging.basicConfig(level=os.getenv("DSPY_CLIENT_LOG_LEVEL", "INFO"))
        
        # Log initialization details
        self._logger.info("Initializing DSpyCognitiveClient with app_name: %s", self.app_name)
        self._logger.info("Ray address: %s", self.config.ray_address)
        self._logger.info("Environment: NS=%s, STAGE=%s", _env_ns(), _env_stage())

    @classmethod
    def for_env(cls) -> "DSpyCognitiveClient":
        """Factory that applies env-based namespacing automatically."""
        return cls(app_base_name="sc_cognitive")

    def _connect_if_needed(self) -> None:
        if self._is_connected:
            self._logger.debug("Already connected to Ray")
            return
        
        self._logger.info("Connecting to Ray cluster...")
        
        # Check if Ray is already initialized (possibly by serve import)
        if ray.is_initialized():
            self._logger.info("Ray already initialized, checking connection...")
            try:
                runtime_context = ray.get_runtime_context()
                self._logger.info("Existing Ray runtime context: %s", runtime_context)
                
                # Check if we're connected to the right cluster
                if hasattr(runtime_context, 'worker') and hasattr(runtime_context.worker, 'worker_id'):
                    worker_id = runtime_context.worker.worker_id
                    self._logger.info("Connected to Ray worker: %s", worker_id)
                    
                    # If we're connected to a local worker, try to reconnect to remote cluster
                    if '127.0.0.1' in str(worker_id) or 'localhost' in str(worker_id):
                        self._logger.warning("Connected to local Ray instance, attempting to reconnect to remote cluster...")
                        ray.shutdown()
                        self._logger.info("Local Ray instance shut down, reconnecting to remote cluster...")
                        ray.init(address=self.config.ray_address, ignore_reinit_error=True, namespace=_env_ns())
                        self._logger.info("Successfully reconnected to remote Ray cluster")
                    else:
                        self._logger.info("Already connected to remote Ray cluster")
                else:
                    self._logger.info("Ray runtime context doesn't have worker info")
                    
            except Exception as e:
                self._logger.warning("Error checking existing Ray connection: %s", e)
                # Try to reconnect to remote cluster
                try:
                    ray.shutdown()
                    self._logger.info("Reconnecting to remote Ray cluster...")
                    ray.init(address=self.config.ray_address, ignore_reinit_error=True, namespace=_env_ns())
                    self._logger.info("Successfully reconnected to remote Ray cluster")
                except Exception as reconnect_e:
                    self._logger.error("Failed to reconnect to remote Ray cluster: %s", reconnect_e)
                    raise ConnectionError(f"Failed to connect to Ray cluster at {self.config.ray_address}: {reconnect_e}")
        else:
            try:
                self._logger.info("Initializing Ray with address: %s, namespace: %s", self.config.ray_address, _env_ns())
                self._logger.info("Ray environment variables: RAY_HOST=%s, RAY_PORT=%s, RAY_NAMESPACE=%s", 
                                os.getenv('RAY_HOST'), os.getenv('RAY_PORT'), os.getenv('RAY_NAMESPACE'))
                
                # Try to connect to remote Ray cluster
                ray.init(address=self.config.ray_address, ignore_reinit_error=True, namespace=_env_ns())
                
                # Verify we're connected to the remote cluster
                runtime_context = ray.get_runtime_context()
                self._logger.info("Ray runtime context: %s", runtime_context)
                if hasattr(runtime_context, 'worker') and hasattr(runtime_context.worker, 'worker_id'):
                    self._logger.info("Ray cluster address: %s", runtime_context.worker.worker_id)
                
                self._logger.info("Ray initialized successfully")
            except Exception as e:
                self._logger.error("Failed to initialize Ray with address %s: %s", self.config.ray_address, e)
                self._logger.error("Exception type: %s", type(e).__name__)
                import traceback
                self._logger.error("Full traceback: %s", traceback.format_exc())
                # Don't fall back to local Ray initialization in production
                # This would cause the client to look for applications in the wrong place
                raise ConnectionError(f"Failed to connect to Ray cluster at {self.config.ray_address}: {e}")
        
        try:
            self._logger.info("Connecting to Ray Serve...")
            # In newer Ray versions, serve.connect() is not needed
            # The connection is established when ray.init() succeeds
            self._logger.info("Ray Serve connection established")
        except Exception as exc:
            self._logger.warning("Ray Serve connection warning: %s", exc)
        
        self._is_connected = True
        self._logger.info("Connection setup completed")

    def _get_handle(self, *, force_refetch: bool = False) -> Any:
        self._logger.debug("Getting handle for app: %s (force_refetch: %s)", self.app_name, force_refetch)
        self._connect_if_needed()
        
        if self._handle is None or force_refetch:
            try:
                self._logger.info("Fetching app handle for: %s", self.app_name)
                self._handle = serve.get_app_handle(self.app_name)
                self._logger.info("Successfully got app handle")
            except (RuntimeError, ValueError) as e:
                self._logger.warning("Failed to get app handle for '%s': %s", self.app_name, e)
                self._handle = None
                # Don't raise exception - return None to indicate app not available
                # This allows the client to work non-blocking and retry later
                return None
        return self._handle

    def _serve_app_status(self) -> Optional[Any]:
        try:
            self._logger.debug("Getting Serve status...")
            # Ensure we're connected to the remote cluster before calling serve.status()
            self._connect_if_needed()
            
            st = serve.status()
            app_status = st.applications.get(self.app_name)
            if app_status:
                self._logger.info("App status: %s", app_status.status)
            else:
                self._logger.warning("App '%s' not found in Serve status", self.app_name)
            return app_status
        except Exception as exc:
            self._logger.error("serve.status() failed: %s", exc)
            return None

    async def ready(self, timeout_s: float = 10.0) -> bool:
        self._logger.info("Checking if service is ready (timeout: %s seconds)...", timeout_s)
        deadline = time.time() + max(0.0, timeout_s)
        
        while time.time() < deadline:
            try:
                app_status = self._serve_app_status()
                is_app_running = bool(app_status and "RUNNING" in str(app_status.status))
                
                if not is_app_running:
                    self._logger.debug("App not running yet, waiting %s seconds...", self.config.health_poll_interval_s)
                    await asyncio.sleep(self.config.health_poll_interval_s)
                    continue
                
                self._logger.info("App is running, checking health...")
                health_status = await self.health_async()
                if health_status.get("status") == "healthy":
                    self._logger.info("Service is ready and healthy")
                    return True
                else:
                    self._logger.warning("Service running but unhealthy: %s", health_status)
                    
            except (ConnectionError, RayActorError, NotDeployedError) as e:
                self._logger.debug("Service not ready yet: %s", e)
            
            await asyncio.sleep(self.config.health_poll_interval_s)
        
        self._logger.warning("Service not ready after %s seconds", timeout_s)
        return False

    def ready_sync(self, timeout_s: float = 10.0) -> bool:
        return _run_sync(self.ready(timeout_s=timeout_s))

    def is_deployed(self) -> bool:
        """Check if the cognitive core application is deployed without blocking.
        
        Returns:
            True if the application is deployed and accessible, False otherwise.
        """
        try:
            handle = self._get_handle()
            return handle is not None
        except Exception:
            return False

    def get_deployment_status(self) -> JSONDict:
        """Get detailed deployment status without blocking.
        
        Returns:
            Dictionary with deployment status information.
        """
        try:
            app_status = self._serve_app_status()
            if app_status is None:
                return {"status": "NOT_FOUND", "message": f"Application '{self.app_name}' not found or Serve unavailable."}
            
            try:
                status_info = app_status.dict()
                return status_info
            except Exception:
                return {"status": str(app_status.status)}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    @property
    def status(self) -> JSONDict:
        self._logger.debug("Getting service status...")
        app_status = self._serve_app_status()
        if app_status is None:
            status_info = {"status": "NOT_FOUND", "message": f"Application '{self.app_name}' not found or Serve unavailable."}
            self._logger.warning("Status: %s", status_info)
            return status_info
        try:
            status_info = app_status.dict()
            self._logger.info("Status: %s", status_info)
            return status_info
        except Exception as e:
            status_info = {"status": str(app_status.status)}
            self._logger.warning("Status (fallback): %s", status_info)
            return status_info

    def health(self) -> JSONDict:
        self._logger.info("Checking service health...")
        try:
            return _run_sync(self.health_async())
        except (RuntimeError, ConnectionError, RayActorError, CognitiveClientError) as e:
            health_info = {"status": "UNAVAILABLE", "error": str(e)}
            self._logger.error("Health check failed: %s", health_info)
            return health_info

    async def health_async(self) -> JSONDict:
        self._logger.debug("Checking service health (async)...")
        try:
            handle = self._get_handle()
            if handle is None:
                # App handle not available - cognitive core not deployed yet
                return {"status": "NOT_DEPLOYED", "message": f"Application '{self.app_name}' not deployed yet"}
            
            # Note: The health endpoint in the service doesn't take a request body
            health_result = await self._rpc_call(handle, "health", timeout_s=self.config.default_rpc_timeout_s)
            self._logger.info("Health check successful: %s", health_result)
            return health_result
        except (ConnectionError, RayActorError, NotDeployedError) as e:
            self._logger.error("Health check failed: %s", e)
            self._handle = None
            raise

    async def _rpc_call(self, handle: Any, method_name: str, *args: Any, timeout_s: Optional[float] = None) -> JSONDict:
        if handle is None:
            # App handle not available - cognitive core not deployed yet
            return {"status": "NOT_DEPLOYED", "message": f"Application '{self.app_name}' not deployed yet", "method": method_name}
        
        timeout_s = float(timeout_s or self.config.default_rpc_timeout_s)
        attempt = 0
        
        self._logger.debug("Making RPC call: %s (timeout: %s)", method_name, timeout_s)
        
        while True:
            try:
                method = getattr(handle, method_name)
                # FIX: Pass arguments individually, not as a single dict
                result = await asyncio.wait_for(method.remote(*args), timeout=timeout_s)
                self._logger.debug("RPC call successful: %s", method_name)
                return result
            except asyncio.TimeoutError as e:
                self._logger.error("RPC timeout: %s exceeded %s seconds", method_name, timeout_s)
                raise RPCTimeoutError(f"RPC '{method_name}' exceeded {timeout_s:.2f}s") from e
            except RayActorError as e:
                attempt += 1
                self._logger.warning("RayActorError on '%s' (attempt %d/%d): %s", method_name, attempt, self.config.max_retries, e)
                
                if attempt > self.config.max_retries:
                    self._logger.error("Max retries exceeded for RPC call: %s", method_name)
                    raise
                
                self._logger.debug("Retrying RPC call: %s", method_name)
                await asyncio.sleep(_jitter_backoff(attempt, self.config.backoff_base_s, self.config.backoff_cap_s))
                handle = self._get_handle(force_refetch=True)
                if handle is None:
                    # App handle still not available after retry
                    return {"status": "NOT_DEPLOYED", "message": f"Application '{self.app_name}' not deployed yet", "method": method_name}
    
    # FIX: All cognitive tasks are updated to pass arguments individually.
    async def assess(self, agent_id: str, performance_data: Mapping[str, Any], current_capabilities: Optional[Mapping[str, Any]] = None, target_capabilities: Optional[Mapping[str, Any]] = None, *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "assess_capabilities", agent_id, dict(performance_data), dict(current_capabilities or {}), dict(target_capabilities or {}), timeout_s=timeout_s)

    async def plan(self, agent_id: str, task_description: str, current_capabilities: Mapping[str, Any], available_tools: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "plan_task", agent_id, task_description, dict(current_capabilities), dict(available_tools), timeout_s=timeout_s)

    async def decide(self, agent_id: str, decision_context: Mapping[str, Any], historical_data: Optional[Mapping[str, Any]] = None, *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "make_decision", agent_id, dict(decision_context), dict(historical_data or {}), timeout_s=timeout_s)

    async def solve(self, agent_id: str, problem_statement: str, constraints: Mapping[str, Any], available_tools: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "solve_problem", agent_id, problem_statement, dict(constraints), dict(available_tools), timeout_s=timeout_s)

    async def synthesize(self, agent_id: str, memory_fragments: list, synthesis_goal: str, *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "synthesize_memory", agent_id, list(memory_fragments), synthesis_goal, timeout_s=timeout_s)

    async def analyze_failure(self, agent_id: str, incident_context: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        handle = self._get_handle()
        return await self._rpc_call(handle, "reason_about_failure", agent_id, dict(incident_context), timeout_s=timeout_s)

    # --- Sync wrappers ---
    def assess_sync(self, agent_id: str, performance_data: Mapping[str, Any], current_capabilities: Optional[Mapping[str, Any]] = None, target_capabilities: Optional[Mapping[str, Any]] = None, *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.assess(agent_id, performance_data, current_capabilities=current_capabilities, target_capabilities=target_capabilities, timeout_s=timeout_s))

    def plan_sync(self, agent_id: str, task_description: str, current_capabilities: Mapping[str, Any], available_tools: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.plan(agent_id, task_description, current_capabilities, available_tools, timeout_s=timeout_s))

    def decide_sync(self, agent_id: str, decision_context: Mapping[str, Any], historical_data: Optional[Mapping[str, Any]] = None, *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.decide(agent_id, decision_context, historical_data=historical_data, timeout_s=timeout_s))

    def solve_sync(self, agent_id: str, problem_statement: str, constraints: Mapping[str, Any], available_tools: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.solve(agent_id, problem_statement, constraints, available_tools, timeout_s=timeout_s))

    def synthesize_sync(self, agent_id: str, memory_fragments: list, synthesis_goal: str, *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.synthesize(agent_id, memory_fragments, synthesis_goal, timeout_s=timeout_s))

    def analyze_failure_sync(self, agent_id: str, incident_context: Mapping[str, Any], *, timeout_s: Optional[float] = None) -> JSONDict:
        return _run_sync(self.analyze_failure(agent_id, incident_context, timeout_s=timeout_s))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _jitter_backoff(attempt: int, base: float, cap: float) -> float:
    """Exponential backoff with ±20% jitter, capped."""
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    jitter = delay * random.uniform(-0.2, 0.2)
    return max(0.0, delay + jitter)


def _run_sync(coro: "asyncio.Future[Any] | asyncio.Task[Any] | asyncio.coroutines.Coroutine[Any, Any, Any]") -> Any:
    """Safely run a coroutine from a sync context."""
    try:
        loop = asyncio.get_running_loop()
        raise RuntimeError("Cannot run sync wrapper inside an active event loop. Use the async methods instead.")
    except RuntimeError as e:
        if "no running event loop" not in str(e):
            raise e
        # No running loop — OK to create a new one.
        return asyncio.run(coro)

# ---------------------------------------------------------------------------
# Optional quick-check
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Set up comprehensive logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 80)
    print("DSpyCognitiveClient Diagnostic Test")
    print("=" * 80)
    
    client = DSpyCognitiveClient.for_env()
    print(f"App: {client.app_name}")
    
    # Check environment variables
    print(f"Environment variables:")
    print(f"  SEEDCORE_NS: {os.getenv('SEEDCORE_NS', 'NOT_SET')}")
    print(f"  SEEDCORE_STAGE: {os.getenv('SEEDCORE_STAGE', 'NOT_SET')}")
    print(f"  RAY_ADDRESS: {os.getenv('RAY_ADDRESS', 'NOT_SET')}")
    print(f"  DSPY_CLIENT_LOG_LEVEL: {os.getenv('DSPY_CLIENT_LOG_LEVEL', 'NOT_SET')}")
    
    # Check Ray initialization
    print(f"\nRay status:")
    print(f"  Ray initialized: {ray.is_initialized()}")
    if ray.is_initialized():
        print(f"  Ray address: {ray.get_runtime_context().worker.worker_id}")
        print(f"  Ray namespace: {ray.get_runtime_context().namespace}")
    
    # Check if service is ready (this will connect to remote Ray cluster first)
    print(f"\nService readiness check:")
    try:
        ready_status = client.ready_sync(timeout_s=10)
        print(f"  Ready: {ready_status}")
        
        if ready_status:
            print(f"  Health check:")
            health_result = client.health()
            print(f"    {health_result}")
        else:
            print(f"  Service not ready - checking status:")
            status_result = client.status
            print(f"    {status_result}")
            
    except Exception as e:
        print(f"  Error during readiness check: {e}")
        import traceback
        traceback.print_exc()
    
    # Now check Serve status after client has connected
    print(f"\nServe status (after client connection):")
    try:
        # Ensure client is connected before checking Serve status
        client._connect_if_needed()
        serve_status = serve.status()
        print(f"  Serve available: True")
        print(f"  Applications: {list(serve_status.applications.keys())}")
        
        # Look for sc_cognitive app
        if 'sc_cognitive' in serve_status.applications:
            app_status = serve_status.applications['sc_cognitive']
            print(f"  ✅ Found sc_cognitive app: {app_status.status}")
        else:
            print(f"  ❌ sc_cognitive app not found")
            
    except Exception as e:
        print(f"  Serve available: False")
        print(f"  Error: {e}")
    
    print("=" * 80)