from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine

from seedcore.coordinator.result_verifier_dao import ResultVerifierJobDAO


pytestmark = pytest.mark.asyncio


def _postgres_test_dsn() -> str | None:
    raw = os.getenv("SEEDCORE_RESULT_VERIFIER_TEST_DSN")
    if not raw:
        return None
    return raw.strip() or None


async def _ensure_result_verifier_tables(session: AsyncSession) -> None:
    # Use extension-free UUID defaults so the lane can run on a vanilla postgres image.
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS result_verifier_jobs (
              id uuid PRIMARY KEY DEFAULT (md5(random()::text || clock_timestamp()::text)::uuid),
              event_journal_id uuid NOT NULL UNIQUE,
              task_id uuid NULL,
              intent_id text NULL,
              asset_id text NULL,
              status text NOT NULL DEFAULT 'queued',
              attempt_count integer NOT NULL DEFAULT 0,
              next_attempt_at timestamptz NOT NULL DEFAULT NOW(),
              last_error_code text NULL,
              last_error_detail text NULL,
              created_at timestamptz NOT NULL DEFAULT NOW(),
              updated_at timestamptz NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS result_verifier_outcomes (
              id uuid PRIMARY KEY DEFAULT (md5(random()::text || clock_timestamp()::text)::uuid),
              job_id uuid NOT NULL,
              event_journal_id uuid NOT NULL,
              verified boolean NOT NULL,
              failure_code text NULL,
              failure_class text NULL,
              twin_event_type text NULL,
              asset_id text NULL,
              evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
              artifact_results jsonb NOT NULL DEFAULT '{}'::jsonb,
              issues jsonb NOT NULL DEFAULT '[]'::jsonb,
              created_at timestamptz NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS result_verifier_runtime_state (
              stream_key text PRIMARY KEY,
              watermark_recorded_at timestamptz NOT NULL,
              watermark_event_id uuid NOT NULL,
              updated_at timestamptz NOT NULL DEFAULT NOW()
            )
            """
        )
    )


async def _truncate_result_verifier_tables(session: AsyncSession) -> None:
    await session.execute(text("TRUNCATE TABLE result_verifier_outcomes, result_verifier_jobs, result_verifier_runtime_state"))


@pytest.fixture
async def _postgres_session_factory():
    dsn = _postgres_test_dsn()
    if not dsn:
        pytest.skip("set SEEDCORE_RESULT_VERIFIER_TEST_DSN to run Postgres-backed RESULT_VERIFIER integration tests")

    engine = create_async_engine(dsn, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            async with session.begin():
                await _ensure_result_verifier_tables(session)
                await _truncate_result_verifier_tables(session)
        yield session_factory
    finally:
        await engine.dispose()


async def test_result_verifier_dao_postgres_enqueue_claim_and_terminal_flow(_postgres_session_factory) -> None:
    dao = ResultVerifierJobDAO()
    event_id = str(uuid.uuid4())

    async with _postgres_session_factory() as session:
        async with session.begin():
            job_id = await dao.enqueue_job(
                session,
                event_journal_id=event_id,
                task_id=str(uuid.uuid4()),
                intent_id="intent-postgres-1",
                asset_id="asset:postgres-1",
            )
            duplicate = await dao.enqueue_job(
                session,
                event_journal_id=event_id,
                task_id=str(uuid.uuid4()),
                intent_id="intent-postgres-1b",
                asset_id="asset:postgres-1b",
            )
            assert job_id is not None
            assert duplicate is None

    async with _postgres_session_factory() as session:
        async with session.begin():
            claimed = await dao.claim_jobs(session, batch_size=10)
            assert len(claimed) == 1
            assert claimed[0]["id"] == job_id
            assert claimed[0]["status"] == "processing"

            outcome_id = await dao.insert_outcome(
                session,
                job_id=job_id,
                event_journal_id=event_id,
                verified=False,
                failure_code="result_verifier_lockout",
                failure_class="trust",
                twin_event_type="verification_quarantined",
                asset_id="asset:postgres-1",
                evidence_refs=["evidence:postgres-1"],
                artifact_results={"verified": False},
                issues=["stale_telemetry"],
            )
            assert outcome_id
            await dao.mark_job_done(session, job_id=job_id)

    async with _postgres_session_factory() as session:
        rows = (
            await session.execute(
                text("SELECT status FROM result_verifier_jobs WHERE id = CAST(:job_id AS uuid)"),
                {"job_id": job_id},
            )
        ).mappings().all()
        assert rows and rows[0]["status"] == "done"
        outcome_rows = (await session.execute(text("SELECT COUNT(*) AS c FROM result_verifier_outcomes"))).mappings().all()
        assert int(outcome_rows[0]["c"]) == 1


async def test_result_verifier_claim_jobs_uses_skip_locked_under_contention(_postgres_session_factory) -> None:
    dao = ResultVerifierJobDAO()
    event_a = str(uuid.uuid4())
    event_b = str(uuid.uuid4())
    task_a = str(uuid.uuid4())
    task_b = str(uuid.uuid4())

    async with _postgres_session_factory() as session:
        async with session.begin():
            job_a = await dao.enqueue_job(
                session,
                event_journal_id=event_a,
                task_id=task_a,
                intent_id="intent-contention-a",
                asset_id="asset:contention-a",
            )
            job_b = await dao.enqueue_job(
                session,
                event_journal_id=event_b,
                task_id=task_b,
                intent_id="intent-contention-b",
                asset_id="asset:contention-b",
            )
            assert job_a and job_b

    async with _postgres_session_factory() as locking_session:
        async with locking_session.begin():
            await locking_session.execute(
                text("SELECT id FROM result_verifier_jobs WHERE id = CAST(:id AS uuid) FOR UPDATE"),
                {"id": job_a},
            )

            async with _postgres_session_factory() as claimant_session:
                async with claimant_session.begin():
                    claimed = await dao.claim_jobs(claimant_session, batch_size=5)
                    claimed_ids = {row["id"] for row in claimed}
                    assert job_a not in claimed_ids
                    assert job_b in claimed_ids

    async with _postgres_session_factory() as session:
        async with session.begin():
            remaining = await dao.claim_jobs(session, batch_size=5)
            remaining_ids = {row["id"] for row in remaining}
            assert job_a in remaining_ids


async def test_result_verifier_runtime_watermark_round_trip_on_postgres(_postgres_session_factory) -> None:
    dao = ResultVerifierJobDAO()
    stream_key = "digital_twin_event_journal"
    watermark_id = uuid.uuid4()
    watermark_ts = datetime.now(timezone.utc)

    async with _postgres_session_factory() as session:
        async with session.begin():
            before = await dao.get_runtime_watermark(session, stream_key=stream_key)
            assert before["stream_key"] == stream_key

            await dao.upsert_runtime_watermark(
                session,
                stream_key=stream_key,
                watermark_recorded_at=watermark_ts,
                watermark_event_id=watermark_id,
            )

    async with _postgres_session_factory() as session:
        async with session.begin():
            after = await dao.get_runtime_watermark(session, stream_key=stream_key)
            assert after["stream_key"] == stream_key
            assert after["watermark_event_id"] == watermark_id
            delta = abs((after["watermark_recorded_at"] - watermark_ts).total_seconds())
            assert delta < 2
