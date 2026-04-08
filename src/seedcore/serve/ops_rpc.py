#!/usr/bin/env python3
"""Helpers for in-cluster RPC access to the OpsGateway deployment."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _env_truthy(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ops_rpc_enabled() -> bool:
    """Whether internal callers should prefer Ray Serve RPC over HTTP."""
    return _env_truthy("SEEDCORE_OPS_RPC_ENABLED", "true")


def get_ops_gateway_handle() -> Optional[Any]:
    """Return a deployment handle for the in-cluster Ops gateway when available."""
    if not ops_rpc_enabled():
        return None

    try:
        from ray import serve  # pyright: ignore[reportMissingImports]
    except Exception as exc:
        logger.debug("Ops RPC unavailable: Ray Serve import failed: %s", exc)
        return None

    app_name = os.getenv("SEEDCORE_OPS_APP_NAME", "ops")
    deployment_name = os.getenv("SEEDCORE_OPS_DEPLOYMENT_NAME", "OpsGateway")
    try:
        return serve.get_deployment_handle(deployment_name, app_name=app_name)
    except Exception as exc:
        logger.debug(
            "Ops RPC unavailable: failed to get handle %s/%s: %s",
            app_name,
            deployment_name,
            exc,
        )
        return None


async def call_ops_rpc(
    handle: Any,
    method_name: str,
    *args: Any,
    timeout_s: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    """Call an OpsGateway RPC method through a deployment handle."""
    if handle is None:
        raise RuntimeError("ops_gateway_handle_unavailable")

    method = getattr(handle, method_name, None)
    if method is None or not hasattr(method, "remote"):
        raise AttributeError(f"ops_gateway_method_missing:{method_name}")

    response = method.remote(*args, **kwargs)
    if timeout_s is None:
        return await response
    return await asyncio.wait_for(response, timeout=float(timeout_s))
