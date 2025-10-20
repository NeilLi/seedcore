#!/usr/bin/env python3
"""Regression tests for task↔fact provenance logging."""

import asyncio

import pytest
from sqlalchemy import text

import tests.mock_eventizer_dependencies  # noqa: F401

from seedcore.database import get_async_pg_session_factory
from seedcore.models.task import Task
from seedcore.models.fact import Fact
from seedcore.services.fact_manager import FactManager
from seedcore.ops.eventizer.fact_dao import FactDAO
from seedcore.services.coordinator_service import CoordinatorCore, TaskPayload
from seedcore.ops.eventizer.eventizer_features import features_from_payload


@pytest.mark.asyncio
async def test_fact_manager_records_task_fact_relationships():
    """Creating and reading facts should persist task provenance edges."""

    try:
        session_factory = get_async_pg_session_factory()
    except Exception as exc:  # pragma: no cover - database not available
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    async with session_factory() as session:
        try:
            task = Task(
                type="unit-test",
                domain="provenance",
                description="Ensure task↔fact edges exist",
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            fact_manager = FactManager(session)

            fact = await fact_manager.create_fact(
                text="Task provenance fact",
                tags=["unit-test"],
                produced_by_task_id=task.id,
            )

            produce_result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM task_produces_fact "
                    "WHERE task_id = :task_id AND fact_id = :fact_id"
                ),
                {"task_id": str(task.id), "fact_id": str(fact.id)},
            )
            assert produce_result.scalar_one() == 1

            task_node_id = await session.execute(
                text(
                    "SELECT node_id FROM graph_node_map "
                    "WHERE node_type = 'task' AND ext_table = 'tasks' AND ext_uuid = :task_id"
                ),
                {"task_id": str(task.id)},
            )
            assert task_node_id.scalar_one() is not None

            fact_node_id = await session.execute(
                text(
                    "SELECT node_id FROM graph_node_map "
                    "WHERE node_type = 'fact' AND ext_table = 'facts' AND ext_uuid = :fact_id"
                ),
                {"fact_id": str(fact.id)},
            )
            assert fact_node_id.scalar_one() is not None

            # Reading the fact multiple times should remain idempotent
            await fact_manager.get_fact(str(fact.id), reading_task_id=task.id)
            await fact_manager.get_fact(str(fact.id), reading_task_id=task.id)

            read_result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM task_reads_fact "
                    "WHERE task_id = :task_id AND fact_id = :fact_id"
                ),
                {"task_id": str(task.id), "fact_id": str(fact.id)},
            )
            assert read_result.scalar_one() == 1

        except Exception as exc:
            if "task_produces_fact" in str(exc) or "task_reads_fact" in str(exc):
                pytest.skip(f"Task↔fact tables unavailable: {exc}")
            raise
        finally:
            if "fact" in locals():
                await session.execute(
                    text("DELETE FROM task_reads_fact WHERE fact_id = :fact_id"),
                    {"fact_id": str(fact.id)},
                )
                await session.execute(
                    text("DELETE FROM task_produces_fact WHERE fact_id = :fact_id"),
                    {"fact_id": str(fact.id)},
                )
                await session.execute(
                    text("DELETE FROM facts WHERE id = :fact_id"),
                    {"fact_id": str(fact.id)},
                )
            if "task" in locals():
                await session.execute(
                    text("DELETE FROM tasks WHERE id = :task_id"),
                    {"task_id": str(task.id)},
                )
            await session.commit()


@pytest.mark.asyncio
async def test_fact_dao_concurrent_operations_and_proto_plan_hints():
    """Concurrent DAO calls should remain idempotent and enrich proto-plan hints."""

    try:
        session_factory = get_async_pg_session_factory()
    except Exception as exc:  # pragma: no cover - database not available
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    async with session_factory() as session:
        task = Task(
            type="graph_fact_query",
            domain="facts",
            description="Concurrent fact DAO test",
        )
        fact = Fact(text="DAO provenance fact", tags=["unit-test"])
        session.add_all([task, fact])
        await session.commit()
        await session.refresh(task)
        await session.refresh(fact)

    async def _read_fact():
        async with session_factory() as session:
            dao = FactDAO(session)
            return await dao.get_for_task([fact.id], task.id)

    async def _record_fact():
        async with session_factory() as session:
            dao = FactDAO(session)
            await dao.record_produced_fact(fact.id, task.id)

    await asyncio.gather(_read_fact(), _read_fact(), _record_fact(), _record_fact())

    async with session_factory() as session:
        read_count = await session.execute(
            text(
                "SELECT COUNT(*) FROM task_reads_fact "
                "WHERE task_id = :task_id AND fact_id = :fact_id"
            ),
            {"task_id": str(task.id), "fact_id": str(fact.id)},
        )
        produce_count = await session.execute(
            text(
                "SELECT COUNT(*) FROM task_produces_fact "
                "WHERE task_id = :task_id AND fact_id = :fact_id"
            ),
            {"task_id": str(task.id), "fact_id": str(fact.id)},
        )

        assert read_count.scalar_one() == 1
        assert produce_count.scalar_one() == 1

    core = CoordinatorCore()
    payload = TaskPayload(
        type="graph_fact_query",
        params={
            "text": "VIP guest luggage custody incident",
            "start_fact_ids": [str(fact.id)],
            "produced_fact_ids": [str(fact.id)],
        },
        description="Ensure proto-plan hints include fact edges",
        domain="facts",
        drift_score=0.0,
        task_id=str(task.id),
    )

    async with session_factory() as session:
        async with session.begin():
            dao = FactDAO(session)
            result = await core.route_and_execute(
                payload,
                fact_dao=dao,
                eventizer_helper=features_from_payload,
            )

    proto_plan = result["payload"]["metadata"]["proto_plan"]
    hints = proto_plan.get("hints", {})
    assert str(fact.id) in hints.get("facts_read", [])
    assert str(fact.id) in hints.get("facts_produced", [])

    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM task_reads_fact WHERE fact_id = :fact_id"),
            {"fact_id": str(fact.id)},
        )
        await session.execute(
            text("DELETE FROM task_produces_fact WHERE fact_id = :fact_id"),
            {"fact_id": str(fact.id)},
        )
        await session.execute(
            text("DELETE FROM facts WHERE id = :fact_id"),
            {"fact_id": str(fact.id)},
        )
        await session.execute(
            text("DELETE FROM tasks WHERE id = :task_id"),
            {"task_id": str(task.id)},
        )
        await session.commit()

