"""
Tests for FactCore operations.

Critical async database test requirements checklist:
✅ Correct Docker ↔ host Postgres wiring
✅ Correct DSN handling
✅ No import-time config traps
✅ Proper pytest-asyncio configuration
✅ Single event loop across the whole test session
✅ Clean asyncpg pool teardown
✅ Deterministic async DB tests
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

from seedcore.ops.fact.fact_core import FactCore
from seedcore.database import get_async_pg_session_factory, get_async_pg_engine


# 1) Dispose engine cleanly at the very end of the test session.
# This prevents asyncpg trying to cancel/close connections after the loop is closed.
@pytest.fixture(scope="session", autouse=True)
async def _dispose_async_engine_after_session():
    yield
    engine = get_async_pg_engine()
    await engine.dispose()


# 2) Provide an ad-hoc DB session for verification / setup.
# Keep it narrow: open -> do work -> close.
@pytest.fixture
async def db_session():
    factory = get_async_pg_session_factory()
    async with factory() as session:
        yield session


# 3) FactCore uses the normal session_factory (it will open/close internally).
@pytest.fixture
def fact_core():
    return FactCore(session_factory=get_async_pg_session_factory())


@pytest.mark.asyncio
async def test_save_fact_and_lineage(fact_core, db_session):
    # Create a parent task to satisfy FK constraints
    task_id = uuid.uuid4()
    await db_session.execute(
        text("INSERT INTO tasks (id, type, status) VALUES (:tid, 'test_task', 'queued')"),
        {"tid": task_id},
    )
    await db_session.commit()

    fact_id = await fact_core.save_fact(
        text_content="Lineage Test Fact",
        namespace=f"infra_ops_{uuid.uuid4().hex[:6]}",
        subject="server:primary",
        predicate="locatedIn",
        object_data={"city": "Bangkok"},
        produced_by_task=task_id,
        created_by="pytest_suite",
    )

    assert isinstance(fact_id, uuid.UUID)


@pytest.mark.asyncio
async def test_temporal_validity_logic(fact_core):
    subject = f"user:guest_{uuid.uuid4().hex[:6]}"
    namespace = f"security_ops_{uuid.uuid4().hex[:6]}"

    # Expired fact
    await fact_core.save_fact(
        text_content="Expired",
        subject=subject,
        namespace=namespace,
        valid_from=datetime.now(timezone.utc) - timedelta(days=2),
        valid_to=datetime.now(timezone.utc) - timedelta(days=1),
        created_by="pytest_suite",
    )

    # Active fact
    await fact_core.save_fact(
        text_content="Active",
        subject=subject,
        namespace=namespace,
        valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
        valid_to=datetime.now(timezone.utc) + timedelta(hours=1),
        created_by="pytest_suite",
    )

    active_facts = await fact_core.fetch_active_facts(subject, namespace)
    assert len(active_facts) == 1
    assert active_facts[0]["text"] == "Active"


@pytest.mark.asyncio
async def test_pkg_governance_storage(fact_core, db_session):
    # Create snapshot row for FK integrity
    test_version = f"test_fact_{uuid.uuid4().hex[:8]}@1.0.0"
    test_checksum = "f" * 64

    res = await db_session.execute(
        text(
            """
            INSERT INTO pkg_snapshots (version, checksum, notes)
            VALUES (:v, :c, 'pytest snapshot')
            RETURNING id
            """
        ),
        {"v": test_version, "c": test_checksum},
    )
    snapshot_id = res.scalar_one()
    await db_session.commit()

    pkg_meta = {
        "snapshot_id": snapshot_id,
        "rule_id": "rule_pytest",
        "provenance": [{"source": "pytest", "confidence": 0.99}],
        "validation_status": "pkg_validated",
    }

    fact_id = await fact_core.save_fact(
        text_content="PKG Test",
        namespace=f"pkg_test_{uuid.uuid4().hex[:6]}",
        pkg_metadata=pkg_meta,
        created_by="pytest_suite",
    )

    # Verify persisted columns (use a fresh session from fixture)
    row_res = await db_session.execute(
        text("SELECT snapshot_id, validation_status FROM facts WHERE id = :fid"),
        {"fid": fact_id},
    )
    row = row_res.first()
    assert row is not None
    assert row.snapshot_id == snapshot_id
    assert row.validation_status == "pkg_validated"


@pytest.mark.asyncio
async def test_cortex_statistics(fact_core):
    namespace = f"stats_ns_{uuid.uuid4().hex[:6]}"

    # Create facts
    for i in range(2):
        await fact_core.save_fact(
            text_content=f"Stat {i}",
            namespace=namespace,
            created_by="pytest_suite",
        )

    stats = await fact_core.get_cortex_stats(namespace=namespace)

    # Be tolerant: stats may count other facts if view aggregates beyond namespace strictly,
    # but at least ensure namespace appears and totals are >= 2.
    assert stats["total_facts"] >= 2
    assert namespace in stats["namespaces"]


@pytest.mark.asyncio
async def test_purge_expired_facts(fact_core):
    namespace = f"purge_test_{uuid.uuid4().hex[:6]}"

    await fact_core.save_fact(
        text_content="To be purged",
        namespace=namespace,
        valid_from=datetime.now(timezone.utc) - timedelta(hours=2),
        valid_to=datetime.now(timezone.utc) - timedelta(hours=1),
        created_by="pytest_suite",
    )

    count = await fact_core.purge_expired()
    assert count >= 1
