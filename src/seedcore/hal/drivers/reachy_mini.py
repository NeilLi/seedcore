"""
Reachy Mini Robot Driver
========================
SDK-specific implementation for the Reachy Mini robot.
Maps SeedCore behavior_config (Energy/Warmth) to physical actuation.
"""

import os
import logging
import time
from typing import Dict, Any, Optional, List
import numpy as np

from ..interfaces import (
    BaseRobotDriver,
    RobotState,
    RobotCapabilities,
    ProprioceptionState,
)

logger = logging.getLogger(__name__)

# Try-except block for safe SDK imports in headless or simulation environments
try:
    from reachy_mini import ReachyMini  # pyright: ignore[reportMissingImports]
    from reachy_mini.utils import create_head_pose  # pyright: ignore[reportMissingImports]

    REACHY_AVAILABLE = True
except ImportError:
    REACHY_AVAILABLE = False
    logger.warning("reachy_mini SDK not available. Running in Mock/Sim mode.")


class ReachyMiniDriver(BaseRobotDriver):
    """
    SeedCore Driver for Reachy Mini.
    Implements the 'Physical-Actuation' contract for hotel simulator scenarios.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Args:
            config: Mapped from SeedCore behavior_config.
                - 'host': Robot IP (e.g., 192.168.1.5)
                - 'energy': 0-100 (maps to motion duration)
                - 'warmth': 0-100 (maps to interpolation method)
        """
        super().__init__(config)
        self._robot: Optional[ReachyMini] = None
        # Read from config, then environment variable, then default
        self._host = self.config.get("host") or os.getenv("ROBOT_HOST", "localhost")
        self._last_frame: Optional[np.ndarray] = None

    def _initialize_capabilities(self) -> RobotCapabilities:
        """Defines Reachy Mini hardware limits."""
        return RobotCapabilities(
            has_arms=False,
            has_head=True,
            has_base=False,
            has_camera=True,
            has_microphone=True,
            supported_pose_types=["head", "antennas", "body_yaw"],
        )

    # --- Lifecycle & Safety ---

    def connect(self) -> bool:
        """Establishes network connection to Reachy Mini daemon."""
        if not REACHY_AVAILABLE:
            self._state = RobotState.ERROR
            return False
        try:
            # SDK auto-detects connection mode based on host
            self._robot = ReachyMini(host=self._host)
            self._state = RobotState.CONNECTED
            logger.info(f"Reachy Mini connected at {self._host}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._state = RobotState.ERROR
            return False

    def disconnect(self) -> None:
        """Disconnect from robot gracefully."""
        if self._robot:
            try:
                # ReachyMini context manager handles cleanup
                if hasattr(self._robot, '__exit__'):
                    pass  # Context manager handles cleanup
                else:
                    self._robot = None
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._robot = None
        
        self._state = RobotState.DISCONNECTED
        logger.info("Disconnected from Reachy Mini")
    
    def emergency_stop(self) -> None:
        """Immediate hardware stop."""
        if self._robot:
            # Bypass interpolation for immediate freeze
            self._robot.set_target(head=create_head_pose(), antennas=[0, 0], body_yaw=0)
            self._state = RobotState.EMERGENCY_STOP
            logger.warning("SAFETY: Emergency stop triggered.")
    
    def get_current_pose(self, pose_type: str = "head") -> Dict[str, Any]:
        """
        Get current pose of robot component.
        
        Args:
            pose_type: "head", "antennas", or "body"
            
        Returns:
            Pose dictionary
        """
        if not self._robot:
            raise RuntimeError("Robot not connected")
        
        if pose_type == "head":
            # Reachy Mini SDK doesn't expose current head pose directly
            # Return a placeholder structure
            return {
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0
            }
        elif pose_type == "antennas":
            return {"left": 0.0, "right": 0.0}
        elif pose_type == "body":
            return {"yaw": 0.0}
        else:
            raise ValueError(f"Unsupported pose_type: {pose_type}")

    # --- Behavioral Mapping (The Magic) ---

    def _get_duration(self, base_s: float = 1.0) -> float:
        """Maps 'Energy' slider to duration. Energy 100 = 0.3s (Hyper)."""
        energy = self.config.get("energy", 50)
        # Inversely proportional: High energy = Low duration
        multiplier = 2.0 - (energy / 100.0) * 1.7
        return base_s * multiplier

    def _get_method(self) -> str:
        """Maps 'Warmth' slider to interpolation. Warmth 80 = 'minjerk'."""
        warmth = self.config.get("warmth", 50)
        if warmth >= 75:
            return "minjerk"  # Smooth, organic
        if warmth >= 40:
            return "ease"  # Natural
        return "linear"  # Direct, mechanical

    # --- Motion Execution ---

    def move_instant(
        self,
        target: Dict[str, Any],
        pose_type: str = "head",
        **kwargs
    ) -> None:
        """High-frequency VLA token control (20Hz)."""
        if not self._robot:
            raise RuntimeError("Robot not connected")
        
        if self._state != RobotState.CONNECTED:
            raise RuntimeError(f"Robot not ready (state: {self._state.value})")
        
        try:
            self._robot.set_target(
                head=target.get("head"),
                antennas=target.get("antennas"),
                body_yaw=target.get("body_yaw"),
                **kwargs
            )
            self._state = RobotState.MOVING
        except Exception as e:
            logger.error(f"Error in instant move: {e}")
            self._state = RobotState.ERROR
            raise

    def move_smooth(
        self,
        target: Dict[str, Any],
        duration: Optional[float] = None,
        pose_type: str = "head",
        method: str = "minjerk",
        **kwargs
    ) -> bool:
        """Smooth movement for high-level tasks (e.g., 'Snack & Sip Scout')."""
        if not self._robot:
            return False

        target_duration = duration if duration else self._get_duration()
        motion_method = method if method != "minjerk" else self._get_method()

        try:
            self._robot.goto_target(
                head=target.get("head"),
                antennas=target.get("antennas"),
                body_yaw=target.get("body_yaw"),
                duration=target_duration,
                method=motion_method,
                **kwargs
            )
            self._state = RobotState.MOVING
            return True
        except Exception as e:
            logger.error(f"Motion error: {e}")
            self._state = RobotState.ERROR
            return False
    
    def move_to_pose(
        self,
        pose: Dict[str, Any],
        pose_type: str = "head",
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Move to target pose (legacy method, delegates to move_smooth).
        """
        return self.move_smooth(pose, duration=duration, pose_type=pose_type, **kwargs)
    
    def move_joints(
        self,
        joints: List[float],
        arm_id: Optional[str] = None,
        duration: Optional[float] = None,
        **kwargs
    ) -> bool:
        """
        Move joints. Not applicable for Reachy Mini (no arms).
        
        Raises:
            NotImplementedError: Reachy Mini has no arms
        """
        raise NotImplementedError("Reachy Mini has no articulated arms")
    
    def is_moving(self) -> bool:
        """Check if robot is moving."""
        return self._state == RobotState.MOVING
    
    def wait_for_motion_complete(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for motion to complete.
        
        Note: Reachy Mini SDK doesn't expose motion completion callbacks,
        so we use a simple sleep-based approach.
        """
        if not self.is_moving():
            return True
        
        # Simple timeout-based wait
        if timeout:
            time.sleep(min(timeout, 0.1))
        else:
            time.sleep(0.1)
        
        # Assume motion completes quickly (Reachy Mini motions are typically < 2s)
        self._state = RobotState.CONNECTED
        return True

    # --- Multimodal & Proprioception (The Pulse) ---

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Captures frame for 'params.multimodal' envelope."""
        if not self._robot:
            raise RuntimeError("Robot not connected")
        
        # TODO: Implement actual camera frame retrieval from Reachy Mini SDK
        # For now, return None or cached frame
        # Example (if SDK provides it):
        #   return self._robot.camera.get_latest_frame()
        
        return self._last_frame
    
    def play_audio(
        self,
        samples: np.ndarray,
        samplerate: int = 44100,
        **kwargs
    ) -> None:
        """
        Stream audio samples to robot speakers.
        
        Note: Reachy Mini SDK may provide audio playback through a separate
        media module. This is a placeholder implementation.
        """
        if not self._robot:
            raise RuntimeError("Robot not connected")
        
        if not self._capabilities.has_microphone:
            raise RuntimeError("Robot has no audio output capability")
        
        # Validate samples format
        if samples.ndim not in (1, 2):
            raise ValueError(f"Invalid samples shape: {samples.shape}. Expected 1D or 2D array")
        
        # TODO: Implement actual audio playback from Reachy Mini SDK
        # For now, log the request
        logger.debug(
            f"Audio playback requested: shape={samples.shape}, "
            f"samplerate={samplerate}, duration={len(samples)/samplerate:.2f}s"
        )
        
        # Example (if SDK provides it):
        #   self._robot.audio.play(samples, samplerate=samplerate, **kwargs)

    def get_proprioception(self) -> ProprioceptionState:
        """Streams real-time joint and IMU data back to SeedCore."""
        if not self._robot:
            return None

        imu = self._robot.imu
        return ProprioceptionState(
            joint_positions=self._robot.get_current_angles(),  # Custom SDK helper
            ee_pose=self.get_current_pose("head"),
            imu_data=imu,
            is_moving=self.is_moving(),
            timestamp=time.time(),
        )
