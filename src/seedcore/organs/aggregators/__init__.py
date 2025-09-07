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
Light Aggregators Package

This package contains lightweight aggregators that efficiently collect state
from distributed Ray actors and memory managers, implementing Paper §3.1
requirements for light aggregators.

Components:
- AgentStateAggregator: Collects agent state (h vectors, P matrix, capability, lifecycle)
- MemoryManagerAggregator: Collects memory statistics (ma, mw, mlt, mfb)
- SystemStateAggregator: Collects system state (h_hgnn, E patterns, w_mode)
"""

from .agent_state_aggregator import AgentStateAggregator
from .memory_manager_aggregator import MemoryManagerAggregator
from .system_state_aggregator import SystemStateAggregator

__all__ = [
    "AgentStateAggregator",
    "MemoryManagerAggregator", 
    "SystemStateAggregator"
]

