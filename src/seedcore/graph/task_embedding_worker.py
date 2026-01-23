"""
Unified Task Embedding System for SeedCore.
Focuses on 1024d embeddings for the Knowledge Graph and Unified Cortex.
This module supports both synchronous execution (Coordinator) and background workers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Union
from uuid import UUID

from sqlalchemy import text  # pyright: ignore[reportMissingImports]
from prometheus_client import Counter  # pyright: ignore[reportMissingImports]

from seedcore.database import get_async_pg_session_factory
from seedcore.utils.ray_utils import ensure_ray_initialized

logger = logging.getLogger(__name__)

# --- Configuration Constants ---
TASK_EMBED_LABEL = os.getenv("TASK_EMBED_LABEL", "task.primary")
TASK_EMBED_MODEL = os.getenv("TASK_EMBED_MODEL", "text-embedding-004")
TASK_EMBED_K_HOPS = int(os.getenv("TASK_EMBED_K_HOPS", "2"))
TASK_EMBED_TEXT_MAX_CHARS = int(os.getenv("TASK_EMBED_TEXT_MAX_CHARS", "16000"))
TASK_EMBED_BACKFILL_INTERVAL_S = int(os.getenv("TASK_EMBED_BACKFILL_INTERVAL_S", "120"))
TASK_EMBED_BACKFILL_BATCH = int(os.getenv("TASK_EMBED_BACKFILL_BATCH", "250"))

AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
LTM_EMBEDDER_ACTOR_NAME = os.getenv("TASK_EMBEDDER_ACTOR_NAME", "seedcore_ltm_embedder")

VALID_TASK_EMBED_LABELS = frozenset({"task.primary", "task.output", "default"})

if TASK_EMBED_LABEL not in VALID_TASK_EMBED_LABELS:
    logger.warning(
        "TASK_EMBED_LABEL=%s not in recognised set %s; ensure views are aligned.",
        TASK_EMBED_LABEL,
        sorted(VALID_TASK_EMBED_LABELS),
    )

# --- Metrics ---
LTM_EMBED_ENQUEUE_OK = Counter(
    "ltm_embed_enqueue_ok_total", "Jobs enqueued", ["reason"]
)
LTM_EMBED_ENQUEUE_DEDUPE = Counter(
    "ltm_embed_enqueue_dedupe_total", "Enqueues skipped (already pending)", ["reason"]
)
LTM_EMBED_JOB_PROCESSED = Counter(
    "ltm_embed_jobs_processed_total", "Successful 1024d embeddings", ["reason"]
)
LTM_EMBED_JOB_SKIPPED = Counter(
    "ltm_embed_jobs_skipped_total", "Skipped embeddings", ["reason", "why"]
)
LTM_EMBED_JOB_REQUEUED = Counter(
    "ltm_embed_jobs_requeued_total", "Transient failures re-queued", ["reason", "why"]
)


@dataclass(frozen=True)
class TaskEmbeddingJob:
    task_id: str
    reason: str = "unspecified"


# --- Shared Logic ---


def build_task_text(
    description: Optional[str], task_type: Optional[str], params_pretty: Optional[str]
) -> str:
    """Builds the deterministic text payload used for hashing and embedding."""
    parts = [
        p.strip() for p in [description, task_type, params_pretty] if p and p.strip()
    ]
    text_blob = "\n".join(parts)
    return text_blob[:TASK_EMBED_TEXT_MAX_CHARS]


async def _get_embedder_handle():
    """Obtains the Ray Actor handle for the LTM Embedder."""
    if not ensure_ray_initialized():
        logger.warning("Ray not initialized; cannot obtain LTM embedder")
        return None
    import ray  # pyright: ignore[reportMissingImports]

    try:
        return ray.get_actor(LTM_EMBEDDER_ACTOR_NAME, namespace=AGENT_NAMESPACE)
    except ValueError:
        logger.debug("Creating LTMEmbedder actor '%s'", LTM_EMBEDDER_ACTOR_NAME)
        # In production, usually the bootstrap script starts this, but we provide a fallback
        from seedcore.graph.ltm_embeddings import LTMEmbedder

        return LTMEmbedder.options(
            name=LTM_EMBEDDER_ACTOR_NAME, namespace=AGENT_NAMESPACE, lifetime="detached"
        ).remote()


# --- The "Coordinator" Direct Execution Function ---


async def generate_and_persist_task_embedding(
    task_id: Union[UUID, str],
    description: Optional[str],
    task_type: Optional[str],
    params: Dict[str, Any],
    reason: str = "coordinator_execute",
) -> Optional[List[float]]:
    """
    Primary 1024d embedding logic.
    1. Checks for changes via SHA256.
    2. Calls Ray for 1024d vector.
    3. Persists to graph_embeddings_1024.
    """
    task_id_str = str(task_id)
    params_pretty = json.dumps(params, indent=2)
    text_blob = build_task_text(description, task_type, params_pretty)

    if not text_blob:
        logger.debug("Task %s has empty embedding payload; skipping", task_id_str)
        LTM_EMBED_JOB_SKIPPED.labels(reason, "empty_content").inc()
        return None

    content_hash = hashlib.sha256(text_blob.encode("utf-8")).hexdigest()
    session_factory = get_async_pg_session_factory()

    try:
        async with session_factory() as session:
            # 1. Ensure node mapping exists
            ensure_result = await session.execute(
                text("SELECT ensure_task_node(CAST(:tid AS uuid))"),
                {"tid": task_id_str},
            )
            node_id = ensure_result.scalar_one_or_none()
            if node_id is None:
                logger.warning("ensure_task_node returned NULL for %s", task_id_str)
                return None

            # 2. Check for existing identical embedding
            existing = await session.execute(
                text("""
                    SELECT emb FROM graph_embeddings_1024 
                    WHERE node_id = :nid AND label = :label AND content_sha256 = :hash
                """),
                {"nid": node_id, "label": TASK_EMBED_LABEL, "hash": content_hash},
            )
            vec = existing.scalar_one_or_none()
            if vec:
                logger.debug(
                    "Task %s 1024d embedding up-to-date; skipping Ray call", task_id_str
                )
                LTM_EMBED_JOB_SKIPPED.labels(reason, "up_to_date").inc()
                return vec

            # 3. Ray Execution
            embedder = await _get_embedder_handle()
            if not embedder:
                return None

            import ray  # pyright: ignore[reportMissingImports]

            # Note: We use the remote actor to generate the 1024d vector
            # The 'k' hops logic is handled within the actor's upsert if necessary
            result = await asyncio.to_thread(
                ray.get,
                embedder.upsert_task_embeddings.remote(
                    [int(node_id)],
                    k=TASK_EMBED_K_HOPS,
                    label=TASK_EMBED_LABEL,
                    props_map={
                        int(node_id): {"sha256": content_hash, "source": reason}
                    },
                    model_map={int(node_id): TASK_EMBED_MODEL},
                    content_hash_map={int(node_id): content_hash},
                ),
            )

            upserted = result.get("upserted", 0)
            if upserted == 0:
                # 4. Isolated Node/Placeholder Handling
                await _handle_no_upsert(session, node_id, content_hash, reason)
                await session.commit()
                return None

            # 5. Retrieve and Return for Coordinator context
            final_res = await session.execute(
                text(
                    "SELECT emb FROM graph_embeddings_1024 WHERE node_id = :nid AND label = :label"
                ),
                {"nid": node_id, "label": TASK_EMBED_LABEL},
            )
            await session.commit()
            LTM_EMBED_JOB_PROCESSED.labels(reason).inc()
            return final_res.scalar_one_or_none()

    except Exception:
        logger.exception("Unexpected error embedding task %s", task_id_str)
        return None


async def _handle_no_upsert(session, node_id, content_hash, reason):
    """Checks if embedding exists; if not, inserts placeholder to stop backfill loop."""
    check = await session.execute(
        text(
            "SELECT 1 FROM graph_embeddings_1024 WHERE node_id = :nid AND label = :label"
        ),
        {"nid": node_id, "label": TASK_EMBED_LABEL},
    )
    if not check.scalar_one_or_none():
        logger.warning("Task node %s is isolated; inserting 1024d placeholder", node_id)
        LTM_EMBED_JOB_SKIPPED.labels(reason, "no_graph_edges").inc()
        # Convert list to JSON array string for pgvector CAST(:zero AS vector)
        zero_vec_str = json.dumps([0.0] * 1024)
        await session.execute(
            text("""
                INSERT INTO graph_embeddings_1024 (node_id, label, emb, props, model, content_sha256)
                VALUES (:nid, :label, CAST(:zero AS vector), :props, :mod, :hash)
                ON CONFLICT (node_id, label) DO NOTHING
            """),
            {
                "nid": node_id,
                "label": TASK_EMBED_LABEL,
                "zero": zero_vec_str,
                "props": json.dumps({"reason": "isolated_node", "source": reason}),
                "mod": TASK_EMBED_MODEL,
                "hash": content_hash,
            },
        )


# --- Background Worker Infrastructure ---


async def enqueue_task_embedding_job(
    app_state: Any, task_id: Union[UUID, str], *, reason: str = "manual"
) -> bool:
    """Safely adds a task to the background processing queue."""
    queue = getattr(app_state, "task_embedding_queue", None)
    pending = getattr(app_state, "task_embedding_pending", None)
    lock = getattr(app_state, "task_embedding_pending_lock", None)

    if not all([queue, pending, lock]):
        return False

    tid = str(task_id)
    async with lock:
        if tid in pending:
            LTM_EMBED_ENQUEUE_DEDUPE.labels(reason).inc()
            return False
        pending.add(tid)
        await queue.put(TaskEmbeddingJob(task_id=tid, reason=reason))
        LTM_EMBED_ENQUEUE_OK.labels(reason).inc()
        return True


async def task_embedding_worker(app_state: Any) -> None:
    """Async background consumer for task embeddings."""
    queue = getattr(app_state, "task_embedding_queue", None)
    pending = getattr(app_state, "task_embedding_pending", None)
    lock = getattr(app_state, "task_embedding_pending_lock", None)
    if not queue:
        return

    session_factory = get_async_pg_session_factory()

    while True:
        job: TaskEmbeddingJob = await queue.get()
        try:
            async with session_factory() as session:
                res = await session.execute(
                    text(
                        "SELECT type, description, params FROM tasks WHERE id = CAST(:tid AS uuid)"
                    ),
                    {"tid": job.task_id},
                )
                row = res.mappings().first()
                if row:
                    await generate_and_persist_task_embedding(
                        job.task_id,
                        row["description"],
                        row["type"],
                        row["params"],
                        reason=job.reason,
                    )
        except Exception:
            logger.exception("Worker failed processing task %s", job.task_id)
        finally:
            if lock and pending:
                async with lock:
                    pending.discard(job.task_id)
            queue.task_done()


async def task_embedding_backfill_loop(app_state: Any) -> None:
    """Periodic check for tasks that slipped through the cracks."""
    while True:
        try:
            session_factory = get_async_pg_session_factory()
            async with session_factory() as session:
                # Note: View name updated to reflect 1024d focus
                rows = await session.execute(
                    text(
                        "SELECT task_id::text FROM tasks_missing_embeddings_1024 LIMIT :limit"
                    ),
                    {"limit": TASK_EMBED_BACKFILL_BATCH},
                )
                for tid in rows.scalars():
                    await enqueue_task_embedding_job(app_state, tid, reason="backfill")
        except Exception as e:
            logger.error("Backfill error: %s", e)
        await asyncio.sleep(TASK_EMBED_BACKFILL_INTERVAL_S)
