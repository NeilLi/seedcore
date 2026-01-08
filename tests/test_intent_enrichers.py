import os
import sys

# Add project root and src to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))
sys.path.insert(0, project_root)

import pytest
from unittest.mock import MagicMock

from seedcore.coordinator.core.intent.enrichers import IntentEnricher
from seedcore.coordinator.core.intent.model import (
    RoutingIntent,
    IntentSource,
    IntentConfidence,
)
from seedcore.agents.roles import Specialization


@pytest.fixture
def intent_instance():
    """Create a real RoutingIntent instance."""
    return RoutingIntent(
        specialization="generalist",
        skills={"test_skill": 0.5},
        source=IntentSource.COORDINATOR_BASELINE,
        confidence=IntentConfidence.MEDIUM,
    )


@pytest.fixture
def ctx():
    """Minimal TaskContext stub for synthesize_baseline tests."""
    ctx = MagicMock()
    ctx.attributes = {}
    ctx.domain = None
    ctx.task_type = "action"
    return ctx


# -------------------------
# synthesize_baseline tests
# -------------------------


def test_synthesize_baseline_from_service_hint(ctx):
    """Test that synthesize_baseline maps service hints to specializations."""
    ctx.attributes = {"required_service": "guest_request"}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert isinstance(intent, RoutingIntent)
    assert intent.specialization == Specialization.USER_LIAISON.value
    assert intent.source == IntentSource.COORDINATOR_BASELINE
    assert intent.confidence == IntentConfidence.MEDIUM


def test_synthesize_baseline_from_domain_device(ctx):
    """Test domain-based fallback for device domain."""
    ctx.domain = "device"
    ctx.attributes = {}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.specialization == Specialization.DEVICE_ORCHESTRATOR.value


def test_synthesize_baseline_from_domain_robot(ctx):
    """Test domain-based fallback for robot domain."""
    ctx.domain = "robot"
    ctx.attributes = {}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.specialization == Specialization.ROBOT_COORDINATOR.value


def test_synthesize_baseline_from_task_type_chat(ctx):
    """Test task_type-based fallback for chat tasks."""
    ctx.task_type = "chat"
    ctx.domain = None
    ctx.attributes = {}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.specialization == Specialization.USER_LIAISON.value


def test_synthesize_baseline_fallback_to_generalist(ctx):
    """Test that synthesize_baseline falls back to GENERALIST."""
    ctx.domain = None
    ctx.task_type = "unknown"
    ctx.attributes = {}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.specialization == Specialization.GENERALIST.value


def test_synthesize_baseline_includes_required_skills(ctx):
    """Test that synthesize_baseline includes required_skills from attributes."""
    ctx.attributes = {
        "required_service": "hvac_service",
        "required_skills": {"temperature_control": 0.8},
    }

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.skills == {"temperature_control": 0.8}


def test_synthesize_baseline_empty_skills_when_none(ctx):
    """Test that synthesize_baseline uses empty dict when no required_skills."""
    ctx.attributes = {"required_service": "guest_request"}

    intent = IntentEnricher.synthesize_baseline(ctx)

    assert intent.skills == {}


# -------------------------
# enrich tests
# -------------------------


def test_enrich_returns_same_object_when_no_semantic_context(intent_instance):
    """Test that enrich returns the same object when semantic_context is None."""
    ctx = object()

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=None)

    assert enriched is intent_instance


def test_enrich_returns_same_object_when_empty_semantic_context(intent_instance):
    """Test that enrich returns the same object when semantic_context is empty."""
    ctx = object()

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=[])

    assert enriched is intent_instance


def test_enrich_returns_same_object_when_low_similarity(intent_instance):
    """Test that enrich returns unchanged intent when similarity is low."""
    ctx = object()
    semantic_context = [
        {
            "similarity": 0.5,  # Below 0.95 threshold
            "metadata": {"intended_specialization": "different_spec"},
        }
    ]

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=semantic_context)

    assert enriched is intent_instance
    assert enriched.specialization == "generalist"  # Unchanged


def test_enrich_updates_specialization_when_high_similarity_different_spec(intent_instance):
    """Test that enrich updates specialization when similarity > 0.95 and spec differs."""
    ctx = object()
    semantic_context = [
        {
            "similarity": 0.97,  # Above 0.95 threshold
            "metadata": {"intended_specialization": "user_liaison"},
        }
    ]

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=semantic_context)

    assert enriched is not intent_instance  # Should be a copy
    assert enriched.specialization == "user_liaison"
    assert enriched.confidence == IntentConfidence.HIGH


def test_enrich_keeps_same_specialization_when_high_similarity_same_spec(intent_instance):
    """Test that enrich keeps specialization when similarity > 0.95 but spec matches."""
    ctx = object()
    semantic_context = [
        {
            "similarity": 0.97,
            "metadata": {"intended_specialization": "generalist"},  # Same as intent
        }
    ]

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=semantic_context)

    # Should still update confidence to HIGH even if spec matches
    assert enriched.confidence == IntentConfidence.HIGH


def test_enrich_handles_missing_metadata(intent_instance):
    """Test that enrich handles semantic_context with missing metadata gracefully."""
    ctx = object()
    semantic_context = [
        {
            "similarity": 0.97,
            # Missing metadata field
        }
    ]

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=semantic_context)

    # Should return unchanged when metadata is missing
    assert enriched is intent_instance


def test_enrich_handles_missing_intended_specialization(intent_instance):
    """Test that enrich handles missing intended_specialization in metadata."""
    ctx = object()
    semantic_context = [
        {
            "similarity": 0.97,
            "metadata": {},  # Empty metadata
        }
    ]

    enriched = IntentEnricher.enrich(intent_instance, ctx, semantic_context=semantic_context)

    # Should return unchanged when intended_specialization is missing
    assert enriched is intent_instance
