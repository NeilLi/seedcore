"""Canonical topic names for SeedCore streams (Phase 1 schedule)."""

TOPIC_INTENT_V1 = "seedcore.intent.v1"
TOPIC_TELEMETRY_V1 = "seedcore.telemetry.v1"
TOPIC_POLICY_OUTCOME_V1 = "seedcore.policy_outcome.v1"

ALL_STREAM_TOPICS_V1: tuple[str, ...] = (
    TOPIC_INTENT_V1,
    TOPIC_TELEMETRY_V1,
    TOPIC_POLICY_OUTCOME_V1,
)
