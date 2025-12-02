"""
Metrics Integration Service

This service automatically updates Prometheus metrics by polling the rich API endpoints
and converting the data into Prometheus format. This leverages the existing comprehensive
API endpoints without requiring additional instrumentation.

When running on the same server, it can access app state directly for better performance.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional
from .metrics import (
    update_all_metrics_from_api_data,
    API_REQUESTS_TOTAL,
    API_REQUEST_DURATION
)
import time

logger = logging.getLogger(__name__)

def safe_dict(data) -> Dict[str, Any]:
    """Ensure data is always a dictionary to prevent 'bool' object has no attribute 'get' errors."""
    if isinstance(data, dict):
        return data
    elif data is None:
        return {}
    else:
        logger.warning(f"Expected dict but got {type(data).__name__}: {data}, returning empty dict")
        return {}

class MetricsIntegrationService:
    """
    Service that integrates with existing API endpoints to update Prometheus metrics.
    
    This approach leverages the rich API endpoints we already have instead of
    instrumenting every component individually.
    
    When running on the same server, it can access app state directly for better performance.
    """
    
    def __init__(self, base_url: str = "http://localhost:80", update_interval: int = 30, app_state=None):
        self.base_url = base_url.rstrip('/')
        self.update_interval = update_interval
        self.app_state = app_state  # FastAPI app state for local access
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        
        # Check if we're running locally (same server)
        # Normalize base_url for comparison
        normalized_url = base_url.lower().replace('http://', '').replace('https://', '')
        self.is_local = normalized_url in ["localhost:80", "localhost:8002", "127.0.0.1:80", "127.0.0.1:8002", "0.0.0.0:8002"]
        
    async def start(self):
        """Start the metrics integration service."""
        if not self.is_local:
            self.session = aiohttp.ClientSession()
        
        self.running = True
        logger.info(f"🚀 Starting Metrics Integration Service (interval: {self.update_interval}s, mode: {'local' if self.is_local else 'remote'})")
        
        while self.running:
            try:
                await self._update_all_metrics()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error in metrics integration: {e}")
                await asyncio.sleep(self.update_interval)
    
    async def stop(self):
        """Stop the metrics integration service."""
        self.running = False
        if self.session:
            await self.session.close()
        logger.info("🛑 Stopped Metrics Integration Service")
    
    async def _fetch_endpoint(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Fetch data from an API endpoint with metrics tracking."""
        if self.is_local and self.app_state:
            # Use local app state for better performance
            return await self._get_local_data(endpoint)
        elif self.session:
            # Use HTTP calls for remote services
            return await self._fetch_remote_endpoint(endpoint)
        else:
            logger.warning(f"Cannot fetch {endpoint}: no session or app state available")
            return None
    
    async def _get_local_data(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Get data from local app state instead of HTTP calls."""
        try:
            if endpoint == "/energy/gradient":
                # Access energy data from app state
                if hasattr(self.app_state, 'energy_weights'):
                    return {"energy_weights": self.app_state.energy_weights}
                return {"energy_weights": None}
                
            elif endpoint == "/tier0/agents/state":
                # Access agent data from app state
                if hasattr(self.app_state, 'organism') and self.app_state.organism:
                    try:
                        # Get agent states from organism manager
                        agent_states = {}
                        # This would need to be implemented based on your agent structure
                        return {"agents": agent_states}
                    except Exception as e:
                        logger.debug(f"Could not get agent states: {e}")
                        return {"agents": {}}
                return {"agents": {}}
                
            elif endpoint == "/system/status":
                # Access system status from app state
                # Ensure we always return a dict, never a boolean
                organism = getattr(self.app_state, 'organism', None)
                status = {
                    "ray_connected": hasattr(self.app_state, 'organism') and organism is not None,
                    "memory_system": {"available": hasattr(self.app_state, 'mem')},  # make it a dict
                    "organism_initialized": hasattr(self.app_state, 'organism') and getattr(organism, '_initialized', False) if organism else False
                }
                return status
                
            elif endpoint == "/energy/monitor":
                # Access energy monitoring data from app state
                if hasattr(self.app_state, 'energy_weights'):
                    return {"energy_weights_available": True}
                return {"energy_weights_available": False}
                
            else:
                logger.warning(f"Unknown local endpoint: {endpoint}")
                return {}
                
        except Exception as e:
            logger.error(f"Error getting local data for {endpoint}: {e}")
            return {}
    
    async def _fetch_remote_endpoint(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Fetch data from a remote API endpoint with metrics tracking."""
        if not self.session:
            return None
            
        start_time = time.time()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with self.session.get(url) as response:
                duration = time.time() - start_time
                
                # Update API metrics
                API_REQUESTS_TOTAL.labels(endpoint=endpoint, method="GET").inc()
                API_REQUEST_DURATION.labels(endpoint=endpoint, method="GET").observe(duration)
                
                if response.status == 200:
                    data = await response.json()
                    # Ensure we always return a dict, never a boolean
                    if isinstance(data, dict):
                        return data
                    else:
                        logger.warning(f"Unexpected non-dict JSON from {endpoint}: {data} (type: {type(data).__name__})")
                        return {}
                else:
                    logger.warning(f"Failed to fetch {endpoint}: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {e}")
            return {}
    
    async def _update_all_metrics(self):
        """Update all metrics from API endpoints."""
        logger.debug("📊 Updating metrics from API endpoints...")
        
        # Fetch data from all endpoints concurrently
        tasks = [
            self._fetch_endpoint("/energy/gradient"),
            self._fetch_endpoint("/tier0/agents/state"),
            self._fetch_endpoint("/system/status"),
            self._fetch_endpoint("/energy/monitor")
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and ensure they're all dictionaries
        energy_data = safe_dict(results[0] if not isinstance(results[0], Exception) else None)
        agents_data = safe_dict(results[1] if not isinstance(results[1], Exception) else None)
        system_data = safe_dict(results[2] if not isinstance(results[2], Exception) else None)
        energy_monitor_data = safe_dict(results[3] if not isinstance(results[3], Exception) else None)
        
        # Update metrics with guaranteed dictionary data
        update_all_metrics_from_api_data(
            energy_data=energy_data,
            agents_data=agents_data,
            system_data=system_data
        )
        
        # Log summary
        if any([energy_data, agents_data, system_data, energy_monitor_data]):
            logger.debug("✅ Metrics updated successfully")
        else:
            logger.warning("⚠️ No metrics data received from API endpoints")

# Global instance
_metrics_service: Optional[MetricsIntegrationService] = None

async def start_metrics_integration(base_url: str = "http://localhost:80", update_interval: int = 30, app_state=None):
    """Start the global metrics integration service."""
    global _metrics_service
    
    if _metrics_service is None:
        _metrics_service = MetricsIntegrationService(base_url, update_interval, app_state)
        await _metrics_service.start()

async def stop_metrics_integration():
    """Stop the global metrics integration service."""
    global _metrics_service
    
    if _metrics_service:
        await _metrics_service.stop()
        _metrics_service = None

def get_metrics_service() -> Optional[MetricsIntegrationService]:
    """Get the global metrics integration service instance."""
    return _metrics_service
