import time
import os
import sys
import logging
import numpy as np
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

# Configure logging to suppress audio device warnings (they're non-critical)
# The library will fall back to default audio devices
logging.getLogger("reachy_mini.media.audio_base").setLevel(logging.ERROR)

# Add a custom filter to suppress the specific audio device error from root logger
class AudioDeviceFilter(logging.Filter):
    """Filter to suppress audio device not found errors."""
    def filter(self, record):
        return "Reachy Mini Audio USB device" not in record.getMessage()

# Apply filter to root logger to suppress audio device errors
logging.getLogger().addFilter(AudioDeviceFilter())

# Configure UDP buffer settings to prevent overrun warnings
# These environment variables help ffmpeg handle UDP streams better
os.environ.setdefault("FFREPORT", "file=/dev/null:level=error")  # Suppress ffmpeg reports
# Increase UDP buffer size for better handling of video streams
os.environ.setdefault("UDP_FIFO_SIZE", "10485760")  # 10MB buffer

# Filter stderr to suppress UDP buffer overrun warnings from ffmpeg
# This warning is non-critical and doesn't affect functionality
class StderrFilter:
    """Filter to suppress UDP buffer overrun warnings from ffmpeg."""
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
    
    def write(self, message):
        # Suppress UDP buffer overrun warnings
        if "Circular buffer overrun" not in message:
            self.original_stderr.write(message)
    
    def flush(self):
        self.original_stderr.flush()

# Apply the filter to stderr
sys.stderr = StderrFilter(sys.stderr)

# Connects to the simulation running on localhost
with ReachyMini() as mini:
    print("Connected to simulation!")
    
    # Helper function for smooth, buffer-friendly motion
    # Adds a small pause after each command to prevent UDP buffer overruns
    def smooth_move(**kwargs):
        """Execute a motion command with a small buffer pause afterward."""
        mini.goto_target(**kwargs)
        time.sleep(0.15)  # Small pause to prevent UDP buffer overruns
    
    # 1) Initial greeting: tilt head up
    print("Greeting pose...")
    smooth_move(
        head=create_head_pose(z=20, roll=10, mm=True, degrees=True),
        duration=1.0
    )

    # 2) Wiggle antennas with a bit more flair
    print("Expressive antennas...")
    smooth_move(antennas=np.deg2rad([45, -45]), duration=0.4)
    smooth_move(antennas=np.deg2rad([-45, 45]), duration=0.4)
    smooth_move(antennas=[0, 0], duration=0.5)

    # 3) Body rotation to look left and right
    print("Turning body to look around...")
    smooth_move(body_yaw=np.deg2rad(30), duration=1.0)
    time.sleep(0.3)  # Hold position briefly
    smooth_move(body_yaw=np.deg2rad(-30), duration=1.0)
    time.sleep(0.3)  # Hold position briefly
    smooth_move(body_yaw=0, duration=0.8)

    # 4) Simple “nodding” action
    print("Nodding head...")
    for _ in range(2):
        smooth_move(
            head=create_head_pose(x=0, z=15, pitch=-10, degrees=True, mm=True),
            duration=0.4,
        )
        smooth_move(
            head=create_head_pose(x=0, z=15, pitch=10, degrees=True, mm=True),
            duration=0.4,
        )

    # 5) Look around (up/down, left/right) casual scan
    print("Scanning environment...")
    scan_positions = [
        create_head_pose(x=10, z=10, yaw=10, degrees=True, mm=True),
        create_head_pose(x=-10, z=10, yaw=-10, degrees=True, mm=True),
        create_head_pose(x=0, z=0, yaw=0, degrees=True, mm=True),
    ]
    for pose in scan_positions:
        smooth_move(head=pose, duration=0.8)

    # 6) Cool pose with antennas “happy”
    print("Happy antennas!")
    smooth_move(antennas=np.deg2rad([60, 60]), duration=0.5)
    time.sleep(0.5)  # Hold happy pose
    smooth_move(antennas=[0, 0], duration=1.0)

    # 7) Reset to rest position (batched for efficiency)
    print("Returning to rest position...")
    smooth_move(
        head=create_head_pose(),
        antennas=[0, 0],
        body_yaw=0,
        duration=1.0
    )

    print("Demo finished!")
