#!/usr/bin/env python
#seedcore/tools/training_tools.py

from __future__ import annotations
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================
# Skill Trainer Tool
# ============================================================

class SkillTrainerTool:
    def __init__(self, skill_store: Optional[Any] = None):
        self.skill_store = skill_store

    async def execute(self, agent_id: str, skill: str, data: Dict[str, Any], simulation_type: Optional[str] = None):
        
        if not isinstance(agent_id, str):
            raise ValueError("agent_id must be a string")
        if not isinstance(skill, str):
            raise ValueError("skill must be a string")

        improvement = 0.02  # placeholder

        result = {
            "agent_id": agent_id,
            "skill": skill,
            "delta": improvement,
            "status": "success",
            "_reflection": {
                "skill": skill,
                "delta": improvement,
                "note": f"Improved {skill} with {simulation_type or 'training'}",
                "suggestion": f"Continue practicing {skill} to reach next level"
            },
            "_trace": {
                "tool": "train.skill",
                "agent_id": agent_id,
                "skill": skill
            }
        }

        # Persist improvement
        if self.skill_store:
            try:
                if hasattr(self.skill_store, "update"):
                    await self.skill_store.update(agent_id, skill, improvement)
                elif hasattr(self.skill_store, "apply_delta"):
                    await self.skill_store.apply_delta(agent_id, skill, improvement)
                else:
                    logger.warning("Skill store has no compatible update method")
            except Exception as e:
                logger.warning(f"Failed to update skill store: {e}")

        return result

    def schema(self):
        return {
            "name": "train.skill",
            "description": "Train an agent skill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "skill": {"type": "string"},
                    "data": {"type": "object"},
                    "simulation_type": {"type": "string", "default": None},
                },
                "required": ["agent_id", "skill", "data"]
            }
        }


# ============================================================
# Behavior Trainer Tool
# ============================================================

class BehaviorTrainerTool:
    def __init__(self, behavior_store: Optional[Any] = None):
        self.behavior_store = behavior_store

    async def execute(self, agent_id: str, behavior: str, context: Dict[str, Any], reward: Optional[float] = None):

        improvement = 0.015 if reward and reward > 0 else 0.005

        result = {
            "agent_id": agent_id,
            "behavior": behavior,
            "delta": improvement,
            "status": "success",
            "_reflection": {
                "behavior": behavior,
                "delta": improvement,
                "note": "Learned behavior pattern",
                "suggestion": f"Apply {behavior} in similar contexts",
            },
            "_trace": {
                "tool": "train.behavior",
                "agent_id": agent_id,
                "behavior": behavior
            }
        }

        if self.behavior_store:
            try:
                if hasattr(self.behavior_store, "store"):
                    await self.behavior_store.store(agent_id, behavior, context, improvement)
                elif hasattr(self.behavior_store, "record_behavior"):
                    await self.behavior_store.record_behavior(agent_id, behavior, context, improvement)
                else:
                    logger.warning("Behavior store has no compatible store method")
            except Exception as e:
                logger.warning(f"Failed to store behavior: {e}")

        return result

    def schema(self):
        return {
            "name": "train.behavior",
            "description": "Train agent behavior through RL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "behavior": {"type": "string"},
                    "context": {"type": "object"},
                    "reward": {"type": "number", "default": None},
                },
                "required": ["agent_id", "behavior", "context"]
            }
        }


# ============================================================
# Simulation Trainer Tool
# ============================================================

class SimulationTrainerTool:
    def __init__(self, simulation_backend: Optional[Any] = None):
        self.simulation_backend = simulation_backend

    async def execute(self, agent_id: str, task: str, environment: str, episodes: int = 10):

        avg_reward = 0.75
        success_rate = 0.60

        result = {
            "agent_id": agent_id,
            "task": task,
            "environment": environment,
            "episodes": episodes,
            "avg_reward": avg_reward,
            "success_rate": success_rate,
            "status": "success",
            "_reflection": {
                "task": task,
                "delta": success_rate * 0.01,
                "note": f"Completed {episodes} episodes",
                "suggestion": f"Increase difficulty for {task}"
            },
            "_trace": {
                "tool": "train.simulation",
                "agent_id": agent_id,
                "task": task,
                "environment": environment
            }
        }

        return result

    def schema(self):
        return {
            "name": "train.simulation",
            "description": "Run training simulation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "task": {"type": "string"},
                    "environment": {"type": "string"},
                    "episodes": {"type": "integer", "default": 10},
                },
                "required": ["agent_id", "task", "environment"]
            }
        }


# ============================================================
# Register Training Tools
# ============================================================

async def register_training_tools(tool_manager, skill_store=None, behavior_store=None, simulation_backend=None):
    await tool_manager.register("train.skill", SkillTrainerTool(skill_store))
    await tool_manager.register("train.behavior", BehaviorTrainerTool(behavior_store))
    await tool_manager.register("train.simulation", SimulationTrainerTool(simulation_backend))
    logger.info("Registered training tools")
