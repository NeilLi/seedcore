"""
Motion Adapter
==============

Converts SeedCore task parameters (Energy, Warmth, etc.) into HAL driver
configuration parameters for motion control.

This adapter bridges the "Buddy Setup" UI parameters (Energy 65/100, Warmth 80/100)
to actual robot motion behavior.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class MotionAdapter:
    """
    Adapter for converting SeedCore motion parameters to HAL driver config.
    
    Handles conversion of:
    - Energy level (0-100) -> motion duration/speed
    - Warmth level (0-100) -> interpolation method/style
    - TaskPayload motion parameters -> driver-specific commands
    """
    
    @staticmethod
    def task_to_driver_config(
        task_params: Dict[str, Any],
        base_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extract driver configuration from TaskPayload params.
        
        Args:
            task_params: TaskPayload.params dictionary (or params.motion subdict)
            base_config: Optional base configuration to merge with
            
        Returns:
            Driver configuration dictionary with:
            - "energy": int (0-100) affecting motion speed
            - "warmth": int (0-100) affecting motion style
            - Other driver-specific parameters
            
        Example:
            >>> task_params = {
            ...     "motion": {"energy": 65, "warmth": 80},
            ...     "robot": {"host": "192.168.1.100"}
            ... }
            >>> config = MotionAdapter.task_to_driver_config(task_params)
            >>> # Returns: {"energy": 65, "warmth": 80, "host": "192.168.1.100"}
        """
        config = dict(base_config or {})
        
        # Extract motion parameters
        motion = task_params.get("motion", {})
        if not motion:
            # Try direct params
            motion = task_params
        
        # Energy level (0-100) - affects motion speed/duration
        # Higher energy = faster motion (lower duration)
        energy = motion.get("energy")
        if energy is not None:
            energy = max(0, min(100, int(energy)))  # Clamp to 0-100
            config["energy"] = energy
            logger.debug(f"Motion energy set to {energy}/100")
        
        # Warmth level (0-100) - affects motion style/interpolation
        # Higher warmth = smoother, more "warm" motion (minjerk/ease)
        # Lower warmth = more direct, "cool" motion (linear)
        warmth = motion.get("warmth")
        if warmth is not None:
            warmth = max(0, min(100, int(warmth)))  # Clamp to 0-100
            config["warmth"] = warmth
            logger.debug(f"Motion warmth set to {warmth}/100")
        
        # Robot-specific config (host, port, etc.)
        robot_config = task_params.get("robot", {})
        if robot_config:
            config.update(robot_config)
        
        return config
    
    @staticmethod
    def compute_duration(
        base_duration: float,
        energy: Optional[int] = None
    ) -> float:
        """
        Compute motion duration based on energy level.
        
        Args:
            base_duration: Base duration in seconds (at energy=50)
            energy: Energy level (0-100). If None, uses base_duration as-is
            
        Returns:
            Adjusted duration in seconds
            
        Formula:
            - Energy 0: duration = base_duration * 2.0 (slowest)
            - Energy 50: duration = base_duration * 1.0 (baseline)
            - Energy 100: duration = base_duration * 0.3 (fastest)
        """
        if energy is None:
            return base_duration
        
        energy = max(0, min(100, int(energy)))
        
        # Map energy 0-100 to multiplier 2.0 (slow) to 0.3 (fast)
        # Linear interpolation
        multiplier = 2.0 - (energy / 100.0) * 1.7
        
        return base_duration * multiplier
    
    @staticmethod
    def select_interpolation_method(
        warmth: Optional[int] = None,
        default: str = "minjerk"
    ) -> str:
        """
        Select interpolation method based on warmth level.
        
        Args:
            warmth: Warmth level (0-100). If None, returns default
            default: Default method if warmth not specified
            
        Returns:
            Interpolation method name ("minjerk", "ease", "linear")
            
        Mapping:
            - Warmth 70-100: "minjerk" (very smooth, warm)
            - Warmth 40-69: "ease" (moderate smoothness)
            - Warmth 0-39: "linear" (direct, less warm)
        """
        if warmth is None:
            return default
        
        warmth = max(0, min(100, int(warmth)))
        
        if warmth >= 70:
            return "minjerk"  # Very smooth, warm motion
        elif warmth >= 40:
            return "ease"  # Moderate smoothness
        else:
            return "linear"  # Direct, less warm
    
    @staticmethod
    def extract_motion_target(
        task_params: Dict[str, Any],
        pose_type: str = "head"
    ) -> Optional[Dict[str, Any]]:
        """
        Extract motion target from TaskPayload params.
        
        Args:
            task_params: TaskPayload.params dictionary
            pose_type: Type of pose to extract ("head", "arm", "base", etc.)
            
        Returns:
            Target pose dictionary, or None if not found
            
        Example:
            >>> task_params = {
            ...     "motion": {
            ...         "head": {"x": 10, "z": 20, "pitch": -10},
            ...         "antennas": [0.5, -0.5]
            ...     }
            ... }
            >>> target = MotionAdapter.extract_motion_target(task_params, "head")
            >>> # Returns: {"x": 10, "z": 20, "pitch": -10}
        """
        motion = task_params.get("motion", {})
        if not motion:
            return None
        
        return motion.get(pose_type)
