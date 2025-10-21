"""Database-backed helpers for graph tasks.

This repository centralizes CRUD helpers around the ``tasks`` table
for graph-related workloads.  It intentionally uses the synchronous
SQLAlchemy engine returned by :func:`seedcore.database.get_sync_pg_engine`
so it can be called from existing worker code, while also exposing
async wrappers for integration with asyncio-based coordinators.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError, DataError

from seedcore.database import get_sync_pg_engine


class GraphTaskSqlRepository:
    """Lightweight repository for creating graph tasks and wiring dependencies."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self._engine: Engine = engine or get_sync_pg_engine()

    # ------------------------------------------------------------------
    # Task creation
    # ------------------------------------------------------------------
    def create_task(
        self,
        task_type: str,
        params: Optional[Mapping[str, Any]],
        description: Optional[str],
        agent_id: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> UUID:
        """Insert a new task record and return its UUID."""
        try:
            params_dict = dict(params or {})

            if task_type == "graph_embed":
                return self._create_graph_embed_task(params_dict, description, agent_id, organ_id)
            if task_type == "graph_rag_query":
                return self._create_graph_rag_task(params_dict, description, agent_id, organ_id)

            return self._create_generic_task(task_type, params_dict, description, agent_id, organ_id)
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation while creating task type '%s': %s. "
                "This may indicate duplicate data or invalid foreign key references. "
                "Agent: %s, Organ: %s",
                task_type, str(e), agent_id, organ_id
            )
            raise
        except OperationalError as e:
            logger.error(
                "Database operational error while creating task type '%s': %s. "
                "This may indicate connection issues or database unavailability. "
                "Agent: %s, Organ: %s",
                task_type, str(e), agent_id, organ_id
            )
            raise
        except DataError as e:
            logger.error(
                "Data error while creating task type '%s': %s. "
                "This may indicate invalid data types or constraint violations. "
                "Agent: %s, Organ: %s",
                task_type, str(e), agent_id, organ_id
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error while creating task type '%s': %s. "
                "Agent: %s, Organ: %s, Params: %s",
                task_type, str(e), agent_id, organ_id, params_dict
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error while creating task type '%s': %s. "
                "Agent: %s, Organ: %s, Params: %s",
                task_type, str(e), agent_id, organ_id, params_dict
            )
            raise

    async def create_task_async(
        self,
        task_type: str,
        params: Optional[Mapping[str, Any]],
        description: Optional[str],
        agent_id: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> UUID:
        """Async wrapper around :meth:`create_task`."""

        return await asyncio.to_thread(
            self.create_task,
            task_type,
            params,
            description,
            agent_id,
            organ_id,
        )

    # ------------------------------------------------------------------
    # Task dependencies
    # ------------------------------------------------------------------
    def add_dependency(self, parent_id: UUID, child_id: UUID) -> None:
        """Register a dependency edge between two tasks."""
        try:
            stmt = text(
                """
                INSERT INTO task_depends_on_task (src_task_id, dst_task_id)
                VALUES (:parent_id, :child_id)
                ON CONFLICT DO NOTHING
                """
            )
            with self._engine.begin() as conn:
                conn.execute(stmt, {"parent_id": parent_id, "child_id": child_id})
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation while adding dependency %s -> %s: %s. "
                "This may indicate invalid task IDs or circular dependencies.",
                parent_id, child_id, str(e)
            )
            raise
        except OperationalError as e:
            logger.error(
                "Database operational error while adding dependency %s -> %s: %s. "
                "This may indicate connection issues or database unavailability.",
                parent_id, child_id, str(e)
            )
            raise
        except DataError as e:
            logger.error(
                "Data error while adding dependency %s -> %s: %s. "
                "This may indicate invalid data types.",
                parent_id, child_id, str(e)
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error while adding dependency %s -> %s: %s",
                parent_id, child_id, str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error while adding dependency %s -> %s: %s",
                parent_id, child_id, str(e)
            )
            raise

    async def add_dependency_async(self, parent_id: UUID, child_id: UUID) -> None:
        """Async wrapper around :meth:`add_dependency`."""

        await asyncio.to_thread(self.add_dependency, parent_id, child_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _create_graph_embed_task(
        self,
        params: Mapping[str, Any],
        description: Optional[str],
        agent_id: Optional[str],
        organ_id: Optional[str],
    ) -> UUID:
        try:
            start_ids = self._coerce_int_list(params, "start_node_ids", "start_ids")
            if not start_ids:
                raise ValueError("graph_embed requires 'start_ids' or 'start_node_ids'")
            k_hops = self._coerce_int(params.get("k")) or self._coerce_int(params.get("k_hops")) or 2

            stmt = text(
                """
                SELECT create_graph_embed_task_v2(:start_ids, :k_hops, :description, :agent_id, :organ_id) AS id
                """
            )
            with self._engine.begin() as conn:
                result = conn.execute(
                    stmt,
                    {
                        "start_ids": start_ids,
                        "k_hops": k_hops,
                        "description": description,
                        "agent_id": agent_id,
                        "organ_id": organ_id,
                    },
                )
                task_id = result.scalar_one()
            return self._coerce_uuid(task_id)
        except ValueError as e:
            logger.error(
                "Validation error in graph_embed task creation: %s. Params: %s",
                str(e), params
            )
            raise
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation in graph_embed task creation: %s. "
                "Start IDs: %s, K-hops: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, agent_id, organ_id
            )
            raise
        except OperationalError as e:
            logger.error(
                "Database operational error in graph_embed task creation: %s. "
                "Start IDs: %s, K-hops: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, agent_id, organ_id
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error in graph_embed task creation: %s. "
                "Start IDs: %s, K-hops: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, agent_id, organ_id
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error in graph_embed task creation: %s. "
                "Start IDs: %s, K-hops: %s, Agent: %s, Organ: %s, Params: %s",
                str(e), start_ids, k_hops, agent_id, organ_id, params
            )
            raise

    def _create_graph_rag_task(
        self,
        params: Mapping[str, Any],
        description: Optional[str],
        agent_id: Optional[str],
        organ_id: Optional[str],
    ) -> UUID:
        try:
            start_ids = self._coerce_int_list(params, "start_node_ids", "start_ids")
            if not start_ids:
                raise ValueError("graph_rag_query requires 'start_ids' or 'start_node_ids'")
            k_hops = self._coerce_int(params.get("k")) or self._coerce_int(params.get("k_hops")) or 2
            top_k = (
                self._coerce_int(params.get("topk"))
                or self._coerce_int(params.get("top_k"))
                or self._coerce_int(params.get("topK"))
                or 10
            )

            stmt = text(
                """
                SELECT create_graph_rag_task_v2(:start_ids, :k_hops, :top_k, :description, :agent_id, :organ_id) AS id
                """
            )
            with self._engine.begin() as conn:
                result = conn.execute(
                    stmt,
                    {
                        "start_ids": start_ids,
                        "k_hops": k_hops,
                        "top_k": top_k,
                        "description": description,
                        "agent_id": agent_id,
                        "organ_id": organ_id,
                    },
                )
                task_id = result.scalar_one()
            return self._coerce_uuid(task_id)
        except ValueError as e:
            logger.error(
                "Validation error in graph_rag_query task creation: %s. Params: %s",
                str(e), params
            )
            raise
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation in graph_rag_query task creation: %s. "
                "Start IDs: %s, K-hops: %s, Top-K: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, top_k, agent_id, organ_id
            )
            raise
        except OperationalError as e:
            logger.error(
                "Database operational error in graph_rag_query task creation: %s. "
                "Start IDs: %s, K-hops: %s, Top-K: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, top_k, agent_id, organ_id
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error in graph_rag_query task creation: %s. "
                "Start IDs: %s, K-hops: %s, Top-K: %s, Agent: %s, Organ: %s",
                str(e), start_ids, k_hops, top_k, agent_id, organ_id
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error in graph_rag_query task creation: %s. "
                "Start IDs: %s, K-hops: %s, Top-K: %s, Agent: %s, Organ: %s, Params: %s",
                str(e), start_ids, k_hops, top_k, agent_id, organ_id, params
            )
            raise

    def _create_generic_task(
        self,
        task_type: str,
        params: Mapping[str, Any],
        description: Optional[str],
        agent_id: Optional[str],
        organ_id: Optional[str],
    ) -> UUID:
        try:
            stmt = text(
                """
                INSERT INTO tasks (type, status, description, params)
                VALUES (:task_type, :status, :description, CAST(:params AS jsonb))
                RETURNING id
                """
            )
            json_params = json.dumps(params or {})

            with self._engine.begin() as conn:
                result = conn.execute(
                    stmt,
                    {
                        "task_type": task_type,
                        "status": "queued",
                        "description": description,
                        "params": json_params,
                    },
                )
                task_id = result.scalar_one()

                if agent_id:
                    self._ensure_agent(conn, agent_id)
                    conn.execute(
                        text(
                            """
                            INSERT INTO task_owned_by_agent (task_id, agent_id)
                            VALUES (:task_id, :agent_id)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {"task_id": task_id, "agent_id": agent_id},
                    )

                if organ_id:
                    self._ensure_organ(conn, organ_id, agent_id)
                    conn.execute(
                        text(
                            """
                            INSERT INTO task_executed_by_organ (task_id, organ_id)
                            VALUES (:task_id, :organ_id)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {"task_id": task_id, "organ_id": organ_id},
                    )

            return self._coerce_uuid(task_id)
        except (TypeError, ValueError) as e:
            logger.error(
                "JSON serialization error in generic task creation: %s. "
                "Task type: %s, Params: %s",
                str(e), task_type, params
            )
            raise
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation in generic task creation: %s. "
                "Task type: %s, Agent: %s, Organ: %s",
                str(e), task_type, agent_id, organ_id
            )
            raise
        except OperationalError as e:
            logger.error(
                "Database operational error in generic task creation: %s. "
                "Task type: %s, Agent: %s, Organ: %s",
                str(e), task_type, agent_id, organ_id
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error in generic task creation: %s. "
                "Task type: %s, Agent: %s, Organ: %s, Params: %s",
                str(e), task_type, agent_id, organ_id, params
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error in generic task creation: %s. "
                "Task type: %s, Agent: %s, Organ: %s, Params: %s",
                str(e), task_type, agent_id, organ_id, params
            )
            raise

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_uuid(value: Any) -> UUID:
        if isinstance(value, UUID):
            return value
        return UUID(str(value))

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_int_list(params: Mapping[str, Any], *keys: str) -> list[int]:
        for key in keys:
            raw = params.get(key)
            if raw is None:
                continue
            if isinstance(raw, (list, tuple, set)):
                ints: list[int] = []
                for item in raw:
                    coerced = GraphTaskSqlRepository._coerce_int(item)
                    if coerced is None:
                        raise ValueError(f"All entries for '{key}' must be integers")
                    ints.append(coerced)
                if ints:
                    return ints
            # allow comma-separated string
            if isinstance(raw, str):
                values = [x.strip() for x in raw.split(",") if x.strip()]
                ints = [GraphTaskSqlRepository._coerce_int(x) for x in values]
                if any(v is None for v in ints):
                    raise ValueError(f"All entries for '{key}' must be integers")
                if ints:
                    return [int(v) for v in ints if v is not None]
        return []

    @staticmethod
    def _ensure_agent(conn, agent_id: str) -> None:
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_registry (agent_id)
                    VALUES (:agent_id)
                    ON CONFLICT (agent_id) DO NOTHING
                    """
                ),
                {"agent_id": agent_id},
            )
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation while ensuring agent %s: %s",
                agent_id, str(e)
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error while ensuring agent %s: %s",
                agent_id, str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error while ensuring agent %s: %s",
                agent_id, str(e)
            )
            raise

    @staticmethod
    def _ensure_organ(conn, organ_id: str, agent_id: Optional[str]) -> None:
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO organ_registry (organ_id, agent_id)
                    VALUES (:organ_id, :agent_id)
                    ON CONFLICT (organ_id) DO NOTHING
                    """
                ),
                {"organ_id": organ_id, "agent_id": agent_id},
            )
        except IntegrityError as e:
            logger.error(
                "Integrity constraint violation while ensuring organ %s (agent: %s): %s",
                organ_id, agent_id, str(e)
            )
            raise
        except SQLAlchemyError as e:
            logger.error(
                "SQLAlchemy error while ensuring organ %s (agent: %s): %s",
                organ_id, agent_id, str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error while ensuring organ %s (agent: %s): %s",
                organ_id, agent_id, str(e)
            )
            raise

