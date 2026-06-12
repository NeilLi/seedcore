from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text  # pyright: ignore[reportMissingImports]

from seedcore.ops.evidence.nfc_verification import anchor_counter_key


class CounterStoreError(Exception):
    """Raised when the monotonic counter ledger cannot be consulted safely."""


@dataclass(frozen=True)
class CounterAdmission:
    admitted: bool
    previous_highest: int
    current_highest: int


class NfcCounterLedger(Protocol):
    def get_highest_counter(self, *, nfc_uid_hash: str, anchor_profile_ref: str) -> int:
        ...

    def admit_counter(
        self,
        *,
        nfc_uid_hash: str,
        anchor_profile_ref: str,
        scan_counter: int,
        workflow_join_key: str,
        observed_at: datetime,
    ) -> CounterAdmission:
        ...


class InMemoryNfcCounterLedger:
    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self._highest_by_anchor = dict(initial or {})

    def get_highest_counter(self, *, nfc_uid_hash: str, anchor_profile_ref: str) -> int:
        key = anchor_counter_key(nfc_uid_hash=nfc_uid_hash, anchor_profile_ref=anchor_profile_ref)
        return int(self._highest_by_anchor.get(key, -1))

    def admit_counter(
        self,
        *,
        nfc_uid_hash: str,
        anchor_profile_ref: str,
        scan_counter: int,
        workflow_join_key: str,
        observed_at: datetime,
    ) -> CounterAdmission:
        key = anchor_counter_key(nfc_uid_hash=nfc_uid_hash, anchor_profile_ref=anchor_profile_ref)
        previous = int(self._highest_by_anchor.get(key, -1))
        if scan_counter <= previous:
            return CounterAdmission(admitted=False, previous_highest=previous, current_highest=previous)
        self._highest_by_anchor[key] = scan_counter
        return CounterAdmission(admitted=True, previous_highest=previous, current_highest=scan_counter)


class SyncDatabaseNfcCounterLedger:
    def __init__(self, *, session_factory: Any, redis_client: Any | None = None) -> None:
        self._session_factory = session_factory
        self._redis_client = redis_client

    def get_highest_counter(self, *, nfc_uid_hash: str, anchor_profile_ref: str) -> int:
        key = anchor_counter_key(nfc_uid_hash=nfc_uid_hash, anchor_profile_ref=anchor_profile_ref)
        cached = self._read_redis(key)
        if cached is not None:
            return cached

        session = self._session()
        try:
            row = session.execute(
                text(
                    """
                    SELECT highest_scan_counter
                    FROM nfc_monotonic_counters
                    WHERE nfc_uid_hash = :uid
                      AND anchor_profile_ref = :profile
                    """
                ),
                {"uid": nfc_uid_hash, "profile": anchor_profile_ref},
            ).fetchone()
            highest = int(row[0]) if row is not None else -1
            self._write_redis(key, highest)
            return highest
        except Exception as exc:
            raise CounterStoreError(f"nfc counter lookup failed: {exc}") from exc
        finally:
            session.close()

    def admit_counter(
        self,
        *,
        nfc_uid_hash: str,
        anchor_profile_ref: str,
        scan_counter: int,
        workflow_join_key: str,
        observed_at: datetime,
    ) -> CounterAdmission:
        key = anchor_counter_key(nfc_uid_hash=nfc_uid_hash, anchor_profile_ref=anchor_profile_ref)
        observed = _ensure_utc(observed_at)
        session = self._session()
        try:
            row = session.execute(
                text(
                    """
                    INSERT INTO nfc_monotonic_counters (
                        nfc_uid_hash,
                        anchor_profile_ref,
                        highest_scan_counter,
                        last_observed_at,
                        last_workflow_join_key,
                        updated_at
                    )
                    VALUES (
                        :uid,
                        :profile,
                        :counter,
                        :observed_at,
                        :workflow_join_key,
                        NOW()
                    )
                    ON CONFLICT (nfc_uid_hash, anchor_profile_ref)
                    DO UPDATE SET
                        highest_scan_counter = EXCLUDED.highest_scan_counter,
                        last_observed_at = EXCLUDED.last_observed_at,
                        last_workflow_join_key = EXCLUDED.last_workflow_join_key,
                        updated_at = NOW()
                    WHERE nfc_monotonic_counters.highest_scan_counter < EXCLUDED.highest_scan_counter
                    RETURNING highest_scan_counter
                    """
                ),
                {
                    "uid": nfc_uid_hash,
                    "profile": anchor_profile_ref,
                    "counter": scan_counter,
                    "observed_at": observed,
                    "workflow_join_key": workflow_join_key,
                },
            ).fetchone()
            if row is not None:
                session.commit()
                self._write_redis(key, scan_counter)
                return CounterAdmission(
                    admitted=True,
                    previous_highest=-1,
                    current_highest=scan_counter,
                )

            current = self._select_current_highest(
                session=session,
                nfc_uid_hash=nfc_uid_hash,
                anchor_profile_ref=anchor_profile_ref,
            )
            session.rollback()
            return CounterAdmission(
                admitted=False,
                previous_highest=current,
                current_highest=current,
            )
        except Exception as exc:
            session.rollback()
            raise CounterStoreError(f"nfc counter admission failed: {exc}") from exc
        finally:
            session.close()

    def _session(self) -> Any:
        try:
            return self._session_factory()
        except Exception as exc:
            raise CounterStoreError(f"nfc counter session unavailable: {exc}") from exc

    def _read_redis(self, key: str) -> int | None:
        if self._redis_client is None:
            return None
        try:
            value = self._redis_client.get(_redis_key(key))
            if value is None:
                return None
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return int(value)
        except Exception as exc:
            raise CounterStoreError(f"nfc counter cache read failed: {exc}") from exc

    def _write_redis(self, key: str, highest: int) -> None:
        if self._redis_client is None:
            return
        try:
            self._redis_client.set(_redis_key(key), str(highest))
        except Exception as exc:
            raise CounterStoreError(f"nfc counter cache write failed: {exc}") from exc

    @staticmethod
    def _select_current_highest(*, session: Any, nfc_uid_hash: str, anchor_profile_ref: str) -> int:
        row = session.execute(
            text(
                """
                SELECT highest_scan_counter
                FROM nfc_monotonic_counters
                WHERE nfc_uid_hash = :uid
                  AND anchor_profile_ref = :profile
                """
            ),
            {"uid": nfc_uid_hash, "profile": anchor_profile_ref},
        ).fetchone()
        return int(row[0]) if row is not None else -1


def _redis_key(anchor_key: str) -> str:
    return f"nfc:counter:{anchor_key}"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
