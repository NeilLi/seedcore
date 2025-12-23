#!/usr/bin/env python
# seedcore/tools/tuya/tuya_tools.py

"""
Tuya tools for SeedCore ToolManager.

Each tool represents a single, explicit intent and is compatible with:
- TaskPayload v2
- RBAC enforcement
- ToolHandler discovery
- LLM tool planning
"""

from __future__ import annotations

from typing import Dict, Any, List

from seedcore.tools.base import ToolBase
from seedcore.logging_setup import ensure_serve_logger

from .tuya_client import TuyaClient

logger = ensure_serve_logger("seedcore.tools.tuya", level="INFO")


# ---------------------------------------------------------------------
# Read-only tool
# ---------------------------------------------------------------------

class TuyaGetStatusTool(ToolBase):
    """
    Tool: tuya.get_status

    Fetch current status of a Tuya IoT device.
    """

    name = "tuya.get_status"
    description = "Get current status of a Tuya IoT device"

    async def run(self, *, device_id: str) -> Dict[str, Any]:
        if not device_id:
            raise ValueError("device_id is required")

        logger.info("Querying Tuya device status: %s", device_id)

        async with TuyaClient() as client:
            resp = await client.get_device_status(device_id)

        return {
            "device_id": device_id,
            "status": resp,
        }

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Tuya device ID",
                }
            },
            "required": ["device_id"],
        }


# ---------------------------------------------------------------------
# Mutating tool
# ---------------------------------------------------------------------

class TuyaSendCommandTool(ToolBase):
    """
    Tool: tuya.send_command

    Send one or more DP commands to a Tuya IoT device.
    """

    name = "tuya.send_command"
    description = "Send control commands to a Tuya IoT device"

    async def run(
        self,
        *,
        device_id: str,
        commands: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not device_id:
            raise ValueError("device_id is required")

        if not commands or not isinstance(commands, list):
            raise ValueError("commands must be a non-empty list")

        for cmd in commands:
            if not isinstance(cmd, dict):
                raise ValueError("each command must be a dict")
            if "code" not in cmd or "value" not in cmd:
                raise ValueError("each command must include 'code' and 'value'")

        logger.info(
            "Sending Tuya commands to device %s: %s",
            device_id,
            commands,
        )

        async with TuyaClient() as client:
            resp = await client.send_commands(
                device_id,
                commands=commands,
            )

        return {
            "device_id": device_id,
            "commands": commands,
            "tuya_response": resp,
        }

    def schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Tuya device ID",
                },
                "commands": {
                    "type": "array",
                    "description": "Tuya DP command list",
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
            "required": ["device_id", "commands"],
        }
