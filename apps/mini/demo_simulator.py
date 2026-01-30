import time
import grpc
import numpy as np

import robot_sim_pb2
import robot_sim_pb2_grpc


channel = grpc.insecure_channel("localhost:50055")
robot = robot_sim_pb2_grpc.RobotSimStub(channel)


def smooth_move(duration=0.5, head=None, antennas=None, body_yaw=None):
    cmd = robot_sim_pb2.MotionCommand(duration=duration)

    if head:
        cmd.head.update(head)   # ✅ FIXED
    if antennas is not None:
        cmd.antennas.extend(antennas)
    if body_yaw is not None:
        cmd.body_yaw = body_yaw

    robot.Goto(cmd)
    time.sleep(0.15)


print("✅ Connected to custom robot simulation!")

# 1) Greeting
smooth_move(
    head={"z": 20, "roll": 10},
    duration=1.0
)

# 2) Antennas
smooth_move(antennas=np.deg2rad([45, -45]), duration=0.4)
smooth_move(antennas=np.deg2rad([-45, 45]), duration=0.4)
smooth_move(antennas=[0.0, 0.0], duration=0.5)

# 3) Body rotation
smooth_move(body_yaw=np.deg2rad(30), duration=1.0)
smooth_move(body_yaw=np.deg2rad(-30), duration=1.0)
smooth_move(body_yaw=0.0, duration=0.8)

# 4) Nodding
for _ in range(2):
    smooth_move(head={"z": 15, "pitch": -10}, duration=0.4)
    smooth_move(head={"z": 15, "pitch": 10}, duration=0.4)

# 5) Scan
for yaw in [10, -10, 0]:
    smooth_move(head={"yaw": yaw}, duration=0.8)

# 6) Happy antennas
smooth_move(antennas=np.deg2rad([60, 60]), duration=0.5)
smooth_move(antennas=[0.0, 0.0], duration=1.0)

print("🎉 Demo finished!")
