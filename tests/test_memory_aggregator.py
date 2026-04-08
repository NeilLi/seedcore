"""MemoryAggregator injection and semantic stats polling."""

from __future__ import annotations

import pytest

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.memory.contracts import (
    IncidentMemoryStats,
    MemoryHealth,
    MemorySubsystemStatus,
    SemanticMemoryStats,
)
from seedcore.ops.state.memory_aggregator import MemoryAggregator


class _FakeSemantic:
    async def stats_snapshot(self) -> SemanticMemoryStats:
        return SemanticMemoryStats(
            health=MemoryHealth(status=MemorySubsystemStatus.ENABLED),
            total_holons=7,
            total_relationships=3,
            bytes_used=4096,
        )

class _FakeIncident:
    async def stats_snapshot(self) -> IncidentMemoryStats:
        return IncidentMemoryStats(
            health=MemoryHealth(status=MemorySubsystemStatus.ENABLED),
            incidents_recorded=11,
        )


@pytest.mark.asyncio
async def test_memory_aggregator_poll_mlt_uses_injected_semantic():
    agg = MemoryAggregator(poll_interval=60.0, semantic_memory=_FakeSemantic())
    mlt = await agg._poll_mlt_stats()
    assert mlt["total_holons"] == 7
    assert mlt["total_relationships"] == 3
    assert mlt["bytes_used"] == 4096


@pytest.mark.asyncio
async def test_memory_aggregator_stop_does_not_close_injected_runtime(monkeypatch):
    closed: list[bool] = []

    class _RT:
        semantic = _FakeSemantic()

        async def close(self) -> None:
            closed.append(True)

    rt = _RT()
    agg = MemoryAggregator(memory_runtime=rt)
    await agg._get_semantic_memory()
    await agg.stop()
    assert closed == []


@pytest.mark.asyncio
async def test_memory_aggregator_stop_closes_lazy_runtime(monkeypatch):
    closed: list[bool] = []

    class _RT:
        semantic = _FakeSemantic()

        async def close(self) -> None:
            closed.append(True)

    rt = _RT()

    async def fake_connect(**kwargs):
        return rt

    monkeypatch.setattr(
        "seedcore.ops.state.memory_aggregator.connect_default_memory_runtime",
        fake_connect,
    )
    agg = MemoryAggregator()
    sem = await agg._get_semantic_memory()
    assert sem is rt.semantic
    await agg.stop()
    assert closed == [True]


@pytest.mark.asyncio
async def test_memory_aggregator_poll_mfb_uses_injected_incident():
    agg = MemoryAggregator(poll_interval=60.0, incident_memory=_FakeIncident())
    mfb = await agg._poll_mfb_stats()
    assert mfb["status"] == "enabled"
    assert mfb["incidents"] == 11
    assert mfb["total_events"] == 11


@pytest.mark.asyncio
async def test_memory_aggregator_poll_mfb_uses_runtime_incident():
    class _RT:
        semantic = _FakeSemantic()
        incident = _FakeIncident()

        async def close(self) -> None:
            return None

    agg = MemoryAggregator(memory_runtime=_RT())
    mfb = await agg._poll_mfb_stats()
    assert mfb["status"] == "enabled"
    assert mfb["incidents"] == 11
