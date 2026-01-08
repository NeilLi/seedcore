# new file: proactive_system_aggregator.py

import asyncio
import logging
import time
from typing import Optional
import httpx  # pyright: ignore[reportMissingImports]
import numpy as np

from seedcore.utils.ray_utils import COG

logger = logging.getLogger(__name__)

class SystemAggregator:
    """
    Polls high-level system services (like CognitiveService)
    for system-wide state like E_patterns.
    """
    
    def __init__(self, poll_interval: float = 5.0):
        self.poll_interval = poll_interval
        
        # Get the Cognitive/HGNN service URL from config
        # This is the service that provides the E_patterns
        cognitive_url = COG
        
        self._http_client = httpx.AsyncClient(base_url=cognitive_url, timeout=2.0)
        
        # Internal state cache
        self._E_patterns: np.ndarray = np.array([])
        self._last_update_time: float = 0.0

        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._is_running = asyncio.Event()

    async def start(self):
        if self._loop_task is None or self._loop_task.done():
            logger.info(f"Starting proactive E_patterns poll loop (interval: {self.poll_interval}s)")
            self._loop_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self.is_running() and self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        await self._http_client.aclose()
        logger.info("Proactive E_patterns loop stopped.")

    def is_running(self) -> bool:
        return self._is_running.is_set()
        
    async def wait_for_first_poll(self, timeout: float = 10.0):
        await asyncio.wait_for(self._is_running.wait(), timeout=timeout)

    async def _poll_loop(self):
        while True:
            try:
                start_time = time.monotonic()
                
                # Poll the endpoint that serves E_patterns
                # Try multiple possible endpoints for backward compatibility
                endpoints_to_try = ["/cognitive/patterns", "/patterns", "/metrics"]
                data = None
                last_error = None
                
                for endpoint in endpoints_to_try:
                    try:
                        response = await self._http_client.get(endpoint, timeout=2.0)
                        if response.status_code == 200:
                            data = response.json()
                            # Check if this endpoint has the data we need
                            if "e_patterns" in data or "E_patterns" in data or "patterns" in data:
                                break
                        elif response.status_code == 404:
                            # Try next endpoint
                            continue
                        else:
                            response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            # Try next endpoint
                            continue
                        last_error = e
                        raise
                    except Exception as e:
                        last_error = e
                        # Try next endpoint for non-HTTP errors
                        continue
                
                if data is None:
                    # No endpoint worked, use empty patterns (degraded mode)
                    logger.warning(
                        f"Could not fetch E_patterns from CognitiveService. "
                        f"Tried endpoints: {endpoints_to_try}. Using empty patterns. "
                        f"Last error: {last_error}"
                    )
                    e_patterns_list = []
                else:
                    # Extract e_patterns from response
                    e_patterns_list = (
                        data.get("e_patterns") or 
                        data.get("E_patterns") or 
                        data.get("patterns") or 
                        []
                    )
                
                new_patterns = np.array(e_patterns_list, dtype=np.float32)
                
                # Atomically update
                async with self._lock:
                    self._E_patterns = new_patterns
                    self._last_update_time = time.time()
                
                self._is_running.set()
                
                duration = time.monotonic() - start_time
                await asyncio.sleep(max(0, self.poll_interval - duration))

            except asyncio.CancelledError:
                logger.info("E_patterns poll loop cancelled.")
                break
            except Exception as e:
                # Log error but continue polling (degraded mode)
                logger.warning(f"Error in E_patterns poll loop: {e}. Using empty patterns.")
                # Use empty patterns as fallback
                async with self._lock:
                    self._E_patterns = np.array([], dtype=np.float32)
                    self._last_update_time = time.time()
                self._is_running.set()
                await asyncio.sleep(self.poll_interval)

    async def get_E_patterns(self) -> np.ndarray:
        async with self._lock:
            return self._E_patterns.copy()
            
    async def get_last_update_time(self) -> float:
        return self._last_update_time