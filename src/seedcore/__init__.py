# src/seedcore/__init__.py
"""
SeedCore
========
A scalable, cognitive-first execution framework for building intelligent,
distributed agent systems.

SeedCore powers multi-agent orchestration with:
- Control Plane (Coordinator): Surprise-driven routing, PKG-based planning,
  and OCPS adaptive policy.
- Intelligence Plane (Cognitive): LLM-driven reasoning, HGNN-based retrieval,
  and Holon Memory Fabric for long-term + episodic memory.
- Execution Plane (Organism): Skill-based routing, agent lifecycle management,
  and ultra-low-latency task execution.

Core features:
--------------
✓ TaskPayload v2.0 (structured envelopes: chat, interaction, cognitive, graph)
✓ OrganismCore router with skill- and organ-aware routing
✓ Agent Tunnels for conversational affinity
✓ HolonFabric memory, episodic replay, and controlled forgetting
✓ PKG-based strategic planning + DAG decomposition
✓ Ray-native distributed execution (actors, distributed services)
✓ Config-driven bootstrapping, pluggable agents, and extensible tools

Import Guide:
-------------
Models:
    from seedcore.models import Task, TaskPayload, TaskStatus, GraphTask

Coordinator:
    from seedcore.services import CoordinatorService

Organism:
    from seedcore.services import OrganismService

Agents:
    from seedcore.agents import ConversationAgent, BaseAgent

Tools:
    from seedcore.tools import QueryTools, Registry

Memory / Cognitive:
    from seedcore.cognitive import CognitiveCore

This package keeps heavy runtime dependencies optional; Ray and LLM clients
are imported only when invoked.
"""

from __future__ import annotations

__version__ = "2.0.0"
__author__ = "SeedCore Team"

__all__ = [
    "__version__",
    "__author__",
]

