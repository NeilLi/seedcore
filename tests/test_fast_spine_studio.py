"""Exercise the actual localhost API, authority boundary and independent watchdog."""

import time

from fastapi.testclient import TestClient
import pytest

from seedcore.robotics.fast_spine.studio import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client


@pytest.mark.parametrize(
    "case", ["out_of_bounds", "expired", "forged", "wrong_endpoint"]
)
def test_negative_proposals_never_open_a_controller(client, case):
    response = client.post("/api/spine-demo/start", json={"case": case, "joints": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["decision"]["status"] == "denied"
    assert data["decision"]["dispatched_commands"] == 0
    assert "session" not in data
    assert client.get("/api/spine-demo/evidence").status_code == 409


@pytest.mark.parametrize("joints", [1, 3])
def test_browser_loss_stops_without_another_request(client, joints):
    started = client.post("/api/spine-demo/start", json={"joints": joints}).json()
    assert started["session"]["state"] == "active"
    time.sleep(0.35)
    stopped = client.get("/api/spine-demo/state").json()
    assert stopped["session"]["reason"] == "stale_command"
    assert len(stopped["session"]["positions_rad"]) == joints
    assert stopped["verification"]["verified"] is True
    evidence = client.get("/api/spine-demo/evidence").json()
    assert evidence["python_verification"]["physical_acceptance"] is False
    # The browser receives public provenance, never host signing/channel secrets.
    serialized = str(evidence)
    assert "private_key" not in serialized and "channel_key" not in serialized
    assert (
        evidence["trust_bundle"]["trusted_keys"]["simulation-receipt-host"][
            "trust_anchor_type"
        ]
        == "host_simulation"
    )
    assert client.post("/api/spine-demo/refresh").status_code == 409


@pytest.mark.parametrize(
    "operation,reason", [("revoke", "revoked"), ("stop", "local_stop")]
)
def test_operator_controls_fence_the_attempt(client, operation, reason):
    client.post("/api/spine-demo/start", json={})
    stopped = client.post(f"/api/spine-demo/{operation}").json()
    assert stopped["session"]["reason"] == reason
    assert stopped["session"]["queued_points"] == 0
    assert stopped["verification"]["verified"]


def test_repeated_browser_refresh_cannot_extend_deadline(client):
    client.post("/api/spine-demo/start", json={})
    for _ in range(11):
        time.sleep(0.1)
        response = client.post("/api/spine-demo/refresh")
        assert response.status_code in {200, 409}
    stopped = client.get("/api/spine-demo/state").json()
    assert stopped["session"]["reason"] == "session_deadline"
    assert stopped["verification"]["verified"]


def test_immediate_browser_refresh_does_not_append_a_tiny_spline_interval(client):
    started = client.post("/api/spine-demo/start", json={}).json()
    assert started["decision"]["dispatched_commands"] == 1
    for _ in range(10):
        response = client.post("/api/spine-demo/refresh")
        assert response.status_code == 200
        assert response.json()["session"]["state"] == "active"


def test_reject_remote_origins_and_unknown_body_fields(client):
    assert (
        client.post(
            "/api/spine-demo/start",
            json={},
            headers={"Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/spine-demo/start", json={}, headers={"Host": "untrusted.example"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/spine-demo/start", json={"hardware": True}).status_code == 422
    )
    page = client.get("/studio/session-lab.html")
    assert page.status_code == 200
    assert "Simulation only" in page.text
