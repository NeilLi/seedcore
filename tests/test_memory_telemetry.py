"""Unit tests for seedcore.memory.telemetry helpers."""

from __future__ import annotations

import pytest

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.memory.telemetry import (
    incident_memory_stats_dict,
    semantic_memory_stats_dict,
    working_memory_stats_dict,
)


@pytest.mark.asyncio
async def test_working_memory_stats_unavailable_without_manager():
    d = await working_memory_stats_dict(None)
    assert d["status"] == "unavailable"
    assert "mw_manager" in d.get("reason", "")


@pytest.mark.asyncio
async def test_semantic_memory_stats_unavailable_without_service():
    d = await semantic_memory_stats_dict(None)
    assert d["status"] == "unavailable"


@pytest.mark.asyncio
async def test_incident_memory_not_configured_without_service():
    d = await incident_memory_stats_dict(None)
    assert d["reason"] == "incident_memory_not_configured"
