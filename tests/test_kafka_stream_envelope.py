from seedcore.infra.kafka.envelope import STREAM_ENVELOPE_SCHEMA_VERSION, build_stream_envelope
from seedcore.infra.kafka.topics import ALL_STREAM_TOPICS_V1, TOPIC_POLICY_OUTCOME_V1


def test_build_stream_envelope_shape():
    env = build_stream_envelope({"x": 1}, producer="test")
    assert env["schema_version"] == STREAM_ENVELOPE_SCHEMA_VERSION
    assert env["producer"] == "test"
    assert env["payload"] == {"x": 1}
    assert "event_id" in env and env["event_id"]
    assert "occurred_at" in env and env["occurred_at"]


def test_topic_constants():
    assert TOPIC_POLICY_OUTCOME_V1 == "seedcore.policy_outcome.v1"
    assert len(ALL_STREAM_TOPICS_V1) == 3
