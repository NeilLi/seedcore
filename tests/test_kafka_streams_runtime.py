from __future__ import annotations

import json
import importlib
import sys
import types

import pytest

from scripts.kafka.smoke_kafka_streams import _matches_smoke_message


class _StubProducer:
    def __init__(self, conf: dict[str, object]):
        self.conf = conf

    def produce(self, **_: object) -> None:
        return None

    def poll(self, timeout: float) -> None:
        return None

    def flush(self, timeout: float) -> None:
        return None


fake_confluent = types.ModuleType("confluent_kafka")
fake_confluent.Producer = _StubProducer
sys.modules.setdefault("confluent_kafka", fake_confluent)

from seedcore.infra.kafka.producer import KafkaProducerBestEffort


class _FailingProducer:
    def produce(self, **_: object) -> None:
        raise RuntimeError("queue full")

    def poll(self, timeout: float) -> None:
        raise AssertionError(f"poll should not run after produce failure: {timeout}")


class _FakeConn:
    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, _query: object) -> None:
        return None


class _HealthyEngine:
    def connect(self) -> _FakeConn:
        return _FakeConn()


def _load_ready_check():
    fake_routers = types.ModuleType("seedcore.api.routers")
    fake_routers.get_active_routers = lambda: []

    original = sys.modules.get("seedcore.api.routers")
    sys.modules["seedcore.api.routers"] = fake_routers
    try:
        main_module = importlib.import_module("seedcore.main")
        main_module = importlib.reload(main_module)
        return main_module.app, main_module.ready_check
    finally:
        if original is None:
            sys.modules.pop("seedcore.api.routers", None)
        else:
            sys.modules["seedcore.api.routers"] = original


def test_best_effort_send_swallows_synchronous_produce_error(caplog: pytest.LogCaptureFixture) -> None:
    producer = KafkaProducerBestEffort.__new__(KafkaProducerBestEffort)
    producer._producer = _FailingProducer()

    with caplog.at_level("WARNING"):
        producer.send("seedcore.policy_outcome.v1", {"payload": {"x": 1}})

    assert "Kafka best-effort publish dropped before enqueue" in caplog.text


def test_smoke_helper_filters_out_stale_or_unrelated_messages() -> None:
    expected = {
        "payload": {
            "kind": "smoke",
            "topic": "seedcore.intent.v1",
            "suffix": "123",
        }
    }
    stale_suffix = {
        "payload": {
            "kind": "smoke",
            "topic": "seedcore.intent.v1",
            "suffix": "122",
        }
    }
    wrong_topic = {
        "payload": {
            "kind": "smoke",
            "topic": "seedcore.telemetry.v1",
            "suffix": "123",
        }
    }

    assert _matches_smoke_message(expected, topic="seedcore.intent.v1", suffix="123") is True
    assert _matches_smoke_message(stale_suffix, topic="seedcore.intent.v1", suffix="123") is False
    assert _matches_smoke_message(wrong_topic, topic="seedcore.intent.v1", suffix="123") is False
    assert _matches_smoke_message({"payload": "bad-shape"}, topic="seedcore.intent.v1", suffix="123") is False


@pytest.mark.asyncio
async def test_readyz_returns_503_when_kafka_gate_enabled_and_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    app, ready_check = _load_ready_check()
    app.state.db_engine = _HealthyEngine()
    monkeypatch.setenv("SEEDCORE_KAFKA_READYZ_CHECK", "1")
    monkeypatch.setattr("seedcore.infra.kafka.health.kafka_ping", lambda: False)

    response = await ready_check()

    assert response.status_code == 503
    body = json.loads(response.body.decode("utf-8"))
    assert body["status"] == "not_ready"
    assert body["deps"]["db"] == "ok"
    assert body["deps"]["kafka"] == "error: broker unreachable"
