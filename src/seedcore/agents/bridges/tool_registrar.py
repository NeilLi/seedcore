# agents/bridges/tool_registrar.py

class QueryToolRegistrar:
    """
    Handles async registration of query tools.
    Keeps RayAgent clean.
    """

    def __init__(self, agent):
        self.agent = agent

    async def register(self):
        try:
            from ...tools import query_tools

            # Ensure tool_manager has required dependencies
            # register_query_tools extracts mw_manager, ltm_manager, and cognitive_client from tool_manager
            tool_manager = self.agent.tools
            
            # Set mw_manager and ltm_manager on tool_manager if not already set
            if tool_manager.mw_manager is None:
                tool_manager.mw_manager = self.agent.memory.mw
            if tool_manager.ltm_manager is None:
                tool_manager.ltm_manager = self.agent.memory.ltm
            
            # Set cognitive_client on tool_manager (separate from _mcp_client)
            # cognitive_client is for Cognitive Service (LLM/reasoning), not MCP service
            if tool_manager.cognitive_client is None and self.agent.cog.client is not None:
                tool_manager.cognitive_client = self.agent.cog.client

            await query_tools.register_query_tools(
                tool_manager=tool_manager,
                agent_id=self.agent.agent_id,
                get_agent_capabilities=self.agent._summarize_agent_capabilities,
                get_energy_slice=self.agent._energy_slice,
                in_flight_tracker=self.agent.cog.inflight,
                in_flight_lock=self.agent.cog.lock,
                mfb_client=getattr(self.agent, "mfb_client", None),
                get_memory_context=self.agent._get_memory_context,
                normalize_cog_resp=self.agent.cog.normalize,
                get_energy_state=self.agent.get_energy_state,
                update_energy_state=self.agent.update_energy_state,
                get_performance_data=self.agent._get_performance_data,
                get_agent_capabilities_dict=self.agent._get_agent_capabilities,
            )

        except Exception:
            pass
