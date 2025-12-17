#!/usr/bin/env python
# seedcore/tools/tuya/tuya_device_tool.py

"""
Tuya Device Tool for SeedCore ToolManager.

This tool provides integration with Tuya IoT devices, allowing agents
to control and query Tuya-compatible smart devices through the Tuya OpenAPI.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import logging

from .tuya_client import TuyaClient

logger = logging.getLogger(__name__)


class TuyaDeviceTool:
    """
    Tool for controlling Tuya devices (virtual or physical).
    
    Implements the Tool protocol for integration with SeedCore's ToolManager.
    Supports device control (set commands) and status queries.
    """

    def __init__(self, client: TuyaClient):
        """
        Initialize Tuya device tool.
        
        Args:
            client: TuyaClient instance for API communication
        """
        self.client = client

    @property
    def name(self) -> str:
        return "iot.tuya.device"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Control or query a Tuya IoT device",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Tuya device ID",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["set", "get_status"],
                    },
                    "commands": {
                        "type": "array",
                        "description": "Tuya DP commands",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "value": {},
                            },
                            "required": ["code", "value"],
                        },
                    },
                },
                "required": ["device_id", "action"],
            },
        }

    async def execute(
        self,
        device_id: str,
        action: str,
        commands: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a Tuya device action.
        
        Args:
            device_id: Tuya device ID
            action: Action to perform ("set" or "get_status")
            commands: List of command dictionaries (required for "set" action)
                Each command should have "code" (str) and "value" (any) keys.
                Example: [{"code": "switch_led", "value": True}]
                
        Returns:
            Response dictionary from Tuya API
            
        Raises:
            ValueError: If action is invalid or commands are missing for "set"
            httpx.HTTPStatusError: If the API request fails
        """
        if not device_id:
            raise ValueError("device_id is required")
        
        if action == "get_status":
            logger.info(f"Getting status for Tuya device: {device_id}")
            return await self.client.get_status(device_id)

        if action == "set":
            if not commands:
                raise ValueError("commands required for action=set")
            if not isinstance(commands, list):
                raise ValueError("commands must be a list")
            # Validate command structure
            for cmd in commands:
                if not isinstance(cmd, dict):
                    raise ValueError(f"Each command must be a dict, got {type(cmd)}")
                if "code" not in cmd:
                    raise ValueError("Each command must have a 'code' key")
                if "value" not in cmd:
                    raise ValueError("Each command must have a 'value' key")
            
            logger.info(f"Sending commands to Tuya device {device_id}: {commands}")
            return await self.client.send_command(device_id, commands)

        raise ValueError(f"Unknown action: {action}. Must be 'set' or 'get_status'")
