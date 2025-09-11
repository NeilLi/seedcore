from __future__ import annotations
"""
Persistent (Redis-backed) GPU Guard for SeedCore
------------------------------------------------
Enforces cluster-wide GPU concurrency and daily budget limits across processes/
replicas. Designed to be resilient to restarts via Redis keys with TTL.

Usage (typical):
    guard = GPUGuard.from_env()
    ok, reason = guard.try_acquire(job_id, gpu_seconds_budget=1800)
    if not ok:
        # reject or queue
    ... run job ...
    guard.complete(job_id, actual_gpu_seconds=elapsed_gpu_secs, success=True)
"""
import os
import time
import json
import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any

try:
    import redis  # type: ignore
except Exception:
    redis = None

logger = logging.getLogger(__name__)


def _utc_midnight_epoch() -> int:
    now = datetime.now(timezone.utc)
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return int(midnight.timestamp())


class GPUGuard:
    """
    Redis-backed budget & concurrency guard.
    Keys (namespace: gpu_guard):
      - daily_budget_used:{YYYYMMDD} -> float seconds used (expires +2d)
      - inflight_jobs -> hash {job_id: start_ts}
      - settings -> hash {max_concurrency, daily_budget_seconds}
    """
    def __init__(
        self,
        r: Optional["redis.Redis"],
        namespace: str = "gpu_guard",
        max_concurrency: int = 1,
        daily_budget_seconds: int = 4 * 3600,  # default 4 GPU-hours/day
    ):
        self.r = r
        self.ns = namespace
        self.max_conc = int(max_concurrency)
        self.day_budget = int(daily_budget_seconds)

    @classmethod
    def from_env(cls) -> "GPUGuard":
        """
        Construct from env:
          GPU_GUARD_NAMESPACE  (default: gpu_guard)
          GPU_GUARD_MAX_CONCURRENCY (default: 1)
          GPU_GUARD_DAILY_BUDGET_SEC (default: 14400 -> 4h)
        """
        url = os.getenv("REDIS_URL", "redis://redis-master:6379/0")
        ns = os.getenv("GPU_GUARD_NAMESPACE", "gpu_guard")
        maxc = int(os.getenv("GPU_GUARD_MAX_CONCURRENCY", "1"))
        budget = int(os.getenv("GPU_GUARD_DAILY_BUDGET_SEC", "14400"))

        r = None
        if redis is not None:
            try:
                r = redis.from_url(url, decode_responses=True)
                # quick ping
                r.ping()
                logger.info(f"✅ GPUGuard connected to Redis at {url}")
            except Exception as e:
                logger.warning(f"⚠️ GPUGuard failed to connect Redis ({url}): {e}. Falling back to no-op guard.")
                r = None
        else:
            logger.warning("⚠️ redis package not available. GPUGuard will be no-op.")

        return cls(r, ns, maxc, budget)

    # ---------- Redis key helpers ----------
    def _k_settings(self) -> str:
        return f"{self.ns}:settings"

    def _k_inflight(self) -> str:
        return f"{self.ns}:inflight_jobs"

    def _k_daily_used(self, yyyymmdd: str) -> str:
        return f"{self.ns}:daily_budget_used:{yyyymmdd}"

    def _today_tag(self) -> str:
        now = datetime.now(timezone.utc)
        return f"{now.year:04d}{now.month:02d}{now.day:02d}"

    # ---------- Public API ----------
    def get_status(self) -> Dict[str, Any]:
        """
        Returns guard status: concurrency, daily usage, and inflight count.
        """
        if self.r is None:
            return {
                "backend": "noop",
                "max_concurrency": self.max_conc,
                "daily_budget_seconds": self.day_budget,
                "inflight_jobs": 0,
                "today_used_seconds": 0.0,
            }

        today = self._today_tag()
        used = float(self.r.get(self._k_daily_used(today)) or 0.0)
        inflight = self.r.hlen(self._k_inflight())
        return {
            "backend": "redis",
            "max_concurrency": self.max_conc,
            "daily_budget_seconds": self.day_budget,
            "inflight_jobs": inflight,
            "today_used_seconds": used,
        }

    def try_acquire(self, job_id: str, gpu_seconds_budget: int) -> Tuple[bool, str]:
        """
        Admission control:
          1) Enforce concurrency
          2) Enforce daily budget (remaining >= requested budget)
        On success: mark job inflight with start time.
        """
        if not job_id:
            return False, "missing_job_id"
        if gpu_seconds_budget <= 0:
            gpu_seconds_budget = 1

        # No-op mode
        if self.r is None:
            logger.info("GPUGuard (noop) admitting job (no Redis).")
            return True, "ok"

        pipe = self.r.pipeline()
        try:
            # Concurrency check
            inflight_key = self._k_inflight()
            pipe.hlen(inflight_key)
            # Budget check
            today = self._today_tag()
            daily_key = self._k_daily_used(today)
            pipe.get(daily_key)
            res = pipe.execute()
            inflight = int(res[0] or 0)
            used = float(res[1] or 0.0)

            if inflight >= self.max_conc:
                return False, f"concurrency_limit_reached:{inflight}/{self.max_conc}"

            remaining = self.day_budget - used
            if remaining <= 0:
                return False, f"daily_budget_exhausted:{used:.0f}s/{self.day_budget}s"
            if gpu_seconds_budget > remaining:
                return False, f"insufficient_daily_budget:need={gpu_seconds_budget}s remaining={remaining:.0f}s"

            # Admit: record inflight
            now = time.time()
            self.r.hset(inflight_key, job_id, json.dumps({"start_ts": now, "reserve_s": gpu_seconds_budget}))
            # Keep inflight hash indefinitely; cleanup happens at completion.

            # Initialize daily key TTL to survive until +2 days (reset after midnight)
            # (so we don't leak keys if system is idle)
            if not self.r.ttl(daily_key):
                # expire at end of tomorrow
                tomorrow_midnight = _utc_midnight_epoch() + 2 * 24 * 3600
                self.r.setnx(daily_key, used)  # ensure key exists
                self.r.expireat(daily_key, tomorrow_midnight)
            return True, "ok"
        except Exception as e:
            logger.warning(f"GPUGuard admission failed (soft-allow): {e}")
            # Soft-allow on guard failure to avoid blocking prod
            return True, "guard_error_soft_allow"

    def complete(self, job_id: str, actual_gpu_seconds: float, success: bool = True) -> None:
        """
        Releases the inflight slot and increments the daily usage with the *actual*
        GPU seconds (clamped >=0). Always safe to call.
        """
        if self.r is None:
            return
        try:
            inflight_key = self._k_inflight()
            entry_raw = self.r.hget(inflight_key, job_id)
            if entry_raw:
                self.r.hdel(inflight_key, job_id)

            today = self._today_tag()
            daily_key = self._k_daily_used(today)
            inc = max(0.0, float(actual_gpu_seconds or 0.0))
            # Use float increment
            self.r.setnx(daily_key, 0.0)
            self.r.incrbyfloat(daily_key, inc)
        except Exception as e:
            logger.warning(f"GPUGuard completion failed (ignored): {e}")