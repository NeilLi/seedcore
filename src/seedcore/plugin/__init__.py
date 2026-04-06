"""Seedcore plugin-facing surfaces for Codex and Gemini hosts."""

from .mcp_server import GEMINI_MINIMAL_READ_ONLY_BUNDLE, PLUGIN_TOOL_NAMES, app, mcp

__all__ = ["GEMINI_MINIMAL_READ_ONLY_BUNDLE", "PLUGIN_TOOL_NAMES", "app", "mcp"]
