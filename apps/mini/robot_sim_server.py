import time
import grpc
from concurrent import futures
from dataclasses import dataclass

import robot_sim_pb2
import robot_sim_pb2_grpc


@dataclass
class SimState:
    head: dict
    antennas: list
    body_yaw: float


STATE = SimState(
    head={"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0},
    antennas=[0.0, 0.0],
    body_yaw=0.0,
)


class RobotSimServicer(robot_sim_pb2_grpc.RobotSimServicer):

    def GetState(self, request, context):
        return robot_sim_pb2.RobotState(
            head=STATE.head,
            antennas=STATE.antennas,
            body_yaw=STATE.body_yaw,
        )

    def Goto(self, request, context):
        # ✅ FIX: map fields have NO presence in proto3
        if request.head:
            STATE.head.update(request.head)

        if len(request.antennas) > 0:
            STATE.antennas = list(request.antennas)

        # Scalars always exist; use sentinel logic if needed
        STATE.body_yaw = request.body_yaw

        print("🧠 Sim state updated:", STATE)

        # Simulate blocking motion
        time.sleep(request.duration)

        return robot_sim_pb2.Ack(ok=True)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    robot_sim_pb2_grpc.add_RobotSimServicer_to_server(
        RobotSimServicer(), server
    )
    server.add_insecure_port("[::]:50055")
    server.start()
    print("🤖 RobotSim gRPC server listening on :50055")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
