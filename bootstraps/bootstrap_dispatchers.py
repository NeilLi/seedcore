#!/usr/bin/env python3
"""
Bootstrap script to start Coordinator and Dispatcher actors on the Ray cluster.
Run this once to initialize the detached actors that handle task processing.
"""

import os
import sys
import logging
import time
import httpx
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import Ray utilities
from seedcore.utils.ray_utils import is_ray_available, get_ray_cluster_info
from seedcore.agents.queue_dispatcher import Dispatcher
from seedcore.agents.graph_dispatcher import GraphDispatcher

# --- add right after imports, before logger = logging.getLogger(...) ---
import traceback

# Force-reset logging so our INFO lines actually print
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,
)

# Ensure RAY_ADDRESS is present as a sane default when running interactively
os.environ.setdefault("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")

# Configure logging
logger = logging.getLogger(__name__)

import ray

def _ensure_ray(ns: str, addr: str) -> None:
    """Idempotent ray.init() that plays nice with Ray Client/Jobs."""
    if ray.is_initialized():
        logger.info("ℹ️ Ray already initialized, skipping ray.init()")
        return
    ray.init(address=addr, namespace=ns, ignore_reinit_error=True, logging_level=logging.INFO)

def _optional_resources():
    """Optionally pin to head node via custom resource (only if enabled)."""
    if os.getenv("PIN_TO_HEAD_NODE", "false").lower() in ("1", "true", "yes"):
        return {"head_node": 0.001}
    return None

