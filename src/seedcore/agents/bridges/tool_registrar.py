# agents/bridges/tool_registrar.py

import asyncio
import logging

logger = logging.getLogger(__name__)


class QueryToolRegistrar:
    """
    Responsible for registering query tools for agent execution.
    Supports both:
      - Local ToolManager (single mode)
      - Remote ToolManagerShard actors (sharded mode)
    """

    def __init__(self, agent):
        self.agent = agent

    async def register(self, max_retries: int = 5, initial_delay: float = 0.5):
        """
        Register query tools with retry logic to handle lazy tool_handler initialization.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 5)
            initial_delay: Initial delay in seconds before first retry (default: 0.5)
        """
        try:
            from ...tools import query_tools

            # Wait for tool_handler to become available (with retry)
            handler = await self._wait_for_tool_handler(max_retries, initial_delay)
            
            if handler is None:
                logger.warning(
                    f"⚠️ QueryToolRegistrar: tool_handler still None after {max_retries} retries "
                    f"for agent {getattr(self.agent, 'agent_id', 'unknown')}. "
                    "Skipping query tool registration. Tools will be registered when tool_handler is available."
                )
                return

            # -----------------------------------------------------
            # Build agent-side capability & helper closures
            # -----------------------------------------------------
            get_cap_summary = self._get_cap_summary
            get_cap_dict = self._get_cap_dict
            get_energy_slice = self._get_energy_slice
            get_energy_state = self._get_energy_state
            update_energy_state = self._update_energy_state
            get_performance = self._get_performance
            def get_memory_context():
                return {}
            get_conversation_history = self._get_conversation_history

            # Common args passed regardless of mode
            common_args = dict(
                agent_id=self.agent.agent_id,
                get_agent_capabilities=get_cap_summary,
                get_agent_capabilities_dict=get_cap_dict,
                get_energy_slice=get_energy_slice,
                get_energy_state=get_energy_state,
                update_energy_state=update_energy_state,
                get_performance_data=get_performance,
                get_memory_context=get_memory_context,
                get_conversation_history=get_conversation_history,
                in_flight_tracker=getattr(self.agent, "_inflight", {}),
                in_flight_lock=getattr(self.agent, "_inflight_lock", None),
                mfb_client=getattr(self.agent, "mfb_client", None),
                normalize_cog_resp=getattr(self.agent, "_normalize_cog_resp", None),
            )

            # SHARDED MODE ----------------------------------------
            if isinstance(handler, list):
                # Broadcast registration to every shard
                for shard in handler:
                    await shard.register_query_tools.remote(
                        cognitive_client=self.agent.cognitive_client,
                        **common_args
                    )
                return

            # SINGLE-MODE -----------------------------------------
            await query_tools.register_query_tools(
                tool_manager=handler,
                cognitive_client=getattr(handler, "cognitive_client", None) or getattr(self.agent, "cognitive_client", None),
                **common_args,
            )

        except Exception as e:
            logger.error(
                "❌ QueryToolRegistrar failed for agent %s: %s",
                getattr(self.agent, "agent_id", "unknown"), e, exc_info=True
            )
            raise

    async def _wait_for_tool_handler(self, max_retries: int, initial_delay: float):
        """
        Wait for tool_handler to become available, triggering lazy initialization if needed.
        
        Strategy:
        1. Check if tool_handler is already set (from shards or legacy)
        2. If None, try to trigger lazy initialization via _ensure_tool_handler()
        3. Retry with exponential backoff
        
        Returns:
            tool_handler instance or None if unavailable after retries
        """
        handler = getattr(self.agent, "tool_handler", None)
        
        # Fast path: handler already available
        if handler is not None:
            return handler
        
        # Try to trigger lazy initialization
        if hasattr(self.agent, "_ensure_tool_handler"):
            try:
                await self.agent._ensure_tool_handler()
                handler = getattr(self.agent, "tool_handler", None)
                if handler is not None:
                    logger.debug(
                        f"✅ QueryToolRegistrar: tool_handler initialized via _ensure_tool_handler() "
                        f"for agent {getattr(self.agent, 'agent_id', 'unknown')}"
                    )
                    return handler
            except Exception as e:
                logger.debug(
                    f"QueryToolRegistrar: _ensure_tool_handler() failed for agent "
                    f"{getattr(self.agent, 'agent_id', 'unknown')}: {e}. Will retry."
                )
        
        # Retry with exponential backoff
        delay = initial_delay
        for attempt in range(max_retries):
            await asyncio.sleep(delay)
            
            handler = getattr(self.agent, "tool_handler", None)
            if handler is not None:
                logger.debug(
                    f"✅ QueryToolRegistrar: tool_handler became available after {attempt + 1} retries "
                    f"for agent {getattr(self.agent, 'agent_id', 'unknown')}"
                )
                return handler
            
            # Try lazy initialization again on each retry
            if hasattr(self.agent, "_ensure_tool_handler"):
                try:
                    await self.agent._ensure_tool_handler()
                    handler = getattr(self.agent, "tool_handler", None)
                    if handler is not None:
                        logger.debug(
                            f"✅ QueryToolRegistrar: tool_handler initialized on retry {attempt + 1} "
                            f"for agent {getattr(self.agent, 'agent_id', 'unknown')}"
                        )
                        return handler
                except Exception:
                    pass  # Continue retrying
            
            # Exponential backoff: 0.5s, 1s, 2s, 4s, 8s
            delay = min(delay * 2, 8.0)
        
        return None

    # -------------------------------------------------------------
    # CAPABILITY / ENERGY / PERFORMANCE HELPERS (unchanged API)
    # -------------------------------------------------------------
    def _get_cap_summary(self):
        if hasattr(self.agent, "advertise_capabilities"):
            caps = self.agent.advertise_capabilities()
            if isinstance(caps, dict):
                return caps.get("summary") or caps.get("description") or str(caps)
            return str(caps)
        ctx = self.agent._role_context()
        return (
            f"Specialization: {ctx.get('specialization','unknown')}, "
            f"Capability: {ctx.get('capability',0.5):.2f}, "
            f"Skills: {', '.join(ctx.get('skills',[])[:5])}"
        )

    def _get_cap_dict(self):
        if hasattr(self.agent, "advertise_capabilities"):
            return self.agent.advertise_capabilities()
        return {}

    def _get_energy_slice(self):
        if hasattr(self.agent, "_energy_slice"):
            return self.agent._energy_slice()
        return getattr(self.agent.state, "c", 0.5)

    def _get_energy_state(self):
        if hasattr(self.agent, "get_energy_state"):
            return self.agent.get_energy_state()
        return None

    def _update_energy_state(self, v):
        if hasattr(self.agent, "update_energy_state"):
            return self.agent.update_energy_state(v)

    def _get_performance(self):
        if hasattr(self.agent.state, "to_performance_metrics"):
            return self.agent.state.to_performance_metrics()
        return {}

    def _get_conversation_history(self):
        if hasattr(self.agent, "get_recent_history"):
            return self.agent.get_recent_history(max_turns=6)
        if hasattr(self.agent, "get_chat_history"):
            return self.agent.get_chat_history()
        return []

