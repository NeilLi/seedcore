# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Apache License, Version 2.0 (the "License");
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Organism Serve Client for SeedCore

This module provides a client interface to communicate with the organism
deployed as a Ray Serve application, replacing the old plain Ray actor approach.

The client handles:
- HTTP requests to the organism Serve endpoints
- Fallback to direct Serve handle calls when possible
- Proper error handling and retries
- Integration with existing task processing workflows
"""

import os
import logging
import time
import asyncio
from typing import Dict, Any, Optional, Union
import requests
from urllib.parse import urljoin

import ray
from ray import serve

logger = logging.getLogger(__name__)

class OrganismServeClient:
    """
    Client for communicating with the organism deployed as a Ray Serve application.
    
    This replaces the old plain Ray actor approach and provides:
    - HTTP endpoint access for external clients
    - Direct Serve handle access for internal Ray operations
    - Proper error handling and health checking
    - Fallback mechanisms for reliability
    """
    
    def __init__(self, 
                 base_url: str = None,
                 serve_app_name: str = "organism",
                 namespace: str = None):
        """
        Initialize the organism serve client.
        
        Args:
            base_url: Base URL for HTTP endpoints (e.g., "http://localhost:8000")
            serve_app_name: Name of the Serve application
            namespace: Ray namespace for direct Serve handle access
        """
        self.base_url = base_url or os.getenv("ORGANISM_BASE_URL", "http://localhost:8000")
        self.serve_app_name = serve_app_name
        self.namespace = namespace or os.getenv("RAY_NAMESPACE", "seedcore-dev")
        
        # Health check endpoint
        self.health_url = urljoin(self.base_url, f"/{serve_app_name}/health")
        
        # Task handling endpoint
        self.handle_task_url = urljoin(self.base_url, f"/{serve_app_name}/handle-task")
        
        # Status endpoints
        self.status_url = urljoin(self.base_url, f"/{serve_app_name}/status")
        self.organism_status_url = urljoin(self.base_url, f"/{serve_app_name}/organism-status")
        self.organism_summary_url = urljoin(self.base_url, f"/{serve_app_name}/organism-summary")
        
        # Serve handle for direct access (when available)
        self._serve_handle = None
        self._serve_handle_available = False
        
        # Initialize Serve handle if possible
        self._init_serve_handle()
    
    def _init_serve_handle(self):
        """Initialize the Serve handle for direct access if possible."""
        try:
            # Try to get the Serve handle
            self._serve_handle = serve.get_app_handle(self.serve_app_name)
            self._serve_handle_available = True
            logger.info(f"✅ Serve handle available for {self.serve_app_name}")
        except Exception as e:
            logger.warning(f"⚠️ Serve handle not available: {e}")
            self._serve_handle_available = False
            self._serve_handle = None
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the organism service.
        
        Returns:
            Health status dictionary
        """
        try:
            response = requests.get(self.health_url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "organism_initialized": False
            }
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get the detailed status of the organism service.
        
        Returns:
            Status dictionary
        """
        try:
            response = requests.get(self.status_url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Status check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "organism_initialized": False
            }
    
    async def handle_incoming_task(self, 
                                 task: Dict[str, Any], 
                                 app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Handle an incoming task through the organism service.
        
        This is the main method that replaces the old plain Ray actor task handling.
        
        Args:
            task: Task dictionary with type, params, description, domain, drift_score
            app_state: Optional application state
            
        Returns:
            Task result dictionary
        """
        # Try Serve handle first (faster, internal)
        if self._serve_handle_available and self._serve_handle:
            try:
                logger.debug("🔄 Using Serve handle for task handling")
                result = await self._serve_handle.handle_incoming_task.remote(task, app_state)
                return result
            except Exception as e:
                logger.warning(f"⚠️ Serve handle failed, falling back to HTTP: {e}")
                self._serve_handle_available = False
        
        # Fallback to HTTP endpoint
        try:
            logger.debug("🌐 Using HTTP endpoint for task handling")
            payload = {
                "task_type": task.get("type", ""),
                "params": task.get("params", {}),
                "description": task.get("description", ""),
                "domain": task.get("domain", "general"),
                "drift_score": task.get("drift_score", 0.0),
                "app_state": app_state or {}
            }
            
            response = requests.post(self.handle_task_url, json=payload, timeout=30.0)
            response.raise_for_status()
            result = response.json()
            
            # Check if the result indicates success
            if not result.get("success", True):
                logger.error(f"❌ Task handling failed: {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ HTTP task handling failed: {e}")
            return {
                "success": False,
                "error": f"Task handling failed: {str(e)}",
                "task_type": task.get("type", "unknown")
            }
    
    async def make_decision(self, 
                           task: Dict[str, Any], 
                           app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a decision through the organism service.
        
        Args:
            task: Task dictionary
            app_state: Optional application state
            
        Returns:
            Decision result dictionary
        """
        # Try Serve handle first
        if self._serve_handle_available and self._serve_handle:
            try:
                result = await self._serve_handle.make_decision.remote(task, app_state)
                return result
            except Exception as e:
                logger.warning(f"⚠️ Serve handle failed for decision: {e}")
        
        # Fallback: use handle_incoming_task with decision task type
        decision_task = {
            "type": "make_decision",
            "params": task,
            "description": "Decision making request",
            "domain": "decision",
            "drift_score": 0.0
        }
        return await self.handle_incoming_task(decision_task, app_state)
    
    async def plan_task(self, 
                       task: Dict[str, Any], 
                       app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Plan a task through the organism service.
        
        Args:
            task: Task dictionary
            app_state: Optional application state
            
        Returns:
            Planning result dictionary
        """
        # Try Serve handle first
        if self._serve_handle_available and self._serve_handle:
            try:
                result = await self._serve_handle.plan_task.remote(task, app_state)
                return result
            except Exception as e:
                logger.warning(f"⚠️ Serve handle failed for planning: {e}")
        
        # Fallback: use handle_incoming_task with planning task type
        planning_task = {
            "type": "plan_task",
            "params": task,
            "description": "Task planning request",
            "domain": "planning",
            "drift_score": 0.0
        }
        return await self.handle_incoming_task(planning_task, app_state)
    
    async def get_organism_status(self) -> Dict[str, Any]:
        """
        Get detailed status of all organs in the organism.
        
        Returns:
            Organism status dictionary
        """
        try:
            response = requests.get(self.organism_status_url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Organism status check failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_organism_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the organism's current state.
        
        Returns:
            Organism summary dictionary
        """
        try:
            response = requests.get(self.organism_summary_url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Organism summary check failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def wait_for_ready(self, timeout: float = 60.0) -> bool:
        """
        Wait for the organism service to be ready.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if ready, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                status = await self.get_status()
                if status.get("status") == "healthy" and status.get("organism_initialized"):
                    logger.info("✅ Organism service is ready")
                    return True
                elif status.get("status") == "initializing":
                    logger.info("⏳ Organism service still initializing, waiting...")
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"⚠️ Organism service status: {status}")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"⚠️ Waiting for organism service: {e}")
                await asyncio.sleep(2)
        
        logger.error(f"❌ Organism service not ready after {timeout} seconds")
        return False
    
    def is_available(self) -> bool:
        """
        Check if the organism service is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            # Quick health check
            response = requests.get(self.health_url, timeout=2.0)
            return response.status_code == 200
        except:
            return False


# Global instance for backward compatibility
organism_client: Optional[OrganismServeClient] = None

def get_organism_client() -> OrganismServeClient:
    """
    Get the global organism client instance.
    
    Returns:
        OrganismServeClient instance
    """
    global organism_client
    if organism_client is None:
        organism_client = OrganismServeClient()
    return organism_client
