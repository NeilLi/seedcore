import time
import os
import sys
import logging
import numpy as np
from reachy_mini import ReachyMini
from reachy_mini.utils import create_head_pose

# ----------------------------
# Noise suppression / buffers
# ----------------------------
logging.getLogger("reachy_mini.media.audio_base").setLevel(logging.ERROR)

class AudioDeviceFilter(logging.Filter):
    def filter(self, record):
        return "Reachy Mini Audio USB device" not in record.getMessage()

logging.getLogger().addFilter(AudioDeviceFilter())

os.environ.setdefault("FFREPORT", "file=/dev/null:level=error")
os.environ.setdefault("UDP_FIFO_SIZE", "10485760")

class StderrFilter:
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
    def write(self, message):
        if "Circular buffer overrun" not in message:
            self.original_stderr.write(message)
    def flush(self):
        self.original_stderr.flush()

sys.stderr = StderrFilter(sys.stderr)

# ----------------------------
# Demo
# ----------------------------
with ReachyMini() as mini:
    print("Connected to simulation!")

    # ---- Core motion helpers ----
    BUFFER_PAUSE = 0.15

    def pose(duration=0.6, sleep_after=True, **kwargs):
        """Single buffered motion command."""
        mini.goto_target(duration=duration, **kwargs)
        if sleep_after:
            time.sleep(BUFFER_PAUSE)

    def hold(t=0.3):
        """Hold current pose briefly."""
        time.sleep(t)

    def sequence(steps):
        """Run a list of (kwargs, duration, hold_time) tuples."""
        for kwargs, dur, h in steps:
            pose(duration=dur, **kwargs)
            if h:
                hold(h)

    def rad(deg_left, deg_right=None):
        """Convenience: degrees -> radians for antennas or yaw."""
        if deg_right is None:
            return np.deg2rad(deg_left)
        return np.deg2rad([deg_left, deg_right])

    # ---- Emotion presets (only using head/body/antennas) ----
    def emo_happy():
        # Up + slight roll, antennas up
        sequence([
            (dict(head=create_head_pose(z=22, roll=10, pitch=-5, mm=True, degrees=True),
                  antennas=rad(55, 55)), 0.6, 0.2),
            (dict(antennas=rad(65, 65)), 0.35, 0.2),
            (dict(antennas=rad(55, 55)), 0.35, 0.1),
        ])

    def emo_sad():
        # Head down + antennas droop
        sequence([
            (dict(head=create_head_pose(z=10, pitch=18, roll=0, mm=True, degrees=True),
                  antennas=rad(-25, -25),
                  body_yaw=rad(0)), 0.8, 0.4),
        ])

    def emo_surprised():
        # Quick snap up + antennas pop
        sequence([
            (dict(head=create_head_pose(z=26, pitch=-12, roll=0, mm=True, degrees=True),
                  antennas=rad(70, 70)), 0.35, 0.15),
            (dict(head=create_head_pose(z=22, pitch=-6, roll=0, mm=True, degrees=True),
                  antennas=rad(60, 60)), 0.45, 0.2),
        ])

    def emo_confused():
        # Tilt + look left/right + antennas asymmetry
        sequence([
            (dict(head=create_head_pose(z=18, roll=14, yaw=8, mm=True, degrees=True),
                  antennas=rad(35, -10)), 0.55, 0.15),
            (dict(head=create_head_pose(z=18, roll=-14, yaw=-8, mm=True, degrees=True),
                  antennas=rad(-10, 35)), 0.55, 0.15),
            (dict(antennas=rad(0, 0)), 0.5, 0.05),
        ])

    def emo_excited():
        # Quick bouncy head + antenna wiggle
        for _ in range(2):
            pose(head=create_head_pose(z=24, pitch=-10, mm=True, degrees=True),
                 antennas=rad(60, 20), duration=0.25)
            pose(head=create_head_pose(z=18, pitch=6, mm=True, degrees=True),
                 antennas=rad(20, 60), duration=0.25)
        pose(antennas=rad(55, 55), duration=0.35)

    # ---- Dance moves ----
    def dance_head_bob_groove(beats=8, yaw_amp=10, pitch_up=-10, pitch_down=10):
        """Beat-based head bob with slight yaw alternation."""
        for i in range(beats):
            y = yaw_amp if (i % 2 == 0) else -yaw_amp
            pose(head=create_head_pose(z=18, pitch=pitch_up, yaw=y, mm=True, degrees=True),
                 duration=0.25)
            pose(head=create_head_pose(z=16, pitch=pitch_down, yaw=-y, mm=True, degrees=True),
                 duration=0.25)

    def dance_body_sway(beats=8, amp=25):
        """Body yaw sway left/right like dancing."""
        for i in range(beats):
            angle = amp if (i % 2 == 0) else -amp
            pose(body_yaw=rad(angle), duration=0.35, sleep_after=False)
            time.sleep(0.10)  # small beat hold, different than BUFFER_PAUSE
        pose(body_yaw=rad(0), duration=0.6)

    def dance_antenna_wave(beats=10, amp=55):
        """Alternating antenna wave."""
        for i in range(beats):
            if i % 2 == 0:
                pose(antennas=rad(amp, -amp), duration=0.22)
            else:
                pose(antennas=rad(-amp, amp), duration=0.22)
        pose(antennas=rad(0, 0), duration=0.5)

    def dance_spin_and_dip():
        """A little spin then a dip (safe, playful)."""
        sequence([
            (dict(body_yaw=rad(40), antennas=rad(40, 40)), 0.5, 0.05),
            (dict(body_yaw=rad(-40), antennas=rad(55, 20)), 0.5, 0.05),
            (dict(body_yaw=rad(0)), 0.4, 0.05),
            (dict(head=create_head_pose(z=10, pitch=16, roll=8, mm=True, degrees=True),
                  antennas=rad(-15, -15)), 0.6, 0.2),
            (dict(head=create_head_pose(z=20, pitch=-6, roll=0, mm=True, degrees=True),
                  antennas=rad(45, 45)), 0.6, 0.15),
        ])

    def dance_finale():
        """Big finish: excited + sway + antenna wave + happy pose."""
        emo_excited()
        dance_body_sway(beats=6, amp=30)
        dance_antenna_wave(beats=12, amp=60)
        emo_happy()

    # ---- Tiny idle/breathing style motion (adds life) ----
    def micro_breathe(cycles=3):
        """Subtle head z oscillation (breathing vibe)."""
        for _ in range(cycles):
            pose(head=create_head_pose(z=17, pitch=2, mm=True, degrees=True), duration=0.7)
            pose(head=create_head_pose(z=15, pitch=4, mm=True, degrees=True), duration=0.7)

    # ============================
    # Scripted show starts here
    # ============================

    print("Greeting pose...")
    pose(head=create_head_pose(z=20, roll=10, mm=True, degrees=True), duration=1.0)

    print("Expressive antennas...")
    sequence([
        (dict(antennas=rad(45, -45)), 0.4, 0.05),
        (dict(antennas=rad(-45, 45)), 0.4, 0.05),
        (dict(antennas=rad(0, 0)), 0.5, 0.10),
    ])

    print("Turning body to look around...")
    sequence([
        (dict(body_yaw=rad(30)), 1.0, 0.25),
        (dict(body_yaw=rad(-30)), 1.0, 0.25),
        (dict(body_yaw=rad(0)), 0.8, 0.10),
    ])

    print("Nodding head...")
    for _ in range(2):
        pose(head=create_head_pose(x=0, z=15, pitch=-10, degrees=True, mm=True), duration=0.4)
        pose(head=create_head_pose(x=0, z=15, pitch=10, degrees=True, mm=True), duration=0.4)

    print("Scanning environment...")
    for p in [
        create_head_pose(x=10, z=10, yaw=10, degrees=True, mm=True),
        create_head_pose(x=-10, z=10, yaw=-10, degrees=True, mm=True),
        create_head_pose(x=0, z=0, yaw=0, degrees=True, mm=True),
    ]:
        pose(head=p, duration=0.8)

    print("Adding 'alive' micro-breathe...")
    micro_breathe(cycles=2)

    # ---- Emotions showcase ----
    print("Emotion: Happy")
    emo_happy()
    hold(0.3)

    print("Emotion: Surprised")
    emo_surprised()
    hold(0.25)

    print("Emotion: Confused")
    emo_confused()
    hold(0.25)

    print("Emotion: Sad (brief)")
    emo_sad()
    hold(0.35)

    print("Back to excited!")
    emo_excited()
    hold(0.25)

    # ---- Dance segment ----
    print("Dance: head-bob groove")
    dance_head_bob_groove(beats=10)

    print("Dance: antenna wave")
    dance_antenna_wave(beats=14)

    print("Dance: body sway")
    dance_body_sway(beats=10, amp=28)

    print("Dance: spin + dip")
    dance_spin_and_dip()

    print("Dance: finale")
    dance_finale()

    # ---- Reset ----
    print("Returning to rest position...")
    pose(
        head=create_head_pose(),
        antennas=[0, 0],
        body_yaw=0,
        duration=1.0
    )

    print("Demo finished!")
