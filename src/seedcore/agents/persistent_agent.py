
import asyncio
import ray  # pyright: ignore[reportMissingImports]
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import DEFAULT_ROLE_REGISTRY, NullSkillStore, Specialization


@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class PersistentAgent(BaseAgent):
    """
    Stateful agent with conversational memory:
    - BaseAgent handles tool execution + stateless logic
    - CheckpointManager handles persistence
    - QueryToolRegistrar installs query tools
    - Chat history management (short-term conversational memory)
    
    Architecture:
    - PersistentAgent owns chat_history (short-term, per conversation)
    - CognitiveCore owns long-term holons + episodic consolidation
    - QueryTools remain stateless and receive history from agent
    
    Note: Memory consolidation is now handled centrally by CognitiveCore via CognitiveMemoryBridge.
    LongTermMemoryManager and MemoryBridge have been removed and replaced with HolonFabric + CognitiveMemoryBridge.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        specialization=Specialization.GENERALIST,
        role_registry=None,
        skill_store=None,
        tool_manager=None,
        cognitive_client=None,
        organ_id=None,
        initial_role_probs=None,
        mw_manager=None,
        checkpoint_cfg=None,
        **legacy_kwargs
    ):
        super().__init__(
            agent_id=agent_id,
            tool_manager=tool_manager,
            specialization=specialization,
            role_registry=role_registry or DEFAULT_ROLE_REGISTRY,
            skill_store=skill_store or NullSkillStore(),
            cognitive_client=cognitive_client,
            organ_id=organ_id,
        )

        if initial_role_probs:
            self.state.p = dict(initial_role_probs)

        # Inflight task tracking for cognitive operations
        self._inflight: dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

        # Chat history storage (short-term conversational memory)
        # Ring buffer: last N messages per agent
        self._chat_history: list[dict[str, str]] = []
        self._chat_history_limit = 50  # last N messages

        # Store mw_manager for optional chat history persistence
        self._mw_manager = mw_manager

        # --- Delegated components ---
        from .bridges.checkpoint_manager import CheckpointManager
        from .bridges.tool_registrar import QueryToolRegistrar

        self.ckpt = CheckpointManager(
            cfg=checkpoint_cfg or {"enabled": False},
            agent_id=self.agent_id,
            privmem=self._privmem,
            organ_id=self.organ_id,
        )

        # Register query tools asynchronously
        # Note: Ray actors run in an async context, so this should work
        # If registration fails, tools will be registered lazily on first use
        self.tool_registrar = QueryToolRegistrar(self)
        try:
            # Try to get running loop first (Python 3.7+)
            loop = asyncio.get_running_loop()
            loop.create_task(self.tool_registrar.register())
        except RuntimeError:
            # No running loop - try get_event_loop (works in Ray actor context)
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self.tool_registrar.register())
            except RuntimeError:
                # Fallback: registration will happen lazily or on first async call
                # This is acceptable - tools can be registered on-demand
                pass

        # Optional checkpoint restore
        self.ckpt.maybe_restore()

    # ---------------------------------------------------------------------
    # Chat history management
    # ---------------------------------------------------------------------
    def add_user_message(self, content: str):
        """Add a user message to chat history."""
        self._chat_history.append({"role": "user", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._chat_history_limit:
            self._chat_history = self._chat_history[-self._chat_history_limit:]

    def add_assistant_message(self, content: str):
        """Add an assistant message to chat history."""
        self._chat_history.append({"role": "assistant", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._chat_history_limit:
            self._chat_history = self._chat_history[-self._chat_history_limit:]

    def get_chat_history(self):
        """Get a shallow copy of the full chat history."""
        return list(self._chat_history)
    
    def get_recent_history(self, max_turns: int = 6):
        """
        Get a windowed subset of recent chat history for CognitiveCore.
        
        This method returns only the last N turns to avoid sending large payloads
        to CognitiveCore. The full history remains stored locally in the agent
        for episodic memory, consolidation, and audit trails.
        
        Args:
            max_turns: Maximum number of recent turns to return (default: 6)
            
        Returns:
            List of recent chat history entries (last max_turns turns)
        """
        return list(self._chat_history[-max_turns:])

    def persist_chat_history(self):
        """Optionally persist chat history via MwManager (for multi-session persistence)."""
        if self._mw_manager:
            try:
                self._mw_manager.set_item(
                    f"chat_history:{self.agent_id}",
                    self._chat_history,
                    ttl_s=3600  # 1 hour TTL
                )
            except Exception:
                pass  # Fail silently if persistence unavailable

    def _normalize_cog_resp(self, resp):
        """Normalize cognitive responses into consistent structure.
        
        Used by cognitive query tools (reason_about_failure, make_decision, etc.)
        to normalize cognitive service responses.
        """
        if not isinstance(resp, dict):
            return {
                "success": False,
                "payload": {},
                "meta": {},
                "error": "Invalid response",
            }

        payload = resp.get("result") or resp.get("payload") or {}
        meta = resp.get("meta") or resp.get("metadata") or {}

        return {
            "success": bool(resp.get("success", bool(payload))),
            "payload": payload,
            "meta": meta,
            "error": resp.get("error"),
        }

    # ---------------------------------------------------------------------
    # Main execution path
    # ---------------------------------------------------------------------
    async def execute_task(self, task_data):
        """Run stateless execution + stateful post-processing with chat history management.
        
        For agent_tunnel mode:
        - Detects incoming chat messages
        - Updates chat history
        - Injects conversation_history into task_data.params before tool execution
        - Extracts assistant response and updates chat history after execution
        
        Note: Memory consolidation is now handled centrally by CognitiveCore
        via CognitiveMemoryBridge.process_post_execution().
        """
        # Ensure dict
        if not isinstance(task_data, dict):
            task_data = dict(task_data) if hasattr(task_data, "__dict__") else {}

        params = task_data.setdefault("params", {})
        interaction = params.setdefault("interaction", {})

        # Detect chat-tunnel conversational mode
        if interaction.get("mode") == "agent_tunnel":
            # ---- 1. Extract incoming message (single authoritative logic) ----
            incoming_msg = (
                task_data.get("message")
                or task_data.get("description")
                or params.get("chat", {}).get("message")
            )
            if incoming_msg:
                self.add_user_message(incoming_msg)

            # ---- 2. Inject windowed chat history into payload ----
            # Use recent history only to avoid large payloads to CognitiveCore
            # Full history remains stored locally for episodic memory/consolidation
            recent_history = self.get_recent_history(max_turns=6)
            
            # Set in params (QueryTools reads from here)
            params["conversation_history"] = recent_history
            # Also set at top level (required by ChatSignature)
            task_data["conversation_history"] = recent_history

            # ---- 3. Canonicalize interaction metadata ----
            interaction["mode"] = "agent_tunnel"
            interaction.setdefault("assigned_agent_id", self.agent_id)
            
            # Preserve conversation_id if present
            if "conversation_id" in interaction:
                params["interaction"]["conversation_id"] = interaction["conversation_id"]

        # ---- Run BaseAgent logic ----
        result = await super().execute_task(task_data)

        # ---- Update assistant history (post-op) ----
        if interaction.get("mode") == "agent_tunnel":
            assistant_msg = None
            try:
                if isinstance(result, dict):
                    res = result.get("result") or result
                    if isinstance(res, dict):
                        assistant_msg = (
                            res.get("response")
                            or res.get("message")
                        )
                    if not assistant_msg and isinstance(res, str):
                        assistant_msg = res
            except Exception:
                pass

            if isinstance(assistant_msg, str) and assistant_msg.strip():
                self.add_assistant_message(assistant_msg)

        # Persist checkpoint
        self.ckpt.after_task()

        return result

    # ---------------------------------------------------------------------
    async def shutdown(self):
        # Cancel inflight cognitive tasks
        async with self._inflight_lock:
            for task in self._inflight.values():
                try:
                    task.cancel()
                except Exception:
                    pass
            self._inflight.clear()
        await super().shutdown()
        return True

    # Expose minimal telemetry
    def get_summary_stats(self):
        """Return summary statistics for the agent."""
        return {
            "agent_id": self.agent_id,
            "tasks_processed": self.state.tasks_processed,
            "memory_writes": self.state.memory_writes,
        }
