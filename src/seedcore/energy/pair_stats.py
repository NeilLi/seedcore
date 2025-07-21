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
Pair statistics tracking for agent collaboration history.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple

@dataclass
class PairStats:
    """Historical collaboration data for a single agent pair."""
    w: float = 1.0  # Learned weight (can exceed 1.0 for strong collaborations)
    success_count: int = 0
    trial_count: int = 0
    
    def update_weight(self, success: bool, learning_rate: float = 0.1):
        """Update weight using a modified approach that allows growth above 1.0."""
        if success:
            # For success: increase weight (can go above 1.0)
            # Use a multiplicative increase: new_weight = old_weight * (1 + learning_rate)
            self.w = self.w * (1 + learning_rate)
        else:
            # For failure: decrease weight (but not below 0.1)
            # Use a multiplicative decrease: new_weight = old_weight * (1 - learning_rate)
            self.w = max(0.1, self.w * (1 - learning_rate))
        
        # Update counters
        self.trial_count += 1
        if success:
            self.success_count += 1

class PairStatsTracker:
    """Manages collaboration statistics for all agent pairs."""
    
    def __init__(self):
        """Initialize the tracker with an empty dictionary."""
        self.pair_stats: Dict[Tuple[str, str], PairStats] = {}
    
    def _get_pair_key(self, agent1_id: str, agent2_id: str) -> Tuple[str, str]:
        """Get a consistent key for a pair of agents (sorted to ensure consistency)."""
        return tuple(sorted([agent1_id, agent2_id]))
    
    def get_pair(self, agent1_id: str, agent2_id: str) -> PairStats:
        """Get PairStats for a pair of agents, creating if it doesn't exist."""
        pair_key = self._get_pair_key(agent1_id, agent2_id)
        
        if pair_key not in self.pair_stats:
            self.pair_stats[pair_key] = PairStats()
        
        return self.pair_stats[pair_key]
    
    def update_on_task_complete(self, agent1_id: str, agent2_id: str, success: bool, learning_rate: float = 0.1):
        """Update collaboration statistics when a task is completed."""
        pair_stats = self.get_pair(agent1_id, agent2_id)
        pair_stats.update_weight(success, learning_rate)
    
    def reset(self):
        """Reset all pair statistics."""
        self.pair_stats.clear()
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get all pair statistics as a dictionary for API responses."""
        result = {}
        for (agent1_id, agent2_id), stats in self.pair_stats.items():
            pair_name = f"{agent1_id}-{agent2_id}"
            result[pair_name] = {
                "weight": stats.w,
                "success_count": stats.success_count,
                "trial_count": stats.trial_count,
                "success_rate": stats.success_count / stats.trial_count if stats.trial_count > 0 else 0.0
            }
        return result 