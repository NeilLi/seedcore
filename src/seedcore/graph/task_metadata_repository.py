"""Repository helpers for persisting HGNN task graph metadata.

This repository is stateless and centralizes CRUD helpers for task metadata.
It expects an ``AsyncSession`` to be injected into its methods.

The caller is responsible for session lifecycle and transaction management
(e.g., ``async with session.begin()``).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError, DataError  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from seedcore.models import DatabaseTask as Task

logger = logging.getLogger(__name__)


class TaskMetadataRepository:
    """Enhanced Repository for Unified Memory and Multimodal Task Metadata.

    This class provides high-level helpers that take care of:
    - creating or updating task rows
    - wiring cross-layer edges (task↔agent, task↔organ)
    - materialising node ids via the ``ensure_*`` helper functions
    - adding task dependencies for HGNN plans
    - persisting multimodal embeddings into Working Memory
    - querying across unified memory (Events + Knowledge Graph)
    - fetching complete multimodal task context

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

    async def save_task_multimodal_embedding(
        self,
        session: AsyncSession,
        task_id: uuid.UUID,
        embedding: List[float],
        source_modality: str = "text",
        model_version: str = "seedcore-v2-1024",
    ) -> None:
        """Persist a high-dimensional embedding into the Working Memory tier.

        This populates the 'task_multimodal_embeddings' table and ensures
        the Unified View is updated for immediate reading.

        Args:
            session: The AsyncSession to use for database operations.
            task_id: The UUID of the task to associate with this embedding.
            embedding: The high-dimensional embedding vector (list of floats).
            source_modality: The source modality (e.g., "text", "image", "audio").
            model_version: The model version used to generate the embedding.

        Raises:
            SQLAlchemyError: If database operations fail.
        """
        stmt = text("""
            INSERT INTO task_multimodal_embeddings (
                task_id, emb, source_modality, model_version, created_at
            )
            VALUES (:task_id, :emb, :modality, :version, NOW())
            ON CONFLICT (task_id, source_modality) DO UPDATE SET
                emb = EXCLUDED.emb,
                model_version = EXCLUDED.model_version,
                updated_at = NOW()
        """)
        try:
            await session.execute(stmt, {
                "task_id": task_id,
                "emb": json.dumps(embedding),
                "modality": source_modality,
                "version": model_version
            })
            # We flush here to ensure the Unified View is updated for immediate reading
            await session.flush()
        except SQLAlchemyError as e:
            logger.error(
                "Failed to persist multimodal embedding for task %s: %s. "
                "This may indicate invalid task_id or embedding dimension mismatch.",
                task_id, str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error while persisting multimodal embedding for task %s: %s",
                task_id, str(e)
            )
            raise

    async def query_unified_memory(
        self,
        session: AsyncSession,
        query_embedding: List[float],
        k: int = 5,
        min_similarity: float = 0.7,
        tier_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Perform semantic search across the entire Unified Memory View.

        This bridges the 'Now' (Tasks) and 'Always' (Knowledge Graph) tiers,
        allowing queries across both event_working and knowledge_base memory.

        Args:
            session: The AsyncSession to use for database operations.
            query_embedding: The query embedding vector (list of floats).
            k: Number of nearest neighbors to return (default: 5).
            min_similarity: Minimum similarity threshold (default: 0.7).
            tier_filter: Optional filter for memory tier (e.g., "event_working", "knowledge_base").

        Returns:
            List of dictionaries containing memory information and similarity scores.
            Each dict has: id, category, content, tier, metadata, similarity.
        """
        query_vec = json.dumps(query_embedding)

        # Build the dynamic filter for tiers (event_working vs knowledge_base)
        tier_clause = "AND memory_tier = :tier" if tier_filter else ""

        stmt = text(f"""
            SELECT 
                id, category, content, memory_tier, metadata,
                1 - (vector <=> CAST(:vec AS vector)) as similarity
            FROM v_unified_cortex_memory
            WHERE 1=1 {tier_clause}
            AND 1 - (vector <=> CAST(:vec AS vector)) >= :min_sim
            ORDER BY vector <=> CAST(:vec AS vector)
            LIMIT :k
        """)

        try:
            params = {"vec": query_vec, "k": k, "min_sim": min_similarity}
            if tier_filter:
                params["tier"] = tier_filter

            result = await session.execute(stmt, params)

            memories = []
            for row in result:
                memories.append({
                    "id": row.id,
                    "category": row.category,
                    "content": row.content,
                    "tier": row.memory_tier,
                    "metadata": row.metadata,
                    "similarity": float(row.similarity) if row.similarity is not None else 0.0,
                })
            return memories
        except SQLAlchemyError as e:
            logger.error(
                "Unified Memory query failed: %s. "
                "This may indicate the v_unified_cortex_memory view is not available or vector dimension mismatch.",
                str(e)
            )
            return []
        except Exception as e:
            logger.error(f"Unexpected error during Unified Memory query: {e}")
            return []

    async def find_similar_task(
        self,
        session: AsyncSession,
        embedding: List[float],
        threshold: float = 0.98,
        limit: int = 1,
        hours_back: int = 24
    ) -> Optional[Dict[str, Any]]:
        """Find a similar completed task by embedding similarity.
        
        Queries for completed tasks with similar embeddings within the specified
        time window. Used for semantic caching to avoid re-executing identical tasks.
        
        Args:
            session: The AsyncSession to use for database operations.
            embedding: The query embedding vector (list of floats).
            threshold: Minimum similarity threshold (default: 0.98 for near-exact matches).
            limit: Maximum number of results to return (default: 1).
            hours_back: Number of hours to look back (default: 24).
        
        Returns:
            Dictionary with task id, result, and similarity score, or None if no match found.
        """
        embedding_str = json.dumps(embedding)
        
        stmt = text(f"""
            SELECT 
                t.id,
                t.result,
                t.description,
                t.created_at,
                1 - (tme.emb <=> CAST(:vec AS vector)) as similarity
            FROM tasks t
            INNER JOIN task_multimodal_embeddings tme ON t.id = tme.task_id
            WHERE t.status = 'completed'
                AND t.result IS NOT NULL
                AND tme.source_modality = 'text'
                AND t.created_at >= NOW() - INTERVAL '{hours_back} hours'
                AND 1 - (tme.emb <=> CAST(:vec AS vector)) >= :threshold
            ORDER BY tme.emb <=> CAST(:vec AS vector)
            LIMIT :limit
        """)
        
        try:
            result = await session.execute(stmt, {
                "vec": embedding_str,
                "threshold": threshold,
                "limit": limit
            })
            
            row = result.fetchone()
            if row:
                return {
                    "id": str(row.id),
                    "result": row.result if isinstance(row.result, dict) else json.loads(row.result) if row.result else None,
                    "description": row.description,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "similarity": float(row.similarity) if row.similarity is not None else 0.0,
                }
            return None
        except SQLAlchemyError as e:
            logger.error(
                "Similar task query failed: %s. "
                "This may indicate the task_multimodal_embeddings table is not available or vector dimension mismatch.",
                str(e)
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error during similar task query: {e}")
            return None

    async def get_multimodal_task_context(
        self,
        session: AsyncSession,
        task_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """Fetch the complete multimodal context for a task.

        Retrieves task data from the Unified View, including refined text
        and media pointers. This feeds the Coordinator and PKG with
        high-fidelity signals (like standard 24h time or S3 media links)
        without multiple table joins.

        Args:
            session: The AsyncSession to use for database operations.
            task_id: The UUID of the task to fetch.

        Returns:
            Dictionary containing multimodal task context, or None if task not found.
            Contains: id, type, description, memory_tier, multimodal_params, grounded_time.
        """
        stmt = text("""
            SELECT * FROM v_unified_cortex_memory 
            WHERE id = :task_id::text 
            LIMIT 1
        """)
        try:
            result = await session.execute(stmt, {"task_id": str(task_id)})
            row = result.fetchone()
            if not row:
                return None

            metadata = row.metadata if isinstance(row.metadata, dict) else {}
            return {
                "id": row.id,
                "type": row.category,
                "description": row.content,
                "memory_tier": row.memory_tier,
                "multimodal_params": metadata.get("multimodal") if metadata else None,
                "grounded_time": metadata.get("grounded_time") if metadata else None
            }
        except SQLAlchemyError as e:
            logger.error(
                "Failed to fetch multimodal context for task %s: %s. "
                "This may indicate the v_unified_cortex_memory view is not available.",
                task_id, str(e)
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error while fetching multimodal context for task %s: %s",
                task_id, str(e)
            )
            return None

    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
