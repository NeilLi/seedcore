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
Energy Control Loops - Nested cadences and contractivity guardrails.
Implements fast/medium/slow ticks and contractivity/Lipschitz guard.
"""

import time
import asyncio
import threading
import logging
import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .ledger import EnergyLedger
from .calculator import energy_and_grad, compute_energy_unified, SystemParameters
from .weights import EnergyWeights
from ...models.state import UnifiedState, SystemState, MemoryVector, AgentSnapshot, OrganState
from .grad_adapter import get_global_gradient_bus, Gradients
# SOLUTION: Remove module-level import to avoid accessing organism_manager before initialization
# from ..organs.organism_manager import organism_manager

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
        """Main loop that runs every 2 seconds (medium cadence)."""
        while self.running:
            try:
                # Sleep for 2 seconds (medium cadence)
                time.sleep(2.0)
                
                if not self.running:
                    break
                
                # 0. Medium tick: compute energy + gradients via unified adapter and persist snapshot
                try:
                    # Producer refresh: compute fresh gradients via bus
                    bus = get_global_gradient_bus()
                    ustate = self._get_unified_state_safely()
                    if ustate is not None:
                        grads: Gradients = bus.latest(ustate, allow_stale=False)
                        bd = grads.breakdown
                        grad = {
                            "dE/dH": grads.dE_dH,
                            "dE/dP_entropy": grads.dE_dP_entropy,
                            "dE/dE_sel": grads.dE_dE_sel,
                            "dE/dmem": grads.dE_dmem,
                        }
                    else:
                        bd, grad = self._energy_snapshot_and_gradients()
                    if bd:
                        # Update ledger terms for visibility
                        self.ledger.pair = float(bd.get("pair", self.ledger.pair))
                        self.ledger.hyper = float(bd.get("hyper", self.ledger.hyper))
                        self.ledger.entropy = float(bd.get("entropy", self.ledger.entropy))
                        self.ledger.reg = float(bd.get("reg", self.ledger.reg))
                        self.ledger.mem = float(bd.get("mem", self.ledger.mem))
                        # Persist transaction (treat total as dE for now)
                        self.ledger.log_step(bd, {"ts": time.time(), "dE": float(bd.get("total", 0.0)), "cost": 0.0, "scope": "cluster", "scope_id": "-"})
                    # Stash gradients for controllers
                    self._last_gradients = grad or {}
                except Exception:
                    logger.exception("Failed medium tick compute/persist")

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

    # --- Unified adapter to compute energy + gradients ---
    def _energy_snapshot_and_gradients(self) -> tuple[Dict[str, float], Dict[str, Any]]:
        """Build inputs from UnifiedState and call energy_and_grad."""
        try:
            ustate = self._get_unified_state_safely()
            if ustate is None:
                return {}, {}
            # Accept either typed UnifiedState or dict payload
            if isinstance(ustate, UnifiedState):
                try:
                    uproj = ustate.projected()
                except Exception:
                    uproj = ustate
                state = uproj.to_energy_state()
                H = state["h_agents"]
                P = state["P_roles"]
                E_sel = state.get("hyper_sel")
                s_norm = float(state.get("s_norm", 0.0))
            else:
                # Dict fallback
                agents = ustate.get("agents", {})
                H = np.vstack([np.asarray(v.get("h", []), dtype=np.float32) for v in agents.values()]) if agents else np.zeros((0, 0), dtype=np.float32)
                P = np.asarray([[float(v.get("p", {}).get("E", 0.0)), float(v.get("p", {}).get("S", 0.0)), float(v.get("p", {}).get("O", 0.0))] for v in agents.values()], dtype=np.float32) if agents else np.zeros((0, 3), dtype=np.float32)
                sysd = ustate.get("system", {})
                E_sel = np.asarray(sysd.get("E_patterns", []), dtype=np.float32) if sysd.get("E_patterns") is not None else None
                s_norm = float(np.linalg.norm(H)) if H.size > 0 else 0.0

            # Build weights per current dimensions and ledger scalars
            n_agents = H.shape[0] if H.size > 0 else 1
            n_hyper = int(E_sel.shape[0]) if E_sel is not None and hasattr(E_sel, "shape") else 1
            weights = EnergyWeights(
                W_pair=np.eye(n_agents, dtype=np.float32) * 0.1,
                W_hyper=np.ones((n_hyper,), dtype=np.float32) * 0.1,
                alpha_entropy=float(getattr(self.ledger, "alpha", 0.1)),
                lambda_reg=float(self.ledger.lambda_reg),
                beta_mem=float(self.ledger.beta_mem),
            )
            # Memory stats (coarse)
            memory_stats = {"r_effective": 1.0, "p_compress": 0.0}

            result = compute_energy_unified(
                uproj if isinstance(ustate, UnifiedState) else {"h_agents": H, "P_roles": P, "hyper_sel": E_sel, "s_norm": s_norm},
                SystemParameters(weights=weights, memory_stats=memory_stats, include_gradients=True),
            )
            bd, grad = result.breakdown, (result.gradients or {})
            return bd, grad
        except Exception as e:
            logger.debug(f"energy_and_grad adapter failed: {e}")
            return {}, {}

    def _get_unified_state_safely(self):
        """Attempt to fetch UnifiedState from organism manager, handling async/sync styles."""
        try:
            val = self.organism.get_unified_state()  # may be coroutine
            if asyncio.iscoroutine(val):
                # Run in this background thread
                return asyncio.run(val)
            return val
        except TypeError:
            # Method likely requires parameters
            try:
                val = self.organism.get_unified_state(agent_ids=None)
                if asyncio.iscoroutine(val):
                    return asyncio.run(val)
                return val
            except Exception:
                return None
        except Exception:
            return None

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

    # New: fast/slow cadence placeholders and Lipschitz guard
    def fast_tick(self):
        """200ms local selection and tiny updates (placeholder)."""
        pass

    def slow_tick(self):
        """20s HGNN pattern learning and projection (placeholder)."""
        pass

    @staticmethod
    def lipschitz_guard(p_fast: float, beta_meta: float, beta_mem: float, rho: float = 0.99) -> float:
        """Composite Lipschitz-like factor; keep < 1 for contractivity."""
        p_fast = float(max(0.0, min(1.0, p_fast)))
        L_tot = min(0.999, (p_fast * 1.0 + (1.0 - p_fast) * beta_meta) * rho * beta_mem)
        return L_tot

# Global instance - lazy initialization to avoid accessing organism_manager before it's ready
_slow_psoloop_instance = None

def get_slow_psoloop_instance():
    """Get the global slow PSO loop instance with lazy initialization."""
    global _slow_psoloop_instance
    if _slow_psoloop_instance is None:
        # Lazy import to avoid circular dependencies
        from ..organs.organism_manager import organism_manager
        if organism_manager is None:
            raise RuntimeError("OrganismManager not yet initialized. Please wait for startup to complete.")
        _slow_psoloop_instance = SlowPSOLoop(EnergyLedger(), organism_manager)
    return _slow_psoloop_instance

def start_slow_psoloop():
    """Start the global slow PSO loop instance."""
    get_slow_psoloop_instance().start()

def stop_slow_psoloop():
    """Stop the global slow PSO loop instance."""
    if _slow_psoloop_instance is not None:
        _slow_psoloop_instance.stop() 