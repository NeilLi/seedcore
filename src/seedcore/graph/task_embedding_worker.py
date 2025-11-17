"""Asynchronous task embedding producer/consumer for LTM embeddings."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from seedcore.database import get_async_pg_session_factory
from seedcore.utils.ray_utils import ensure_ray_initialized
from prometheus_client import Counter

logger = logging.getLogger(__name__)

TASK_EMBED_LABEL = os.getenv("TASK_EMBED_LABEL", "task.primary")
TASK_EMBED_MODEL = os.getenv("TASK_EMBED_MODEL", "seedcore-ltm-fusion-v1")
TASK_EMBED_K_HOPS = int(os.getenv("TASK_EMBED_K_HOPS", "2"))
TASK_EMBED_TEXT_MAX_CHARS = int(os.getenv("TASK_EMBED_TEXT_MAX_CHARS", "16000"))
TASK_EMBED_BACKFILL_INTERVAL_S = int(os.getenv("TASK_EMBED_BACKFILL_INTERVAL_S", "120"))
TASK_EMBED_BACKFILL_BATCH = int(os.getenv("TASK_EMBED_BACKFILL_BATCH", "250"))

AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
LTM_EMBEDDER_ACTOR_NAME = os.getenv("TASK_EMBEDDER_ACTOR_NAME", "seedcore_ltm_embedder")

VALID_TASK_EMBED_LABELS = frozenset({"task.primary", "task.output", "default"})

if TASK_EMBED_LABEL not in VALID_TASK_EMBED_LABELS:
    logger.warning(
        "TASK_EMBED_LABEL=%s is not in the recognised label set %s; downstream consumers must "
        "be prepared for this custom label.",
        TASK_EMBED_LABEL,
        sorted(VALID_TASK_EMBED_LABELS),
    )


@dataclass(frozen=True)
class TaskEmbeddingJob:
    task_id: str
    reason: str = "unspecified"


async def enqueue_task_embedding_job(app_state: Any, task_id: UUID | str, *, reason: str = "manual") -> bool:
    """Enqueue a task for embedding if the background worker is available."""

    queue = getattr(app_state, "task_embedding_queue", None)
    pending = getattr(app_state, "task_embedding_pending", None)
    lock = getattr(app_state, "task_embedding_pending_lock", None)

    if queue is None or pending is None or lock is None:
        logger.debug("Task embedding queue not initialized; skipping enqueue for %s", task_id)
        return False

    task_id_str = str(task_id)
    async with lock:
        if task_id_str in pending:
            logger.debug("Task %s already pending embedding (reason=%s)", task_id_str, reason)
            LTM_EMBED_ENQUEUE_DEDUPE.labels(reason).inc()
            return False
        pending.add(task_id_str)
        await queue.put(TaskEmbeddingJob(task_id=task_id_str, reason=reason))
        logger.debug("Enqueued task %s for embedding (reason=%s)", task_id_str, reason)
        LTM_EMBED_ENQUEUE_OK.labels(reason).inc()
        return True


async def task_embedding_worker(app_state: Any) -> None:
    """Background worker that refreshes task embeddings using the LTM embedder."""

    queue = getattr(app_state, "task_embedding_queue", None)
    pending = getattr(app_state, "task_embedding_pending", None)
    lock = getattr(app_state, "task_embedding_pending_lock", None)
    if queue is None:
        logger.warning("Task embedding queue missing; worker exiting")
        return

    session_factory = get_async_pg_session_factory()
    embedder_handle = None

    def _get_embedder():
        nonlocal embedder_handle
        if embedder_handle is not None:
            return embedder_handle
        if not ensure_ray_initialized():
            logger.warning("Ray not initialized; cannot obtain LTM embedder")
            return None
        import ray
        from seedcore.graph.ltm_embeddings import LTMEmbedder

        try:
            embedder_handle = ray.get_actor(LTM_EMBEDDER_ACTOR_NAME, namespace=AGENT_NAMESPACE)
            logger.debug("Reusing existing LTMEmbedder actor '%s'", LTM_EMBEDDER_ACTOR_NAME)
        except ValueError:
            logger.info("Creating LTMEmbedder actor '%s' (namespace=%s)", LTM_EMBEDDER_ACTOR_NAME, AGENT_NAMESPACE)
            embedder_handle = LTMEmbedder.options(
                name=LTM_EMBEDDER_ACTOR_NAME,
                namespace=AGENT_NAMESPACE,
                lifetime="detached",
            ).remote()
        return embedder_handle

    while True:
        job: TaskEmbeddingJob = await queue.get()
        try:
            async with session_factory() as session:
                task_id = job.task_id

                # Ensure the task node exists and fetch the numeric node id.
                ensure_result = await session.execute(
                    text("SELECT ensure_task_node(CAST(:tid AS uuid)) AS node_id"),
                    {"tid": task_id},
                )
                node_id = ensure_result.scalar_one_or_none()
                if node_id is None:
                    logger.warning("ensure_task_node returned NULL for task %s", task_id)
                    await session.rollback()
                    continue

                await session.commit()

                task_row = await session.execute(
                    text(
                        """
                        SELECT
                          t.id::text AS task_id,
                          t.type,
                          t.description,
                          jsonb_pretty(t.params) AS params_pretty
                        FROM tasks t
                        WHERE t.id = CAST(:tid AS uuid)
                        """
                    ),
                    {"tid": task_id},
                )
                row = task_row.mappings().first()
                if not row:
                    logger.debug("Task %s no longer exists; skipping embedding", task_id)
                    await session.rollback()
                    continue

                text_blob = build_task_text(
                    description=row.get("description"),
                    task_type=row.get("type"),
                    params_pretty=row.get("params_pretty"),
                )
                if not text_blob:
                    logger.debug("Task %s has empty embedding payload; skipping", task_id)
                    await session.rollback()
                    continue
                content_hash = sha256(text_blob.encode("utf-8")).hexdigest()

                existing_hash = await session.execute(
                    text(
                        """
                        SELECT content_sha256
                          FROM graph_embeddings_128
                         WHERE node_id = :nid
                           AND label = :label
                        """
                    ),
                    {"nid": int(node_id), "label": TASK_EMBED_LABEL},
                )
                existing = existing_hash.scalar_one_or_none()
                if existing and existing == content_hash:
                    logger.debug(
                        "Task %s embedding up-to-date (hash=%s); skipping", task_id, content_hash
                    )
                    await session.rollback()
                    LTM_EMBED_JOB_SKIPPED.labels(job.reason, "up_to_date").inc()
                    continue

                embedder = _get_embedder()
                if embedder is None:
                    logger.warning("No LTM embedder available; task %s re-queued", task_id)
                    await queue.put(job)
                    await asyncio.sleep(1)
                    await session.rollback()
                    continue

                props: Dict[str, Any] = {
                    "source": "tasks.description+type+params",
                    "len_chars": len(text_blob),
                    "sha256": content_hash,
                    "reason": job.reason,
                    "model": TASK_EMBED_MODEL,
                }

                import ray
                from ray.exceptions import RayActorError

                try:
                    result = await asyncio.to_thread(
                        ray.get,
                        embedder.upsert_task_embeddings.remote(
                            [int(node_id)],
                            k=TASK_EMBED_K_HOPS,
                            label=TASK_EMBED_LABEL,
                            props_map={int(node_id): props},
                            model_map={int(node_id): TASK_EMBED_MODEL},
                            content_hash_map={int(node_id): content_hash},
                        ),
                    )
                except RayActorError as exc:
                    logger.warning(
                        "Ray actor error while embedding task %s: %s; recreating actor and re-queuing",
                        task_id,
                        exc,
                    )
                    embedder_handle = None
                    await queue.put(job)
                    await asyncio.sleep(1)
                    await session.rollback()
                    LTM_EMBED_JOB_REQUEUED.labels(job.reason, "actor_error").inc()
                    continue
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Embedding failed for task %s: %s", task_id, exc)
                    await queue.put(job)
                    await asyncio.sleep(1)
                    await session.rollback()
                    LTM_EMBED_JOB_REQUEUED.labels(job.reason, "exception").inc()
                    continue
                logger.debug(
                    "Task %s embedding updated via LTM (node_id=%s, upserted=%s)",
                    task_id,
                    node_id,
                    result.get("upserted"),
                )
                await session.commit()
                LTM_EMBED_JOB_PROCESSED.labels(job.reason).inc()
        except SQLAlchemyError as exc:
            logger.exception("Database error while processing embedding for %s: %s", job.task_id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error while embedding task %s: %s", job.task_id, exc)
        finally:
            if lock is not None and pending is not None:
                async with lock:
                    pending.discard(job.task_id)
            queue.task_done()


# Prometheus metrics
LTM_EMBED_ENQUEUE_OK = Counter(
    "ltm_embed_enqueue_ok_total",
    "Number of LTM embedding jobs enqueued",
    ["reason"],
)
LTM_EMBED_ENQUEUE_DEDUPE = Counter(
    "ltm_embed_enqueue_dedupe_total",
    "Number of LTM embedding enqueues deduped/skipped",
    ["reason"],
)
LTM_EMBED_JOB_PROCESSED = Counter(
    "ltm_embed_jobs_processed_total",
    "Number of LTM embedding jobs processed successfully",
    ["reason"],
)
LTM_EMBED_JOB_SKIPPED = Counter(
    "ltm_embed_jobs_skipped_total",
    "Number of LTM embedding jobs skipped",
    ["reason", "why"],
)
LTM_EMBED_JOB_REQUEUED = Counter(
    "ltm_embed_jobs_requeued_total",
    "Number of LTM embedding jobs requeued after transient failures",
    ["reason", "why"],
)


async def task_embedding_backfill_loop(app_state: Any) -> None:
    """Periodic job that enqueues tasks missing embeddings."""

    queue = getattr(app_state, "task_embedding_queue", None)
    if queue is None:
        logger.debug("Task embedding queue missing; backfill loop exiting")
        return

    session_factory = get_async_pg_session_factory()

    while True:
        try:
            async with session_factory() as session:
                rows = await session.execute(
                    text(
                        """
                        SELECT task_id::text
                          FROM tasks_missing_embeddings_128
                         LIMIT :limit
                        """
                    ),
                    {"limit": TASK_EMBED_BACKFILL_BATCH},
                )
                for row in rows.scalars():
                    await enqueue_task_embedding_job(
                        app_state,
                        row,
                        reason="backfill",
                    )

                stale_rows = await session.execute(
                    text(
                        """
                        SELECT DISTINCT task_id::text
                          FROM task_embeddings_stale_128
                         LIMIT :limit
                        """
                    ),
                    {"limit": TASK_EMBED_BACKFILL_BATCH},
                )
                for row in stale_rows.scalars():
                    await enqueue_task_embedding_job(
                        app_state,
                        row,
                        reason="stale",
                    )
        except SQLAlchemyError as exc:
            logger.exception("Database error during embedding backfill: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error during embedding backfill: %s", exc)

        await asyncio.sleep(max(5, TASK_EMBED_BACKFILL_INTERVAL_S))


def build_task_text(
    *,
    description: Optional[str],
    task_type: Optional[str],
    params_pretty: Optional[str],
) -> str:
    """Build the deterministic text payload used for hashing and observability."""

    parts = []
    if description:
        trimmed = description.strip()
        if trimmed:
            parts.append(trimmed)
    if task_type:
        trimmed = task_type.strip()
        if trimmed:
            parts.append(trimmed)
    if params_pretty:
        trimmed = params_pretty.strip()
        if trimmed:
            parts.append(trimmed)

    text_blob = "\n".join(parts)
    if len(text_blob) > TASK_EMBED_TEXT_MAX_CHARS:
        text_blob = text_blob[:TASK_EMBED_TEXT_MAX_CHARS]
    return text_blob
