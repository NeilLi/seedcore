# tools.py
from typing import Any, Dict, List

from transformers.utils import get_json_schema  # pyright: ignore[reportMissingImports]

# ---------------------------------------------------------------------
# Tuya tools (model-facing only)
# These are NOT runtime implementations.
# They exist purely to define tool schemas for the LLM.
# ---------------------------------------------------------------------

def tuya_send_command(
    device_id: str,
    commands: List[Dict[str, Any]],
):
    """
    Send one or more DP commands to a Tuya IoT device.

    Args:
        device_id: Tuya device ID
        commands: List of DP commands, each with:
            - code: DP code string (e.g. "switch_led")
            - value: DP value (bool, number, string, etc.)
    """
    pass


def tuya_get_status(device_id: str):
    """
    Get the current status of a Tuya IoT device.

    Args:
        device_id: Tuya device ID
    """
    pass


# ---------------------------------------------------------------------
# Build JSON schemas
# ---------------------------------------------------------------------

tuya_send_command_schema = get_json_schema(tuya_send_command)
tuya_get_status_schema = get_json_schema(tuya_get_status)

# Override function names to match SeedCore + dataset
tuya_send_command_schema["function"]["name"] = "tuya.send_command"
tuya_get_status_schema["function"]["name"] = "tuya.get_status"

# Strengthen schema for commands (important for training quality)
tuya_send_command_schema["function"]["parameters"] = {
    "type": "object",
    "properties": {
        "device_id": {
            "type": "string",
            "description": "Tuya device ID",
        },
        "commands": {
            "type": "array",
            "description": "List of Tuya DP commands",
            "items": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Tuya DP code",
                    },
                    "value": {
                        "description": "DP value (bool, number, string, etc.)",
                    },
                },
                "required": ["code", "value"],
            },
        },
    },
    "required": ["device_id", "commands"],
}

tuya_get_status_schema["function"]["parameters"] = {
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
# Tool registry exposed to the model
# ---------------------------------------------------------------------

TOOLS = [
    tuya_send_command_schema,
    tuya_get_status_schema,
]
