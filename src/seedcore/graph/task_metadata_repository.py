"""Repository helpers for persisting HGNN task graph metadata.

This repository is stateless and centralizes CRUD helpers for task metadata.
It expects an ``AsyncSession`` to be injected into its methods.

The caller is responsible for session lifecycle and transaction management
(e.g., ``async with session.begin()``).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError, DataError
from sqlalchemy.ext.asyncio import AsyncSession

from seedcore.models import DatabaseTask as Task

logger = logging.getLogger(__name__)


class TaskMetadataRepository:
    """Lightweight, stateless repository for persisting task graph metadata.

    This class provides high-level helpers that take care of:
    - creating or updating task rows
    - wiring cross-layer edges (task↔agent, task↔organ)
    - materialising node ids via the ``ensure_*`` helper functions
    - adding task dependencies for HGNN plans

    All public methods must be passed an ``AsyncSession`` and are designed
    to be run within a transaction managed by the caller.
    """

    async def create_task(
        self,
        session: AsyncSession,
        metadata: Dict[str, Any],
        *,
        agent_id: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> uuid.UUID:
        """Create or update a task and its cross-layer edges.

        Args:
            session: The AsyncSession to use for database operations.
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

        try:
            # The caller is responsible for `session.begin()`
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
                text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
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

    async def get_task_context(
        self,
        session: AsyncSession,
        task_id: Union[str, uuid.UUID],
    ) -> Optional[Dict[str, Any]]:
        """Fetch task context (params, history, graph neighbors) for cognitive processing.

        Used by CognitiveCore for server-side hydration.

        Args:
            session: The AsyncSession to use for database operations.
            task_id: The UUID or string ID of the task to fetch.

        Returns:
            Dictionary containing task data and dependencies, or None if task not found.
        """
        tid = self._coerce_task_id(task_id)

        try:
            # 1. Fetch Core Task Data
            task_obj = await session.get(Task, tid)
            if not task_obj:
                return None

            result = {
                "task_id": str(task_obj.id),
                "type": task_obj.type,
                "description": task_obj.description,
                "params": task_obj.params,
                "domain": task_obj.domain,
                "drift_score": task_obj.drift_score
            }

            # 2. Fetch Dependency Graph (Optional but useful for Context)
            # "What tasks does this task depend on?" (History/Prerequisites)
            # Query: Find all tasks where this task (src_task_id) depends on them (dst_task_id)
            stmt = text("""
                SELECT t.id, t.type, t.description 
                FROM tasks t
                JOIN task_depends_on_task dep ON t.id = dep.dst_task_id
                WHERE dep.src_task_id = :tid
            """)
            deps_result = await session.execute(stmt, {"tid": tid})
            result["dependencies"] = [
                {"id": str(row.id), "type": row.type, "description": row.description}
                for row in deps_result
            ]

            return result

        except SQLAlchemyError as e:
            logger.error(f"Failed to fetch task context for {tid}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while fetching task context for {tid}: {e}")
            return None

    async def add_dependency(
        self,
        session: AsyncSession,
        parent_task_id: Union[str, uuid.UUID],
        child_task_id: Union[str, uuid.UUID],
    ) -> None:
        """Insert a dependency edge (parent depends on child).

        Args:
            session: The AsyncSession to use for database operations.
            parent_task_id: The UUID of the task that has the dependency.
            child_task_id: The UUID of the task that must be completed first.
        """

        parent_id = self._coerce_task_id(parent_task_id)
        child_id = self._coerce_task_id(child_task_id)
        if parent_id == child_id:
            logger.debug("Skipping self-dependency for task %s", parent_id)
            return

        try:
            # The caller is responsible for `session.begin()`
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
            await session.execute(
                text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
                {"task_id": parent_id},
            )
            await session.execute(
                text("SELECT ensure_task_node(CAST(:task_id AS uuid))"),
                {"task_id": child_id},
            )
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

    async def find_hgnn_neighbors(
        self,
        session: AsyncSession,
        embedding: List[float],
        k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Converts an HGNN embedding into a list of semantic graph nodes.
        Requires 'pgvector' extension in Postgres.

        Args:
            session: The AsyncSession to use for database operations.
            embedding: The HGNN embedding vector (list of floats).
            k: Number of nearest neighbors to return (default: 10).

        Returns:
            List of dictionaries containing node information and similarity scores.
            Each dict has: id, type, description, similarity
        """
        # Determine table name based on embedding dimension
        # Default to 128d table, but could be extended to support 1024d
        dim = len(embedding)
        if dim == 128:
            table_name = "graph_embeddings_128"
        elif dim == 1024:
            table_name = "graph_embeddings_1024"
        else:
            # Fallback: try to use graph_embeddings_128 and let DB handle dimension mismatch
            logger.warning(f"Unexpected embedding dimension {dim}, using graph_embeddings_128")
            table_name = "graph_embeddings_128"

        # Ensure embedding is string formatted for SQL (e.g. '[0.1, 0.2, ...]')
        import json
        embedding_str = json.dumps(embedding)

        stmt = text(f"""
            SELECT 
                ge.node_id,
                gnm.node_type as type,
                ge.props->>'description' as description,
                1 - (ge.emb <=> CAST(:vec AS vector)) as similarity
            FROM {table_name} ge
            LEFT JOIN graph_node_map gnm ON ge.node_id = gnm.node_id
            ORDER BY ge.emb <=> CAST(:vec AS vector)
            LIMIT :k
        """)

        try:
            result = await session.execute(stmt, {"vec": embedding_str, "k": k})
            neighbors = []
            for row in result:
                neighbors.append({
                    "id": str(row.node_id),
                    "type": row.type or "unknown",
                    "description": row.description or "",
                    "similarity": float(row.similarity) if row.similarity is not None else 0.0,
                })
            return neighbors
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
