"""Dedicated Agent Action Gateway service.

This package hosts a standalone FastAPI application that exposes *only* the
agent action gateway surface (`/api/v1/agent-actions/*`).  Splitting the
gateway into its own process limits the blast radius of an external-facing
compromise and lets the hot-path evaluate/execute/closure endpoints scale
independently of the rest of the SeedCore management API.

The module is deliberately a thin composition layer:

- The gateway business logic still lives in
  `src/seedcore/api/routers/agent_actions_router.py`.
- The pydantic models still live in `src/seedcore/models/agent_action_gateway.py`.
- The only new concern here is the FastAPI app, its lifespan, and the
  health/readyz endpoints appropriate for an external-facing service.
"""

from .main import app, build_gateway_app

__all__ = ["app", "build_gateway_app"]
