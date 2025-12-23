
import asyncio
from typing import Any, Awaitable, Dict, List, Optional
import ray  # pyright: ignore[reportMissingImports]
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import Specialization
from seedcore.logging_setup import ensure_serve_logger,setup_logging

setup_logging(app_name="seedcore.agents.conversation_agent")
logger = ensure_serve_logger("seedcore.agents.conversation_agent", level="DEBUG")


@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class ConversationAgent(BaseAgent):
    """
    Stateful agent responsible for TaskPayload v2 conversational execution.

    Semantic Owner (not schema owner):
    - Owns: params.chat normalization and windowing
    - Owns: params.chat.history (windowed context for CognitiveCore)
    - Owns: conversation_history (top-level ChatSignature compatibility)
    - Owns: Episodic memory buffer (agent-local only, respects cognitive flags)
    """

    def __init__(
        self,
        agent_id: str,
        *,
        # --- Chat-Specific Configs ---
        mw_manager_organ_id: Optional[str] = None,
        checkpoint_cfg: Optional[Dict[str, Any]] = None,
        initial_role_probs: Optional[Dict[str, float]] = None,
        
        # --- BaseAgent Configs (Passthrough) ---
        specialization: Specialization = Specialization.GENERALIST,
        organ_id: Optional[str] = None,
        tool_handler_shards: Optional[List[Any]] = None,
        role_registry_snapshot: Optional[Dict[str, Any]] = None,
        holon_fabric_config: Optional[Dict[str, Any]] = None,
        cognitive_client_cfg: Optional[Dict[str, Any]] = None,
        ml_client_cfg: Optional[Dict[str, Any]] = None,
        mcp_client_cfg: Optional[Dict[str, Any]] = None,
        
        # --- Legacy / Deprecated ---
        **legacy_kwargs
    ):
        # 1. Initialize BaseAgent (Passes all configs up)
        super().__init__(
            agent_id=agent_id,
            specialization=specialization,
            organ_id=organ_id,
            tool_handler_shards=tool_handler_shards,
            role_registry_snapshot=role_registry_snapshot,
            holon_fabric_config=holon_fabric_config,
            cognitive_client_cfg=cognitive_client_cfg,
            ml_client_cfg=ml_client_cfg,
            mcp_client_cfg=mcp_client_cfg,
            # Handle legacy args by unpacking or specific mapping if needed
            **legacy_kwargs 
        )

        # 2. Chat State & History (Short-term Memory)
        # Ring buffer: stores the last N messages for the active conversation context
        self._chat_history: List[Dict[str, str]] = [] 
        self._chat_history_limit = 50

        # Apply initial role probabilities if provided (overrides BaseAgent default)
        if initial_role_probs:
            self.state.p = dict(initial_role_probs)

        # 3. Concurrency Control (Inflight Tasks)
        self._inflight: Dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()

        # 4. Middleware Manager (Lazy Configuration)
        # We store the ID/Config now; the connection is created on first access
        self._mw_manager_organ_id = mw_manager_organ_id or self.organ_id
        self._mw_manager = legacy_kwargs.get("mw_manager")  # Legacy support

        # 5. Checkpoint Manager (Persistence)
        from .bridges.checkpoint_manager import CheckpointManager
        self.ckpt = CheckpointManager(
            cfg=checkpoint_cfg or {"enabled": False},
            agent_id=self.agent_id,
            privmem=self._privmem, # Links to BaseAgent's private memory
            organ_id=self.organ_id,
        )

        # 6. Query Tool Registration (Async Hook)
        from .bridges.tool_registrar import QueryToolRegistrar
        self.tool_registrar = QueryToolRegistrar(self)
        self._schedule_background_task(self.tool_registrar.register())

        # 7. Restore State (if available)
        self.ckpt.maybe_restore()

    # ------------------------------------------------------------------
    #  Lazy Properties & Helpers
    # ------------------------------------------------------------------

    @property
    def chat_history(self) -> List[Dict[str, str]]:
        """Read-only access to chat history ring buffer."""
        return self._chat_history

    def _schedule_background_task(self, coro: Awaitable):
        """
        Safely schedules a background task during Ray Actor initialization.
        Handles the edge case where the event loop might differ in test vs prod.
        """
        try:
            # Standard Ray Actor environment (Python 3.7+)
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # Fallback for environments where init is called outside a running loop
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(coro)
            except Exception as e:
                # Critical Fallback: The task will fail to start. 
                # In production, this should ideally raise, but we log to prevent crash on init.
                logger.warning(f"⚠️ Could not schedule background task in ConversationAgent {self.agent_id}: {e}")

    # ---------------------------------------------------------------------
    # Chat history management
    # ---------------------------------------------------------------------
    def add_user_message(self, content: str):
        """
        Add a user message to chat history (episodic memory buffer).
        
        Note: This method does NOT check cognitive flags. The caller (execute_task)
        is responsible for checking params.cognitive.disable_memory_write before calling.
        
        Args:
            content: User message content
        """
        self._chat_history.append({"role": "user", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._chat_history_limit:
            self._chat_history = self._chat_history[-self._chat_history_limit:]

    def add_assistant_message(self, content: str):
        """
        Add an assistant message to chat history (episodic memory buffer).
        
        Note: This method does NOT check cognitive flags. The caller (execute_task)
        is responsible for checking params.cognitive.disable_memory_write before calling.
        
        Args:
            content: Assistant message content
        """
        self._chat_history.append({"role": "assistant", "content": content})
        # Maintain ring buffer size
        if len(self._chat_history) > self._chat_history_limit:
            self._chat_history = self._chat_history[-self._chat_history_limit:]

    def get_chat_history(self):
        """Get a shallow copy of the full chat history."""
        return list(self._chat_history)
    
    def get_recent_conversation_window(self, max_turns: int = 6):
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
    
    def get_recent_history(self, max_turns: int = 6):
        """
        Backward-compatible alias for get_recent_conversation_window.
        
        Args:
            max_turns: Maximum number of recent turns to return (default: 6)
            
        Returns:
            List of recent chat history entries (last max_turns turns)
        """
        return self.get_recent_conversation_window(max_turns)

    def _get_mw_manager(self):
        """Lazily create MwManager from organ_id to avoid serialization issues."""
        if self._mw_manager is None and self._mw_manager_organ_id:
            from seedcore.memory.mw_manager import MwManager
            self._mw_manager = MwManager(organ_id=self._mw_manager_organ_id)
            logger.debug(f"✅ [{self.agent_id}] MwManager created for organ_id={self._mw_manager_organ_id}")
        return self._mw_manager
    
    def persist_chat_history(self):
        """Optionally persist chat history via MwManager (for multi-session persistence)."""
        mw = self._get_mw_manager()
        if mw:
            try:
                mw.set_item(
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
    # Main execution path (TaskPayload v2)
    # ---------------------------------------------------------------------
    async def execute_task(self, task_data):
        """
        Run stateless execution + stateful post-processing with chat history management.

        TaskPayload v2 Compliant Responsibilities:
        - Normalize params.chat envelope (canonical location for conversational data)
        - Manage conversation history window (params.chat.history)
        - Maintain episodic memory buffer (agent-local, respects cognitive flags)
        - Extract assistant messages after LLM execution
        - Respect params.cognitive.disable_memory_write flag
        - Do NOT write to params.routing or params._router (Router's authority)
        - Do NOT change params.interaction.mode (preserve routing decisions)
        """

        # ---------------------------------------------------------
        # 0. Defensive normalization (TaskPayload v2 compliant)
        # ---------------------------------------------------------
        if not isinstance(task_data, dict):
            task_data = dict(task_data) if hasattr(task_data, "__dict__") else {}

        params = task_data.setdefault("params", {})
        interaction = params.setdefault("interaction", {})
        chat = params.setdefault("chat", {})  # ✅ Canonical: params.chat (not params.conversation)
        cognitive = params.get("cognitive", {})  # ✅ Check cognitive flags

        is_tunnel = interaction.get("mode") == "agent_tunnel"
        
        # Extract cognitive flag for memory write control
        disable_memory_write = cognitive.get("disable_memory_write", False)

        # =========================================================
        # 1. Handle agent_tunnel chat mode
        # =========================================================
        if is_tunnel:

            # -----------------------------------------------------
            # 1A. Extract authoritative incoming message
            # -----------------------------------------------------
            incoming_msg = (
                task_data.get("message") or
                task_data.get("description") or
                chat.get("message")
            )

            if incoming_msg:
                # Local episodic write (agent-level only)
                # ✅ Respect cognitive flags: only write if disable_memory_write is False
                if not disable_memory_write:
                    self.add_user_message(incoming_msg)
                else:
                    logger.debug(f"[{self.agent_id}] Skipping user message write (disable_memory_write=true)")

                # v2 Chat Envelope (always set, regardless of memory flags)
                chat["message"] = incoming_msg

            # -----------------------------------------------------
            # 1B. Inject WINDOWED chat history for CognitiveCore
            # -----------------------------------------------------
            recent_history = self.get_recent_conversation_window(max_turns=6)

            # Canonical v2 placement: params.chat.history (internal windowed context)
            chat["history"] = recent_history

            # ChatSignature requirement (top-level compatibility)
            task_data["conversation_history"] = recent_history

            # -----------------------------------------------------
            # 1C. Canonicalize interaction envelope (v2)
            # -----------------------------------------------------
            # ✅ Preserve existing mode (do not overwrite Router decisions)
            # Only set if not already present (defensive initialization)
            if "mode" not in interaction:
                interaction["mode"] = "agent_tunnel"

            # The agent that owns this tunnel
            interaction.setdefault("assigned_agent_id", self.agent_id)

            # conversation_id is preserved if present; nothing to change

        # =========================================================
        # 2. Delegate to BaseAgent or parent execution
        # =========================================================
        result = await super().execute_task(task_data)

        # =========================================================
        # 3. Post-processing: extract assistant message for memory
        # =========================================================
        if is_tunnel:
            assistant_msg = None

            # --------------------------
            # Extract assistant output
            # --------------------------
            try:
                if isinstance(result, dict):
                    # Standard SeedCore shape: { "result": {...} }
                    res = result.get("result") or result

                    if isinstance(res, dict):
                        # Most common return shapes
                        assistant_msg = (
                            res.get("response") or
                            res.get("assistant_reply") or
                            res.get("message")
                        )

                    # Raw string (rare but possible)
                    if not assistant_msg and isinstance(res, str):
                        assistant_msg = res

            except Exception:
                pass

            # --------------------------
            # Write assistant message (respect cognitive flags)
            # --------------------------
            if isinstance(assistant_msg, str) and assistant_msg.strip():
                # ✅ Respect cognitive flags: only write if disable_memory_write is False
                if not disable_memory_write:
                    self.add_assistant_message(assistant_msg)
                else:
                    logger.debug(f"[{self.agent_id}] Skipping assistant message write (disable_memory_write=true)")

        # =========================================================
        # 4. Local checkpoint (not long-term memory)
        # =========================================================
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