def _wait_actor_gone(name: str, ns: str, timeout: float = 30.0) -> bool:
    """After kill, wait until the named actor is actually gone so the name is reusable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _ = ray.get_actor(name, namespace=ns)
            time.sleep(0.5)
        except Exception:
            return True
    return False

def _kill_actor_if_exists(name: str, ns: str) -> None:
    try:
        a = ray.get_actor(name, namespace=ns)
        ray.kill(a, no_restart=True)
        logger.info("♻️  Sent kill to actor %s", name)
        if not _wait_actor_gone(name, ns):
            logger.warning("⚠️ Actor %s did not disappear within timeout; creation may race", name)
    except Exception:
        logger.info("ℹ️ No existing actor %s to kill", name)


def ensure_organism_initialized(timeout_s: float = 180) -> None:
    """Ensure OrganismManager is initialized (idempotent). Fail fast if not."""
    start = time.time()
    
    # 1) Try via Serve handle (best: no DNS dependency)
    try:
        from ray import serve
        
        h = serve.get_deployment_handle("OrganismManager", app_name="organism")
        # Quick health check
        try:
            health = ray.get(h.health.remote(), timeout=15)
            if isinstance(health, dict) and health.get("organism_initialized") is True:
                logger.info("✅ Organism already initialized (Serve handle)")
                return
        except Exception:
            logger.info("ℹ️ Serve health check failed; will try to initialize")

        # Trigger initialization (idempotent)
        logger.info("🚀 Initializing organism via Serve handle…")
        resp = ray.get(h.initialize_organism.remote(), timeout=60)
        logger.info(f"📋 initialize_organism response: {resp}")

        # Poll until healthy
        while time.time() - start < timeout_s:
            try:
                health = ray.get(h.health.remote(), timeout=10)
                if isinstance(health, dict) and health.get("organism_initialized") is True:
                    logger.info("✅ Organism initialized (Serve handle)")
                    return
            except Exception:
                pass
            time.sleep(2)
        
        logger.warning("⚠️ Organism did not become initialized (Serve handle) within timeout")
        
    except Exception as e:
        logger.info(f"ℹ️ Serve handle approach failed: {e}")

    # 2) Fallback: HTTP (if SERVE_BASE_URL / ORGANISM_URL are set)
    base = os.getenv("SERVE_BASE_URL", "http://seedcore-svc-serve-svc.seedcore-dev.svc.cluster.local:8000")
    org = os.getenv("ORGANISM_URL", f"{base}/organism")
    logger.info(f"🔗 Fallback HTTP init at {org}")

    with httpx.Client(timeout=10) as client:
        # health
        try:
            r = client.get(f"{org}/health")
            if r.status_code == 200 and r.json().get("organism_initialized") is True:
                logger.info("✅ Organism already initialized (HTTP)")
                return
        except Exception:
            logger.info("ℹ️ HTTP health not ready; continuing")

        # init (POST)
        for _ in range(3):
            try:
                rr = client.post(f"{org}/initialize")
                if rr.status_code == 200:
                    logger.info(f"📋 POST /initialize: {rr.text[:200]}")
                    break
            except Exception as e:
                logger.info(f"ℹ️ POST /initialize retry: {e}")
            time.sleep(2)

        # poll
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                r = client.get(f"{org}/health")
                if r.status_code == 200 and r.json().get("organism_initialized") is True:
                    logger.info("✅ Organism initialized (HTTP)")
                    return
            except Exception:
                pass
            time.sleep(2)

    raise RuntimeError("Organism did not become initialized (HTTP) within timeout")

def _ensure_reaper(ns: str, dsn: str, env_vars: dict) -> None:
    """Create the detached reaper if missing (idempotent)."""
    if os.getenv("ENABLE_REAPER", "true").lower() not in ("1", "true", "yes"):
        logger.info("ℹ️ Reaper disabled by ENABLE_REAPER")
        return
    try:
        ray.get_actor("seedcore_reaper", namespace=ns)
        logger.info("✅ Reaper already exists")
    except Exception:
        from seedcore.agents.queue_dispatcher import Reaper
        logger.info("🚀 Creating Reaper actor…")
        Reaper.options(name="seedcore_reaper", lifetime="detached", namespace=ns, num_cpus=0.05,
                       runtime_env={"env_vars": env_vars}).remote(dsn=dsn)
        logger.info("✅ Reaper created")

def _ensure_graph_dispatchers(ns: str, dsn: str, env_vars: dict, force_replace: bool = False) -> None:
    """Create the detached GraphDispatcher actors if missing (idempotent)."""
    if os.getenv("ENABLE_GRAPH_DISPATCHERS", "true").lower() not in ("1", "true", "yes"):
        logger.info("ℹ️ GraphDispatchers disabled by ENABLE_GRAPH_DISPATCHERS")
        return
    
    # Validate namespace
    if not ns or ns.strip() == "":
        logger.error("❌ Invalid namespace for GraphDispatcher creation")
        return
    
    # Validate GraphDispatcher count
    try:
        graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
        if graph_dispatcher_count < 0:
            logger.warning("⚠️ SEEDCORE_GRAPH_DISPATCHERS cannot be negative, using 0")
            graph_dispatcher_count = 0
        elif graph_dispatcher_count > 10:
            logger.warning("⚠️ SEEDCORE_GRAPH_DISPATCHERS is very high ({graph_dispatcher_count}), consider reducing")
    except ValueError:
        logger.warning("⚠️ Invalid SEEDCORE_GRAPH_DISPATCHERS value, using 1")
        graph_dispatcher_count = 1
    
    if graph_dispatcher_count == 0:
        logger.info("ℹ️ GraphDispatchers disabled (count=0)")
        return
    
    logger.info(f"🚀 Ensuring {graph_dispatcher_count} GraphDispatcher(s) exist in namespace '{ns}'...")
    
    # Track creation success/failure
    created_count = 0
    failed_count = 0
    
    for i in range(graph_dispatcher_count):
        gname = f"seedcore_graph_dispatcher_{i}"
        
        if force_replace:
            _kill_actor_if_exists(gname, ns)
        
        # Check if GraphDispatcher exists and is healthy (unless force replace is enabled)
        if not force_replace:
            try:
                actor = ray.get_actor(gname, namespace=ns)
                # Health check via ping
                try:
                    if ray.get(actor.ping.remote(), timeout=5.0) == "pong":
                        logger.info(f"✅ GraphDispatcher {gname} is alive")
                        created_count += 1
                        continue
                    else:
                        logger.warning(f"⚠️ GraphDispatcher {gname} exists but unhealthy, will recreate")
                        ray.kill(actor, no_restart=True)
                        _wait_actor_gone(gname, ns)
                except Exception:
                    logger.warning(f"⚠️ GraphDispatcher {gname} unresponsive, recreating…")
                    ray.kill(actor, no_restart=True)
                    _wait_actor_gone(gname, ns)
            except Exception:
                logger.info(f"ℹ️ GraphDispatcher {gname} not found, creating new one…")

        # (Re)create GraphDispatcher
        try:
            logger.info(f"🚀 Creating GraphDispatcher {gname}...")
            
            # Validate that GraphDispatcher class is available
            try:
                from seedcore.agents.graph_dispatcher import GraphDispatcher
                logger.debug(f"✅ GraphDispatcher class imported successfully")
            except ImportError as import_e:
                logger.error(f"❌ Failed to import GraphDispatcher class: {import_e}")
                logger.error("❌ Make sure the GraphDispatcher module is available")
                logger.error("❌ Check that the module path is correct and dependencies are installed")
                failed_count += 1
                continue
            except Exception as import_e:
                logger.error(f"❌ Unexpected error importing GraphDispatcher: {import_e}")
                logger.error(f"❌ Error type: {type(import_e).__name__}")
                failed_count += 1
                continue
            
            resources = _optional_resources()
            opts = dict(
                name=gname,
                lifetime="detached",
                namespace=ns,
                num_cpus=0.1,
                runtime_env={"env_vars": env_vars},
                max_restarts=1,
            )
            if resources:
                opts["resources"] = resources
            
            # Validate options
            if not opts.get("name"):
                logger.error(f"❌ Invalid name in GraphDispatcher options: {opts}")
                failed_count += 1
                continue
            
            if not opts.get("namespace"):
                logger.error(f"❌ Invalid namespace in GraphDispatcher options: {opts}")
                failed_count += 1
                continue
            
            logger.debug(f"GraphDispatcher {gname} options: {opts}")
            
            # Validate DSN
            if not dsn or dsn.strip() == "":
                logger.error(f"❌ Invalid DSN for GraphDispatcher {gname}: {dsn}")
                failed_count += 1
                continue
            
            # Validate environment variables
            if not env_vars:
                logger.warning(f"⚠️ No environment variables provided for GraphDispatcher {gname}")
            else:
                logger.debug(f"ℹ️ Environment variables for GraphDispatcher {gname}: {env_vars}")
            
            logger.info(f"🚀 Calling GraphDispatcher.remote() for {gname}...")
            
            # Check Ray cluster status before creating actor
            try:
                if not ray.is_initialized():
                    logger.error(f"❌ Ray not initialized, cannot create GraphDispatcher {gname}")
                    failed_count += 1
                    continue
                
                # Get cluster info for debugging
                try:
                    cluster_info = get_ray_cluster_info()
                    logger.debug(f"ℹ️ Ray cluster info: {cluster_info}")
                except Exception:
                    logger.debug("ℹ️ Could not get Ray cluster info")
                
            except Exception as ray_check_e:
                logger.error(f"❌ Ray cluster check failed: {ray_check_e}")
                failed_count += 1
                continue
            
            try:
                actor = GraphDispatcher.options(**opts).remote(dsn=dsn, name=gname)
                logger.info(f"✅ GraphDispatcher {gname} remote() call completed")
            except Exception as create_e:
                logger.error(f"❌ GraphDispatcher.remote() call failed for {gname}: {create_e}")
                logger.error(f"❌ Error type: {type(create_e).__name__}")
                failed_count += 1
                continue
            
            # Verify the actor was actually created and is accessible
            try:
                logger.info(f"🔍 Verifying GraphDispatcher {gname} creation...")
                # Small delay to let Ray register the actor
                time.sleep(0.5)
                
                try:
                    verify_actor = ray.get_actor(gname, namespace=ns)
                    logger.info(f"✅ GraphDispatcher {gname} found in Ray registry")
                except Exception as get_actor_e:
                    logger.error(f"❌ GraphDispatcher {gname} not found in Ray registry: {get_actor_e}")
                    failed_count += 1
                    continue
                
                logger.info(f"🏓 Testing GraphDispatcher {gname} ping...")
                try:
                    ping_result = ray.get(verify_actor.ping.remote(), timeout=5.0)
                    if ping_result == "pong":
                        logger.info(f"✅ GraphDispatcher {gname} verified and responsive")
                        created_count += 1
                    else:
                        logger.warning(f"⚠️ GraphDispatcher {gname} created but ping returned: {ping_result}")
                        failed_count += 1
                except Exception as ping_e:
                    logger.error(f"❌ GraphDispatcher {gname} ping failed: {ping_e}")
                    failed_count += 1
                    
            except Exception as verify_e:
                logger.warning(f"⚠️ GraphDispatcher {gname} verification failed: {verify_e}")
                failed_count += 1
                
        except Exception as e:
            logger.exception(f"❌ Failed to create GraphDispatcher {gname}: {e}")
            # Log additional context for debugging
            logger.error(f"❌ GraphDispatcher creation failed for {gname}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            logger.error(f"❌ Error details: {e}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(f"❌ Full traceback: {''.join(traceback.format_tb(e.__traceback__))}")
            failed_count += 1
            # Don't exit on GraphDispatcher creation failure - it's optional
            continue
    
    # Summary of GraphDispatcher creation
    logger.info(f"📊 GraphDispatcher creation summary: {created_count}/{graph_dispatcher_count} successful, {failed_count} failed")
    if failed_count > 0:
        logger.warning(f"⚠️ {failed_count} GraphDispatcher(s) failed to create - check logs for details")
        logger.warning("⚠️ Common issues:")
        logger.warning("⚠️   - GraphDispatcher class not available/importable")
        logger.warning("⚠️   - Invalid DSN or database connection issues")
        logger.warning("⚠️   - Ray cluster issues or resource constraints")
        logger.warning("⚠️   - Missing dependencies or configuration")
    if created_count == 0 and graph_dispatcher_count > 0:
        logger.warning("⚠️ No GraphDispatchers were successfully created - this may indicate a configuration issue")
        logger.warning("⚠️ Check the logs above for specific error messages")
    elif created_count > 0:
        logger.info(f"✅ Successfully created {created_count} GraphDispatcher(s)")

def main():
    """Initialize Ray and start Coordinator + Dispatcher actors."""
    
    # Get configuration from environment
    ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    dsn = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
    dispatcher_count = int(os.getenv("DISPATCHER_COUNT", "2"))
    exit_after_bootstrap = os.getenv("EXIT_AFTER_BOOTSTRAP", "false").lower() in ("1", "true", "yes")
    force_replace = os.getenv("FORCE_REPLACE_DISPATCHERS", "false").lower() in ("1", "true", "yes")
    
    logger.info(f"🔧 Configuration: namespace={ns}, dispatchers={dispatcher_count}, dsn={dsn}")
    logger.info(f"🔧 Exit after bootstrap: {exit_after_bootstrap}")
    logger.info(f"🔧 Force replace dispatchers: {force_replace}")
    
    # Initialize Ray connection using ray_utils
    logger.info("🚀 Connecting to Ray cluster...")
    try:
        # Single, guarded init
        _ensure_ray(ns=ns, addr=os.getenv("RAY_ADDRESS", "auto"))
        
        # Verify Ray is available and get cluster info
        if not is_ray_available():
            logger.error("❌ Ray connection established but cluster not available")
            sys.exit(1)
        
        cluster_info = get_ray_cluster_info()
        logger.info(f"✅ Connected to Ray cluster: {cluster_info}")
        
    except Exception:
        logger.exception("❌ Ray connect blew up")  # prints stacktrace
        sys.exit(1)
    
    # Define environment variables to pass to actors
    ENV_KEYS = [
        "OCPS_DRIFT_THRESHOLD", "COGNITIVE_TIMEOUT_S", "COGNITIVE_MAX_INFLIGHT",
        "FAST_PATH_LATENCY_SLO_MS", "MAX_PLAN_STEPS",
        "SEEDCORE_GRAPH_DISPATCHERS", "ENABLE_GRAPH_DISPATCHERS",
    ]
    env_vars = {k: os.getenv(k, "") for k in ENV_KEYS}
    logger.info(f"🔧 Environment variables for actors: {env_vars}")
    
    # Log GraphDispatcher-specific configuration
    graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
    enable_graph_dispatchers = os.getenv("ENABLE_GRAPH_DISPATCHERS", "true").lower() in ("1", "true", "yes")
    logger.info(f"🔧 GraphDispatcher config: count={graph_dispatcher_count}, enabled={enable_graph_dispatchers}")
    
    # Ensure Reaper exists (idempotent)
    _ensure_reaper(ns=ns, dsn=dsn, env_vars=env_vars)
    
    # Ensure GraphDispatchers exist (idempotent)
    _ensure_graph_dispatchers(ns=ns, dsn=dsn, env_vars=env_vars, force_replace=force_replace)
    
    # Note: Coordinator is now managed by Ray Serve as part of the organism app
    # The organism will be automatically deployed via serveConfigV2 in rayservice.yaml
    logger.info("ℹ️  Coordinator is now managed by Ray Serve organism app")
    logger.info("ℹ️  No need to create plain Ray actors - Serve will handle deployment")
    
    # Start Dispatcher actors (idempotent & self-healing)
    dispatchers = []
    ready_count = 0
    created = []
    for i in range(dispatcher_count):
        name = f"seedcore_dispatcher_{i}"
        
        if force_replace:
            _kill_actor_if_exists(name, ns)
        
        # Check if dispatcher exists and is healthy (unless force replace is enabled)
        if not force_replace:
            try:
                actor = ray.get_actor(name, namespace=ns)
                # Health check via ping
                try:
                    if ray.get(actor.ping.remote(), timeout=5.0) == "pong":
                        logger.info(f"✅ Dispatcher {name} is alive")
                        dispatchers.append(actor)
                        continue
                    else:
                        logger.warning(f"⚠️ Dispatcher {name} exists but unhealthy, will recreate")
                        ray.kill(actor, no_restart=True)
                        _wait_actor_gone(name, ns)
                except Exception:
                    logger.warning(f"⚠️ Dispatcher {name} unresponsive, recreating…")
                    ray.kill(actor, no_restart=True)
                    _wait_actor_gone(name, ns)
            except Exception:
                logger.info(f"ℹ️ Dispatcher {name} not found, creating new one…")

        # (Re)create dispatcher
        try:
            resources = _optional_resources()
            opts = dict(
                name=name,
                lifetime="detached",
                namespace=ns,
                num_cpus=0.1,
                runtime_env={"env_vars": env_vars},
                max_restarts=1,
            )
            if resources:
                opts["resources"] = resources
            actor = Dispatcher.options(
                **opts
            ).remote(dsn=dsn, name=name)
            dispatchers.append(actor)
            logger.info(f"✅ Dispatcher {name} created successfully")
            created.append(actor)
        except Exception:
            logger.exception(f"❌ Failed to create Dispatcher {name}")
            if exit_after_bootstrap:
                sys.exit(1)
            continue

    # Warm-up newly created dispatchers so their pools exist before run()
    for idx, actor in enumerate(created):
        try:
            ok = ray.get(actor.ready.remote(timeout_s=30.0, interval_s=0.5), timeout=35.0)
            if ok:
                ready_count += 1
                st = ray.get(actor.get_status.remote(), timeout=5.0)
                logger.info("✅ Dispatcher %d ready: %s", idx, st)
            else:
                st = ray.get(actor.get_status.remote(), timeout=5.0)
                logger.warning("⚠️ Dispatcher %d not ready: %s", idx, st)
        except Exception as e:
            try:
                st = ray.get(actor.get_status.remote(), timeout=5.0)
            except Exception:
                st = "<unavailable>"
            logger.warning("⚠️ Dispatcher %d warmup failed: %s; status=%s", idx, e, st)

    logger.info("✅ %d/%d dispatchers ready", ready_count, dispatcher_count)
    if ready_count == 0:
        logger.error("❌ No dispatchers are ready")
        sys.exit(1)

    # Warm-up GraphDispatchers if they exist
    try:
        graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
        for i in range(graph_dispatcher_count):
            gname = f"seedcore_graph_dispatcher_{i}"
            try:
                gd = ray.get_actor(gname, namespace=ns)
                # Try to warm up the GraphDispatcher if it has a ready method
                if hasattr(gd, 'ready'):
                    try:
                        ok = ray.get(gd.ready.remote(timeout_s=30.0, interval_s=0.5), timeout=35.0)
                        if ok:
                            logger.info(f"✅ GraphDispatcher {gname} ready")
                        else:
                            logger.warning(f"⚠️ GraphDispatcher {gname} not ready")
                    except Exception as e:
                        logger.debug(f"ℹ️ GraphDispatcher {gname} warmup failed (may not have ready method): {e}")
                else:
                    # Just check if it's responsive
                    ping_result = ray.get(gd.ping.remote(), timeout=5.0)
                    if ping_result == "pong":
                        logger.info(f"✅ GraphDispatcher {gname} responsive")
                    else:
                        logger.warning(f"⚠️ GraphDispatcher {gname} ping returned unexpected result: {ping_result}")
            except Exception as e:
                logger.debug(f"ℹ️ GraphDispatcher {gname} warmup skipped: {e}")
    except Exception as e:
        logger.debug(f"ℹ️ GraphDispatcher warmup skipped: {e}")

    # Wait for dispatchers to be ready
    if dispatchers:
        logger.info(f"⏳ Waiting for {len(dispatchers)} dispatcher(s) to be ready...")
        # Note: ready_count is already calculated above from the warmup phase
        for i, actor in enumerate(dispatchers):
            try:
                # Wait for dispatcher to be ready
                status = ray.get(actor.get_status.remote(), timeout=30.0)
                if status.get("pool_initialized", False):
                    logger.info(f"✅ Dispatcher {i} ready: {status}")
                else:
                    logger.warning(f"⚠️ Dispatcher {i} not ready: {status}")
            except Exception as e:
                logger.warning(f"⚠️ Dispatcher {i} status check failed: {e}")
        
        logger.info(f"✅ {ready_count}/{len(dispatchers)} dispatchers ready")
        
        if ready_count == 0:
            logger.error("❌ No dispatchers are ready")
            if exit_after_bootstrap:
                sys.exit(1)
    else:
        logger.warning("⚠️ No dispatchers were created")

    # Health check GraphDispatchers if they exist
    try:
        graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
        for i in range(graph_dispatcher_count):
            gname = f"seedcore_graph_dispatcher_{i}"
            try:
                gd = ray.get_actor(gname, namespace=ns)
                ping_ref = gd.ping.remote()
                ping_result = ray.get(ping_ref, timeout=5.0)
                if ping_result == "pong":
                    logger.debug(f"✅ GraphDispatcher {gname} is responsive")
                else:
                    logger.warning(f"⚠️ GraphDispatcher {gname} ping returned unexpected result: {ping_result}")
            except Exception as e:
                logger.warning(f"⚠️ GraphDispatcher {gname} health check failed: {e}")
    except Exception as e:
        logger.debug(f"ℹ️ GraphDispatcher health check skipped: {e}")

    logger.info("✅ Bootstrap complete!")
    logger.info(f"📊 Coordinator: OrganismManager Serve deployment")
    logger.info(f"📊 Dispatchers: {[f'seedcore_dispatcher_{i}' for i in range(dispatcher_count)]}")
    
    # Summary of GraphDispatcher status
    try:
        graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
        graph_dispatcher_status = []
        for i in range(graph_dispatcher_count):
            gname = f"seedcore_graph_dispatcher_{i}"
            try:
                gd = ray.get_actor(gname, namespace=ns)
                ping_result = ray.get(gd.ping.remote(), timeout=5.0)
                if ping_result == "pong":
                    graph_dispatcher_status.append(f"{gname} ✅")
                else:
                    graph_dispatcher_status.append(f"{gname} ⚠️")
            except Exception:
                graph_dispatcher_status.append(f"{gname} ❌")
        logger.info(f"📊 GraphDispatchers: {graph_dispatcher_status}")
    except Exception as e:
        logger.warning(f"⚠️ Could not determine GraphDispatcher status: {e}")
        logger.info(f"📊 GraphDispatchers: {[f'seedcore_graph_dispatcher_{i}' for i in range(int(os.getenv('SEEDCORE_GRAPH_DISPATCHERS', '1')))]}")
    
    logger.info(f"📊 Namespace: {ns}")
    
    # If configured to exit after bootstrap, do so now
    if exit_after_bootstrap:
        logger.info("🚪 Exiting after bootstrap as requested")
        return
    
    # Keep the script running to maintain the actors and monitor health
    logger.info("🔄 Keeping bootstrap script alive to maintain actors...")
    logger.info("💡 Set EXIT_AFTER_BOOTSTRAP=true to exit after bootstrap")
    
    try:
        while True:
            time.sleep(60)  # Sleep for 1 minute
            
            # Check if actors are still alive
            try:
                # ✅ FIX: Coordinator is now a Serve deployment, health check handled by Serve
                # Check Dispatcher health using ping method
                for i, dispatcher in enumerate(dispatchers):
                    try:
                        dispatcher_name = f"seedcore_dispatcher_{i}"
                        # Use the ping method for health check
                        ping_ref = dispatcher.ping.remote()
                        ping_result = ray.get(ping_ref, timeout=5.0)
                        if ping_result == "pong":
                            logger.debug(f"✅ Dispatcher {dispatcher_name} is responsive")
                        else:
                            logger.warning(f"⚠️ Dispatcher {dispatcher_name} ping returned unexpected result: {ping_result}")
                    except Exception as e:
                        logger.warning(f"⚠️ Dispatcher {dispatcher_name} health check failed: {e}")
                
                # Check Reaper health (optional)
                try:
                    reaper = ray.get_actor("seedcore_reaper", namespace=ns)
                    ping_ref = reaper.ping.remote()
                    ping_result = ray.get(ping_ref, timeout=5.0)
                    if ping_result == "pong":
                        logger.debug("✅ Reaper is responsive")
                    else:
                        logger.warning(f"⚠️ Reaper ping returned unexpected result: {ping_result}")
                except Exception as e:
                    logger.debug(f"ℹ️ Reaper health check skipped: {e}")
                
                # Check GraphDispatcher health
                try:
                    graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
                    for i in range(graph_dispatcher_count):
                        gname = f"seedcore_graph_dispatcher_{i}"
                        try:
                            gd = ray.get_actor(gname, namespace=ns)
                            ping_ref = gd.ping.remote()
                            ping_result = ray.get(ping_ref, timeout=5.0)
                            if ping_result == "pong":
                                logger.debug(f"✅ GraphDispatcher {gname} is responsive")
                            else:
                                logger.warning(f"⚠️ GraphDispatcher {gname} ping returned unexpected result: {ping_result}")
                        except Exception as e:
                            logger.warning(f"⚠️ GraphDispatcher {gname} health check failed: {e}")
                except Exception as e:
                    logger.debug(f"ℹ️ GraphDispatcher health check skipped: {e}")
                
                # Log cluster status periodically
                cluster_info = get_ray_cluster_info()
                if cluster_info.get("status") == "available":
                    logger.debug("✅ Ray cluster is healthy")
                else:
                    logger.warning(f"⚠️ Ray cluster status: {cluster_info}")
                    
            except Exception as e:
                logger.error(f"❌ Health check failed: {e}")
                
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down bootstrap script...")
        # Note: We don't call ray.shutdown() here because we want the actors to persist
        # The detached actors will continue running even after this script exits
        logger.info("ℹ️ Detached actors will continue running after script exit")

if __name__ == "__main__":
    main()
