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

# Import Ray utilities instead of direct ray.init()
from seedcore.utils.ray_utils import ensure_ray_initialized, is_ray_available, get_ray_cluster_info
from seedcore.agents.queue_dispatcher import Dispatcher
from seedcore.agents.graph_dispatcher import GraphDispatcher

# --- add right after imports, before logger = logging.getLogger(...) ---
import traceback

# Force-reset logging so our INFO lines actually print
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,  # <— important
)

# Ensure RAY_ADDRESS is present as a sane default when running interactively
os.environ.setdefault("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")

# Configure logging
logger = logging.getLogger(__name__)

def ensure_organism_initialized(timeout_s: float = 180) -> None:
    """Ensure OrganismManager is initialized (idempotent). Fail fast if not."""
    start = time.time()
    
    # 1) Try via Serve handle (best: no DNS dependency)
    try:
        import ray
        from ray import serve
        
        h = serve.get_deployment_handle("OrganismManager", app_name="organism")
        # Quick health check
        try:
            health = h.health.remote().result(timeout_s=15)
            if isinstance(health, dict) and health.get("organism_initialized") is True:
                logger.info("✅ Organism already initialized (Serve handle)")
                return
        except Exception:
            logger.info("ℹ️ Serve health check failed; will try to initialize")

        # Trigger initialization (idempotent)
        logger.info("🚀 Initializing organism via Serve handle…")
        resp = h.initialize_organism.remote().result(timeout_s=60)
        logger.info(f"📋 initialize_organism response: {resp}")

        # Poll until healthy
        while time.time() - start < timeout_s:
            try:
                health = h.health.remote().result(timeout_s=10)
                if isinstance(health, dict) and health.get("organism_initialized") is True:
                    logger.info("✅ Organism initialized (Serve handle)")
                    return
            except Exception:
                pass
            time.sleep(2)
        raise RuntimeError("Organism did not become initialized (Serve handle) within timeout")
    except Exception as e:
        logger.warning(f"⚠️ Serve handle path failed: {e}")

    # 2) Fallback: HTTP (if SERVE_BASE_URL / ORGANISM_URL are set)
    base = os.getenv("SERVE_BASE_URL", "http://seedcore-svc-serve-svc.seedcore-dev.svc.cluster.local:8000")
    org = os.getenv("ORGANISM_URL", f"{base}/organism")
    logger.info(f"🔗 Fallback HTTP init at {org}")

    # health
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{org}/health")
            if r.status_code == 200 and r.json().get("organism_initialized") is True:
                logger.info("✅ Organism already initialized (HTTP)")
                return
    except Exception:
        logger.info("ℹ️ HTTP health not ready; continuing")

    # init (POST)
    for _ in range(3):
        try:
            with httpx.Client(timeout=15) as client:
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
            with httpx.Client(timeout=5) as client:
                r = client.get(f"{org}/health")
                if r.status_code == 200 and r.json().get("organism_initialized") is True:
                    logger.info("✅ Organism initialized (HTTP)")
                    return
        except Exception:
            pass
        time.sleep(2)

    raise RuntimeError("Organism did not become initialized (HTTP) within timeout")

