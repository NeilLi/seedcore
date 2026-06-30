from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RELATIVE = Path(".local-runtime") / "governance_shadow_advisory" / "events.jsonl"
_DEFAULT_DB_RELATIVE = Path(".local-runtime") / "governance_shadow_advisory" / "events.db"


def governance_shadow_log_file_path() -> Path:
    raw = os.getenv("SEEDCORE_GOVERNANCE_SHADOW_LOG", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / _DEFAULT_RELATIVE


def governance_shadow_db_file_path() -> Path:
    raw = os.getenv("SEEDCORE_GOVERNANCE_SHADOW_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    raw_log = os.getenv("SEEDCORE_GOVERNANCE_SHADOW_LOG", "").strip()
    if raw_log:
        return Path(raw_log).expanduser().with_suffix(".db")
    return Path.cwd() / _DEFAULT_DB_RELATIVE


class GovernanceShadowAdvisoryLogger:
    """Isolated append-only store for non-authoritative governance advisory telemetry."""

    def __init__(self, *, max_events: int) -> None:
        self._max_events = max(1, int(max_events))
        self._memory_lock = Lock()

    @property
    def max_events(self) -> int:
        return self._max_events

    def append(self, event: dict[str, Any]) -> None:
        path = governance_shadow_log_file_path()
        db_path = governance_shadow_db_file_path()
        line = json.dumps(event, separators=(",", ":"), default=str)
        with self._memory_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Governance shadow log directory create failed: %s", exc)
                return
            self._append_sqlite(db_path, event)
            self._append_locked(path, line)

    def read_window(self) -> list[dict[str, Any]]:
        sqlite_window = self._read_window_sqlite()
        if sqlite_window:
            return sqlite_window[-self._max_events :]

        path = governance_shadow_log_file_path()
        if not path.is_file():
            return []
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("Governance shadow log read failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for raw_line in rows:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                parsed = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        return out[-self._max_events :]

    def window_stats(self) -> dict[str, Any]:
        window = self.read_window()
        total = len(window)
        completed = sum(1 for item in window if item.get("status") == "completed")
        failed = sum(1 for item in window if item.get("status") == "failed")
        queue_full = sum(1 for item in window if item.get("status") == "queue_full")
        false_safe = sum(1 for item in window if bool(item.get("false_safe_advisory")))
        authority_usage = sum(1 for item in window if int(item.get("student_final_authority_usage") or 0) != 0)

        false_safe_rate = false_safe / completed if completed > 0 else 0.0
        authority_usage_rate = authority_usage / completed if completed > 0 else 0.0

        last_false_safe_meta = None
        for item in reversed(window):
            if bool(item.get("false_safe_advisory")):
                last_false_safe_meta = {
                    "request_id": item.get("request_id"),
                    "recorded_at": item.get("recorded_at"),
                    "pdp": item.get("pdp"),
                    "prediction": item.get("prediction"),
                }
                break

        alert_hints = []
        if false_safe > 0:
            alert_hints.append("critical: false_safe_advisory_detected")
        if authority_usage > 0:
            alert_hints.append("critical: student_authority_usage_detected")
        if failed > 5:
            alert_hints.append("warning: high_prediction_failure_rate")
        if queue_full > 5:
            alert_hints.append("warning: queue_pressure_detected")

        return {
            "window_capacity": self._max_events,
            "window_events": total,
            "completed": completed,
            "failed": failed,
            "queue_full": queue_full,
            "false_safe_advisory_count": false_safe,
            "false_safe_advisory_rate": false_safe_rate,
            "authority_usage_count": authority_usage,
            "authority_usage_rate": authority_usage_rate,
            "last_false_safe_metadata": last_false_safe_meta,
            "alert_hints": alert_hints,
            "log_path": str(governance_shadow_log_file_path()),
            "db_path": str(governance_shadow_db_file_path()),
        }

    def _append_sqlite(self, db_path: Path, event: dict[str, Any]) -> None:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS governance_shadow_advisory_events (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      recorded_at TEXT NOT NULL,
                      request_id TEXT,
                      asset_ref TEXT,
                      status TEXT NOT NULL,
                      false_safe_advisory INTEGER NOT NULL,
                      student_final_authority_usage INTEGER NOT NULL,
                      event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO governance_shadow_advisory_events (
                      recorded_at, request_id, asset_ref, status,
                      false_safe_advisory, student_final_authority_usage, event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.get("recorded_at") or ""),
                        str(event.get("request_id") or ""),
                        str(event.get("asset_ref") or ""),
                        str(event.get("status") or ""),
                        1 if bool(event.get("false_safe_advisory")) else 0,
                        int(event.get("student_final_authority_usage") or 0),
                        json.dumps(event, separators=(",", ":"), default=str),
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM governance_shadow_advisory_events
                    WHERE id NOT IN (
                      SELECT id FROM governance_shadow_advisory_events ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self._max_events,),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Governance shadow sqlite write failed: %s", exc)

    def _append_locked(self, path: Path, line: str) -> None:
        try:
            import fcntl  # type: ignore[import-not-found]
        except ImportError:
            fcntl = None  # type: ignore[assignment]

        try:
            path.touch(exist_ok=True)
        except OSError as exc:
            logger.warning("Governance shadow log touch failed: %s", exc)
            return

        try:
            with open(path, "r+", encoding="utf-8") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                rows = [row for row in handle.read().splitlines() if row.strip()]
                rows.append(line)
                rows = rows[-self._max_events :]
                handle.seek(0)
                handle.truncate()
                handle.write("\n".join(rows) + ("\n" if rows else ""))
                handle.flush()
        except OSError as exc:
            logger.warning("Governance shadow log write failed: %s", exc)

    def _read_window_sqlite(self) -> list[dict[str, Any]]:
        db_path = governance_shadow_db_file_path()
        if not db_path.is_file():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT event_json
                    FROM governance_shadow_advisory_events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (self._max_events,),
                ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("Governance shadow sqlite read failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for (payload,) in rows:
            try:
                parsed = json.loads(str(payload))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                out.append(parsed)
        out.reverse()
        return out


_GOVERNANCE_SHADOW_LOGGER: GovernanceShadowAdvisoryLogger | None = None
_LOGGER_LOCK = Lock()


def get_governance_shadow_advisory_logger() -> GovernanceShadowAdvisoryLogger:
    global _GOVERNANCE_SHADOW_LOGGER
    with _LOGGER_LOCK:
        if _GOVERNANCE_SHADOW_LOGGER is None:
            capacity = int(os.getenv("SEEDCORE_GOVERNANCE_SHADOW_WINDOW_N", "1000"))
            _GOVERNANCE_SHADOW_LOGGER = GovernanceShadowAdvisoryLogger(max_events=capacity)
        return _GOVERNANCE_SHADOW_LOGGER


def reset_governance_shadow_advisory_logger_for_tests() -> None:
    global _GOVERNANCE_SHADOW_LOGGER
    with _LOGGER_LOCK:
        _GOVERNANCE_SHADOW_LOGGER = None
