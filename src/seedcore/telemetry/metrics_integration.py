"""
Metrics Integration Service

This service automatically updates Prometheus metrics by polling the rich API endpoints
and converting the data into Prometheus format. This leverages the existing comprehensive
API endpoints without requiring additional instrumentation.
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

class MetricsIntegrationService:
    """
    Service that integrates with existing API endpoints to update Prometheus metrics.
    
    This approach leverages the rich API endpoints we already have instead of
    instrumenting every component individually.
    """
    
    def __init__(self, base_url: str = "http://localhost:80", update_interval: int = 30):
        self.base_url = base_url.rstrip('/')
        self.update_interval = update_interval
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        
    async def start(self):
        """Start the metrics integration service."""
        self.session = aiohttp.ClientSession()
        self.running = True
        logger.info(f"🚀 Starting Metrics Integration Service (interval: {self.update_interval}s)")
        
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
                    return await response.json()
                else:
                    logger.warning(f"Failed to fetch {endpoint}: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error fetching {endpoint}: {e}")
            return None
    
    async def _update_all_metrics(self):
        """Update all metrics from API endpoints."""
        logger.debug("📊 Updating metrics from API endpoints...")
        
        # Fetch data from all endpoints concurrently
        tasks = [
            self._fetch_endpoint("/energy/gradient"),
            self._fetch_endpoint("/agents/state"),
            self._fetch_endpoint("/system/status"),
            self._fetch_endpoint("/energy/monitor")
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        energy_data = results[0] if not isinstance(results[0], Exception) else None
        agents_data = results[1] if not isinstance(results[1], Exception) else None
        system_data = results[2] if not isinstance(results[2], Exception) else None
        energy_monitor_data = results[3] if not isinstance(results[3], Exception) else None
        
        # Update metrics
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

async def start_metrics_integration(base_url: str = "http://localhost:80", update_interval: int = 30):
    """Start the global metrics integration service."""
    global _metrics_service
    
    if _metrics_service is None:
        _metrics_service = MetricsIntegrationService(base_url, update_interval)
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