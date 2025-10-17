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
Graph-aware specifications for Tier 0 Memory Manager.

This module provides data structures and interfaces for managing agents and organs
based on a canonical graph (Neo4j, etc.) rather than ad-hoc calls.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class AgentSpec:
    """Specification for a Ray agent based on graph state."""
    agent_id: str
    organ_id: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    resources: Dict[str, float] = field(default_factory=dict)   # {"num_cpus":1, "num_gpus":0}
    namespace: Optional[str] = None
    lifetime: str = "detached"
    name: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)      # freeform labels


@dataclass
class OrganSpec:
    """Specification for an organ based on graph state."""
    organ_id: str
    provides_skills: List[str] = field(default_factory=list)
    uses_services: List[str] = field(default_factory=list)
    governed_by_policies: List[str] = field(default_factory=list)


class GraphClient:
    """Abstract graph interface; implement for Neo4j, etc."""
    
    def list_agent_specs(self) -> List[AgentSpec]:
        """Return all agent specifications from the graph."""
        raise NotImplementedError

    def list_organ_specs(self) -> List[OrganSpec]:
        """Return all organ specifications from the graph."""
        raise NotImplementedError


class MockGraphClient(GraphClient):
    """Mock implementation for testing and development."""
    
    def __init__(self, agent_specs: List[AgentSpec] = None, organ_specs: List[OrganSpec] = None):
        self.agent_specs = agent_specs or []
        self.organ_specs = organ_specs or []
    
    def list_agent_specs(self) -> List[AgentSpec]:
        """Return mock agent specifications."""
        return self.agent_specs.copy()
    
    def list_organ_specs(self) -> List[OrganSpec]:
        """Return mock organ specifications."""
        return self.organ_specs.copy()
    
    def add_agent_spec(self, spec: AgentSpec):
        """Add an agent specification to the mock."""
        self.agent_specs.append(spec)
    
    def add_organ_spec(self, spec: OrganSpec):
        """Add an organ specification to the mock."""
        self.organ_specs.append(spec)
