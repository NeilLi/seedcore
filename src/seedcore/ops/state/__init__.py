"""
State Management Module

This module provides cross-cutting state orchestration and aggregation functionality
that spans multiple domains (agents, organs, system, memory) in the SeedCore system.

Key Components:
- StateAggregator: Main orchestrator for unified state construction
- AgentStateAggregator: Specialized agent state collection
- MemoryManagerAggregator: Memory tier statistics aggregation  
- SystemStateAggregator: System-level state collection

This module implements Paper §3.1 requirements for light aggregators from
live Ray actors and memory managers.
"""


