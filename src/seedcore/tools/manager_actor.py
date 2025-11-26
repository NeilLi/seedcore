import ray  # pyright: ignore[reportMissingImports]
from .manager import ToolManager

@ray.remote(num_cpus=0.2)
class ToolManagerShard:
    def __init__(self, skill_store, mw_manager, holon_fabric, cognitive_client, mcp_client):
        self.manager = ToolManager(
            skill_store=skill_store,
            mw_manager=mw_manager,
            holon_fabric=holon_fabric,
            cognitive_client=cognitive_client,
            mcp_client=mcp_client,
        )

    async def execute_tool(self, agent_id, name, args):
        return await self.manager.execute(name, args, agent_id)

    async def register_tool(self, name, tool):
        await self.manager.register(name, tool)

    async def list_tools(self):
        return await self.manager.list_tools()

    async def stats(self):
        return await self.manager.stats()

