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
Base Agent abstraction.
Implements capability & memory utility fields (Section 2.1).
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class Agent:
    agent_id: str
    capability: float = 0.5
    mem_util: float = 0.0
    h: np.ndarray = field(default_factory=lambda: np.random.rand(8))
    role_probs: Dict[str, float] = field(default_factory=lambda: {'E':0.9,'S':0.1,'O':0.0})
    
    # Memory interaction tracking (Section 4.1 Key Metrics per Agent)
    memory_writes: int = 0
    memory_hits_on_writes: int = 0  # How many times this agent's contributions were read by others
    salient_events_logged: int = 0
    total_compression_gain: float = 0.0

    def execute(self, task: Any) -> Dict[str, Any]:
        # placeholder
        return {'ok': True, 'result': None}
