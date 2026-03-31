from __future__ import annotations

from ray import serve  # type: ignore[reportMissingImports]

from seedcore.plugin.mcp_server import app


@serve.deployment(name="SeedcorePluginMCPService")
@serve.ingress(app)
class SeedcorePluginMCPService:
    def __init__(self):
        pass
