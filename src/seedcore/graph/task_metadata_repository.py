"""Repository helpers for persisting HGNN task graph metadata."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional, Union

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError, DataError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from seedcore.database import get_async_pg_session_factory
from seedcore.models.task import Task

logger = logging.getLogger(__name__)


class TaskMetadataRepository:
    """Lightweight repository for persisting task graph metadata.

    The repository exposes high-level helpers that take care of:
    - creating or updating task rows
    - wiring cross-layer edges (task↔agent, task↔organ)
    - materialising node ids via the ``ensure_*`` helper functions
    - adding task dependencies for HGNN plans

    All public methods wrap their statements in database transactions to
    prevent dangling edges when inserts fail midway.
    """

    def __init__(self, session_factory: Optional[async_sessionmaker[AsyncSession]] = None) -> None:
        self._session_factory = session_factory or get_async_pg_session_factory()

    async def create_task(
        self,
        metadata: Dict[str, Any],
        *,
        agent_id: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> uuid.UUID:
        """Create or update a task and its cross-layer edges.

        Args:
            metadata: Raw task metadata (must include ``type``; ``id`` optional).
            agent_id: Logical agent owner for the task.
            organ_id: Organ that will execute the task.

        Returns:
            The UUID of the persisted task.
        """

        task_dict = dict(metadata or {})
        task_id = self._coerce_task_id(task_dict.get("id") or task_dict.get("task_id"))
        task_dict["id"] = str(task_id)

        task_type = (task_dict.get("type") or task_dict.get("task_type") or "unknown").strip() or "unknown"
        description = task_dict.get("description") or ""
        params = task_dict.get("params") if isinstance(task_dict.get("params"), dict) else {}
        domain = task_dict.get("domain")
        drift_score = self._coerce_float(task_dict.get("drift_score"))

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    task_obj = await session.get(Task, task_id)
                    if task_obj:
                        updated = False
                        if task_obj.type != task_type:
                            task_obj.type = task_type
                            updated = True
                        if description and task_obj.description != description:
                            task_obj.description = description
                            updated = True
                        if params is not None and task_obj.params != params:
                            task_obj.params = params
                            updated = True
                        if domain is not None and task_obj.domain != domain:
                            task_obj.domain = domain
                            updated = True
                        if drift_score is not None and task_obj.drift_score != drift_score:
                            task_obj.drift_score = drift_score
                            updated = True
                        if updated:
                            await session.flush()
                    else:
                        task_obj = Task(
                            id=task_id,
                            type=task_type,
                            description=description,
                            params=params,
                            domain=domain,
                            drift_score=drift_score if drift_score is not None else 0.0,
                        )
                        session.add(task_obj)
                        await session.flush()

                    if agent_id:
                        await session.execute(
                            text(
                                """
                                INSERT INTO agent_registry (agent_id)
                                VALUES (:agent_id)
                                ON CONFLICT (agent_id) DO NOTHING
                                """
                            ),
                            {"agent_id": agent_id},
                        )
                        await session.execute(
                            text(
                                """
                                INSERT INTO task_owned_by_agent (task_id, agent_id)
                                VALUES (:task_id, :agent_id)
                                ON CONFLICT DO NOTHING
                                """
                            ),
                            {"task_id": task_id, "agent_id": agent_id},
                        )
                        await session.execute(
                            text("SELECT ensure_agent_node(:agent_id)"),
                            {"agent_id": agent_id},
                        )

                    if organ_id:
                        await session.execute(
                            text(
                                """
                                INSERT INTO organ_registry (organ_id, agent_id)
                                VALUES (:organ_id, :agent_id)
                                ON CONFLICT (organ_id) DO UPDATE
                                SET agent_id = COALESCE(EXCLUDED.agent_id, organ_registry.agent_id)
                                """
                            ),
                            {"organ_id": organ_id, "agent_id": agent_id},
                        )
                        await session.execute(
                            text(
                                """
                                INSERT INTO task_executed_by_organ (task_id, organ_id)
                                VALUES (:task_id, :organ_id)
                                ON CONFLICT DO NOTHING
                                """
                            ),
                            {"task_id": task_id, "organ_id": organ_id},
                        )
                        await session.execute(
                            text("SELECT ensure_organ_node(:organ_id)"),
                            {"organ_id": organ_id},
                        )

                    await session.execute(
                        text("SELECT ensure_task_node(:task_id)"),
                        {"task_id": task_id},
                    )

                return task_id
            except IntegrityError as e:
                logger.error(
                    "Integrity constraint violation while persisting task %s: %s. "
                    "This may indicate duplicate task_id or invalid foreign key references.",
                    task_id, str(e)
                )
                raise
            except OperationalError as e:
                logger.error(
                    "Database operational error while persisting task %s: %s. "
                    "This may indicate connection issues or database unavailability.",
                    task_id, str(e)
                )
                raise
            except DataError as e:
                logger.error(
                    "Data error while persisting task %s: %s. "
                    "This may indicate invalid data types or constraint violations.",
                    task_id, str(e)
                )
                raise
            except SQLAlchemyError as e:
                logger.error(
                    "SQLAlchemy error while persisting task %s: %s. "
                    "Task metadata: type=%s, agent_id=%s, organ_id=%s",
                    task_id, str(e), task_type, agent_id, organ_id
                )
                raise
            except Exception as e:
                logger.error(
                    "Unexpected error while persisting task %s: %s. "
                    "Task metadata: type=%s, agent_id=%s, organ_id=%s",
                    task_id, str(e), task_type, agent_id, organ_id
                )
                raise

    async def add_dependency(
        self,
        parent_task_id: Union[str, uuid.UUID],
        child_task_id: Union[str, uuid.UUID],
    ) -> None:
        """Insert a dependency edge (parent depends on child)."""

        parent_id = self._coerce_task_id(parent_task_id)
        child_id = self._coerce_task_id(child_task_id)
        if parent_id == child_id:
            logger.debug("Skipping self-dependency for task %s", parent_id)
            return

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    await session.execute(
                        text(
                            """
                            INSERT INTO task_depends_on_task (src_task_id, dst_task_id)
                            VALUES (:src, :dst)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {"src": parent_id, "dst": child_id},
                    )
                    await session.execute(text("SELECT ensure_task_node(:task_id)"), {"task_id": parent_id})
                    await session.execute(text("SELECT ensure_task_node(:task_id)"), {"task_id": child_id})
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

    @staticmethod
    def _coerce_task_id(value: Optional[Union[str, uuid.UUID]]) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        if value:
            try:
                return uuid.UUID(str(value))
            except (ValueError, TypeError):
                logger.debug("Invalid task id %s, generating new UUID", value)
        return uuid.uuid4()

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
