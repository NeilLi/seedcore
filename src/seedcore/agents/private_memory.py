# src/seedcore/agents/private_memory.py
"""
Agent-private memory implementation h ∈ R^128 with fixed budget and lifetime persistence.

Blocks (sum = 128):
- T (64..80): recent task embeddings (EMA after RP/MLP compression)
- S (16..32): skill materialization sketch (hashed deterministic projection)
- P (16..32): peer interaction sketch (Count-Min + Space-Saving)
- F (16):  performance trace features (from AgentState metrics)

Integration:
- F uses AgentState.to_performance_metrics() — no duplicate EWMA inside.
- S uses RoleProfile.materialize_skills(SkillVector.deltas) → stable skill dict → hashed projection.
- Convenience: update_from_agent(BaseAgent, ...) wires the common inputs.
- T (task embeddings): Should use 128d embeddings from graph_embeddings_128 table or 
  task_embeddings_primary_128 view. This module produces 128d output vectors, so 128d input 
  embeddings are expected. If 1024d embeddings are passed, they will be projected but may 
  lose information.

Persistence:
- Process memory only; no disk I/O. dump()/load() are optional JSON-safe helpers.

Telemetry:
- Block-wise inspection and top-k peers for meta-learning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
import math
import time
import numpy as np

from .state import AgentState
from .roles import RoleProfile, SkillVector
from seedcore.logging_setup import ensure_serve_logger

if TYPE_CHECKING:
    from .base import BaseAgent

logger = ensure_serve_logger("seedcore.agents.private_memory", level="DEBUG")

# === Capacity & defaults ===
D_TOTAL = 128
D_FEAT = 16  # F block
# T/S/P active sums to 112
MAX_T = 80
MAX_S = 32
MAX_P = 32
# Default active allocation (sum=112)
INIT_ALLOC: Tuple[int, int, int] = (64, 24, 24)

EPS = 1e-8


# -------------------------- utilities -------------------------------------------

class FeatureHasher:
    """Deterministic index&sign hashing for dense vectors into a fixed size."""
    def __init__(self, out_dim: int, seed: int = 137):
        self.out_dim = int(out_dim)
        self.seed = int(seed)

    def transform(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        n = x.size
        # Deterministic RNG keyed on length + seed
        rng = np.random.default_rng(self.seed + n)
        idx = rng.integers(0, self.out_dim, size=n, endpoint=False)
        sign = rng.integers(0, 2, size=n, dtype=np.int8) * 2 - 1
        h = np.zeros(self.out_dim, dtype=np.float32)
        np.add.at(h, idx, x * sign)
        return h


class CountMinSketch:
    """Count-Min Sketch with float updates."""
    def __init__(self, d: int, w: int, seed: int = 31):
        self.d = int(d)
        self.w = int(w)
        self.table = np.zeros((self.d, self.w), dtype=np.float32)
        self._rng = np.random.default_rng(seed)
        self._salts = [int(self._rng.integers(1, 2**31 - 1)) for _ in range(self.d)]

    def _hash(self, key: str, row: int) -> int:
        return hash((key, self._salts[row])) % self.w

    def update(self, key: str, value: float) -> None:
        v = float(value)
        for r in range(self.d):
            c = self._hash(key, r)
            self.table[r, c] += v


class SpaceSaving:
    """Space-Saving heavy-hitter tracker (top-K)."""
    def __init__(self, k: int = 16):
        self.k = int(k)
        self.counts: Dict[str, float] = {}

    def update(self, key: str, inc: float = 1.0) -> None:
        if key in self.counts:
            self.counts[key] += inc
            return
        if len(self.counts) < self.k:
            self.counts[key] = inc
            return
        # evict min
        mkey = min(self.counts, key=self.counts.get)
        mval = self.counts.pop(mkey)
        self.counts[key] = mval + inc

    def topk(self) -> List[Tuple[str, float]]:
        return sorted(self.counts.items(), key=lambda kv: kv[1], reverse=True)


# -------------------------- allocator -------------------------------------------

class AdaptiveAllocator:
    """
    Simple discrete allocator with hysteresis over T/S/P shares (sum=112).
    """
    def __init__(self, templates: List[Tuple[int, int, int]], hysteresis: float = 0.05, min_steps_between: int = 50):
        self.templates = templates
        self.hysteresis = float(hysteresis)
        self.min_steps_between = int(min_steps_between)
        self._steps_since = 0

    def select(self, scores: Tuple[float, float, float], current: Tuple[int, int, int]) -> Optional[Tuple[int, int, int]]:
        self._steps_since += 1
        sT, sS, sP = scores
        s = np.array([max(sT, 1e-8), max(sS, 1e-8), max(sP, 1e-8)], dtype=np.float32)
        s = s / float(s.sum())

        def score_t(t: Tuple[int, int, int]) -> float:
            t_arr = np.array(t, dtype=np.float32)
            t_arr = t_arr / float(t_arr.sum())
            return float(np.dot(s, t_arr))

        cur_score = score_t(current)
        best_t, best_score = current, cur_score
        for tpl in self.templates:
            sc = score_t(tpl)
            if sc > best_score:
                best_t, best_score = tpl, sc

        rel_gain = (best_score - cur_score) / max(cur_score, 1e-8)
        if best_t != current and rel_gain > self.hysteresis and self._steps_since >= self.min_steps_between:
            self._steps_since = 0
            return best_t
        return None


# -------------------------- peer event ------------------------------------------

@dataclass
class PeerEvent:
    peer_id: str
    outcome: int  # +1 success, -1 failure, 0 neutral
    weight: float = 1.0
    role: Optional[str] = None


# -------------------------- main memory -----------------------------------------

class AgentPrivateMemory:
    """
    128-dim private vector composed of T/S/P/F blocks with adaptive allocation.

    Public API (core):
        update_after_task(...)
        update_from_agent(agent, ...)

    Optional:
        dump()/load() for in-memory checkpoints,
        telemetry() for block-level introspection.
    """

    def __init__(
        self,
        agent_id: str,
        alpha: float = 0.1,
        *,
        use_mlp_task_encoder: bool = False,   # reserved: RP used by default
        hasher_dim: int = 512,                # skill hashing input dim
    ):
        self.agent_id = agent_id
        self.alpha = float(alpha)

        # ---- Task block (T) ----
        self._task_proj: Optional[np.ndarray] = None  # RP basis when needed
        self._task_ema = np.zeros(MAX_T, dtype=np.float32)
        self._task_seen = 0

        # ---- Skill block (S) ----
        self._skill_hasher = FeatureHasher(out_dim=MAX_S, seed=911)  # stable S projection

        # ---- Peer block (P) ----
        self._cms_rows = 4
        self._cms_cols = MAX_P // self._cms_rows
        self._peer_cms = CountMinSketch(self._cms_rows, self._cms_cols, seed=97)
        self._peer_topk = SpaceSaving(k=16)
        self._recent_peers: Dict[str, float] = {}

        # ---- Allocation & scoring ----
        self.dT, self.dS, self.dP = INIT_ALLOC
        assert self.dT + self.dS + self.dP + D_FEAT == D_TOTAL
        self._score_T = 0.0
        self._score_S = 0.0
        self._score_P = 0.0
        self._allocator = AdaptiveAllocator(
            templates=[(80, 16, 16), (64, 32, 16), (64, 24, 24), (48, 32, 32)],
            hysteresis=0.05,
            min_steps_between=50,
        )

        # ---- Public vector ----
        self.h = np.zeros(D_TOTAL, dtype=np.float32)

    # ------------------------ update paths --------------------------------------

    def _ensure_task_proj(self, in_dim: int) -> None:
        if self._task_proj is None or self._task_proj.shape[0] != in_dim:
            # Gaussian random projection to MAX_T with 1/sqrt(in_dim) scaling
            self._task_proj = (np.random.randn(in_dim, MAX_T).astype(np.float32) / math.sqrt(max(1, in_dim)))

    def update_after_task(
        self,
        *,
        task_embed: Optional[np.ndarray],
        agent_state: Optional[AgentState],
        role_profile: Optional[RoleProfile],
        skill_vector: Optional[SkillVector],
        success: bool,
        quality: Optional[float] = None,
        latency_s: Optional[float] = None,
        peers: Optional[List[PeerEvent]] = None,
    ) -> np.ndarray:
        """
        Update T/S/P using provided signals and rebuild h.

        - T: RP-EMA of task_embed (if provided).
          NOTE: task_embed should be 128d (from graph_embeddings_128 or task_embeddings_primary_128).
          This module produces 128d output vectors, so it expects 128d input embeddings.
          If 1024d embeddings are passed, they will be projected but may lose information.
        - S: materialize & hash skills from (role_profile, skill_vector).
        - P: update CMS & top-k from peer events.
        - F: always rebuilt from agent_state metrics.

        Returns: the new 128-d vector.
        """
        # Snapshot current active slices for adaptive scoring
        prev_T = self._task_ema[: self.dT].copy()
        prev_S = self._skills_vector()[: self.dS]  # computed on the fly
        prev_P = self._peer_cms.table.reshape(-1)[: self.dP].copy()

        # ---- T: task block ----
        if task_embed is not None:
            e = np.asarray(task_embed, dtype=np.float32).reshape(-1)
            
            # Warn if 1024d embedding is passed (should use 128d from graph_embeddings_128)
            if e.size == 1024:
                logger.warning(
                    "AgentPrivateMemory.update_after_task: Received 1024d task embedding "
                    "(expected 128d from graph_embeddings_128). "
                    "This will be projected but may lose information. "
                    "Ensure task embeddings are fetched from task_embeddings_primary_128 view."
                )
            elif e.size != 128 and e.size not in (64, 80, 96, 112, 128):  # Common 128d variants
                logger.debug(
                    "AgentPrivateMemory.update_after_task: Task embedding dimension %d "
                    "(expected ~128d from graph_embeddings_128). Will project to %dd.",
                    e.size, MAX_T
                )
            
            self._ensure_task_proj(e.shape[0])
            z = e @ self._task_proj  # (MAX_T,)
            self._task_ema = (1.0 - self.alpha) * self._task_ema + self.alpha * z
            self._task_seen += 1

        # ---- S: skills block ----
        if role_profile is not None and skill_vector is not None:
            s_vec = self._materialize_skills(role_profile, skill_vector)
            s_hash = self._skill_hasher.transform(s_vec)
            # EMA for stability
            # keep an internal buffer same size as MAX_S
            if not hasattr(self, "_skill_ema"):
                self._skill_ema = np.zeros(MAX_S, dtype=np.float32)
            self._skill_ema = (1.0 - self.alpha) * self._skill_ema + self.alpha * s_hash

        # ---- P: peer block ----
        if peers:
            for pe in peers:
                key = f"{pe.peer_id}|{pe.role or ''}|{int(pe.outcome)}"
                self._peer_cms.update(key, float(pe.weight))
                self._peer_topk.update(pe.peer_id, float(pe.weight))
                self._recent_peers[pe.peer_id] = time.time()
                # prune oldest if needed
                if len(self._recent_peers) > 64:
                    oldest = min(self._recent_peers.items(), key=lambda kv: kv[1])[0]
                    self._recent_peers.pop(oldest, None)

        # ---- Adaptive reallocation based on L2 deltas ----
        cur_S = self._skills_vector()[: self.dS]
        cur_P = self._peer_cms.table.reshape(-1)[: self.dP]
        self._score_T = float(np.linalg.norm(self._task_ema[: self.dT] - prev_T))
        self._score_S = float(np.linalg.norm(cur_S - prev_S))
        self._score_P = float(np.linalg.norm(cur_P - prev_P))
        self._maybe_reallocate()

        # ---- Rebuild h ----
        self._rebuild_h(agent_state)
        return self.h

    def update_from_agent(
        self,
        agent: "BaseAgent",
        *,
        task_embed: Optional[np.ndarray],
        peers: Optional[List[PeerEvent]] = None,
        success: bool = True,
        quality: Optional[float] = None,
        latency_s: Optional[float] = None,
    ) -> np.ndarray:
        """
        Convenience wrapper using BaseAgent's state/roles/skills.
        
        NOTE: task_embed should be 128d (from graph_embeddings_128 or task_embeddings_primary_128).
        This ensures compatibility with the 128d private memory vector output.
        """
        return self.update_after_task(
            task_embed=task_embed,
            agent_state=agent.state if isinstance(agent.state, AgentState) else None,
            role_profile=getattr(agent, "role_profile", None),
            skill_vector=getattr(agent, "skills", None),
            success=success,
            quality=quality,
            latency_s=latency_s,
            peers=peers,
        )

    # ------------------------ compose blocks -------------------------------------

    def _skills_vector(self) -> np.ndarray:
        if hasattr(self, "_skill_ema"):
            return np.asarray(self._skill_ema, dtype=np.float32)
        return np.zeros(MAX_S, dtype=np.float32)

    def _feat_block(self, agent_state: Optional[AgentState]) -> np.ndarray:
        """
        16 compact features derived from AgentState.to_performance_metrics().
        If state is None, zeros are returned.
        """
        feats = np.zeros(D_FEAT, dtype=np.float32)
        if agent_state is None:
            return feats

        pm = agent_state.to_performance_metrics()
        # [0..7]: primary KPIs
        feats[0] = float(pm.get("capability_score_c") or 0.0)
        feats[1] = float(pm.get("mem_util") or 0.0)
        feats[2] = float((pm.get("quality_avg") or 0.0))
        feats[3] = float((pm.get("salience_avg") or 0.0))
        feats[4] = float((pm.get("success_rate") or 0.0))
        feats[5] = float((pm.get("latency_avg_s") or 0.0))
        feats[6] = float(pm.get("tasks_processed") or 0.0) / 100.0  # scaled
        feats[7] = float(pm.get("memory_writes") or 0.0) / 100.0    # scaled

        # [8..11]: memory interaction & compression (scaled)
        feats[8] = float(pm.get("memory_hits_on_writes") or 0.0) / 100.0
        feats[9] = float(pm.get("salient_events_logged") or 0.0) / 100.0
        feats[10] = float(pm.get("total_compression_gain") or 0.0)
        feats[11] = 0.0  # reserved

        # [12..15]: reserved for ocps/drift/ext signals (0 for now)
        # (You can map OCPS metrics here when available)
        return feats

    def _norm(self, v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(v) + EPS)
        return v / n

    def _rebuild_h(self, agent_state: Optional[AgentState]) -> None:
        """
        Rebuild the 128-dim vector h from T/S/P/F blocks.
        
        CRITICAL: This MUST always produce exactly D_TOTAL (128) dimensions.
        BaseAgent._get_current_embedding() relies on this for consistency.
        """
        T = self._norm(self._task_ema[: self.dT])
        S = self._norm(self._skills_vector()[: self.dS])
        P = self._norm(self._peer_cms.table.reshape(-1)[: self.dP])
        F = self._norm(self._feat_block(agent_state))
        
        # Ensure the concatenated vector is exactly D_TOTAL dimensions
        h_concatenated = np.concatenate([T, S, P, F]).astype(np.float32)
        
        # Safety check: must be exactly 128 dimensions
        if h_concatenated.size != D_TOTAL:
            logger.warning(
                f"AgentPrivateMemory._rebuild_h: Expected {D_TOTAL} dims, got {h_concatenated.size}. "
                f"Allocation: dT={self.dT}, dS={self.dS}, dP={self.dP}, D_FEAT={D_FEAT}, sum={self.dT + self.dS + self.dP + D_FEAT}"
            )
            # Force to 128 by padding or truncating
            if h_concatenated.size < D_TOTAL:
                h_concatenated = np.pad(h_concatenated, (0, D_TOTAL - h_concatenated.size), mode='constant')
            else:
                h_concatenated = h_concatenated[:D_TOTAL]
        
        self.h = h_concatenated

    # ------------------------ S materialization ----------------------------------

    def _materialize_skills(self, role_profile: RoleProfile, skill_vector: SkillVector) -> np.ndarray:
        """
        Deterministic 1-D list of skills in fixed order for hashing.
        Order: sorted skill names; values already clamped 0..1 by role_profile.materialize_skills().
        
        NOTE: No redundant clamping needed - RoleProfile.materialize_skills() already clamps to [0,1].
        """
        mat = role_profile.materialize_skills(skill_vector.deltas)
        if not mat:
            return np.zeros(1, dtype=np.float32)
        keys = sorted(mat.keys())
        # RoleProfile.materialize_skills() already clamps to [0,1], so no need to clamp again
        vals = np.array([float(mat[k]) for k in keys], dtype=np.float32)
        return vals

    # ------------------------ realloc --------------------------------------------

    def _maybe_reallocate(self) -> None:
        tpl = self._allocator.select((self._score_T, self._score_S, self._score_P), (self.dT, self.dS, self.dP))
        if tpl is None:
            return
        self.dT, self.dS, self.dP = tpl

    # ------------------------ API surface ----------------------------------------

    def reset(self) -> None:
        self.__init__(self.agent_id, self.alpha)

    def get_vector(self) -> np.ndarray:
        """
        Return the 128-dim private memory vector.
        
        CRITICAL: This MUST always return exactly 128 dimensions.
        BaseAgent._get_current_embedding() relies on this for consistency.
        """
        # Ensure h is always exactly D_TOTAL dimensions
        if self.h.size != D_TOTAL:
            logger.warning(
                f"AgentPrivateMemory.get_vector: h has {self.h.size} dims, expected {D_TOTAL}. "
                "Rebuilding h to ensure consistency."
            )
            self._rebuild_h(None)  # Rebuild with current state
        
        return self.h.copy()

    def get_vector_list(self) -> List[float]:
        return self.h.astype(np.float32).tolist()

    # Optional: JSON-safe snapshot for checkpoints (still in-memory by default)
    def dump(self) -> Dict[str, Any]:
        return {
            "h": self.get_vector_list(),
            "task": [float(x) for x in self._task_ema.tolist()],
            "skill": [float(x) for x in self._skills_vector().tolist()],
            "peer_cms": [float(x) for x in self._peer_cms.table.reshape(-1).tolist()],
            "dT": int(self.dT),
            "dS": int(self.dS),
            "dP": int(self.dP),
        }

    def load(self, blob: Dict[str, Any]) -> None:
        try:
            t = np.array(blob.get("task", []), dtype=np.float32)
            s = np.array(blob.get("skill", []), dtype=np.float32)
            p = np.array(blob.get("peer_cms", []), dtype=np.float32)
            if t.size:
                self._task_ema[: min(t.size, self._task_ema.size)] = t[: self._task_ema.size]
            if s.size:
                # restore into EMA buffer
                self._skill_ema = np.zeros(MAX_S, dtype=np.float32)
                self._skill_ema[: min(s.size, MAX_S)] = s[: MAX_S]
            if p.size:
                flat = self._peer_cms.table.reshape(-1)
                flat[: min(p.size, flat.size)] = p[: flat.size]
            self.dT = int(blob.get("dT", self.dT))
            self.dS = int(blob.get("dS", self.dS))
            self.dP = int(blob.get("dP", self.dP))
        except Exception:
            # fail soft
            pass

    def telemetry(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "allocation": {"T": int(self.dT), "S": int(self.dS), "P": int(self.dP), "F": D_FEAT},
            "scores": {"T": float(self._score_T), "S": float(self._score_S), "P": float(self._score_P)},
            "peer_topk": self._peer_topk.topk(),
            "blocks": {
                "task_norm": float(np.linalg.norm(self._task_ema[: self.dT])),
                "skill_norm": float(np.linalg.norm(self._skills_vector()[: self.dS])),
                "peer_norm": float(np.linalg.norm(self._peer_cms.table.reshape(-1)[: self.dP])),
            },
            "counters": {
                "task_seen": int(self._task_seen),
                "peers_tracked": int(len(self._recent_peers)),
            },
        }
