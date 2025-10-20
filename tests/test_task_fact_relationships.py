#!/usr/bin/env python3
"""Regression tests for task↔fact provenance logging."""

import pytest
from sqlalchemy import text

from seedcore.database import get_async_pg_session_factory
from seedcore.models.task import Task
from seedcore.services.fact_manager import FactManager


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

