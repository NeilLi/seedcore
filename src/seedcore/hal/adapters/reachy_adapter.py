"""
Reachy Mini HAL Adapter
=======================
Translates SeedCore TaskPayload JSON into Reachy Mini SDK formats.
Handles coordinate conversion (mm to m), degree-to-radian mapping,
and pose serialization.
"""

import numpy as np
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class ReachyAdapter:
    """
    Adapter to convert SeedCore-standardized JSON to Reachy SDK objects.
    Ensures 'params.tool_calls' map correctly to Physical-Actuation.
    """

    @staticmethod
    def to_radians(degrees: float) -> float:
        """Helper to convert UI degrees to SDK radians."""
        return np.deg2rad(degrees)

    @classmethod
    def transform_head_pose(cls, seedcore_pose: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts SeedCore head pose to SDK 'create_head_pose' args.
        Handles the 'mm' and 'degrees' flags from the UI sliders.
        """
        return {
            "z": seedcore_pose.get("z", 0.0),
            "roll": seedcore_pose.get("roll", 0.0),
            "pitch": seedcore_pose.get("pitch", 0.0),
            "yaw": seedcore_pose.get("yaw", 0.0),
            "mm": seedcore_pose.get("use_mm", True),
            "degrees": seedcore_pose.get("use_degrees", True)
        }

    @classmethod
    def transform_antennas(cls, seedcore_antennas: List[float]) -> np.ndarray:
        """
        Converts antenna degrees [left, right] to radians for the SDK.
        """
        return np.deg2rad(seedcore_antennas)

    @classmethod
    def transform_body_yaw(cls, seedcore_yaw: float) -> float:
        """Converts body yaw degrees to radians."""
        return cls.to_radians(seedcore_yaw)

    @classmethod
    def pack_proprioception(cls, raw_state: Any) -> Dict[str, Any]:
        """
        Serializes raw SDK IMU/Joint data into the 'params.multimodal' format.
        This allows the Gemini AI Architect to 'feel' the robot's state.
        """
        return {
            "accelerometer": {
                "x": raw_state.get("accelerometer", [0,0,0])[0],
                "y": raw_state.get("accelerometer", [0,0,0])[1],
                "z": raw_state.get("accelerometer", [0,0,0])[2]
            },
            "quaternion": list(raw_state.get("quaternion", [1,0,0,0])),
            "temperature": raw_state.get("temperature", 0.0)
        }