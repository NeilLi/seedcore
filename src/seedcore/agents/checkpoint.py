"""
Minimal pluggable checkpoint store with a MySQL backend.
All payloads must be JSON-serializable dicts.
Safe-by-default: if the backend isn't available/misconfigured, falls back to a no-op store.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckpointStore:
    def save(self, key: str, payload: Dict[str, Any]) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def load(self, key: str) -> Optional[Dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, key: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class NullStore(CheckpointStore):
    def save(self, key: str, payload: Dict[str, Any]) -> bool:
        logger.debug(f"NullStore.save({key}) — no-op")
        return False

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        logger.debug(f"NullStore.load({key}) — no-op")
        return None

    def delete(self, key: str) -> bool:
        logger.debug(f"NullStore.delete({key}) — no-op")
        return False


@dataclass
class FSStore(CheckpointStore):
    root: str = "/tmp/seedcore"

    def _resolve(self, key: str) -> Path:
        # Keys can contain nested paths like 'energy/ledger.ndjson'
        p = Path(self.root) / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, key: str, payload: Dict[str, Any]) -> bool:
        try:
            p = self._resolve(key)
            tmp = p.with_suffix(p.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            tmp.replace(p)
            return True
        except Exception as e:
            logger.warning(f"FSStore.save failed for {key}: {e}")
            return False

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            p = self._resolve(key)
            if not p.exists():
                return None
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.info(f"FSStore.load miss/fail for {key}: {e}")
            return None

    def delete(self, key: str) -> bool:
        try:
            p = self._resolve(key)
            if p.exists():
                p.unlink()
            return True
        except Exception as e:
            logger.warning(f"FSStore.delete failed for {key}: {e}")
            return False


@dataclass
class MySQLStore(CheckpointStore):
    host: str
    port: int
    user: str
    password: str
    database: str
    table: str = "agent_checkpoints"

    def _orm(self):
        """Return a pooled SQLAlchemy engine and text() using the central database module.
        Falls back to a local engine if database module is unavailable.
        """
        try:
            # Prefer shared engine from central database module
            from seedcore.database import get_sync_mysql_engine  # type: ignore
            from sqlalchemy import text  # type: ignore
            engine = get_sync_mysql_engine()
            return engine, text
        except Exception:
            # Fallback to creating a local engine if database module isn't available
            from sqlalchemy import create_engine, text  # type: ignore
            dsn = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            engine = create_engine(dsn, pool_pre_ping=True)
            return engine, text

    def _ensure_table(self, engine, text):
        ddl = f"""
        CREATE TABLE IF NOT EXISTS `{self.table}` (
            `agent_key` VARCHAR(255) PRIMARY KEY,
            `payload`   JSON NOT NULL,
            `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with engine.begin() as conn:
            conn.execute(text(ddl))

    def save(self, key: str, payload: Dict[str, Any]) -> bool:
        try:
            engine, text = self._orm()
            self._ensure_table(engine, text)
            upsert = text(f"""
                INSERT INTO `{self.table}` (agent_key, payload, updated_at)
                VALUES (:k, :p, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE payload=:p, updated_at=CURRENT_TIMESTAMP;
            """)
            with engine.begin() as conn:
                conn.execute(upsert, {"k": key, "p": json.dumps(payload)})
            return True
        except Exception as e:
            logger.warning(f"MySQLStore.save failed for {key}: {e}")
            return False

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            engine, text = self._orm()
            sel = text(f"SELECT payload FROM `{self.table}` WHERE agent_key=:k")
            with engine.begin() as conn:
                row = conn.execute(sel, {"k": key}).fetchone()
                if not row:
                    return None
                return json.loads(row[0])
        except Exception as e:
            logger.info(f"MySQLStore.load miss/fail for {key}: {e}")
            return None

    def delete(self, key: str) -> bool:
        try:
            engine, text = self._orm()
            dele = text(f"DELETE FROM `{self.table}` WHERE agent_key=:k")
            with engine.begin() as conn:
                conn.execute(dele, {"k": key})
            return True
        except Exception as e:
            logger.warning(f"MySQLStore.delete failed for {key}: {e}")
            return False


# ---------- Factory ----------
class CheckpointStoreFactory:
    @staticmethod
    def from_config(cfg: Optional[Dict[str, Any]]) -> CheckpointStore:
        if not cfg or not cfg.get("enabled"):
            return NullStore()
        backend = (cfg.get("backend") or "mysql").lower()
        try:
            if backend in ("mysql", "sql"):
                mysql = cfg.get("mysql", cfg)
                return MySQLStore(
                    host=mysql.get("host", "mysql"),
                    port=int(mysql.get("port", 3306)),
                    user=mysql.get("user", "seedcore"),
                    password=mysql.get("password", "password"),
                    database=mysql.get("database", "seedcore"),
                    table=mysql.get("table", "agent_checkpoints"),
                )
            if backend == "fs":
                root = cfg.get("root") or os.getenv("ENERGY_LEDGER_ROOT", "/tmp/seedcore")
                return FSStore(root=root)
        except Exception as e:
            logger.warning(f"CheckpointStoreFactory fallback to NullStore: {e}")
        return NullStore()


