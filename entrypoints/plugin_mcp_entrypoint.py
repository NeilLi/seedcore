import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from ray import serve  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.plugin.mcp_service import SeedcorePluginMCPService
from seedcore.utils.ray_utils import ensure_ray_initialized

RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-stable-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")
APP_NAME = "seedcore-plugin-mcp"
ROUTE_PREFIX = "/seedcore-plugin/mcp"


def main():
    logger = ensure_serve_logger("seedcore.plugin_mcp.driver", level="DEBUG")
    setup_logging(app_name="seedcore.plugin_mcp.driver")

    if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
        raise SystemExit(1)

    serve.run(
        SeedcorePluginMCPService.bind(),
        name=APP_NAME,
        route_prefix=ROUTE_PREFIX,
    )

    logger.info("Seedcore Plugin MCP Service is running.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
