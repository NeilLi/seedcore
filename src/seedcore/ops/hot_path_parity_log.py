from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_RELATIVE = Path(".local-runtime") / "hot_path_parity" / "events.jsonl"
_DEFAULT_DB_RELATIVE = Path(".local-runtime") / "hot_path_parity" / "events.db"


def parity_log_file_path() -> Path:
    raw = os.getenv("SEEDCORE_HOT_PATH_PARITY_LOG", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / _DEFAULT_RELATIVE


def parity_db_file_path() -> Path:
    raw = os.getenv("SEEDCORE_HOT_PATH_PARITY_DB", "").strip()
    if raw:
        return Path(raw).expanduser()
    raw_log = os.getenv("SEEDCORE_HOT_PATH_PARITY_LOG", "").strip()
    if raw_log:
        log_path = Path(raw_log).expanduser()
        return log_path.with_suffix(".db")
    return Path.cwd() / _DEFAULT_DB_RELATIVE


class HotPathParityEventLogger:
    """
    Append-only JSONL store trimmed to the last N parity events for promotion evidence.
    Uses an exclusive file lock (fcntl) when available so concurrent workers serialize writes.
    """

    def __init__(self, *, max_events: int) -> None:
        self._max_events = max(1, int(max_events))
        self._memory_lock = Lock()

    @property
    def max_events(self) -> int:
        return self._max_events

    def append(self, event: dict[str, Any]) -> None:
        path = parity_log_file_path()
        db_path = parity_db_file_path()
        line = json.dumps(event, separators=(",", ":"), default=str)
        with self._memory_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                db_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.warning("Hot-path parity log directory create failed: %s", exc)
                return
            self._append_sqlite(db_path, event)
            self._append_locked(path, line)

    def _append_sqlite(self, db_path: Path, event: dict[str, Any]) -> None:
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hot_path_parity_events (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      recorded_at TEXT NOT NULL,
                      request_id TEXT,
                      asset_ref TEXT,
                      parity_ok INTEGER NOT NULL,
                      latency_ms INTEGER NOT NULL,
                      event_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO hot_path_parity_events (
                      recorded_at, request_id, asset_ref, parity_ok, latency_ms, event_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event.get("recorded_at") or ""),
                        str(event.get("request_id") or ""),
                        str(event.get("asset_ref") or ""),
                        1 if bool(event.get("parity_ok")) else 0,
                        int(event.get("latency_ms") or 0),
                        json.dumps(event, separators=(",", ":"), default=str),
                    ),
                )
                conn.execute(
                    """
                    DELETE FROM hot_path_parity_events
                    WHERE id NOT IN (
                      SELECT id FROM hot_path_parity_events ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self._max_events,),
                )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("Hot-path parity sqlite write failed: %s", exc)

    def _append_locked(self, path: Path, line: str) -> None:
        try:
            import fcntl  # type: ignore[import-not-found]
        except ImportError:
            fcntl = None  # type: ignore[assignment]

        try:
            path.touch(exist_ok=True)
        except OSError as exc:
            logger.warning("Hot-path parity log touch failed: %s", exc)
            return

        try:
            with open(path, "r+", encoding="utf-8") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                existing = handle.read()
                rows = [r for r in existing.splitlines() if r.strip()]
                rows.append(line)
                rows = rows[-self._max_events :]
                handle.seek(0)
                handle.truncate()
                handle.write("\n".join(rows) + ("\n" if rows else ""))
                handle.flush()
        except OSError as exc:
            logger.warning("Hot-path parity log write failed: %s", exc)

    def read_window(self) -> list[dict[str, Any]]:
        sqlite_window = self._read_window_sqlite()
        if sqlite_window:
            return sqlite_window[-self._max_events :]

        path = parity_log_file_path()
        if not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Hot-path parity log read failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out[-self._max_events :]

    def _read_window_sqlite(self) -> list[dict[str, Any]]:
        db_path = parity_db_file_path()
        if not db_path.is_file():
            return []
        try:
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT event_json
                    FROM hot_path_parity_events
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (self._max_events,),
                ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("Hot-path parity sqlite read failed: %s", exc)
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

    def query_events(self, *, parity_ok: bool | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.read_window()
        if parity_ok is None:
            return rows[-max(1, int(limit)) :]
        filtered = [item for item in rows if bool(item.get("parity_ok")) == parity_ok]
        return filtered[-max(1, int(limit)) :]

    def window_stats(self) -> dict[str, Any]:
        window = self.read_window()
        total = len(window)
        parity_ok = sum(1 for item in window if bool(item.get("parity_ok")))
        ratio = (parity_ok / total) if total else None
        min_ratio = float(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_MIN_PARITY_RATIO", "1.0"))
        min_ok_required = (
            math.ceil(min_ratio * total - 1e-12) if total else None
        )
        capacity = self._max_events
        eligible = bool(
            total >= capacity
            and min_ok_required is not None
            and parity_ok >= min_ok_required
        )
        return {
            "window_capacity": capacity,
            "window_events": total,
            "parity_ok_in_window": parity_ok,
            "parity_rate_in_window": ratio,
            "min_parity_ratio": min_ratio,
            "min_parity_ok_required": min_ok_required,
            "promotion_eligible": eligible,
            "promotion_formula": (
                f"parity_ok_in_window >= ceil({min_ratio} * window_events) "
                f"with window_events >= {capacity}"
            ),
        }


_HOT_PATH_PARITY_LOGGER: HotPathParityEventLogger | None = None
_LOGGER_LOCK = Lock()


def get_hot_path_parity_logger() -> HotPathParityEventLogger:
    global _HOT_PATH_PARITY_LOGGER
    with _LOGGER_LOCK:
        if _HOT_PATH_PARITY_LOGGER is None:
            capacity = int(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N", "1000"))
            _HOT_PATH_PARITY_LOGGER = HotPathParityEventLogger(max_events=capacity)
        return _HOT_PATH_PARITY_LOGGER


def reset_hot_path_parity_logger_for_tests() -> None:
    """Test hook: clear singleton so a fresh logger picks up env changes."""
    global _HOT_PATH_PARITY_LOGGER
    with _LOGGER_LOCK:
        _HOT_PATH_PARITY_LOGGER = None
