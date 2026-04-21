"""
Coordinator-embedded RESULT_VERIFIER: poll twin event journal, verify replay chain, enforce quarantine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from seedcore.coordinator.dao import DigitalTwinEventJournalDAO, GovernedExecutionAuditDAO
from seedcore.coordinator.result_verifier_dao import (
    DEFAULT_RESULT_VERIFIER_WATERMARK_ID,
    DEFAULT_RESULT_VERIFIER_WATERMARK_TS,
    ResultVerifierJobDAO,
    result_verifier_backoff_seconds,
    utcnow,
)
from seedcore.hal.custody.execution_token_revocation import (
    execution_token_crl_ttl_seconds,
    store_revoked_execution_token,
)
from seedcore.models.result_verifier_outcome import ResultVerifierOutcome
from seedcore.services.result_verifier_engine import (
    ResultVerifierRetryableError,
    is_restricted_custody_transfer_record,
    verify_governed_audit_record,
)

if TYPE_CHECKING:
    from seedcore.services.coordinator_service import Coordinator

logger = logging.getLogger(__name__)

_JOURNAL_EVENT_TYPES = ("transition_recorded", "evidence_settled")
_RESULT_VERIFIER_STREAM_KEY = "digital_twin_event_journal"


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _asset_id_from_journal_row(row: Dict[str, Any]) -> Optional[str]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    snap = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    cust = snap.get("custody") if isinstance(snap.get("custody"), dict) else {}
    aid = cust.get("asset_id")
    if isinstance(aid, str) and aid.strip():
        return aid.strip()
    twin_id = str(row.get("twin_id") or "")
    if twin_id.startswith("asset:"):
        return twin_id.strip()
    return None


def _parse_journal_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    raw = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return _parse_journal_time(str(value) if value is not None else None)


def _parse_journal_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return DEFAULT_RESULT_VERIFIER_WATERMARK_ID


def _execution_token_id_from_record(record: Dict[str, Any]) -> Optional[str]:
    token_id = str(record.get("token_id") or "").strip()
    if token_id:
        return token_id
    evidence_bundle = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), dict) else {}
    candidate = str(evidence_bundle.get("execution_token_id") or "").strip()
    return candidate or None


def _asset_id_from_record(record: Dict[str, Any]) -> Optional[str]:
    policy_receipt = record.get("policy_receipt") if isinstance(record.get("policy_receipt"), dict) else {}
    action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    for candidate in (policy_receipt.get("asset_ref"), resource.get("asset_id")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


class ResultVerifierRuntime:
    def __init__(self, coordinator: "Coordinator") -> None:
        self._coordinator = coordinator
        self._enabled = _env_flag("SEEDCORE_RESULT_VERIFIER_ENABLED", default=False)
        self._embedded = _env_flag("SEEDCORE_RESULT_VERIFIER_EMBEDDED", default=True)
        self._poll_seconds = float(os.getenv("SEEDCORE_RESULT_VERIFIER_POLL_SECONDS", "10"))
        self._batch_size = int(os.getenv("SEEDCORE_RESULT_VERIFIER_BATCH_SIZE", "20"))
        self._max_attempts = int(os.getenv("SEEDCORE_RESULT_VERIFIER_MAX_ATTEMPTS", "6"))
        self._overlap_seconds = float(os.getenv("SEEDCORE_RESULT_VERIFIER_OVERLAP_SECONDS", "5"))
        self._max_scan_pages = int(os.getenv("SEEDCORE_RESULT_VERIFIER_MAX_SCAN_PAGES", "8"))
        self._processing_stale_seconds = float(
            os.getenv("SEEDCORE_RESULT_VERIFIER_PROCESSING_STALE_SECONDS", "300")
        )
        self._job_dao = ResultVerifierJobDAO()
        self._event_dao = DigitalTwinEventJournalDAO()
        self._governance_dao = GovernedExecutionAuditDAO()
        self._tasks: List[asyncio.Task[Any]] = []
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not self._enabled:
            logger.info("RESULT_VERIFIER disabled (SEEDCORE_RESULT_VERIFIER_ENABLED=false)")
            return
        if not self._embedded:
            logger.warning(
                "RESULT_VERIFIER embedded runtime disabled (SEEDCORE_RESULT_VERIFIER_EMBEDDED=false); "
                "coordinator will not start verifier loops in this process. Ensure a dedicated "
                "RESULT_VERIFIER service is running to avoid verification downtime."
            )
            return
        sf = getattr(self._coordinator, "_session_factory", None)
        if sf is None:
            logger.warning("RESULT_VERIFIER not started: missing session factory")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("RESULT_VERIFIER not started: no running event loop")
            return
        self._tasks.append(loop.create_task(self._intake_loop(), name="result_verifier_intake"))
        self._tasks.append(loop.create_task(self._worker_loop(), name="result_verifier_worker"))
        logger.info(
            "RESULT_VERIFIER started poll_s=%s batch=%s max_attempts=%s",
            self._poll_seconds,
            self._batch_size,
            self._max_attempts,
        )

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    def _metrics(self) -> Any:
        return getattr(self._coordinator, "metrics", None)

    def _build_retry_exhausted_outcome(
        self,
        *,
        record: Dict[str, Any],
        job_id: str,
        event_journal_id: str,
        task_id: Optional[str],
        intent_id: Optional[str],
        token_id: Optional[str],
        error_code: str,
        attempt_count: int,
    ) -> ResultVerifierOutcome:
        operator_escalation = {
            "code": "result_verifier_retry_exhausted",
            "priority": "high",
            "queue": "result_verifier_break_glass_review",
            "recommended_action": "manual_break_glass_review",
            "summary": (
                "RESULT_VERIFIER exhausted its retry budget and forced fail-closed custody quarantine. "
                "Manual operator review is required before any break-glass recovery."
            ),
            "job_id": job_id,
            "event_journal_id": event_journal_id,
            "task_id": task_id,
            "intent_id": intent_id,
            "token_id": token_id,
            "attempt_count": int(attempt_count),
            "max_attempts": int(self._max_attempts),
            "last_error_code": error_code,
        }
        return ResultVerifierOutcome(
            verified=False,
            failure_code="result_verifier_retry_exhausted",
            gate_reason_code="result_verifier_retry_exhausted",
            failure_class="trust",
            twin_event_type="verification_quarantined",
            asset_id=_asset_id_from_record(record),
            artifact_results={
                "result_verifier_retry_exhausted": {
                    "verified": False,
                    "error_code": error_code,
                    "attempt_count": int(attempt_count),
                    "max_attempts": int(self._max_attempts),
                },
                "operator_escalation": operator_escalation,
            },
            issues=[
                "result_verifier_retry_exhausted",
                f"retry_exhausted:{error_code}",
            ],
        )

    async def _intake_loop(self) -> None:
        sf = self._coordinator._session_factory
        while not self._stop.is_set():
            try:
                await self._poll_journal_once(sf)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("RESULT_VERIFIER intake loop error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                break
            except asyncio.TimeoutError:
                continue

    async def _poll_journal_once(self, sf: Any) -> None:
        async with sf() as session:
            begin_ctx = session.begin()
            if asyncio.iscoroutine(begin_ctx):
                begin_ctx = await begin_ctx
            async with begin_ctx:
                watermark = await self._job_dao.get_runtime_watermark(
                    session,
                    stream_key=_RESULT_VERIFIER_STREAM_KEY,
                )
                watermark_ts = _normalize_utc_datetime(watermark.get("watermark_recorded_at"))
                watermark_id = _parse_journal_uuid(watermark.get("watermark_event_id"))
                scan_after_ts = max(
                    DEFAULT_RESULT_VERIFIER_WATERMARK_TS,
                    watermark_ts - timedelta(seconds=max(0.0, self._overlap_seconds)),
                )
                scan_after_id = DEFAULT_RESULT_VERIFIER_WATERMARK_ID
                max_seen_ts = watermark_ts
                max_seen_id = watermark_id
                page_count = 0
                page_limit = max(1, self._max_scan_pages)
                while page_count < page_limit:
                    rows = await self._event_dao.list_events_for_result_verifier_poll(
                        session,
                        event_types=_JOURNAL_EVENT_TYPES,
                        after_recorded_at=scan_after_ts,
                        after_id=scan_after_id,
                        limit=self._batch_size,
                    )
                    if not rows:
                        break
                    for row in rows:
                        eid = str(row.get("id") or "")
                        task_id = row.get("task_id")
                        intent_id = row.get("intent_id")
                        asset_id = _asset_id_from_journal_row(row)
                        jid = await self._job_dao.enqueue_job(
                            session,
                            event_journal_id=eid,
                            task_id=task_id,
                            intent_id=intent_id,
                            asset_id=asset_id,
                        )
                        if jid and self._metrics():
                            self._metrics().increment_counter("result_verifier_jobs_enqueued_total")
                        ts = _parse_journal_time(row.get("recorded_at"))
                        rid = _parse_journal_uuid(row.get("id"))
                        if ts > max_seen_ts or (ts == max_seen_ts and rid > max_seen_id):
                            max_seen_ts = ts
                            max_seen_id = rid
                    last_row = rows[-1]
                    next_after_ts = _parse_journal_time(last_row.get("recorded_at"))
                    next_after_id = _parse_journal_uuid(last_row.get("id"))
                    if (
                        next_after_ts < scan_after_ts
                        or (next_after_ts == scan_after_ts and next_after_id <= scan_after_id)
                    ):
                        break
                    scan_after_ts = next_after_ts
                    scan_after_id = next_after_id
                    page_count += 1
                    if len(rows) < self._batch_size:
                        break
                if max_seen_ts > watermark_ts or (max_seen_ts == watermark_ts and max_seen_id > watermark_id):
                    await self._job_dao.upsert_runtime_watermark(
                        session,
                        stream_key=_RESULT_VERIFIER_STREAM_KEY,
                        watermark_recorded_at=max_seen_ts,
                        watermark_event_id=max_seen_id,
                    )
                await self._record_watermark_lag_gauge(session, watermark_ts=max_seen_ts)

    async def _record_watermark_lag_gauge(self, session: Any, *, watermark_ts: datetime) -> None:
        """Publish intake-watermark-lag for the ADR 0006 scaling-shape trigger.

        Lag is computed against the journal's own newest event so a quiet
        journal reports ~0, not "falling behind". If the gauge write fails we
        swallow the error - observability must never break the intake loop.
        """
        metrics = self._metrics()
        if metrics is None:
            return
        try:
            normalized_watermark_ts = _normalize_utc_datetime(watermark_ts)
            latest = await self._event_dao.get_latest_event_recorded_at(
                session,
                event_types=_JOURNAL_EVENT_TYPES,
            )
            if latest is None:
                lag_seconds = 0.0
            else:
                latest = _normalize_utc_datetime(latest)
                delta = latest - normalized_watermark_ts
                lag_seconds = max(0.0, delta.total_seconds())
            setter = getattr(metrics, "set_gauge", None)
            if callable(setter):
                setter("result_verifier_watermark_lag_seconds", lag_seconds)
        except Exception:
            logger.debug("RESULT_VERIFIER watermark lag gauge emission failed", exc_info=True)

    async def _worker_loop(self) -> None:
        sf = self._coordinator._session_factory
        dts = self._coordinator.digital_twin_service
        while not self._stop.is_set():
            try:
                await self._process_job_batch(sf, dts)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("RESULT_VERIFIER worker loop error")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.5, self._poll_seconds / 2))
                break
            except asyncio.TimeoutError:
                continue

    async def _process_job_batch(self, sf: Any, dts: Any) -> None:
        async with sf() as session:
            begin_ctx = session.begin()
            if asyncio.iscoroutine(begin_ctx):
                begin_ctx = await begin_ctx
            async with begin_ctx:
                await self._recover_stale_processing_jobs(session)
                jobs = await self._job_dao.claim_jobs(session, batch_size=self._batch_size)
                if not jobs:
                    return
                for job in jobs:
                    await self._process_one_job(session, job, dts)

    async def _recover_stale_processing_jobs(self, session: Any) -> None:
        stale_before = utcnow() - timedelta(seconds=max(1.0, self._processing_stale_seconds))
        stale_jobs = await self._job_dao.requeue_stale_processing_jobs(
            session,
            stale_before=stale_before,
        )
        metrics = self._metrics()
        if metrics is None:
            return
        for _ in stale_jobs:
            metrics.increment_counter("result_verifier_stale_processing_requeued_total")

    async def _process_one_job(self, session: Any, job: Dict[str, Any], dts: Any) -> None:
        job_id = str(job.get("id") or "")
        eid = str(job.get("event_journal_id") or "")
        task_id = job.get("task_id")
        intent_id = job.get("intent_id")
        attempt = int(job.get("attempt_count") or 0)
        token_id: Optional[str] = None
        record: Optional[Dict[str, Any]] = None
        resolved_task_id: Optional[str] = str(task_id or "").strip() or None
        resolved_intent_id: Optional[str] = str(intent_id or "").strip() or None
        t0 = time.perf_counter()
        try:
            if task_id:
                record = await self._governance_dao.get_latest_for_task(session, task_id=str(task_id))
            if record is None and intent_id:
                record = await self._governance_dao.get_latest_for_intent(session, intent_id=str(intent_id))
            if not record:
                raise RuntimeError("governed_audit_record_missing")
            resolved_task_id = str(task_id or record.get("task_id") or "").strip() or None
            resolved_intent_id = str(intent_id or record.get("intent_id") or "").strip() or None
            token_id = _execution_token_id_from_record(record)

            if not is_restricted_custody_transfer_record(record):
                outcome = ResultVerifierOutcome(
                    verified=True,
                    failure_class="none",
                    twin_event_type=None,
                    asset_id=None,
                    issues=["skipped_non_rct_scope"],
                )
                await self._persist_terminal(
                    session,
                    job_id,
                    eid,
                    outcome,
                    dts,
                    apply_twin=False,
                    task_id=resolved_task_id,
                    intent_id=resolved_intent_id,
                    token_id=token_id,
                )
                if self._metrics():
                    self._metrics().increment_counter("result_verifier_non_rct_skipped_total")
                    self._metrics().increment_counter("result_verifier_jobs_processed_total")
                return

            outcome = verify_governed_audit_record(record)
            await self._persist_terminal(
                session,
                job_id,
                eid,
                outcome,
                dts,
                apply_twin=True,
                task_id=resolved_task_id,
                intent_id=resolved_intent_id,
                token_id=token_id,
            )
            if self._metrics():
                self._metrics().increment_counter("result_verifier_jobs_processed_total")
                if outcome.verified:
                    self._metrics().increment_counter("result_verifier_pass_total")
                elif outcome.failure_class == "integrity":
                    self._metrics().increment_counter("result_verifier_integrity_fail_total")
                elif outcome.failure_class == "trust":
                    self._metrics().increment_counter("result_verifier_quarantine_total")
        except Exception as exc:
            err = f"{type(exc).__name__}:{exc}"
            logger.warning("RESULT_VERIFIER job %s failed attempt=%s: %s", job_id, attempt, err)
            error_code = "worker_exception"
            metrics = self._metrics()
            if isinstance(exc, RuntimeError) and str(exc) == "missing_subject_for_fail_closed":
                error_code = "missing_subject_for_fail_closed"
                next_attempt = max(int(self._max_attempts), attempt + 1)
                terminal = True
                next_at = utcnow()
                logger.error(
                    "RESULT_VERIFIER fail-closed orphan job_id=%s event_journal_id=%s task_id=%s intent_id=%s token_id=%s",
                    job_id,
                    eid,
                    task_id,
                    intent_id,
                    token_id,
                )
            elif isinstance(exc, ResultVerifierRetryableError):
                error_code = str(exc)[:128] or "result_verifier_retryable_failure"
                next_attempt = attempt + 1
                terminal = next_attempt >= self._max_attempts
                delay_s = result_verifier_backoff_seconds(attempt)
                next_at = utcnow() + timedelta(seconds=delay_s)
            else:
                next_attempt = attempt + 1
                terminal = next_attempt >= self._max_attempts
                delay_s = result_verifier_backoff_seconds(attempt)
                next_at = utcnow() + timedelta(seconds=delay_s)
            if terminal and error_code != "missing_subject_for_fail_closed" and record:
                exhaustion_outcome = self._build_retry_exhausted_outcome(
                    record=record,
                    job_id=job_id,
                    event_journal_id=eid,
                    task_id=resolved_task_id,
                    intent_id=resolved_intent_id,
                    token_id=token_id,
                    error_code=error_code,
                    attempt_count=next_attempt,
                )
                try:
                    await self._persist_terminal(
                        session,
                        job_id,
                        eid,
                        exhaustion_outcome,
                        dts,
                        apply_twin=True,
                        task_id=resolved_task_id,
                        intent_id=resolved_intent_id,
                        token_id=token_id,
                    )
                except ResultVerifierRetryableError as persist_exc:
                    err = f"{type(persist_exc).__name__}:{persist_exc}"
                    error_code = str(persist_exc)[:128] or "result_verifier_terminal_enforcement_retryable_failure"
                    terminal = False
                    delay_s = result_verifier_backoff_seconds(attempt)
                    next_at = utcnow() + timedelta(seconds=delay_s)
                except Exception as persist_exc:
                    err = f"{type(persist_exc).__name__}:{persist_exc}"
                    if isinstance(persist_exc, RuntimeError) and str(persist_exc) == "missing_subject_for_fail_closed":
                        error_code = "missing_subject_for_fail_closed"
                        next_attempt = max(int(self._max_attempts), next_attempt)
                        terminal = True
                        next_at = utcnow()
                        logger.error(
                            "RESULT_VERIFIER fail-closed orphan job_id=%s event_journal_id=%s task_id=%s intent_id=%s token_id=%s",
                            job_id,
                            eid,
                            resolved_task_id,
                            resolved_intent_id,
                            token_id,
                        )
                    else:
                        error_code = "worker_exception"
                        terminal = True
                        next_at = utcnow()
                else:
                    if metrics:
                        metrics.increment_counter("result_verifier_jobs_processed_total")
                        metrics.increment_counter("result_verifier_quarantine_total")
                        metrics.increment_counter("result_verifier_terminal_fail_total")
                    return
            await self._job_dao.schedule_retry(
                session,
                job_id=job_id,
                attempt_count=next_attempt,
                next_attempt_at=next_at,
                error_code=error_code,
                error_detail=err[:2000],
                terminal=terminal,
            )
            if metrics:
                if error_code == "missing_subject_for_fail_closed":
                    metrics.increment_counter("result_verifier_fail_closed_orphan_total")
                if terminal:
                    metrics.increment_counter("result_verifier_terminal_fail_total")
                else:
                    metrics.increment_counter("result_verifier_retry_total")
        finally:
            metrics = self._metrics()
            if metrics is not None:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                metrics.append_latency("result_verifier_worker_latency_ms", elapsed_ms)
                metrics.increment_counter(
                    "result_verifier_job_millis_total",
                    int(elapsed_ms),
                )

    async def _persist_terminal(
        self,
        session: Any,
        job_id: str,
        event_journal_id: str,
        outcome: ResultVerifierOutcome,
        dts: Any,
        *,
        apply_twin: bool,
        task_id: Optional[str],
        intent_id: Optional[str],
        token_id: Optional[str],
    ) -> None:
        tid = (task_id or "").strip() or None
        iid = (intent_id or "").strip() or None
        requires_fail_closed_lockout = outcome.twin_event_type in {
            "verification_failed",
            "verification_quarantined",
        }
        quarantine_mutation_confirmed = False

        if apply_twin and outcome.twin_event_type:
            if requires_fail_closed_lockout and token_id:
                try:
                    stored_revocation = store_revoked_execution_token(
                        token_id=token_id,
                        ttl_seconds=execution_token_crl_ttl_seconds(),
                    )
                except RuntimeError as exc:
                    raise ResultVerifierRetryableError("execution_token_revocation_unavailable") from exc
                if not stored_revocation:
                    raise ResultVerifierRetryableError("execution_token_revocation_unavailable")
            mutation_result = await dts.apply_result_verifier_outcome(
                outcome,
                task_id=tid,
                intent_id=iid,
                session=session,
            )
            mutation_updated = int(mutation_result.get("updated") or 0) > 0
            if requires_fail_closed_lockout and not mutation_updated:
                fallback_result = await dts.apply_result_verifier_outcome_fallback(
                    outcome,
                    task_id=tid,
                    intent_id=iid,
                    session=session,
                )
                mutation_updated = int(fallback_result.get("updated") or 0) > 0
                if not mutation_updated:
                    raise RuntimeError("missing_subject_for_fail_closed")
            quarantine_mutation_confirmed = requires_fail_closed_lockout and mutation_updated
            if self._metrics() and quarantine_mutation_confirmed:
                self._metrics().increment_counter("result_verifier_quarantine_mutations_total")

        await self._job_dao.insert_outcome(
            session,
            job_id=job_id,
            event_journal_id=event_journal_id,
            verified=outcome.verified,
            failure_code=outcome.failure_code,
            failure_class=outcome.failure_class,
            twin_event_type=outcome.twin_event_type,
            asset_id=outcome.asset_id,
            evidence_refs=list(outcome.evidence_refs or []),
            artifact_results=dict(outcome.artifact_results or {}),
            issues=list(outcome.issues or []),
        )
        await self._job_dao.mark_job_done(session, job_id=job_id)
