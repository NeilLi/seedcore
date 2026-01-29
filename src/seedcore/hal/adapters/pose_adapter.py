"""
Pose Adapter
============

Converts between SeedCore JSON pose representations and SDK-native types
(e.g., NumPy arrays, SDK pose objects).

Handles various pose formats:
- Head poses (6DOF: x, y, z, roll, pitch, yaw)
- Arm poses (joint angles or end-effector poses)
- Base poses (2D/3D position + orientation)
- Antenna/joint arrays
"""

import logging
from typing import Dict, Any, Optional, List, Union
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class PoseFormat(Enum):
    """Supported pose representation formats."""
    JSON_DICT = "json_dict"  # SeedCore JSON format
    NUMPY_ARRAY = "numpy_array"  # NumPy array format
    SDK_OBJECT = "sdk_object"  # SDK-specific object


class PoseAdapter:
    """
    Adapter for converting between pose representations.
    
    Converts SeedCore JSON task payloads to SDK-native types (NumPy arrays,
    SDK objects) and vice versa. This allows SeedCore to work with any robot
    SDK without modifying core logic.
    """
    
    @staticmethod
    def task_to_pose(
        task_params: Dict[str, Any],
        pose_type: str = "head",
        target_format: PoseFormat = PoseFormat.JSON_DICT
    ) -> Union[Dict[str, Any], np.ndarray, Any]:
        """
        Extract pose from TaskPayload params and convert to target format.
        
        Args:
            task_params: TaskPayload.params dictionary (or params.motion subdict)
            pose_type: Type of pose ("head", "arm", "base", "antennas")
            target_format: Desired output format
            
        Returns:
            Pose in the requested format:
            - JSON_DICT: {"x": float, "y": float, ...}
            - NUMPY_ARRAY: np.ndarray with pose data
            - SDK_OBJECT: SDK-specific object (if adapter supports it)
            
        Example:
            >>> task_params = {"motion": {"head": {"x": 10, "z": 20, "pitch": -10}}}
            >>> pose = PoseAdapter.task_to_pose(task_params, "head")
            >>> # Returns: {"x": 10, "y": 0, "z": 20, "roll": 0, "pitch": -10, "yaw": 0}
        """
        # Extract motion data from task params
        motion = task_params.get("motion", {})
        if not motion:
            # Try direct pose data
            motion = task_params
        
        # Get pose data for the requested type
        pose_data = motion.get(pose_type, {})
        
        if not pose_data:
            logger.warning(f"No {pose_type} pose data found in task params")
            return PoseAdapter._default_pose(pose_type, target_format)
        
        # Convert to target format
        if target_format == PoseFormat.JSON_DICT:
            return PoseAdapter._normalize_json_pose(pose_data, pose_type)
        elif target_format == PoseFormat.NUMPY_ARRAY:
            return PoseAdapter._json_to_numpy(pose_data, pose_type)
        elif target_format == PoseFormat.SDK_OBJECT:
            # SDK-specific conversion (implemented per SDK)
            return PoseAdapter._json_to_sdk_object(pose_data, pose_type)
        else:
            raise ValueError(f"Unsupported target_format: {target_format}")
    
    @staticmethod
    def numpy_to_json(pose_array: np.ndarray, pose_type: str = "head") -> Dict[str, Any]:
        """
        Convert NumPy array to SeedCore JSON format.
        
        Args:
            pose_array: NumPy array with pose data
            pose_type: Type of pose
            
        Returns:
            JSON dictionary with pose data
        """
        if pose_type == "head":
            # Expect 6DOF: [x, y, z, roll, pitch, yaw]
            if pose_array.shape[0] < 6:
                # Pad with zeros if needed
                padded = np.zeros(6)
                padded[:pose_array.shape[0]] = pose_array
                pose_array = padded
            
            return {
                "x": float(pose_array[0]),
                "y": float(pose_array[1]),
                "z": float(pose_array[2]),
                "roll": float(pose_array[3]),
                "pitch": float(pose_array[4]),
                "yaw": float(pose_array[5])
            }
        
        elif pose_type == "antennas":
            # Expect 2 values: [left, right]
            if pose_array.shape[0] < 2:
                pose_array = np.pad(pose_array, (0, 2 - pose_array.shape[0]))
            
            return {
                "antennas": [float(pose_array[0]), float(pose_array[1])]
            }
        
        elif pose_type == "base":
            # Expect 3 values: [x, y, theta]
            if pose_array.shape[0] < 3:
                pose_array = np.pad(pose_array, (0, 3 - pose_array.shape[0]))
            
            return {
                "x": float(pose_array[0]),
                "y": float(pose_array[1]),
                "theta": float(pose_array[2])
            }
        
        else:
            # Generic: return as list
            return {"values": pose_array.tolist()}
    
    @staticmethod
    def _normalize_json_pose(pose_data: Dict[str, Any], pose_type: str) -> Dict[str, Any]:
        """Normalize JSON pose to standard format."""
        if pose_type == "head":
            return {
                "x": float(pose_data.get("x", 0.0)),
                "y": float(pose_data.get("y", 0.0)),
                "z": float(pose_data.get("z", 0.0)),
                "roll": float(pose_data.get("roll", 0.0)),
                "pitch": float(pose_data.get("pitch", 0.0)),
                "yaw": float(pose_data.get("yaw", 0.0)),
                "mm": pose_data.get("mm", False),  # Preserve units flag
                "degrees": pose_data.get("degrees", False)  # Preserve angle units
            }
        
        elif pose_type == "antennas":
            if isinstance(pose_data, list):
                return {"antennas": [float(v) for v in pose_data]}
            return {"antennas": [float(pose_data.get("left", 0.0)), float(pose_data.get("right", 0.0))]}
        
        elif pose_type == "base":
            return {
                "x": float(pose_data.get("x", 0.0)),
                "y": float(pose_data.get("y", 0.0)),
                "theta": float(pose_data.get("theta", pose_data.get("yaw", 0.0)))
            }
        
        else:
            # Return as-is for unknown types
            return dict(pose_data)
    
    @staticmethod
    def _json_to_numpy(pose_data: Dict[str, Any], pose_type: str) -> np.ndarray:
        """Convert JSON pose to NumPy array."""
        if pose_type == "head":
            return np.array([
                float(pose_data.get("x", 0.0)),
                float(pose_data.get("y", 0.0)),
                float(pose_data.get("z", 0.0)),
                float(pose_data.get("roll", 0.0)),
                float(pose_data.get("pitch", 0.0)),
                float(pose_data.get("yaw", 0.0))
            ], dtype=np.float32)
        
        elif pose_type == "antennas":
            if isinstance(pose_data, list):
                return np.array(pose_data, dtype=np.float32)
            return np.array([
                float(pose_data.get("left", pose_data.get("antennas", [0, 0])[0])),
                float(pose_data.get("right", pose_data.get("antennas", [0, 0])[1]))
            ], dtype=np.float32)
        
        elif pose_type == "base":
            return np.array([
                float(pose_data.get("x", 0.0)),
                float(pose_data.get("y", 0.0)),
                float(pose_data.get("theta", pose_data.get("yaw", 0.0)))
            ], dtype=np.float32)
        
        else:
            # Try to extract numeric values
            values = [v for v in pose_data.values() if isinstance(v, (int, float))]
            return np.array(values, dtype=np.float32) if values else np.array([], dtype=np.float32)
    
    @staticmethod
    def _json_to_sdk_object(pose_data: Dict[str, Any], pose_type: str) -> Any:
        """
        Convert JSON to SDK-specific object.
        
        This is a placeholder. SDK-specific adapters should override this
        method to return SDK-native objects (e.g., ReachyMini pose objects).
        """
        # For now, return the JSON dict
        # SDK-specific drivers can convert further if needed
        return pose_data
    
    @staticmethod
    def _default_pose(pose_type: str, target_format: PoseFormat) -> Union[Dict[str, Any], np.ndarray]:
        """Return a default/zero pose."""
        if pose_type == "head":
            default_json = {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
        elif pose_type == "antennas":
            default_json = {"antennas": [0.0, 0.0]}
        elif pose_type == "base":
            default_json = {"x": 0.0, "y": 0.0, "theta": 0.0}
        else:
            default_json = {}
        
        if target_format == PoseFormat.JSON_DICT:
            return default_json
        elif target_format == PoseFormat.NUMPY_ARRAY:
            return PoseAdapter._json_to_numpy(default_json, pose_type)
        else:
            return default_json
