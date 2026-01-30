#!/usr/bin/env python3
"""
Reachy Tools
=============
HAL adapter tools that bridge SeedCore tool calls to the HAL FastAPI service.

These tools expose:
- reachy.motion: Control robot motion (head, antennas, body_yaw)
- reachy.get_state: Get current robot state

The tools call the HAL service via FastAPI, which handles both physical hardware
and simulation. The HAL layer abstracts away the underlying implementation
(gRPC simulation or physical SDK).

All security and capability checks happen at the SeedCore layer above.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, List
import httpx  # pyright: ignore[reportMissingImports]

from .base import ToolBase
from .manager import ToolError

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.tools.query_tools")
logger = ensure_serve_logger("seedcore.tools.query_tools", level="DEBUG")



class ReachyMotionTool(ToolBase):
    """
    Tool for controlling robot motion via the HAL FastAPI service.
    
    Maps to: HAL /actuate endpoint
    """
    
    name = "reachy.motion"
    description = "Control robot motion (head pose, antennas, body yaw) via HAL service"
    
    def __init__(self, hal_base_url: Optional[str] = None):
        """
        Initialize the motion tool.
        
        Args:
            hal_base_url: HAL service base URL
                Defaults to HAL_BASE_URL env var or http://seedcore-hal-bridge:8001 (K8s service)
        """
        super().__init__()
        # Priority: parameter -> env var HAL_BASE_URL -> K8s service default
        self._hal_base_url = (
            hal_base_url 
            or os.getenv("HAL_BASE_URL") 
            or "http://seedcore-hal-bridge:8001"  # Kubernetes service name (default for K8s)
        )
        self._client: Optional[httpx.AsyncClient] = None
        
    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._hal_base_url,
                timeout=30.0,
            )
        return self._client
    
    def schema(self) -> Dict[str, Any]:
        """Return tool schema for LLM planning."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "head": {
                        "type": "object",
                        "description": "Head pose dictionary with keys: x, y, z, yaw, pitch, roll (all floats)",
                        "additionalProperties": {"type": "number"}
                    },
                    "antennas": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Antenna angles [left, right] in radians",
                        "minItems": 2,
                        "maxItems": 2
                    },
                    "body_yaw": {
                        "type": "number",
                        "description": "Body yaw angle in radians"
                    },
                    "duration": {
                        "type": "number",
                        "description": "Motion duration in seconds",
                        "default": 0.5
                    }
                }
            },
            "required": []
        }
    
    async def run(
        self,
        head: Optional[Dict[str, float]] = None,
        antennas: Optional[List[float]] = None,
        body_yaw: Optional[float] = None,
        duration: float = 0.5,
        instant: bool = False,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Execute motion command via HAL service.
        
        Args:
            head: Optional head pose dict (x, y, z, yaw, pitch, roll)
            antennas: Optional antenna angles [left, right] in radians
            body_yaw: Optional body yaw angle in radians
            duration: Motion duration in seconds (default: 0.5)
            instant: If True, use high-frequency instant motion (default: False)
        
        Returns:
            Dict with status information
        """
        try:
            client = await self._ensure_client()
            
            # Build target dict for HAL /actuate endpoint
            target: Dict[str, Any] = {}
            if head:
                target["head"] = head
            if antennas is not None:
                target["antennas"] = antennas
            if body_yaw is not None:
                target["body_yaw"] = body_yaw
            
            # Determine pose_type (default to "head" if head is provided)
            pose_type = "head"
            if "body_yaw" in target:
                pose_type = "body"
            elif "antennas" in target:
                pose_type = "antennas"
            
            # Call HAL /actuate endpoint
            response = await client.post(
                "/actuate",
                json={
                    "pose_type": pose_type,
                    "target": target,
                    "instant": instant,
                }
            )
            response.raise_for_status()
            
            result = response.json()
            
            return {
                "status": result.get("status", "success"),
                "robot_state": result.get("robot_state"),
                "head": head,
                "antennas": antennas,
                "body_yaw": body_yaw,
                "duration": duration
            }
            
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = e.response.text or str(e)
            
            logger.error(f"HTTP error in {self.name}: {e.response.status_code} - {error_detail}", exc_info=True)
            raise ToolError(self.name, f"HAL service error: {e.response.status_code} - {error_detail}", e)
        except httpx.RequestError as e:
            logger.error(f"Request error in {self.name}: {e}", exc_info=True)
            raise ToolError(self.name, f"HAL service unreachable: {e}", e)
        except Exception as e:
            logger.error(f"Error in {self.name}: {e}", exc_info=True)
            raise ToolError(self.name, str(e), e)


class ReachyGetStateTool(ToolBase):
    """
    Tool for getting current robot state from the HAL FastAPI service.
    
    Maps to: HAL /state endpoint
    """
    
    name = "reachy.get_state"
    description = "Get current robot state (head pose, antennas, body yaw) from HAL service"
    
    def __init__(self, hal_base_url: Optional[str] = None):
        """
        Initialize the get_state tool.
        
        Args:
            hal_base_url: HAL service base URL
                Defaults to HAL_BASE_URL env var or http://seedcore-hal-bridge:8001 (K8s service)
        """
        super().__init__()
        # Priority: parameter -> env var HAL_BASE_URL -> K8s service default
        self._hal_base_url = (
            hal_base_url 
            or os.getenv("HAL_BASE_URL") 
            or "http://seedcore-hal-bridge:8001"  # Kubernetes service name (default for K8s)
        )
        self._client: Optional[httpx.AsyncClient] = None
        
    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._hal_base_url,
                timeout=30.0,
            )
        return self._client
    
    def schema(self) -> Dict[str, Any]:
        """Return tool schema for LLM planning."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {}
            },
            "required": []
        }
    
    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """
        Get current robot state from HAL service.
        
        Returns:
            Dict with robot state (head, antennas, body_yaw)
        """
        try:
            client = await self._ensure_client()
            
            # Call HAL /state endpoint
            response = await client.get("/state")
            response.raise_for_status()
            
            result = response.json()
            
            return result
            
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = e.response.text or str(e)
            
            logger.error(f"HTTP error in {self.name}: {e.response.status_code} - {error_detail}", exc_info=True)
            raise ToolError(self.name, f"HAL service error: {e.response.status_code} - {error_detail}", e)
        except httpx.RequestError as e:
            logger.error(f"Request error in {self.name}: {e}", exc_info=True)
            raise ToolError(self.name, f"HAL service unreachable: {e}", e)
        except Exception as e:
            logger.error(f"Error in {self.name}: {e}", exc_info=True)
            raise ToolError(self.name, str(e), e)


