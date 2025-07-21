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
Tiered memory system implementation.
Implements the memory tiers (Ma, Mw, Mlt, Mfb) described in the energy validation document.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import uuid

@dataclass
class MemoryTier:
    """Represents one tier of memory (like Mw or Mlt)."""
    name: str
    datastore: Dict[str, str] = field(default_factory=dict)  # Maps data_id to agent_id who wrote it
    bytes_used: int = 0
    hit_count: int = 0
    max_capacity: int = 1000  # Maximum bytes this tier can hold
    
    def add_data(self, data_id: str, agent_id: str, data_size: int = 10) -> bool:
        """Add data to this tier. Returns True if successful, False if capacity exceeded."""
        if self.bytes_used + data_size <= self.max_capacity:
            self.datastore[data_id] = agent_id
            self.bytes_used += data_size
            return True
        return False
    
    def get_data_author(self, data_id: str) -> Optional[str]:
        """Get the agent_id who wrote the data, or None if not found."""
        return self.datastore.get(data_id)
    
    def record_hit(self):
        """Record a successful read operation."""
        self.hit_count += 1

class SharedMemorySystem:
    """Main controller for the tiered memory system."""
    
    def __init__(self):
        """Initialize the memory system with working memory (Mw) and long-term memory (Mlt)."""
        self.Mw = MemoryTier("Mw", max_capacity=100)  # Working memory - smaller, faster
        self.Mlt = MemoryTier("Mlt", max_capacity=1000)  # Long-term memory - larger, slower
        
    def write(self, agent, data_id: str = None, tier_name: str = 'Mw', data_size: int = 10) -> bool:
        """
        Write data to the specified memory tier.
        
        Args:
            agent: The agent performing the write
            data_id: Unique identifier for the data (auto-generated if None)
            tier_name: Which tier to write to ('Mw' or 'Mlt')
            data_size: Size of the data in bytes
            
        Returns:
            bool: True if write was successful, False if tier is full
        """
        if data_id is None:
            data_id = str(uuid.uuid4())
        
        # Select the appropriate tier
        tier = self.Mw if tier_name == 'Mw' else self.Mlt
        
        # Attempt to write to the tier
        success = tier.add_data(data_id, agent.agent_id, data_size)
        
        if success:
            # Update agent's memory write count
            agent.memory_writes += 1
            
        return success
    
    def read(self, reader_agent, data_id: str) -> Optional[str]:
        """
        Read data from memory tiers (Mw first, then Mlt).
        
        Args:
            reader_agent: The agent performing the read
            data_id: Unique identifier for the data to read
            
        Returns:
            Optional[str]: The agent_id who originally wrote the data, or None if not found
        """
        # Search Mw first (working memory)
        author_id = self.Mw.get_data_author(data_id)
        if author_id:
            self.Mw.record_hit()
            # Find the original author agent and increment their hits_on_writes
            self._increment_author_hits(author_id)
            return author_id
        
        # Search Mlt if not found in Mw
        author_id = self.Mlt.get_data_author(data_id)
        if author_id:
            self.Mlt.record_hit()
            # Find the original author agent and increment their hits_on_writes
            self._increment_author_hits(author_id)
            return author_id
        
        return None
    
    def _increment_author_hits(self, author_id: str):
        """Helper method to increment memory_hits_on_writes for the author agent."""
        # This will be called by the server to update the specific agent
        # We'll implement this through a callback mechanism
        pass
    
    def log_salient_event(self, agent) -> None:
        """Log a salient event for the specified agent."""
        agent.salient_events_logged += 1
    
    def get_memory_stats(self) -> Dict:
        """Get comprehensive statistics about the memory system."""
        return {
            "Mw": {
                "bytes_used": self.Mw.bytes_used,
                "max_capacity": self.Mw.max_capacity,
                "hit_count": self.Mw.hit_count,
                "data_count": len(self.Mw.datastore)
            },
            "Mlt": {
                "bytes_used": self.Mlt.bytes_used,
                "max_capacity": self.Mlt.max_capacity,
                "hit_count": self.Mlt.hit_count,
                "data_count": len(self.Mlt.datastore)
            },
            "total_bytes": self.Mw.bytes_used + self.Mlt.bytes_used,
            "total_hits": self.Mw.hit_count + self.Mlt.hit_count
        } 