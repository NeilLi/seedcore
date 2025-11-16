import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from ray import serve  # pyright: ignore[reportMissingImports]
from seedcore.utils.ray_utils import ensure_ray_initialized
from seedcore.logging_setup import setup_logging, ensure_serve_logger

from seedcore.services.mcp_service import MCPService

RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")


def build_mcp_app(args=None):
    return MCPService.bind()

def main():
    logger = ensure_serve_logger("seedcore.mcp_service.driver", level="DEBUG")
    setup_logging(app_name="seedcore.mcp_service.driver")

    if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
        raise SystemExit(1)

    serve.run(
        MCPService.bind(),
        name="mcp",
        route_prefix="/mcp"
    )

    logger.info("MCP Service is running.")

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
