
import asyncio
import ray  # pyright: ignore[reportMissingImports]
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import DEFAULT_ROLE_REGISTRY, NullSkillStore, Specialization


@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class PersistentAgent(BaseAgent):
    """
    Minimal stateful agent:
    - BaseAgent handles tool execution + stateless logic
    - CognitiveBridge handles cognitive client (includes centralized memory via CognitiveMemoryBridge)
    - CheckpointManager handles persistence
    - QueryToolRegistrar installs query tools
    
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

        # Store mw_manager for tool registration (kept for backward compatibility with legacy query tools)
        # Memory consolidation is now handled centrally by CognitiveCore via CognitiveMemoryBridge
        # LongTermMemoryManager and MemoryBridge have been removed
        self._mw_manager = mw_manager

        # --- Delegated components ---
        from .bridges.cognitive_bridge import CognitiveBridge
        from .bridges.checkpoint_manager import CheckpointManager
        from .bridges.tool_registrar import QueryToolRegistrar

        self.cog = CognitiveBridge(
            cognitive_client=cognitive_client,
            agent_id=self.agent_id,
        )

        self.ckpt = CheckpointManager(
            cfg=checkpoint_cfg or {"enabled": False},
            agent_id=self.agent_id,
            privmem=self._privmem,
            organ_id=self.organ_id,
        )

        # Register query tools asynchronously
        self.tool_registrar = QueryToolRegistrar(self)
        asyncio.get_event_loop().create_task(
            self.tool_registrar.register()
        )

        # Optional checkpoint restore
        self.ckpt.maybe_restore()

    # ---------------------------------------------------------------------
    # Main execution path
    # ---------------------------------------------------------------------
    async def execute_task(self, task_data):
        """Run stateless execution + stateful post-processing.
        
        Note: Memory consolidation is now handled centrally by CognitiveCore
        via CognitiveMemoryBridge.process_post_execution().
        """
        result = await super().execute_task(task_data)

        # Persist checkpoint
        self.ckpt.after_task()

        return result

    # ---------------------------------------------------------------------
    async def shutdown(self):
        await self.cog.shutdown()
        return True

    # Expose minimal telemetry
    def get_summary_stats(self):
        """Return summary statistics for the agent."""
        return {
            "agent_id": self.agent_id,
            "tasks_processed": self.state.tasks_processed,
            "memory_writes": self.state.memory_writes,
        }
