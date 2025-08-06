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
Energy Control Loops - Slow PSO Loop for role optimization.
Implements the slow control loop described in the energy validation blueprint.
"""

import time
import threading
import logging
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .ledger import EnergyLedger
from ..organs.organism_manager import organism_manager

logger = logging.getLogger(__name__)

@dataclass
class PSOParticle:
    """Represents a particle in the PSO optimization for role distributions."""
    position: Dict[str, float]  # Role probabilities for each agent
    velocity: Dict[str, float]  # Velocity for role updates
    best_position: Dict[str, float]  # Best position found by this particle
    best_fitness: float = float('inf')  # Best fitness value found

class SlowPSOLoop:
    """
    Slow PSO Loop for role optimization and regularization tuning.
    This class runs periodically in the background (every 2 seconds) and optimizes
    agent roles to minimize energy while maintaining diversity.
    """
    
    def __init__(self, energy_ledger: EnergyLedger, organism_manager):
        self.ledger = energy_ledger
        self.organism = organism_manager
        self.running = False
        self.thread = None
        
        # PSO parameters
        self.num_particles = 10
        self.inertia_weight = 0.7
        self.cognitive_weight = 1.5
        self.social_weight = 1.5
        
        # Entropy floor to prevent mode collapse
        self.entropy_floor = 0.2
        
        # Regularization tuning parameters
        self.reg_threshold = 0.3  # 30% of total energy
        self.reg_adjustment_rate = 0.01
        
        # Global best for PSO
        self.global_best_position = {}
        self.global_best_fitness = float('inf')
        
        # Particle swarm
        self.particles: List[PSOParticle] = []
        
    def start(self):
        """Start the slow PSO loop in a background thread."""
        if self.running:
            logger.warning("SlowPSOLoop is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("SlowPSOLoop started")

    def stop(self):
        """Stop the slow PSO loop."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
        logger.info("SlowPSOLoop stopped")

    def _run(self):
        """Main loop that runs every 2 seconds."""
        while self.running:
            try:
                # Sleep for 2 seconds (slow loop)
                time.sleep(2.0)
                
                if not self.running:
                    break
                
                # 1. Optimize Roles with PSO
                self.optimize_roles()
                
                # 2. Adjust Regularization Weight (lambda_reg)
                self.tune_regularization()
                
            except Exception as e:
                logger.error(f"Error in SlowPSOLoop: {e}")
                time.sleep(5.0)  # Wait longer on error

    def optimize_roles(self):
        """Optimize agent roles using PSO to minimize energy."""
        logger.debug("PSO Loop: Optimizing agent roles...")
        
        try:
            # Get current agents and their role distributions
            agents = self._get_all_agents()
            if not agents:
                return
            
            # Initialize particles if not already done
            if not self.particles:
                self._initialize_particles(agents)
            
            # Run PSO optimization
            for iteration in range(5):  # 5 iterations per cycle
                self._update_particles(agents)
                self._evaluate_particles(agents)
                self._update_global_best()
            
            # Apply best solution to agents
            self._apply_best_solution(agents)
            
        except Exception as e:
            logger.error(f"Error in role optimization: {e}")

    def _get_all_agents(self) -> List[Any]:
        """Get all agents from the organism."""
        try:
            # This would need to be implemented based on your organism structure
            # For now, return empty list as placeholder
            return []
        except Exception as e:
            logger.error(f"Error getting agents: {e}")
            return []

    def _initialize_particles(self, agents: List[Any]):
        """Initialize PSO particles with random role distributions."""
        self.particles = []
        
        for _ in range(self.num_particles):
            # Create random role distribution for each agent
            position = {}
            velocity = {}
            
            for agent in agents:
                # Generate random role probabilities that sum to 1
                probs = np.random.dirichlet([1, 1, 1])  # E, S, O roles
                position[agent.agent_id] = {
                    'E': float(probs[0]),
                    'S': float(probs[1]), 
                    'O': float(probs[2])
                }
                velocity[agent.agent_id] = {
                    'E': 0.0, 'S': 0.0, 'O': 0.0
                }
            
            particle = PSOParticle(
                position=position,
                velocity=velocity,
                best_position=position.copy()
            )
            self.particles.append(particle)

    def _update_particles(self, agents: List[Any]):
        """Update particle positions and velocities."""
        for particle in self.particles:
            # Update velocity
            for agent_id in particle.position:
                for role in ['E', 'S', 'O']:
                    # Cognitive component
                    cognitive = self.cognitive_weight * np.random.random() * \
                               (particle.best_position[agent_id][role] - particle.position[agent_id][role])
                    
                    # Social component
                    social = self.social_weight * np.random.random() * \
                            (self.global_best_position.get(agent_id, {}).get(role, 0) - particle.position[agent_id][role])
                    
                    # Update velocity
                    particle.velocity[agent_id][role] = \
                        self.inertia_weight * particle.velocity[agent_id][role] + cognitive + social
            
            # Update position
            for agent_id in particle.position:
                for role in ['E', 'S', 'O']:
                    particle.position[agent_id][role] += particle.velocity[agent_id][role]
                
                # Normalize probabilities to sum to 1
                total = sum(particle.position[agent_id].values())
                if total > 0:
                    for role in ['E', 'S', 'O']:
                        particle.position[agent_id][role] /= total
                
                # Enforce entropy floor
                self._enforce_entropy_floor(particle.position[agent_id])

    def _enforce_entropy_floor(self, role_probs: Dict[str, float]):
        """Enforce minimum entropy to prevent mode collapse."""
        # Calculate current entropy
        entropy = -sum(p * np.log2(p + 1e-9) for p in role_probs.values())
        
        if entropy < self.entropy_floor:
            # Add noise to increase entropy
            noise = np.random.normal(0, 0.1, 3)
            for i, role in enumerate(['E', 'S', 'O']):
                role_probs[role] = max(0.1, role_probs[role] + noise[i])
            
            # Renormalize
            total = sum(role_probs.values())
            for role in ['E', 'S', 'O']:
                role_probs[role] /= total

    def _evaluate_particles(self, agents: List[Any]):
        """Evaluate fitness of all particles."""
        for particle in self.particles:
            # Apply particle's role distribution to agents
            self._apply_role_distribution(agents, particle.position)
            
            # Calculate fitness (negative total energy)
            fitness = -self.ledger.total
            
            # Update particle's best if better
            if fitness > particle.best_fitness:
                particle.best_fitness = fitness
                particle.best_position = {k: v.copy() for k, v in particle.position.items()}

    def _apply_role_distribution(self, agents: List[Any], role_distribution: Dict[str, Dict[str, float]]):
        """Apply role distribution to agents (simulation only)."""
        # This would update agent role probabilities
        # For now, just simulate the effect on energy
        pass

    def _update_global_best(self):
        """Update global best position."""
        for particle in self.particles:
            if particle.best_fitness > self.global_best_fitness:
                self.global_best_fitness = particle.best_fitness
                self.global_best_position = {k: v.copy() for k, v in particle.best_position.items()}

    def _apply_best_solution(self, agents: List[Any]):
        """Apply the best found role distribution to agents."""
        if not self.global_best_position:
            return
            
        logger.debug(f"PSO Loop: Applying best solution with fitness {self.global_best_fitness:.4f}")
        # This would actually update agent role probabilities
        # For now, just log the best solution

    def tune_regularization(self):
        """Tune regularization weight based on energy composition."""
        total_energy = self.ledger.total
        reg_energy = self.ledger.reg
        
        if total_energy > 0:
            reg_ratio = reg_energy / total_energy
            
            if reg_ratio > self.reg_threshold:
                # Tame the regularization spike
                old_lambda = self.ledger.lambda_reg
                self.ledger.lambda_reg *= (1.0 - self.reg_adjustment_rate)
                self.ledger.lambda_reg = max(0.001, self.ledger.lambda_reg)  # Floor
                logger.info(f"PSO Loop: Regularization high ({reg_ratio:.3f}). Tuned lambda_reg from {old_lambda:.4f} to {self.ledger.lambda_reg:.4f}")
            elif reg_ratio < self.reg_threshold * 0.5:
                # Slightly increase if too low
                old_lambda = self.ledger.lambda_reg
                self.ledger.lambda_reg *= (1.0 + self.reg_adjustment_rate)
                self.ledger.lambda_reg = min(0.1, self.ledger.lambda_reg)  # Ceiling
                logger.debug(f"PSO Loop: Regularization low ({reg_ratio:.3f}). Tuned lambda_reg from {old_lambda:.4f} to {self.ledger.lambda_reg:.4f}")

# Global instance
slow_psoloop = SlowPSOLoop(EnergyLedger(), organism_manager)

def start_slow_psoloop():
    """Start the global slow PSO loop instance."""
    slow_psoloop.start()

def stop_slow_psoloop():
    """Stop the global slow PSO loop instance."""
    slow_psoloop.stop()

def get_slow_psoloop_instance():
    """Get the global slow PSO loop instance."""
    return slow_psoloop 