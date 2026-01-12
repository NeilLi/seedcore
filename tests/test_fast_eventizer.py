import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import pytest

from seedcore.ops.eventizer.fast_eventizer import (
    load_pattern_pack,
    FastEventizer,
)
from seedcore.models.eventizer import EventType, RouteDecision


FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "fast_eventizer_patterns.json",
)


@pytest.fixture(scope="module")
def fast_eventizer():
    pack = load_pattern_pack(FIXTURE_PATH)
    return FastEventizer(pack)


def test_pack_loads_correctly():
    pack = load_pattern_pack(FIXTURE_PATH)
    assert pack.pack_id == "fast-core"
    assert pack.pack_version == "1.0.0"
    assert pack.fallback_event_type.value == "routine"
    assert pack.checksum is not None
    assert len(pack.patterns) == 1


def test_emergency_detection(fast_eventizer):
    text = "There is a fire in the lobby, please help!"
    resp = fast_eventizer.process_text(
        normalized_text=text.lower(),
        original_text=text,
    )

    assert EventType.EMERGENCY in resp.event_tags.hard_tags
    assert resp.event_tags.priority == 10
    assert resp.decision_kind == RouteDecision.FAST
    assert resp.confidence.overall_confidence >= 0.9
    assert resp.confidence.needs_ml_fallback is False


def test_early_exit_applied(fast_eventizer):
    text = "fire fire fire fire"
    resp = fast_eventizer.process_text(
        normalized_text=text,
        original_text=text,
    )

    # Only one pattern applied due to early_exit
    assert resp.patterns_applied == 1


def test_fallback_event_type(fast_eventizer):
    text = "just a normal request about towels"
    resp = fast_eventizer.process_text(
        normalized_text=text,
        original_text=text,
    )

    assert resp.event_tags.hard_tags[0].value == "routine"
    assert resp.confidence.needs_ml_fallback is True


def test_pii_detection_luhn_valid(fast_eventizer):
    text = "My card is 4111 1111 1111 1111"
    resp = fast_eventizer.process_text(
        normalized_text=text,
        original_text=text,
        enable_pii_detection=True,
    )

    assert resp.pii_detected.get("possible_cc") is True
    assert resp.pii_redacted is False  # FastEventizer never redacts


def test_pii_detection_luhn_invalid(fast_eventizer):
    text = "Fake number 1234 5678 9012 3456"
    resp = fast_eventizer.process_text(
        normalized_text=text,
        original_text=text,
        enable_pii_detection=True,
    )

    assert resp.pii_detected.get("possible_cc") is False
