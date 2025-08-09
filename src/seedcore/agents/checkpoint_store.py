"""
Minimal pluggable checkpoint store with a MySQL backend.
All payloads must be JSON-serializable dicts.
Safe-by-default: if the backend isn't available/misconfigured, falls back to a no-op store.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import json, logging

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
class MySQLStore(CheckpointStore):
    host: str
    port: int
    user: str
    password: str
    database: str
    table: str = "agent_checkpoints"

    def _orm(self):
        try:
            from sqlalchemy import create_engine, text  # type: ignore
        except Exception as e:
            raise RuntimeError("sqlalchemy not installed for MySQLStore") from e
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
            if backend == "mysql":
                mysql = cfg.get("mysql", cfg)
                return MySQLStore(
                    host=mysql.get("host", "mysql"),
                    port=int(mysql.get("port", 3306)),
                    user=mysql.get("user", "seedcore"),
                    password=mysql.get("password", "password"),
                    database=mysql.get("database", "seedcore"),
                    table=mysql.get("table", "agent_checkpoints"),
                )
        except Exception as e:
            logger.warning(f"CheckpointStoreFactory fallback to NullStore: {e}")
        return NullStore()


