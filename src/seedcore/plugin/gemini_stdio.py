from __future__ import annotations

import importlib
import sys
from typing import Any


def load_seedcore_mcp() -> tuple[Any, tuple[str, ...]]:
    try:
        module = importlib.import_module("seedcore.plugin.mcp_server")
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", "") == "seedcore":
            raise RuntimeError(
                "Could not import 'seedcore'. Run Gemini from the repository's Python environment "
                "with Seedcore dependencies installed."
            ) from exc
        raise

    tool_names = tuple(getattr(module, "PLUGIN_TOOL_NAMES", ()))
    mcp = getattr(module, "mcp", None)
    if mcp is None:
        raise RuntimeError(
            "Seedcore Gemini MCP server is unavailable because the 'mcp' Python dependency is missing. "
            "Install Seedcore dependencies in the active Python environment."
        )
    if not hasattr(mcp, "run"):
        raise RuntimeError("Seedcore Gemini MCP server did not expose a runnable FastMCP instance.")
    return mcp, tool_names


def main() -> int:
    try:
        mcp, _ = load_seedcore_mcp()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
