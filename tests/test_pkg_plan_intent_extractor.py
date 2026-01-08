import os
import sys

# Add project root and src to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "src"))
sys.path.insert(0, project_root)

import pytest
from unittest.mock import MagicMock

from seedcore.coordinator.core.intent.extractors import PKGPlanIntentExtractor
from seedcore.coordinator.core.intent.model import (
    RoutingIntent,
    IntentSource,
    IntentConfidence,
)


# -------------------------
# Fixtures
# -------------------------

@pytest.fixture
def ctx():
    """Minimal TaskContext stub."""
    ctx = MagicMock()
    ctx.task_id = "task-123"
    return ctx


# -------------------------
# Phase 0: Guard rails
# -------------------------

def test_extract_returns_none_for_empty_plan(ctx):
    """Test that extract returns None for empty or None proto_plan."""
    assert PKGPlanIntentExtractor.extract({}, ctx) is None
    assert PKGPlanIntentExtractor.extract(None, ctx) is None


def test_extract_returns_none_for_plan_without_routing(ctx):
    """Test that extract returns None when no routing hints are present."""
    proto_plan = {
        "steps": [],
        "version": "1.0",
    }
    
    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)
    
    assert intent is None


# -------------------------
# Phase 1: Top-level routing
# -------------------------

def test_extract_top_level_required_specialization(ctx):
    """Test extraction from top-level required_specialization."""
    proto_plan = {
        "routing": {
            "required_specialization": "vision",
            "skills": {"ocr": 0.9},
        }
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert isinstance(intent, RoutingIntent)
    assert intent.specialization == "vision"
    assert intent.skills == {"ocr": 0.9}
    assert intent.source == IntentSource.PKG_TOP_LEVEL
    assert intent.confidence == IntentConfidence.HIGH


def test_extract_top_level_specialization_fallback(ctx):
    """Test extraction from top-level specialization (fallback when required_specialization missing)."""
    proto_plan = {
        "routing": {
            "specialization": "nlp",
        }
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "nlp"
    assert intent.skills == {}
    assert intent.source == IntentSource.PKG_TOP_LEVEL
    assert intent.confidence == IntentConfidence.HIGH


def test_extract_top_level_required_specialization_takes_priority(ctx):
    """Test that required_specialization takes priority over specialization."""
    proto_plan = {
        "routing": {
            "required_specialization": "vision",
            "specialization": "nlp",  # Should be ignored
        }
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "vision"


# -------------------------
# Phase 2: Step-level routing
# -------------------------

def test_extract_step_level_routing(ctx):
    """Test extraction from first step's routing params."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "planning",
                            "skills": {"reasoning": 0.8},
                        }
                    }
                }
            }
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "planning"
    assert intent.skills == {"reasoning": 0.8}
    assert intent.source == IntentSource.PKG_STEP_EMBEDDED
    assert intent.confidence == IntentConfidence.MEDIUM


def test_extract_step_level_required_specialization_takes_priority(ctx):
    """Test that required_specialization in step takes priority over specialization."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "required_specialization": "math",
                            "specialization": "general",
                        }
                    }
                }
            }
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "math"
    assert intent.source == IntentSource.PKG_STEP_EMBEDDED


def test_extract_step_level_with_solution_steps_key(ctx):
    """Test that extract also checks solution_steps key (alternative to steps)."""
    proto_plan = {
        "solution_steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "planning",
                        }
                    }
                }
            }
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "planning"
    assert intent.source == IntentSource.PKG_STEP_EMBEDDED


def test_extract_step_level_handles_step_without_task_key(ctx):
    """Test that extract handles steps where the step itself is the task dict."""
    proto_plan = {
        "steps": [
            {
                "params": {
                    "routing": {
                        "specialization": "planning",
                    }
                }
            }
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "planning"
    assert intent.source == IntentSource.PKG_STEP_EMBEDDED


# -------------------------
# Phase 3: Aggregated routing
# -------------------------

def test_aggregated_routing_across_steps(ctx):
    """Test aggregation of routing hints across multiple steps."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "nlp",
                            "skills": {"summarization": 0.6},
                        }
                    }
                }
            },
            {
                "task": {
                    "params": {
                        "routing": {
                            "skills": {"summarization": 0.9, "translation": 0.7},
                        }
                    }
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "nlp"
    assert intent.skills == {
        "summarization": 0.9,  # max wins
        "translation": 0.7,
    }
    assert intent.source == IntentSource.PKG_AGGREGATED
    assert intent.confidence == IntentConfidence.MEDIUM


def test_aggregated_required_specialization_short_circuits(ctx):
    """Test that required_specialization in any step short-circuits aggregation."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "nlp",
                        }
                    }
                }
            },
            {
                "task": {
                    "params": {
                        "routing": {
                            "required_specialization": "vision",
                        }
                    }
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "vision"
    assert intent.source == IntentSource.PKG_AGGREGATED


def test_aggregated_skills_max_intensity_wins(ctx):
    """Test that aggregated skills use max intensity when same skill appears multiple times."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "nlp",
                            "skills": {"translation": 0.3, "summarization": 0.7},
                        }
                    }
                }
            },
            {
                "task": {
                    "params": {
                        "routing": {
                            "skills": {"translation": 0.9, "summarization": 0.5},
                        }
                    }
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.skills == {
        "translation": 0.9,  # max(0.3, 0.9)
        "summarization": 0.7,  # max(0.7, 0.5)
    }


def test_aggregated_handles_steps_without_routing(ctx):
    """Test that aggregation handles steps without routing params gracefully."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "nlp",
                        }
                    }
                }
            },
            {
                "task": {
                    "params": {},  # No routing
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "nlp"
    assert intent.source == IntentSource.PKG_AGGREGATED


def test_aggregated_returns_none_when_no_specialization_found(ctx):
    """Test that aggregation returns None when no specialization is found in any step."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "skills": {"summarization": 0.9},
                            # No specialization
                        }
                    }
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent is None


# -------------------------
# Priority ordering tests
# -------------------------

def test_top_level_takes_priority_over_steps(ctx):
    """Test that top-level routing takes priority over step-level routing."""
    proto_plan = {
        "routing": {
            "specialization": "top_level_spec",
        },
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "step_level_spec",
                        }
                    }
                }
            }
        ],
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "top_level_spec"
    assert intent.source == IntentSource.PKG_TOP_LEVEL


def test_step_level_takes_priority_over_aggregation(ctx):
    """Test that step-level routing takes priority over aggregation."""
    proto_plan = {
        "steps": [
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "first_step_spec",
                        }
                    }
                }
            },
            {
                "task": {
                    "params": {
                        "routing": {
                            "specialization": "second_step_spec",
                        }
                    }
                }
            },
        ]
    }

    intent = PKGPlanIntentExtractor.extract(proto_plan, ctx)

    assert intent.specialization == "first_step_spec"
    assert intent.source == IntentSource.PKG_STEP_EMBEDDED  # Not aggregated
