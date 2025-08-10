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
Pair statistics tracking for agent collaboration history and conversion to
pairwise weights as per the unified energy mapping.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple
import numpy as np

from .weights import EnergyWeights

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

    # New: export to EnergyWeights.W_pair via a gentle EMA-guided merge
    def to_weights(self, agent_ids: Tuple[str, ...], weights: EnergyWeights, ema: float = 0.5) -> None:
        """Blend observed success rates into the pair weight matrix.

        - agent_ids: stable ordering of agents to index into W_pair
        - weights: EnergyWeights instance to mutate
        - ema: smoothing for merge with existing weights
        """
        n = len(agent_ids)
        if n == 0:
            return
        sr_matrix = np.zeros((n, n), dtype=np.float32)
        # Build success-rate matrix from tracker
        for i, ai in enumerate(agent_ids):
            for j, aj in enumerate(agent_ids):
                if i == j:
                    continue
                key = tuple(sorted([ai, aj]))
                stats = self.pair_stats.get(key)
                if stats and stats.trial_count > 0:
                    sr = stats.success_count / stats.trial_count
                else:
                    sr = 0.0
                sr_matrix[i, j] = sr
        # Symmetrize
        sr_matrix = 0.5 * (sr_matrix + sr_matrix.T)
        # Merge with existing weights.W_pair
        if weights.W_pair.shape != (n, n):
            weights.W_pair = sr_matrix.copy()
        else:
            weights.W_pair = ema * weights.W_pair + (1.0 - ema) * sr_matrix
        # Project to keep stable
        weights.project()