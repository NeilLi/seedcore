# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Agent implementations for SeedCore.
"""

# Core agent classes
from .base import BaseAgent
from .conversation_agent import ConversationAgent
from .observer_agent import ObserverAgent
from .utility_agent import UtilityAgent

# Behavior Plugin System
from .behaviors import (
    AgentBehavior,
    BehaviorRegistry,
    create_behavior_registry,
    ChatHistoryBehavior,
    BackgroundLoopBehavior,
    TaskFilterBehavior,
    ToolRegistrationBehavior,
    DedupBehavior,
    SafetyCheckBehavior,
    ToolAutoInjectionBehavior,
)

# Lifecycle management
from .lifecycle import evaluate_lifecycle, LifecycleDecision

# Memory and storage
from .private_memory import AgentPrivateMemory
from .checkpoint import CheckpointStore, CheckpointStoreFactory


__all__ = [
    # Core agent classes
    'BaseAgent',
    'ConversationAgent', 
    'ObserverAgent',
    'UtilityAgent',
    
    # Behavior Plugin System
    'AgentBehavior',
    'BehaviorRegistry',
    'create_behavior_registry',
    'ChatHistoryBehavior',
    'BackgroundLoopBehavior',
    'TaskFilterBehavior',
    'ToolRegistrationBehavior',
    'DedupBehavior',
    'SafetyCheckBehavior',
    'ToolAutoInjectionBehavior',
    
    # Lifecycle management
    'evaluate_lifecycle',
    'LifecycleDecision',
    
    # Memory and storage
    'AgentPrivateMemory',
    'CheckpointStore',
    'CheckpointStoreFactory',
    
]