def main():
    """Initialize Ray and start Coordinator + Dispatcher actors."""
    
    # Get configuration from environment
    ns = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
    dsn = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))
    dispatcher_count = int(os.getenv("SEEDCORE_DISPATCHERS", "2"))
    exit_after_bootstrap = os.getenv("EXIT_AFTER_BOOTSTRAP", "false").lower() in ("1", "true", "yes")
    
    logger.info(f"🔧 Configuration: namespace={ns}, dispatchers={dispatcher_count}, dsn={dsn}")
    logger.info(f"🔧 Exit after bootstrap: {exit_after_bootstrap}")
    
    # Initialize Ray connection using ray_utils
    logger.info("🚀 Connecting to Ray cluster...")
    try:
        # Use ensure_ray_initialized from ray_utils instead of direct ray.init()
        if not ensure_ray_initialized(ray_namespace=ns):
            logger.error("❌ Failed to connect to Ray cluster")
            sys.exit(1)
        
        # Verify Ray is available and get cluster info
        if not is_ray_available():
            logger.error("❌ Ray connection established but cluster not available")
            sys.exit(1)
        
        cluster_info = get_ray_cluster_info()
        logger.info(f"✅ Connected to Ray cluster: {cluster_info}")
        
        # Bootstrap singleton memory actors before creating Coordinator
        try:
            from seedcore.bootstrap import bootstrap_actors
            bootstrap_actors()
            logger.info("✅ Bootstrapped singleton memory actors")
        except Exception:
            logger.exception("⚠️ bootstrap_actors() failed (will continue)")
        
        # Ensure organism is initialized before creating dispatchers
        logger.info("🚀 Ensuring organism is initialized...")
        try:
            ensure_organism_initialized()
            logger.info("✅ Organism initialization verified")
        except Exception as e:
            logger.exception("❌ Failed to ensure organism initialization")
            sys.exit(1)
        
    except Exception as e:
        logger.exception("❌ Ray connect blew up")  # prints stacktrace
        sys.exit(1)
    
    # Import ray after successful connection
    import ray
    
    # Define environment variables to pass to actors
    ENV_KEYS = [
        "OCPS_DRIFT_THRESHOLD",
        "COGNITIVE_TIMEOUT_S", 
        "COGNITIVE_MAX_INFLIGHT",
        "FAST_PATH_LATENCY_SLO_MS",
        "MAX_PLAN_STEPS",
    ]
    env_vars = {k: os.getenv(k, "") for k in ENV_KEYS}
    logger.info(f"🔧 Environment variables for actors: {env_vars}")
    
    # Note: Coordinator is now managed by Ray Serve as part of the organism app
    # The organism will be automatically deployed via serveConfigV2 in rayservice.yaml
    logger.info("ℹ️  Coordinator is now managed by Ray Serve organism app")
    logger.info("ℹ️  No need to create plain Ray actors - Serve will handle deployment")
    
    # Start Dispatcher actors
    dispatchers = []
    for i in range(dispatcher_count):
        name = f"seedcore_dispatcher_{i}"
        try:
            existing_dispatcher = ray.get_actor(name, namespace=ns)
            logger.info(f"✅ Dispatcher actor {name} already exists")
            dispatchers.append(existing_dispatcher)
        except Exception:
            logger.info(f"🚀 Creating Dispatcher actor {name}...")
            try:
                dispatcher = Dispatcher.options(
                    name=name,
                    lifetime="detached",
                    namespace=ns,
                    num_cpus=0.1,
                    resources={"head_node": 0.001},
                    runtime_env={"env_vars": env_vars},  # Pass env vars to actor
                ).remote(dsn=dsn, name=name)
                dispatchers.append(dispatcher)
                logger.info(f"✅ Dispatcher actor {name} created successfully")
            except Exception:
                logger.exception(f"❌ Failed to create Dispatcher actor {name}")
                continue
    
    if not dispatchers:
        logger.error("❌ No dispatchers were created successfully")
        sys.exit(1)
    
    # Start dispatcher run loops (non-blocking)
    logger.info("🚀 Starting dispatcher run loops...")
    for dispatcher in dispatchers:
        try:
            # Use fire-and-forget instead of ray.get() to avoid blocking
            dispatcher.run.remote()  # fire-and-forget infinite loop
            logger.info("✅ Dispatcher run loop triggered")
        except Exception:
            logger.exception("⚠️ Dispatcher run loop failed to start")
    
    # Start GraphDispatcher(s)
    try:
        from seedcore.agents.graph_dispatcher import GraphDispatcher
        
        graph_dispatcher_count = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
        for i in range(graph_dispatcher_count):
            gname = f"seedcore_graph_dispatcher_{i}"
            try:
                _ = ray.get_actor(gname, namespace=ns)
                logger.info(f"✅ GraphDispatcher {gname} already exists")
            except Exception:
                logger.info(f"🚀 Creating GraphDispatcher {gname}...")
                GraphDispatcher.options(
                    name=gname,
                    lifetime="detached",
                    namespace=ns,
                    num_cpus=0.2,
                    resources={"head_node": 0.001},
                    runtime_env={"env_vars": env_vars},  # Pass env vars to actor
                ).remote(dsn=dsn, name=gname)
                logger.info(f"✅ GraphDispatcher {gname} created successfully")
    except Exception as e:
        logger.exception("⚠️ GraphDispatcher creation failed (will continue): %s", e)
    
    logger.info("✅ Bootstrap complete!")
    logger.info(f"📊 Coordinator: OrganismManager Serve deployment")
    logger.info(f"📊 Dispatchers: {[f'seedcore_dispatcher_{i}' for i in range(dispatcher_count)]}")
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
