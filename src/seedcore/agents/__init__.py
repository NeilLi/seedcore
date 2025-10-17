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
from .base import Agent
from .ray_actor import RayAgent
from .observer_agent import ObserverAgent

# Lifecycle management
from .lifecycle import evaluate_lifecycle, LifecycleDecision

# Dispatchers
from .queue_dispatcher import Dispatcher, Reaper
from .graph_dispatcher import GraphDispatcher

# Memory and storage
from .private_memory import AgentPrivateMemory
from .checkpoint_store import CheckpointStore, CheckpointStoreFactory

# Capability management
from .capability_feedback import (
    CapabilityFeedback, 
    CapabilityAssessment, 
    CapabilityManager,
    get_capability_manager,
    evaluate_cognitive_task,
    get_agent_assessment,
    get_promotion_recommendations,
    get_improvement_plan
)

# Utility inference
from .utility_inference_actor import (
    UtilityPredictor,
    get_utility_predictor,
    reset_utility_predictor
)

__all__ = [
    # Core agent classes
    'Agent',
    'RayAgent', 
    'ObserverAgent',
    
    # Lifecycle management
    'evaluate_lifecycle',
    'LifecycleDecision',
    
    # Dispatchers
    'Dispatcher',
    'Reaper', 
    'GraphDispatcher',
    
    # Memory and storage
    'AgentPrivateMemory',
    'CheckpointStore',
    'CheckpointStoreFactory',
    
    # Capability management
    'CapabilityFeedback',
    'CapabilityAssessment', 
    'CapabilityManager',
    'get_capability_manager',
    'evaluate_cognitive_task',
    'get_agent_assessment',
    'get_promotion_recommendations',
    'get_improvement_plan',
    
    # Utility inference
    'UtilityPredictor',
    'get_utility_predictor',
    'reset_utility_predictor'
]
