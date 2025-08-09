"""
Agent-private memory implementation h_i ∈ R^128 with fixed budget and lifetime persistence.
Blocks (sum = 128):
- T (64): recent task embeddings (EMA after random projection)
- S (24): local skill adaptation sketch (count-sketch or random projection)
- P (24): peer interaction history (count-sketch over (peer,event))
- F (16): performance trace features (EWMA stats)

• Persistence: process memory only (agent lifetime). No disk I/O.
• Telemetry: block-wise breakdown for meta-learning controller.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
import numpy as np
import math
import time

# === Capacity & defaults ===
D_TOTAL = 128
D_FEAT = 16

# Capacities for T/S/P and an initial active allocation (sum=112, since F=16)
MAX_T = 80
MAX_S = 32
MAX_P = 32
INIT_ALLOC: Tuple[int, int, int] = (64, 24, 24)

EPS = 1e-8

@dataclass
class PeerEvent:
    peer_id: str
    outcome: int  # +1 success, -1 failure, 0 neutral
    weight: float = 1.0
    role: Optional[str] = None

class EWMStats:
    """Exponentially weighted mean/var for streaming scalars."""
    def __init__(self, alpha: float = 0.1):
        self.alpha = alpha
        self.mean = 0.0
        self.var = 0.0
        self.initialized = False

    def update(self, x: float):
        x = float(x)
        if not self.initialized:
            self.mean = x
            self.var = 0.0
            self.initialized = True
        else:
            prev_mean = self.mean
            self.mean = (1 - self.alpha) * self.mean + self.alpha * x
            # EW variance against previous mean
            self.var = (1 - self.alpha) * (self.var + self.alpha * (x - prev_mean) ** 2)

class FeatureHasher:
    """Hash arbitrary-length dense vector to fixed size using index&sign hashing."""
    def __init__(self, out_dim: int, num_seeds: int = 1, seed: int = 123):
        self.out_dim = out_dim
        self.num_seeds = num_seeds
        self.seed = seed

    def transform(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        h = np.zeros(self.out_dim, dtype=np.float32)
        n = x.size
        # Single-seed simple hashing to keep runtime tiny
        rng = np.random.default_rng(self.seed + n)
        idx = rng.integers(0, self.out_dim, size=n)
        sign = rng.integers(0, 2, size=n, dtype=np.int8) * 2 - 1
        np.add.at(h, idx, x * sign)
        return h


class MLPCompressor:
    """Tiny 2-layer MLP compressor with an auxiliary utility head trained online.

    Architecture: hashed_input(H_IN) -> ReLU(HIDDEN) -> z(D_TASK)
    Auxiliary head: z -> u_hat (scalar), trained to predict utility target.
    """
    def __init__(self, in_dim: int, out_dim: int, hidden_dim: int = 64, lr: float = 1e-2, seed: int = 7):
        self.in_dim = in_dim
        self.out_dim = out_dim
        self.hidden_dim = hidden_dim
        self.lr = lr
        rng = np.random.default_rng(seed)
        # Xavier init
        self.W1 = (rng.standard_normal((in_dim, hidden_dim)).astype(np.float32) / np.sqrt(in_dim))
        self.b1 = np.zeros(hidden_dim, dtype=np.float32)
        self.W2 = (rng.standard_normal((hidden_dim, out_dim)).astype(np.float32) / np.sqrt(hidden_dim))
        self.b2 = np.zeros(out_dim, dtype=np.float32)
        self.Wu = (rng.standard_normal((out_dim, 1)).astype(np.float32) / np.sqrt(out_dim))
        self.bu = np.zeros(1, dtype=np.float32)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        h1 = x @ self.W1 + self.b1
        a1 = np.maximum(h1, 0.0)
        z = a1 @ self.W2 + self.b2
        cache = {"x": x, "h1": h1, "a1": a1, "z": z}
        return z, cache

    def predict_utility(self, z: np.ndarray) -> np.ndarray:
        return z @ self.Wu + self.bu

    def train_step(self, x: np.ndarray, target_utility: float) -> np.ndarray:
        # Forward
        z, cache = self.forward(x)
        u_hat = self.predict_utility(z)  # shape (1,)
        # Loss: (u_hat - y)^2
        y = float(target_utility)
        diff = (u_hat.squeeze() - y)
        # Backprop to Wu, bu
        dWu = np.outer(z, diff)  # (out_dim,)
        dbu = np.array([diff], dtype=np.float32)
        dz = self.Wu.flatten() * diff  # (out_dim,)
        # Backprop through second layer
        da1 = dz @ self.W2.T  # (hidden_dim,)
        dW2 = np.outer(cache["a1"], dz)
        db2 = dz
        # Backprop ReLU
        dh1 = da1 * (cache["h1"] > 0).astype(np.float32)
        dW1 = np.outer(cache["x"], dh1)
        db1 = dh1
        # Update params (SGD)
        self.Wu -= self.lr * dWu.reshape(self.out_dim, 1)
        self.bu -= self.lr * dbu
        self.W2 -= self.lr * dW2
        self.b2 -= self.lr * db2
        self.W1 -= self.lr * dW1
        self.b1 -= self.lr * db1
        return z


class CountMinSketch:
    """Count-Min Sketch with d rows and w columns; supports float updates."""
    def __init__(self, d: int, w: int, seed: int = 31):
        self.d = d
        self.w = w
        self.table = np.zeros((d, w), dtype=np.float32)
        self._rng = np.random.default_rng(seed)
        # row salts to vary hash functions
        self._salts = [int(self._rng.integers(1, 2**31-1)) for _ in range(d)]

    def _hash(self, s: str, row: int) -> int:
        return (hash((s, self._salts[row])) % self.w)

    def update(self, key: str, value: float):
        for r in range(self.d):
            c = self._hash(key, r)
            self.table[r, c] += float(value)

    def estimate(self, key: str) -> float:
        return float(min(self.table[r, self._hash(key, r)] for r in range(self.d)))


class SpaceSaving:
    """Space-Saving algorithm for top-K heavy hitters."""
    def __init__(self, k: int = 16):
        self.k = k
        self.counts: Dict[str, float] = {}

    def update(self, key: str, inc: float = 1.0):
        if key in self.counts:
            self.counts[key] += inc
            return
        if len(self.counts) < self.k:
            self.counts[key] = inc
            return
        # Replace the min-count entry
        min_key = min(self.counts, key=self.counts.get)
        min_val = self.counts[min_key]
        # New key takes over with increased baseline
        self.counts.pop(min_key)
        self.counts[key] = min_val + inc

    def topk(self) -> List[Tuple[str, float]]:
        return sorted(self.counts.items(), key=lambda kv: kv[1], reverse=True)

class AgentPrivateMemory:
    def __init__(self, agent_id: str, alpha: float = 0.1, *,
                 use_mlp_task_encoder: bool = False,
                 hasher_dim: int = 256,
                 mlp_hidden: int = 64,
                 mlp_lr: float = 1e-2):
        self.agent_id = agent_id
        self.alpha = alpha

        # Blocks
        self._task_proj: Optional[np.ndarray] = None  # RP fallback (k, MAX_T)
        self._task_ema = np.zeros(MAX_T, dtype=np.float32)
        self._task_last: Optional[np.ndarray] = None
        self._task_seen = 0

        # Task encoder config
        self._use_mlp = use_mlp_task_encoder
        self._hasher = FeatureHasher(out_dim=hasher_dim)
        self._mlp: Optional[MLPCompressor] = MLPCompressor(hasher_dim, MAX_T, hidden_dim=mlp_hidden, lr=mlp_lr) if self._use_mlp else None

        self._skill_proj: Optional[np.ndarray] = None  # optional (m, MAX_S) if dense deltas
        self._skill_sketch = np.zeros(MAX_S, dtype=np.float32)

        # Peer tracking: CMS (flattened to 24 dims) + SpaceSaving top-K
        # Choose CMS dims to match MAX_P exactly when flattened
        self._cms_rows = 4
        self._cms_cols = MAX_P // self._cms_rows  # 32/4 = 8; we'll slice later to active dP
        self._peer_cms = CountMinSketch(self._cms_rows, self._cms_cols, seed=17)
        self._peer_topk = SpaceSaving(k=16)
        self._recent_peers: Dict[str, float] = {}

        # Performance trace (EWMA)
        self._succ = EWMStats(alpha)
        self._quality = EWMStats(alpha)
        self._lat = EWMStats(alpha)
        self._energy = EWMStats(alpha)
        self._deltaE = EWMStats(alpha)
        self._fail = EWMStats(alpha)
        self._tasks = 0
        self._mem_util = EWMStats(alpha)
        # OCPS regime signals (initialize to avoid AttributeError on first update)
        self._ocps_drift = EWMStats(alpha)
        self._ocps_fast_p = EWMStats(alpha)
        self._ocps_esc_rate = EWMStats(alpha)

        # Adaptive allocation state (active dims for T,S,P)
        self.dT, self.dS, self.dP = INIT_ALLOC
        assert self.dT + self.dS + self.dP + D_FEAT == D_TOTAL

        # Scores for adaptive allocator (EW of L2 deltas)
        self._score_T = EWMStats(alpha)
        self._score_S = EWMStats(alpha)
        self._score_P = EWMStats(alpha)
        self._realloc_cooldown = 0

        # Public vector
        self.h = np.zeros(D_TOTAL, dtype=np.float32)

        # Discrete allocator with hysteresis/cooldown
        self._allocator = AdaptiveAllocator(
            templates=[(80,16,16), (64,32,16), (64,24,24), (48,32,32)],
            hysteresis=0.05,
            min_steps_between=50,
        )

    # ---------- Update paths ----------
    def _ensure_task_proj(self, k: int):
        if self._task_proj is None:
            # Gaussian random projection scaled by 1/sqrt(MAX_T)
            self._task_proj = (np.random.randn(k, MAX_T).astype(np.float32) / math.sqrt(MAX_T))

    def _ensure_skill_proj(self, m: int):
        if self._skill_proj is None:
            self._skill_proj = (np.random.randn(m, MAX_S).astype(np.float32) / math.sqrt(MAX_S))

    def update_after_task(
        self,
        task_embed: Optional[np.ndarray],
        *,
        success: bool,
        quality: Optional[float] = None,
        latency_s: Optional[float] = None,
        energy: Optional[float] = None,
        delta_e: Optional[float] = None,
        peer_events: Optional[List[PeerEvent]] = None,
        skill_delta: Optional[np.ndarray] = None,
        mem_utilization: Optional[float] = None,
        ocps_drift: Optional[float] = None,
        ocps_p_fast: Optional[float] = None,
        ocps_escalated: Optional[bool] = None,
    ) -> np.ndarray:
        """Update all memory blocks and rebuild h.
        Returns the new h (np.ndarray shape (128,)).
        """
        # Snapshot for adaptive scoring
        prev_T = self._task_ema.copy()
        prev_S = self._skill_sketch.copy()
        prev_P = self._peer_cms.table.reshape(-1).copy()

        # Task block
        if task_embed is not None:
            e = np.asarray(task_embed, dtype=np.float32).reshape(-1)
            if self._use_mlp and self._mlp is not None:
                xh = self._hasher.transform(e)
                # Online train step if we have a learning signal
                if quality is not None or energy is not None or delta_e is not None:
                    # Utility target: blend quality and success minus energy costs
                    succ_val = 1.0 if success else 0.0
                    q = float(quality) if quality is not None else succ_val
                    en = float(energy) if energy is not None else 0.0
                    de = float(delta_e) if delta_e is not None else 0.0
                    utility = 0.6 * q + 0.4 * succ_val - 0.05 * en - 0.02 * max(0.0, de)
                    z = self._mlp.train_step(xh, utility)
                else:
                    z, _ = self._mlp.forward(xh)
            else:
                # Random projection fallback
                self._ensure_task_proj(e.shape[0])
                z = e @ self._task_proj  # (MAX_T,)
            # EWMA update
            self._task_ema = (1 - self.alpha) * self._task_ema + self.alpha * z
            self._task_last = z
            self._task_seen += 1

        # Skill block
        if skill_delta is not None:
            sd = np.asarray(skill_delta, dtype=np.float32).reshape(-1)
            # If very high dimensional, fall back to hashed aggregation
            if sd.size > 4096:
                # hashed sketch: 2 passes with different seeds
                for seed in (23, 29):
                    rng = np.random.default_rng(seed)
                    idx = rng.integers(0, MAX_S, size=sd.size)
                    sign = rng.integers(0, 2, size=sd.size, dtype=np.int8) * 2 - 1
                    np.add.at(self._skill_sketch, idx, sd * sign)
                # EWMA smoothing
                self._skill_sketch = (1 - self.alpha) * self._skill_sketch + self.alpha * self._skill_sketch
            else:
                self._ensure_skill_proj(sd.size)
                s = sd @ self._skill_proj
                self._skill_sketch = (1 - self.alpha) * self._skill_sketch + self.alpha * s

        # Peer block
        if peer_events:
            for pe in peer_events:
                key = f"{pe.peer_id}|{pe.role or ''}|{int(pe.outcome)}"
                self._peer_cms.update(key, pe.weight)
                self._peer_topk.update(pe.peer_id, pe.weight)
                # track recent peers for telemetry
                self._recent_peers[pe.peer_id] = time.time()
                if len(self._recent_peers) > 64:
                    # drop the oldest
                    oldest = min(self._recent_peers.items(), key=lambda kv: kv[1])[0]
                    self._recent_peers.pop(oldest, None)

        # Performance block
        self._tasks += 1
        self._succ.update(1.0 if success else 0.0)
        self._fail.update(0.0 if success else 1.0)
        if quality is not None:
            self._quality.update(quality)
        if latency_s is not None:
            self._lat.update(latency_s)
        if energy is not None:
            self._energy.update(energy)
        if delta_e is not None:
            self._deltaE.update(delta_e)
        if mem_utilization is not None:
            self._mem_util.update(mem_utilization)

        # OCPS signals
        if ocps_drift is not None:
            self._ocps_drift.update(float(ocps_drift))
        if ocps_p_fast is not None:
            self._ocps_fast_p.update(float(ocps_p_fast))
        if ocps_escalated is not None:
            self._ocps_esc_rate.update(1.0 if ocps_escalated else 0.0)

        # Adaptive scores from L2 deltas
        self._score_T.update(float(np.linalg.norm(self._task_ema[:self.dT] - prev_T[:self.dT])))
        self._score_S.update(float(np.linalg.norm(self._skill_sketch[:self.dS] - prev_S[:self.dS])))
        # Use flattened CMS table for P
        curr_P = self._peer_cms.table.reshape(-1)
        self._score_P.update(float(np.linalg.norm(curr_P[:self.dP] - prev_P[:self.dP])))

        self._maybe_reallocate()

        # Rebuild h
        self._rebuild_h()
        return self.h

    # ---------- Compose h ----------
    def _norm(self, v: np.ndarray) -> np.ndarray:
        v = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(v) + EPS)
        return v / n

    def _feat_block(self) -> np.ndarray:
        # pack 16 scalar features (clip/normalize reasonable ranges)
        feats = np.zeros(D_FEAT, dtype=np.float32)
        # [0]–[7]
        feats[0] = self._succ.mean
        feats[1] = self._quality.mean
        feats[2] = math.sqrt(max(0.0, self._quality.var))
        feats[3] = self._lat.mean
        feats[4] = math.sqrt(max(0.0, self._lat.var))
        feats[5] = self._energy.mean
        feats[6] = self._deltaE.mean
        feats[7] = self._mem_util.mean
        # [8]–[11]: rates, counts (scaled)
        feats[8] = self._fail.mean
        feats[9] = float(self._tasks) / 100.0
        feats[10] = float(min(self._task_seen, 255)) / 255.0
        feats[11] = float(len(self._recent_peers)) / 64.0
        # [12]–[15]: OCPS signals
        feats[12] = getattr(self, '_ocps_drift', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_drift') else 0.0
        feats[13] = math.sqrt(max(0.0, getattr(self, '_ocps_drift', EWMStats(self.alpha)).var)) if hasattr(self, '_ocps_drift') else 0.0
        feats[14] = getattr(self, '_ocps_fast_p', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_fast_p') else 0.0
        feats[15] = getattr(self, '_ocps_esc_rate', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_esc_rate') else 0.0
        return feats

    def _rebuild_h(self):
        # Use active slices
        T = self._norm(self._task_ema[: self.dT] if hasattr(self, 'dT') else self._task_ema)
        S = self._norm(self._skill_sketch[: self.dS] if hasattr(self, 'dS') else self._skill_sketch)
        P_full = self._peer_cms.table.reshape(-1)
        P = self._norm(P_full[: self.dP] if hasattr(self, 'dP') else P_full)
        F = self._norm(self._feat_block())
        self.h = np.concatenate([T, S, P, F]).astype(np.float32)

    # ---------- API ----------
    def reset(self):
        self.__init__(self.agent_id, self.alpha)

    def get_vector(self) -> np.ndarray:
        return self.h.copy()

    def get_vector_list(self) -> List[float]:
        return self.h.astype(np.float32).tolist()

    # Optional serialization helpers for checkpointing
    def dump(self) -> Dict[str, Any]:
        return {
            "h": self.get_vector_list(),
            "task": [float(x) for x in self._task_ema.tolist()],
            "skill": [float(x) for x in self._skill_sketch.tolist()],
            "peer_cms": [float(x) for x in self._peer_cms.table.reshape(-1).tolist()],
            "dT": int(getattr(self, "dT", 64)),
            "dS": int(getattr(self, "dS", 24)),
            "dP": int(getattr(self, "dP", 24)),
        }

    def load(self, blob: Dict[str, Any]) -> None:
        try:
            t = np.array(blob.get("task", []), dtype=np.float32)
            s = np.array(blob.get("skill", []), dtype=np.float32)
            p = np.array(blob.get("peer_cms", []), dtype=np.float32)
            if t.size:
                self._task_ema[: min(t.size, self._task_ema.size)] = t[: self._task_ema.size]
            if s.size:
                self._skill_sketch[: min(s.size, self._skill_sketch.size)] = s[: self._skill_sketch.size]
            if p.size:
                flat = self._peer_cms.table.reshape(-1)
                flat[: min(p.size, flat.size)] = p[: flat.size]
            # Allocation
            self.dT = int(blob.get("dT", self.dT))
            self.dS = int(blob.get("dS", self.dS))
            self.dP = int(blob.get("dP", self.dP))
            self._rebuild_h()
        except Exception:
            # Fail silently to avoid blocking startup
            pass

    def telemetry(self) -> Dict[str, Any]:
        topk = self._peer_topk.topk()
        return {
            "agent_id": self.agent_id,
            "blocks": {
                "task": [float(x) for x in (self._task_ema[: self.dT] if hasattr(self, 'dT') else self._task_ema).tolist()],
                "skill": [float(x) for x in (self._skill_sketch[: self.dS] if hasattr(self, 'dS') else self._skill_sketch).tolist()],
                "peer_cms": [float(x) for x in (self._peer_cms.table.reshape(-1)[: self.dP] if hasattr(self, 'dP') else self._peer_cms.table.reshape(-1)).tolist()],
                "features": [float(x) for x in self._feat_block().tolist()],
            },
            "counters": {
                "tasks": int(self._tasks),
                "peers_tracked": int(len(self._recent_peers)),
                "task_seen": int(self._task_seen),
            },
            "stats": {
                "success_rate": float(self._succ.mean),
                "quality_mean": float(self._quality.mean),
                "lat_mean": float(self._lat.mean),
                "energy_mean": float(self._energy.mean),
                "deltaE_mean": float(self._deltaE.mean),
                "ocps_drift_mean": float(getattr(self, '_ocps_drift', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_drift') else 0.0),
                "p_fast_mean": float(getattr(self, '_ocps_fast_p', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_fast_p') else 0.0),
                "esc_rate_mean": float(getattr(self, '_ocps_esc_rate', EWMStats(self.alpha)).mean if hasattr(self, '_ocps_esc_rate') else 0.0),
            },
            "peer_topk": topk,
            "encoders": {
                "task_encoder": "mlp" if self._use_mlp else "random_projection",
                "hasher_dim": getattr(self._hasher, 'out_dim', None)
            },
            "allocation": {"T": int(getattr(self, 'dT', 64)), "S": int(getattr(self, 'dS', 24)), "P": int(getattr(self, 'dP', 24)), "F": D_FEAT},
            "scores": {"T": float(getattr(self, '_score_T', EWMStats(self.alpha)).mean if hasattr(self, '_score_T') else 0.0),
                        "S": float(getattr(self, '_score_S', EWMStats(self.alpha)).mean if hasattr(self, '_score_S') else 0.0),
                        "P": float(getattr(self, '_score_P', EWMStats(self.alpha)).mean if hasattr(self, '_score_P') else 0.0)},
        }

# === Simple discrete allocator ===
class AdaptiveAllocator:
    def __init__(self, templates: List[Tuple[int, int, int]], hysteresis: float = 0.05, min_steps_between: int = 50):
        # templates are (T,S,P) triples summing to 112
        self.templates = templates
        self.hysteresis = hysteresis
        self.min_steps_between = min_steps_between

    def select(self, scores: Tuple[float, float, float], current: Tuple[int, int, int]) -> Optional[Tuple[int, int, int]]:
        sT, sS, sP = scores
        s = np.array([max(sT, 1e-8), max(sS, 1e-8), max(sP, 1e-8)], dtype=np.float32)
        s = s / float(s.sum())

        def score_template(t: Tuple[int, int, int]) -> float:
            t_arr = np.array(t, dtype=np.float32)
            t_arr = t_arr / float(t_arr.sum())
            return float(np.dot(s, t_arr))

        current_score = score_template(current)
        best_t = current
        best_score = current_score
        for t in self.templates:
            sc = score_template(t)
            if sc > best_score:
                best_score = sc
                best_t = t

        if best_t != current and (best_score - current_score) / max(current_score, 1e-8) > self.hysteresis:
            return best_t
        return None


