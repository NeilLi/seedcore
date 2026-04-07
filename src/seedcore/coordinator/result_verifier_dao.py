"""Persistence for RESULT_VERIFIER jobs and outcomes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text  # pyright: ignore[reportMissingImports]

DEFAULT_RESULT_VERIFIER_WATERMARK_TS = datetime(1970, 1, 1, tzinfo=timezone.utc)
DEFAULT_RESULT_VERIFIER_WATERMARK_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class ResultVerifierJobDAO:
    async def enqueue_job(
        self,
        session,
        *,
        event_journal_id: str,
        task_id: Optional[str],
        intent_id: Optional[str],
        asset_id: Optional[str],
    ) -> Optional[str]:
        """Return new job id, or None if duplicate event_journal_id."""
        stmt = text(
            """
            INSERT INTO result_verifier_jobs (
                event_journal_id, task_id, intent_id, asset_id, status, next_attempt_at
            )
            VALUES (
                CAST(:event_journal_id AS uuid),
                CAST(:task_id AS uuid),
                :intent_id,
                :asset_id,
                'queued',
                NOW()
            )
            ON CONFLICT (event_journal_id) DO NOTHING
            RETURNING id::text
            """
        )
        res = await session.execute(
            stmt,
            {
                "event_journal_id": str(event_journal_id),
                "task_id": str(task_id) if task_id else None,
                "intent_id": intent_id,
                "asset_id": asset_id,
            },
        )
        row = res.first()
        return str(row[0]) if row and row[0] else None

    async def claim_jobs(
        self,
        session,
        *,
        batch_size: int,
    ) -> List[Dict[str, Any]]:
        """Claim up to batch_size queued jobs ready for work (PostgreSQL SKIP LOCKED)."""
        lim = max(1, min(int(batch_size), 100))
        stmt = text(
            f"""
            WITH cte AS (
                SELECT id
                FROM result_verifier_jobs
                WHERE status = 'queued' AND next_attempt_at <= NOW()
                ORDER BY next_attempt_at ASC, id ASC
                LIMIT {lim}
                FOR UPDATE SKIP LOCKED
            )
            UPDATE result_verifier_jobs AS j
            SET status = 'processing', updated_at = NOW()
            FROM cte
            WHERE j.id = cte.id
            RETURNING
                j.id::text AS id,
                j.event_journal_id::text AS event_journal_id,
                j.task_id::text AS task_id,
                j.intent_id AS intent_id,
                j.asset_id AS asset_id,
                j.status AS status,
                j.attempt_count AS attempt_count,
                j.next_attempt_at AS next_attempt_at,
                j.last_error_code AS last_error_code,
                j.last_error_detail AS last_error_detail
            """
        )
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]

    async def mark_job_done(self, session, *, job_id: str) -> None:
        stmt = text(
            """
            UPDATE result_verifier_jobs
            SET status = 'done', updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            """
        )
        await session.execute(stmt, {"job_id": str(job_id)})

    async def schedule_retry(
        self,
        session,
        *,
        job_id: str,
        attempt_count: int,
        next_attempt_at: datetime,
        error_code: str,
        error_detail: str,
        terminal: bool,
    ) -> None:
        status = "failed_terminal" if terminal else "queued"
        stmt = text(
            """
            UPDATE result_verifier_jobs
            SET
                status = :status,
                attempt_count = :attempt_count,
                next_attempt_at = :next_at,
                last_error_code = :error_code,
                last_error_detail = :error_detail,
                updated_at = NOW()
            WHERE id = CAST(:job_id AS uuid)
            """
        )
        await session.execute(
            stmt,
            {
                "job_id": str(job_id),
                "status": status,
                "attempt_count": int(attempt_count),
                "next_at": next_attempt_at,
                "error_code": error_code[:128] if error_code else None,
                "error_detail": (error_detail or "")[:8000],
            },
        )

    async def insert_outcome(
        self,
        session,
        *,
        job_id: str,
        event_journal_id: str,
        verified: bool,
        failure_code: Optional[str],
        failure_class: Optional[str],
        twin_event_type: Optional[str],
        asset_id: Optional[str],
        evidence_refs: List[str],
        artifact_results: Dict[str, Any],
        issues: List[str],
    ) -> str:
        import json

        stmt = text(
            """
            INSERT INTO result_verifier_outcomes (
                job_id, event_journal_id, verified, failure_code, failure_class,
                twin_event_type, asset_id, evidence_refs, artifact_results, issues
            )
            VALUES (
                CAST(:job_id AS uuid),
                CAST(:event_journal_id AS uuid),
                :verified,
                :failure_code,
                :failure_class,
                :twin_event_type,
                :asset_id,
                CAST(:evidence_refs AS jsonb),
                CAST(:artifact_results AS jsonb),
                CAST(:issues AS jsonb)
            )
            RETURNING id::text
            """
        )
        res = await session.execute(
            stmt,
            {
                "job_id": str(job_id),
                "event_journal_id": str(event_journal_id),
                "verified": verified,
                "failure_code": failure_code,
                "failure_class": failure_class,
                "twin_event_type": twin_event_type,
                "asset_id": asset_id,
                "evidence_refs": json.dumps(evidence_refs),
                "artifact_results": json.dumps(artifact_results),
                "issues": json.dumps(issues),
            },
        )
        row = res.first()
        return str(row[0]) if row and row[0] else ""

    async def get_runtime_watermark(
        self,
        session,
        *,
        stream_key: str,
    ) -> Dict[str, Any]:
        stmt = text(
            """
            SELECT
                stream_key,
                watermark_recorded_at,
                watermark_event_id,
                updated_at
            FROM result_verifier_runtime_state
            WHERE stream_key = :stream_key
            """
        )
        result = await session.execute(stmt, {"stream_key": str(stream_key)})
        row = result.mappings().one_or_none()
        if row is None:
            return {
                "stream_key": str(stream_key),
                "watermark_recorded_at": DEFAULT_RESULT_VERIFIER_WATERMARK_TS,
                "watermark_event_id": DEFAULT_RESULT_VERIFIER_WATERMARK_ID,
                "updated_at": None,
            }
        recorded_at = row.get("watermark_recorded_at")
        if isinstance(recorded_at, datetime):
            if recorded_at.tzinfo is None:
                recorded_at = recorded_at.replace(tzinfo=timezone.utc)
            else:
                recorded_at = recorded_at.astimezone(timezone.utc)
        else:
            recorded_at = DEFAULT_RESULT_VERIFIER_WATERMARK_TS
        watermark_event_id = row.get("watermark_event_id")
        try:
            parsed_wm_id = uuid.UUID(str(watermark_event_id))
        except (TypeError, ValueError):
            parsed_wm_id = DEFAULT_RESULT_VERIFIER_WATERMARK_ID
        return {
            "stream_key": str(row.get("stream_key") or stream_key),
            "watermark_recorded_at": recorded_at,
            "watermark_event_id": parsed_wm_id,
            "updated_at": row.get("updated_at"),
        }

    async def upsert_runtime_watermark(
        self,
        session,
        *,
        stream_key: str,
        watermark_recorded_at: datetime,
        watermark_event_id: uuid.UUID,
    ) -> None:
        stmt = text(
            """
            INSERT INTO result_verifier_runtime_state (
                stream_key,
                watermark_recorded_at,
                watermark_event_id,
                updated_at
            )
            VALUES (
                :stream_key,
                :watermark_recorded_at,
                CAST(:watermark_event_id AS uuid),
                NOW()
            )
            ON CONFLICT (stream_key)
            DO UPDATE SET
                watermark_recorded_at = EXCLUDED.watermark_recorded_at,
                watermark_event_id = EXCLUDED.watermark_event_id,
                updated_at = NOW()
            """
        )
        await session.execute(
            stmt,
            {
                "stream_key": str(stream_key),
                "watermark_recorded_at": watermark_recorded_at,
                "watermark_event_id": str(watermark_event_id),
            },
        )


def result_verifier_backoff_seconds(attempt_index: int) -> int:
    """attempt_index 0 -> first retry delay after initial failure."""
    seq = (30, 120, 600, 1800, 7200)
    if attempt_index < 0:
        attempt_index = 0
    if attempt_index >= len(seq):
        return seq[-1]
    return seq[attempt_index]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
