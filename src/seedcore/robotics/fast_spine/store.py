"""Durable local replay/revocation store for offline sessions; fails closed."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
from threading import RLock


class ClaimStore:
    def __init__(self, path: str | Path):
        self.lock = RLock()
        path = Path(path)
        if path.is_symlink():
            raise ValueError("claim store must not be a symlink")
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=0.1, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS claims(token_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
                                           endpoint TEXT NOT NULL, session_id TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS revoked(kind TEXT NOT NULL, id TEXT NOT NULL, PRIMARY KEY(kind,id));
        """)

    def claim(self, *, token_id, token_hash, endpoint, session_id, key_ref):
        with self.lock, self.db:
            if self.is_revoked(token_id, key_ref):
                raise PermissionError("revoked token/key")
            if self.db.execute("SELECT count(*) FROM claims").fetchone()[0] >= 100000:
                raise RuntimeError("claim store capacity reached")
            try:
                self.db.execute(
                    "INSERT INTO claims VALUES(?,?,?,?)",
                    (token_id, token_hash, endpoint, session_id),
                )
            except sqlite3.IntegrityError as exc:
                raise PermissionError("replayed token or session") from exc

    def is_revoked(self, token_id, key_ref):
        with self.lock:
            return (
                self.db.execute(
                    "SELECT 1 FROM revoked WHERE (kind='token' AND id=?) OR (kind='key' AND id=?)",
                    (token_id, key_ref),
                ).fetchone()
                is not None
            )

    def revoke(self, identity: str, *, kind="token"):
        if kind not in {"token", "key"} or not identity:
            raise ValueError("invalid revocation")
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO revoked VALUES(?,?)", (kind, identity)
            )

    def close(self):
        with self.lock:
            self.db.close()
