# agents/bridges/tool_registrar.py

class QueryToolRegistrar:
    """
    Handles async registration of query tools.
    Keeps PersistentAgent clean.
    
    Responsibilities:
    - Attach required dependencies to ToolManager (mw_manager, holon_fabric, cognitive_client)
    - Provide helper functions for agent capabilities, energy, memory, performance
    - Register query tools with proper dependency injection
    - Ensure proper error handling (no silent failures)
    """

    def __init__(self, agent):
        self.agent = agent

    async def register(self):
        try:
            from ...tools import query_tools

            tool_manager = self.agent.tools

            # -----------------------------------------------------
            # Attach required dependencies to ToolManager
            # -----------------------------------------------------
            
            # Attach mw_manager if missing
            if getattr(tool_manager, "mw_manager", None) is None:
                if hasattr(self.agent, "_mw_manager"):
                    tool_manager.mw_manager = self.agent._mw_manager

            # Attach holon_fabric if missing (required for FindKnowledgeTool)
            if getattr(tool_manager, "holon_fabric", None) is None:
                if hasattr(self.agent, "holon_fabric"):
                    tool_manager.holon_fabric = self.agent.holon_fabric

            # Attach cognitive_client for cognitive service
            if getattr(tool_manager, "cognitive_client", None) is None:
                if self.agent.cognitive_client is not None:
                    tool_manager.cognitive_client = self.agent.cognitive_client

            # -----------------------------------------------------
            # Capability summary (string)
            # -----------------------------------------------------
            def _cap_summary():
                """Get agent capabilities as a summary string."""
                # Prefer public API: advertise_capabilities
                if hasattr(self.agent, "advertise_capabilities"):
                    caps = self.agent.advertise_capabilities()
                    # Extract summary if available, otherwise stringify
                    if isinstance(caps, dict):
                        summary = caps.get("summary") or caps.get("description")
                        if summary:
                            return summary
                    return str(caps)
                # Fallback: use _role_context() to build summary
                ctx = self.agent._role_context()
                skills = ctx.get("skills", [])
                specialization = ctx.get("specialization", "unknown")
                capability = ctx.get("capability", 0.5)
                return (
                    f"Specialization: {specialization}, "
                    f"Capability: {capability:.2f}, "
                    f"Skills: {', '.join(skills[:5])}"
                )

            # -----------------------------------------------------
            # Capability dict
            # -----------------------------------------------------
            def _cap_dict():
                """Get agent capabilities as dict."""
                # Use stable public API only
                if hasattr(self.agent, "advertise_capabilities"):
                    return self.agent.advertise_capabilities()
                # No fallback - return empty dict if API not available
                return {}

            # -----------------------------------------------------
            # Energy helpers
            # -----------------------------------------------------
            def _energy_slice():
                """Get current energy slice value."""
                if hasattr(self.agent, "_energy_slice"):
                    return self.agent._energy_slice()
                # Fallback: use capability as energy proxy
                return getattr(self.agent.state, "c", 0.5)

            def _energy_state():
                """Get energy state."""
                if hasattr(self.agent, "get_energy_state"):
                    return self.agent.get_energy_state()
                # Fallback: return None (optional)
                return None

            def _update_energy_state(v):
                """Update energy state."""
                if hasattr(self.agent, "update_energy_state"):
                    return self.agent.update_energy_state(v)
                # Fallback: no-op (optional)
                return None

            # -----------------------------------------------------
            # Memory & performance helpers
            # -----------------------------------------------------
            def _memory_context():
                """Get memory context dict."""
                # Memory context comes entirely from CognitiveMemoryBridge/HolonFabric/MwManager
                # QueryTools no longer fetch memory context themselves
                # Return empty dict as fallback (backward compatibility only)
                return {}

            def _performance():
                """Get performance data dict."""
                if hasattr(self.agent.state, "to_performance_metrics"):
                    return self.agent.state.to_performance_metrics()
                return {}

            # -----------------------------------------------------
            # Chat history access (for future use)
            # -----------------------------------------------------
            def _conversation_history():
                """
                Get windowed conversation history from PersistentAgent.
                
                Returns recent history (last N turns) consistent with what PersistentAgent
                sends to CognitiveCore. PersistentAgent is the single source of truth.
                """
                # PersistentAgent owns chat history and provides windowed history
                # Use get_recent_history() to match what PersistentAgent sends to CognitiveCore
                if hasattr(self.agent, "get_recent_history"):
                    return self.agent.get_recent_history(max_turns=6)
                # Fallback to full history if get_recent_history not available (backward compatibility)
                if hasattr(self.agent, "get_chat_history"):
                    return self.agent.get_chat_history()
                return []

            # -----------------------------------------------------
            # Register Tools
            # -----------------------------------------------------
            await query_tools.register_query_tools(
                tool_manager=tool_manager,
                agent_id=self.agent.agent_id,
                get_agent_capabilities=_cap_summary,
                get_agent_capabilities_dict=_cap_dict,
                get_energy_slice=_energy_slice,
                get_energy_state=_energy_state,
                update_energy_state=_update_energy_state,
                get_performance_data=_performance,
                get_memory_context=_memory_context,
                get_conversation_history=_conversation_history,
                in_flight_tracker=getattr(self.agent, "_inflight", {}),
                in_flight_lock=getattr(self.agent, "_inflight_lock", None),
                mfb_client=getattr(self.agent, "mfb_client", None),
                cognitive_client=tool_manager.cognitive_client,
                normalize_cog_resp=getattr(self.agent, "_normalize_cog_resp", None),
            )

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                "❌ QueryToolRegistrar failed to register tools for agent %s: %s",
                getattr(self.agent, "agent_id", "unknown"),
                e,
                exc_info=True
            )
            # Re-raise to ensure failures are visible
            raise
