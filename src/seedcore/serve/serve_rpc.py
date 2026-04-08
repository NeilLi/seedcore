#!/usr/bin/env python3
"""Generic Ray Serve RPC helpers for in-cluster service clients."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def env_rpc_enabled(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default)
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_serve_deployment_handle(
    deployment_name: str,
    *,
    app_name: str,
    enabled_env: str,
) -> Optional[Any]:
    """Return a deployment handle when in-cluster RPC is enabled and available."""
    if not env_rpc_enabled(enabled_env, "true"):
        return None

    try:
        from ray import serve  # pyright: ignore[reportMissingImports]
    except Exception as exc:
        logger.debug("Serve RPC unavailable for %s/%s: %s", app_name, deployment_name, exc)
        return None

    try:
        return serve.get_deployment_handle(deployment_name, app_name=app_name)
    except Exception as exc:
        logger.debug(
            "Failed to get Serve deployment handle for %s/%s: %s",
            app_name,
            deployment_name,
            exc,
        )
        return None


async def call_serve_rpc(
    handle: Any,
    method_name: str,
    *args: Any,
    timeout_s: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    """Invoke a method on a Serve deployment handle."""
    if handle is None:
        raise RuntimeError("serve_rpc_handle_unavailable")

    method = getattr(handle, method_name, None)
    if method is None or not hasattr(method, "remote"):
        raise AttributeError(f"serve_rpc_method_missing:{method_name}")

    ref = method.remote(*args, **kwargs)
    if timeout_s is None:
        return await ref
    return await asyncio.wait_for(ref, timeout=float(timeout_s))
