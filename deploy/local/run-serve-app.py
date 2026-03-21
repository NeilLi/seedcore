#!/usr/bin/env python3
"""Deploy one SeedCore Serve app into a local single-node Ray cluster."""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
from pathlib import Path

from ray import serve  # pyright: ignore[reportMissingImports]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PROJECT_ROOT.parent
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    c = str(candidate)
    if c not in sys.path:
        sys.path.insert(0, c)

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.utils.ray_utils import ensure_ray_initialized

APP_SPECS = {
    "organism": {
        "module": "entrypoints.organism_entrypoint",
        "builder": "build_organism_app",
        "app_name": "organism",
        "route_prefix": "/organism",
    },
    "cognitive": {
        "module": "entrypoints.cognitive_entrypoint",
        "builder": "build_cognitive_app",
        "app_name": "cognitive",
        "route_prefix": "/cognitive",
    },
    "coordinator": {
        "module": "entrypoints.coordinator_entrypoint",
        "builder": "build_coordinator",
        "app_name": "coordinator",
        "route_prefix": "/pipeline",
    },
    "ops": {
        "module": "entrypoints.ops_entrypoint",
        "builder": "build_ops_app",
        "app_name": "ops",
        "route_prefix": "/ops",
    },
    "mcp": {
        "module": "entrypoints.mcp_entrypoint",
        "builder": "build_mcp_app",
        "app_name": "mcp",
        "route_prefix": "/mcp",
    },
    "ml": {
        "module": "entrypoints.ml_entrypoint",
        "builder": "build_ml_service",
        "app_name": "ml_service",
        "route_prefix": "/ml",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", choices=sorted(APP_SPECS))
    args = parser.parse_args()

    spec = APP_SPECS[args.app]

    setup_logging(app_name=f"seedcore.local.{args.app}")
    logger = ensure_serve_logger(f"seedcore.local.{args.app}", level="DEBUG")

    ray_address = os.getenv("RAY_ADDRESS", "ray://127.0.0.1:10001")
    ray_namespace = os.getenv("RAY_NAMESPACE", "seedcore-local")

    if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
        logger.error("Failed to connect to Ray: address=%s namespace=%s", ray_address, ray_namespace)
        return 1

    module = importlib.import_module(spec["module"])
    builder = getattr(module, spec["builder"])
    app = builder()

    logger.info(
        "Deploying app=%s as Serve app_name=%s route_prefix=%s",
        args.app,
        spec["app_name"],
        spec["route_prefix"],
    )
    serve.run(app, name=spec["app_name"], route_prefix=spec["route_prefix"])
    logger.info("Serve app deployed: %s", args.app)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Shutting down local app process: %s", args.app)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
