# docker/app_entrypoint.py
import os, time, sys, socket
import ray
import uvicorn
from pathlib import Path

# Add src to path (ensure /app/src is importable)
sys.path.insert(0, str(Path(__file__).parent / "src"))

RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-dev-head-svc:10001")
RAY_NS   = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8002"))

def wait_tcp(host, port, timeout=3, tries=30):
    """Wait for TCP connection to be available."""
    for i in range(tries):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            time.sleep(2)
    return False

def main():
    print(f"[app] Starting SeedCore API application")
    
    # ray://host:port → extract host/port for a basic preflight
    preflight_ok = True
    if RAY_ADDR.startswith("ray://"):
        _ = RAY_ADDR[len("ray://"):]
        host, port = _.split(":")[0], int(_.split(":")[1])
        print(f"[app] Checking Ray head connectivity to {host}:{port}")
        preflight_ok = wait_tcp(host, port, tries=60)
    
    if not preflight_ok:
        print(f"[app] Ray client {RAY_ADDR} not reachable", file=sys.stderr)
        sys.exit(1)

    # Connect to Ray
    print(f"[app] Connecting to Ray at {RAY_ADDR} (ns={RAY_NS})")
    try:
        ray.init(address=RAY_ADDR, namespace=RAY_NS, ignore_reinit_error=True, log_to_driver=True)
        print(f"[app] Successfully connected to Ray cluster")
    except Exception as e:
        print(f"[app] Failed to connect to Ray: {e}", file=sys.stderr)
        sys.exit(1)

    # Check if we can import the telemetry server
    try:
        from seedcore.telemetry.server import app
        print(f"[app] Successfully imported telemetry server")
    except Exception as e:
        print(f"[app] Failed to import telemetry server: {e}", file=sys.stderr)
        sys.exit(1)

    # Start the API server
    print(f"[app] Starting API server at {API_HOST}:{API_PORT}")
    try:
        uvicorn.run(
            app,
            host=API_HOST,
            port=API_PORT,
            log_level="info",
            access_log=True
        )
    except Exception as e:
        print(f"[app] Failed to start API server: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()