# ============================================================
# Registration Helper
# ============================================================

async def register_reachy_tools(tool_manager: Any, hal_base_url: Optional[str] = None) -> bool:
    """
    Register Reachy tools with ToolManager.
    
    These tools call the HAL FastAPI service, which handles both physical
    hardware and simulation based on HAL_DRIVER_MODE configuration.
    
    Args:
        tool_manager: ToolManager instance (or ToolManagerShard actor)
        hal_base_url: Optional HAL service base URL
            Defaults to HAL_BASE_URL env var or http://seedcore-hal-bridge:8001 (K8s service)
    
    Returns:
        True if tools were registered successfully, False otherwise
    """
    try:
        # Get HAL base URL: parameter -> env var -> K8s service default
        base_url = (
            hal_base_url 
            or os.getenv("HAL_BASE_URL") 
            or "http://seedcore-hal-bridge:8001"  # Kubernetes service name
        )
        
        # Create tool instances
        motion_tool = ReachyMotionTool(hal_base_url=base_url)
        get_state_tool = ReachyGetStateTool(hal_base_url=base_url)
        
        # Register tools
        # Handle both ToolManager instance and ToolManagerShard actor
        if hasattr(tool_manager, "register_internal"):
            # Direct ToolManager instance - use register_internal for consistency
            await tool_manager.register_internal(motion_tool)
            await tool_manager.register_internal(get_state_tool)
        elif hasattr(tool_manager, "register_reachy_tools"):
            # ToolManagerShard actor (remote) - use dedicated method
            result = await tool_manager.register_reachy_tools.remote(hal_base_url=base_url)
            return bool(result)
        elif hasattr(tool_manager, "register"):
            # Fallback: use register method
            await tool_manager.register("reachy.motion", motion_tool)
            await tool_manager.register("reachy.get_state", get_state_tool)
        else:
            logger.warning("⚠️ Unknown tool_manager type, cannot register Reachy tools")
            return False
        
        logger.info(f"✅ Registered Reachy tools: reachy.motion, reachy.get_state (HAL: {base_url})")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to register Reachy tools: {e}", exc_info=True)
        return False
