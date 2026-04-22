"""FastAPI application for the dedicated Agent Action Gateway process.

This app mounts only the gateway router and a minimal health surface.  It
reuses the same router, models, and business logic as the monolithic
`seedcore.main` app, so no code is duplicated — the only additional concern
here is wiring a lifespan and a readiness probe that match the gateway's
external-facing responsibilities.

See `docs/development/agent_action_gateway_contract.md` §"Rollout Plan" for
why this split exists.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse  # pyright: ignore[reportMissingImports]
from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncEngine  # pyright: ignore[reportMissingImports]

from ..api.routers.agent_actions_router import router as agent_actions_router
from ..database import (
    get_async_pg_engine,
    get_async_pg_session_factory,
    get_async_redis_client,
)
from ..ops.pkg import PKGClient, get_global_pkg_manager, initialize_global_pkg_manager
from ..ops.pkg.manager import PKGMode

logger = logging.getLogger(__name__)


GATEWAY_SERVICE_NAME = "seedcore-agent-action-gateway"
GATEWAY_SERVICE_VERSION = "1.0.0"


@asynccontextmanager
async def _gateway_lifespan(app: FastAPI):
    """Initialize only what the gateway surface actually needs.

    Intentionally smaller than `seedcore.main.lifespan` — the gateway does
    not run DDL, does not start background task workers, and does not
    depend on Neo4j/Kafka for request evaluation.
    """

    logger.info("Starting %s v%s", GATEWAY_SERVICE_NAME, GATEWAY_SERVICE_VERSION)

    engine = get_async_pg_engine()
    app.state.db_engine = engine

    try:
        if not get_global_pkg_manager():
            logger.info("Initializing PKG Manager for agent action gateway")
            session_factory = get_async_pg_session_factory()
            pkg_client = PKGClient(session_factory)
            try:
                redis_client = await get_async_redis_client()
            except Exception as redis_err:
                logger.warning("Redis unavailable for PKG hot-swap: %s", redis_err)
                redis_client = None
            mode_str = os.getenv("PKG_MODE", PKGMode.CONTROL.value).lower().strip()
            mode = (
                PKGMode.CONTROL
                if mode_str == PKGMode.CONTROL.value
                else PKGMode.ADVISORY
            )
            pkg_manager = await initialize_global_pkg_manager(
                pkg_client,
                redis_client,
                mode=mode,
            )
            if pkg_manager is not None:
                evaluator = pkg_manager.get_active_evaluator()
                if evaluator is not None:
                    logger.info(
                        "PKG Manager ready for gateway (mode=%s, version=%s)",
                        mode.value,
                        evaluator.version,
                    )
                else:
                    logger.warning(
                        "PKG Manager initialized but no active evaluator available",
                    )
            else:
                logger.error("PKG Manager initialization returned None")
    except Exception:
        logger.exception(
            "PKG Manager initialization failed for agent action gateway (non-fatal)",
        )

    logger.info("%s startup complete", GATEWAY_SERVICE_NAME)
    try:
        yield
    finally:
        logger.info("Shutting down %s", GATEWAY_SERVICE_NAME)
        eng: AsyncEngine | None = getattr(app.state, "db_engine", None)
        if eng is not None:
            try:
                await eng.dispose()
            except Exception:
                logger.exception("Failed to dispose gateway DB engine")
        logger.info("%s shutdown complete", GATEWAY_SERVICE_NAME)


def build_gateway_app() -> FastAPI:
    """Construct the standalone Agent Action Gateway FastAPI application."""

    app = FastAPI(
        title="SeedCore Agent Action Gateway",
        description=(
            "Dedicated external-facing surface for governed agent actions. "
            "Implements seedcore.agent_action_gateway.v1."
        ),
        version=GATEWAY_SERVICE_VERSION,
        lifespan=_gateway_lifespan,
    )

    cors_origins = os.getenv("GATEWAY_CORS_ALLOW_ORIGINS")
    if cors_origins is None:
        cors_origins = os.getenv("CORS_ALLOW_ORIGINS", "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[item.strip() for item in cors_origins.split(",") if item.strip()]
        or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(
        agent_actions_router,
        prefix="/api/v1",
        tags=["Agent Actions"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {
            "status": "healthy",
            "service": GATEWAY_SERVICE_NAME,
            "version": GATEWAY_SERVICE_VERSION,
        }

    @app.get("/readyz")
    async def ready_check():
        deps: dict[str, str] = {}
        all_ready = True

        try:
            eng: AsyncEngine = app.state.db_engine
            async with eng.connect() as conn:
                await conn.execute(text("SELECT 1"))
            deps["db"] = "ok"
        except Exception as exc:
            deps["db"] = f"error: {exc}"
            all_ready = False

        try:
            manager = get_global_pkg_manager()
            if manager is None:
                deps["pkg"] = "error: not initialized"
                all_ready = False
            else:
                evaluator = manager.get_active_evaluator()
                if evaluator is None:
                    deps["pkg"] = "error: no active evaluator"
                    all_ready = False
                else:
                    deps["pkg"] = f"ok (version={evaluator.version})"
        except Exception as exc:
            deps["pkg"] = f"error: {exc}"
            all_ready = False

        status = "ready" if all_ready else "not_ready"
        body = {"status": status, "deps": deps, "service": GATEWAY_SERVICE_NAME}
        if all_ready:
            return body
        return JSONResponse(status_code=503, content=body)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": GATEWAY_SERVICE_NAME,
            "version": GATEWAY_SERVICE_VERSION,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = build_gateway_app()


if __name__ == "__main__":
    import uvicorn  # pyright: ignore[reportMissingImports]

    uvicorn.run(
        "seedcore.gateway_service.main:app",
        host=os.getenv("GATEWAY_HOST", os.getenv("HOST", "0.0.0.0")),
        port=int(os.getenv("GATEWAY_PORT", "8022")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
