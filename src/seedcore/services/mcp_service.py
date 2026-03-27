from __future__ import annotations

import os
import httpx  # pyright: ignore[reportMissingImports]
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI, Request  # pyright: ignore[reportMissingImports]
from fastapi.responses import JSONResponse  # pyright: ignore[reportMissingImports]
from ray import serve  # type: ignore[reportMissingImports]

# --- MCP Imports ---
from mcp.server.fastmcp import FastMCP, Context  # pyright: ignore[reportMissingImports]
from mcp.server.session import ServerSession  # pyright: ignore[reportMissingImports]

from seedcore.tools.external_tools import InternetFetchTool, FileReadTool

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.mcp_service.driver")
logger = ensure_serve_logger("seedcore.mcp_service", level="DEBUG")
    

# ============================================================

class ServiceState:
    """Holds our initialized tool instances for injection."""
    def __init__(self, fetch_tool: InternetFetchTool, read_tool: FileReadTool):
        self.fetch_tool = fetch_tool
        self.read_tool = read_tool

# This type hint gives us autocompletion for `ctx.request_context.lifespan_context`
AppContext = Context[ServerSession, ServiceState]

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[ServiceState]:
    """
    Manages the lifecycle of our tools and dependencies.
    """
    logger.info("🚀 MCP ToolService starting up...")
    http_client = None
    state = None
    try:
        # 1. Initialize dependencies
        http_client = httpx.AsyncClient(timeout=10.0)
        
        # Define a sandbox directory (use an env var in production)
        sandbox_dir = os.environ.get("TOOL_SANDBOX_DIR", "/tmp/mcp_sandbox")
        
        # 2. Initialize tools
        fetch_tool_instance = InternetFetchTool(http_client)
        read_tool_instance = FileReadTool(sandbox_dir=sandbox_dir)
        
        # 3. Create and yield the state
        state = ServiceState(
            fetch_tool=fetch_tool_instance,
            read_tool=read_tool_instance
        )
        logger.info(f"✅ Tools initialized. Sandbox at: {sandbox_dir}")
        yield state
        
    except Exception as e:
        logger.error(f"❌ FATAL: Failed to initialize tools: {e}", exc_info=True)
        raise
    finally:
        # 4. Cleanup
        logger.info("🛑 MCP ToolService shutting down...")
        # Optional: cleanup tools if they have cleanup methods
        if state:
            try:
                if hasattr(state.fetch_tool, 'aclose'):
                    await state.fetch_tool.aclose()
                if hasattr(state.read_tool, 'aclose'):
                    await state.read_tool.aclose()
            except Exception as e:
                logger.warning(f"Error during tool cleanup: {e}", exc_info=True)
        if http_client:
            await http_client.aclose()
        logger.info("✅ Shutdown complete.")


# ============================================================
# 3. CREATE THE MCP SERVER (with Lifespan)
# ============================================================

mcp = FastMCP("Ray-MCP-Dev", lifespan=app_lifespan)

#
# 💡 --- THIS IS THE "BRIDGE" --- 💡
#
# We create static facade functions that FastMCP can see.
# These functions use the context (ctx) to find the *real*
# tool instances and call their .execute() methods.
#

@mcp.tool(name="internet.fetch")
async def internet_fetch(ctx: AppContext, url: str) -> str:
    """
    Fetches the text content of a given URL.
    The URL must be http or https.
    """
    logger.debug(f"MCP Facade: Invoking 'internet.fetch' for {url}")
    try:
        # Get the initialized tool from the lifespan context
        tool = ctx.request_context.lifespan_context.fetch_tool
        # Call the real tool's logic
        return await tool.execute(url=url)
    except Exception as e:
        logger.warning(f"Tool 'internet.fetch' failed: {e}", exc_info=True)
        raise  # Re-raise the exception so MCP can report it

@mcp.tool(name="fs.read")
async def file_read(ctx: AppContext, filename: str) -> str:
    """
    Reads the content of a file from a sandboxed directory.
    e.g., 'data.txt'. Path traversal is not allowed.
    """
    logger.debug(f"MCP Facade: Invoking 'fs.read' for {filename}")
    try:
        # Get the initialized tool from the lifespan context
        tool = ctx.request_context.lifespan_context.read_tool
        # Call the real tool's logic
        return await tool.execute(filename=filename)
    except Exception as e:
        logger.warning(f"Tool 'fs.read' failed: {e}", exc_info=True)
        raise  # Re-raise the exception


# ============================================================
# 4. CREATE MAIN FASTAPI APP AND MOUNT MCP
# ============================================================

app = FastAPI(title="MCP Dev Service", version="1.0")

# Streamable HTTP security hardening:
# validate Origin when present to reduce DNS-rebinding risk.
_origin_validation_enabled = (
    os.getenv("MCP_VALIDATE_ORIGIN", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
_configured_allowed_origins = {
    origin.strip()
    for origin in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    host = parsed.hostname
    return host in {"localhost", "127.0.0.1", "::1"}


def _is_origin_allowed(origin: str) -> bool:
    if not origin:
        return True
    if origin in _configured_allowed_origins:
        return True
    return _is_loopback_origin(origin)


@app.middleware("http")
async def validate_origin_middleware(request: Request, call_next):
    if not _origin_validation_enabled:
        return await call_next(request)

    # Keep health/info unauthenticated and non-browser-friendly.
    if request.url.path in {"/health", "/info"}:
        return await call_next(request)

    origin = request.headers.get("origin", "")
    if origin and not _is_origin_allowed(origin):
        logger.warning("Rejected MCP request from disallowed Origin: %s", origin)
        return JSONResponse(
            status_code=403,
            content={
                "jsonrpc": "2.0",
                "error": {"code": -32001, "message": "Forbidden Origin"},
            },
        )

    return await call_next(request)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "MCPService"}

@app.get("/info")
async def info():
    """Returns service information including available tools and resources."""
    return {
        "service": "MCPService",
        "version": "1.0",
        "tools": ["internet.fetch", "fs.read"],
        "description": "MCP service exposing internet fetch and filesystem read tools",
    }

# Mount the entire MCP web app, generated by .streamable_http_app(),
# to the root of our FastAPI app.
app.mount("/", mcp.streamable_http_app())


# ============================================================
# 5. WRAP IN RAY SERVE
# ============================================================

@serve.deployment(name="MCPService")
@serve.ingress(app)
class MCPService:
    def __init__(self):
        # All logic is handled by the FastAPI app and
        # the FastMCP lifespan, so this is empty.
        pass

# Entrypoint for Ray Serve (optional, depending on deploy method)
# tool_app = MCPService.bind()
