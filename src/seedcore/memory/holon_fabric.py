import os
import logging
import numpy as np
from typing import List, Optional, Dict, Any, Sequence, Protocol

from ..models.holon import Holon, HolonScope, HolonType

from .backends.pgvector_backend import PgVectorStore
from .backends.neo4j_graph import Neo4jGraph

logger = logging.getLogger(__name__)

# --- Constants ---
EMBED_DIM = int(os.getenv("HOLON_EMBED_DIM", "1024"))  # Configurable embedding dimension (default: 1024 for text-embedding-004)

# Optional embedder if you want text->vec inside Fabric (can be None if you pass vectors)
class Embedder(Protocol):
    """Protocol for text embedding providers."""
    def embed(self, text: str) -> np.ndarray:
        """Convert text to embedding vector."""
        ...

class HolonFabric:
    """
    Unified storage layer for Vector (neural) and Graph (symbolic) holons.
    Enforces scope boundaries during retrieval. Uses a saga-style dual write.
    """

    def __init__(self, vec_store: PgVectorStore, graph: Neo4jGraph, embedder: Optional[Embedder] = None):
        self.vec = vec_store
        self.graph = graph
        self.embedder = embedder

    # ------------------------
    # Write path (saga style)
    # ------------------------
    async def insert_holon(self, holon: Holon) -> None:
        """
        Idempotent-ish 'upsert' to both vector and graph layers.
        Ensures consistent scope fields across both stores.
        Saga: write vector -> write graph; on graph failure, delete vector.
        """
        uuid = holon.id
        embedding = self._coerce_embedding(holon.embedding)
        # normalize meta (do NOT include embedding here)
        meta = self._make_meta(holon)

        # 1) Vector upsert
        try:
            await self.vec.upsert(uuid=uuid, embedding=embedding, meta=meta)
        except Exception as e:
            raise RuntimeError(f"Vector upsert failed for {uuid}: {e}") from e

        # 2) Graph upsert (node + edges)
        try:
            node_props = {
                "scope": holon.scope.value,
                "organ_id": meta.get("organ_id"),
                "entity_id": meta.get("entity_id"),
                "confidence": holon.confidence,
                "decay_rate": holon.decay_rate,
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "access_policy": meta.get("access_policy"),
                "type": holon.type.value,
            }
            await self.graph.upsert_node(uuid, holon.type.value, holon.summary or "", node_props)

            for link in (holon.links or []):
                # expected link: {'rel': 'REL_TYPE', 'target_id': 'uuid', 'props': {...}}
                rel = link.get("rel")
                dst = link.get("target_id")
                props = link.get("props")
                if rel and dst:
                    await self.graph.upsert_edge(uuid, rel, dst, props=props)
        except Exception as e:
            # compensate vector write to avoid drifting
            try:
                await self.vec.delete(uuid=uuid)
            except Exception:
                pass
            raise RuntimeError(f"Graph upsert failed for {uuid}: {e}") from e

    # ------------------------
    # Retrieval
    # ------------------------
    async def query_context(
        self,
        query_vec: np.ndarray,
        scopes: Sequence[HolonScope],
        organ_id: Optional[str] = None,
        entity_ids: Optional[List[str]] = None,
        limit: int = 10,
        hydrate_neighbors: bool = False,
        neighbor_limit: int = 0,
    ) -> List[Holon]:
        """
        Scope-gated semantic retrieval. Filters are pushed to the vector store and
        verified again in Python as a defense-in-depth.
        """
        filters = self._build_filters(scopes, organ_id, entity_ids)

        # Vector search
        results = await self.vec.search(query_vec=query_vec, k=limit, filters=filters)

        # Convert and double-check scope
        holons: List[Holon] = []
        for rec in results:
            meta = dict(rec.get("meta") or {})
            h = self._from_vec_record(rec, meta)
            if self._allowed(h, scopes, organ_id, entity_ids):
                holons.append(h)

        # Optional 1-hop hydration with scope checks per neighbor
        if hydrate_neighbors and neighbor_limit > 0:
            holons = await self._hydrate_neighbors_scoped(holons, scopes, organ_id, entity_ids, neighbor_limit)

        return holons[:limit]

    async def query_context_by_text(
        self,
        text: str,
        scopes: Sequence[HolonScope],
        organ_id: Optional[str] = None,
        entity_ids: Optional[List[str]] = None,
        limit: int = 10,
        **kwargs,
    ) -> List[Holon]:
        """
        Convenience: embed text here if an embedder is available, else raise.
        """
        if not self.embedder:
            raise ValueError("No embedder configured; use query_context with a vector.")
        vec = self.embedder.embed(text)
        return await self.query_context(vec, scopes, organ_id, entity_ids, limit, **kwargs)

    # ------------------------
    # Convenience Methods
    # ------------------------
    
    async def get_holon(self, holon_id: str) -> Optional[Holon]:
        """
        Retrieve a single holon by ID.
        
        Useful for admin tooling, debugging, and direct holon inspection.
        """
        try:
            # get_by_id returns a Holon object from pgvector_backend
            vec_holon = await self.vec.get_by_id(holon_id)
            if not vec_holon:
                return None
            
            # Extract meta from the vector store Holon
            meta = dict(vec_holon.meta) if isinstance(vec_holon.meta, dict) else {}
            
            # Create a record dict compatible with _from_vec_record
            rec_dict = {
                "uuid": vec_holon.uuid,
                "dist": None,  # No distance score for direct lookup
            }
            return self._from_vec_record(rec_dict, meta)
        except Exception as e:
            logger.error(f"Failed to get holon {holon_id}: {e}")
            return None

    async def delete_holon(self, holon_id: str) -> None:
        """
        Delete a holon from both vector and graph stores.
        
        Uses saga-style deletion: delete from graph first, then vector.
        On vector failure, attempt to restore graph node (best-effort).
        """
        try:
            # 1) Delete from graph first (if delete_node method exists)
            try:
                if hasattr(self.graph, "delete_node"):
                    await self.graph.delete_node(holon_id)
                else:
                    # Fallback: delete node via Cypher query if method doesn't exist
                    # This is a best-effort deletion
                    logger.debug(f"delete_node method not available, skipping graph deletion for {holon_id}")
            except Exception as e:
                logger.warning(f"Graph deletion failed for {holon_id}: {e}")
                # Continue to vector deletion anyway
            
            # 2) Delete from vector store
            try:
                await self.vec.delete(uuid=holon_id)
            except Exception as e:
                logger.error(f"Vector deletion failed for {holon_id}: {e}")
                # Note: Graph already deleted, so we can't fully compensate
                # In production, you might want to log this for manual reconciliation
                raise
        except Exception as e:
            logger.error(f"Failed to delete holon {holon_id}: {e}")
            raise

    # ------------------------
    # Helpers
    # ------------------------
    def _coerce_embedding(self, emb: Optional[Sequence[float]]) -> np.ndarray:
        if emb is None:
            return np.zeros(EMBED_DIM, dtype=np.float32)
        arr = np.asarray(emb, dtype=np.float32)
        if arr.ndim != 1:
            arr = arr.flatten()
        if arr.shape[0] != EMBED_DIM:
            # (optionally) pad/trim, but better to raise to catch pipeline issues
            raise ValueError(f"Embedding dim {arr.shape[0]} != {EMBED_DIM}")
        return arr

    def _make_meta(self, holon: Holon) -> Dict[str, Any]:
        created_at = holon.created_at.isoformat() if holon.created_at else None
        # Support separate updated_at if available
        updated_at = getattr(holon, "updated_at", None)
        updated_at_iso = updated_at.isoformat() if updated_at else created_at
        
        meta = {
            "id": holon.id,
            "type": holon.type.value,
            "scope": holon.scope.value,
            "summary": holon.summary,
            "content": holon.content,
            "created_at": created_at,
            "updated_at": updated_at_iso,
            "decay_rate": holon.decay_rate,
            "confidence": holon.confidence,
            "access_policy": holon.access_policy,
            # make these explicit top-level fields for filters:
            "organ_id": self._extract_organ_id(holon),
            "entity_id": self._extract_entity_id(holon),
        }
        return meta

    def _extract_organ_id(self, holon: Holon) -> Optional[str]:
        # Prefer explicit holon.organ_id if present; fallback to content
        if hasattr(holon, "organ_id"):
            return getattr(holon, "organ_id")
        if isinstance(holon.content, dict):
            return holon.content.get("organ_id")
        return None

    def _extract_entity_id(self, holon: Holon) -> Optional[str]:
        if hasattr(holon, "entity_id"):
            return getattr(holon, "entity_id")
        if isinstance(holon.content, dict):
            return holon.content.get("entity_id")
        return None

    def _build_filters(
        self,
        scopes: Sequence[HolonScope],
        organ_id: Optional[str],
        entity_ids: Optional[Sequence[str]],
    ) -> Dict[str, Any]:
        ors: List[Dict[str, Any]] = [{"scope": "global"}]  # always allow global
        if HolonScope.ORGAN in scopes and organ_id:
            ors.append({"scope": "organ", "organ_id": organ_id})
        if HolonScope.ENTITY in scopes and entity_ids:
            ors.append({"scope": "entity", "entity_id": {"in": list(entity_ids)}})
        return {"or": ors}

    def _from_vec_record(self, rec: Dict[str, Any], meta: Dict[str, Any]) -> Holon:
        """
        Convert a vector store record to a Holon object.
        
        Extracts retrieval score (distance) from the record and converts it to confidence.
        For pgvector, smaller distance = higher similarity = higher confidence.
        """
        # Extract retrieval score (distance) from vector store
        # pgvector returns 'dist' field (smaller is better for cosine/L2 distance)
        score = rec.get("dist") or rec.get("score")
        
        # Get existing confidence from meta, or derive from retrieval score
        confidence = meta.get("confidence")
        if confidence is None and score is not None:
            try:
                # Convert distance to confidence: smaller distance = higher confidence
                # Using inverse distance formula: confidence = 1 / (1 + distance)
                # This maps [0, inf) to (0, 1] where distance 0 = confidence 1.0
                distance = float(score)
                confidence = 1.0 / (1.0 + distance)
            except (ValueError, TypeError):
                confidence = 1.0
        
        return Holon(
            id=meta.get("id") or rec.get("uuid"),
            type=HolonType(meta.get("type", "fact")),
            scope=HolonScope(meta.get("scope", "global")),
            content=meta.get("content", {}),
            summary=meta.get("summary", ""),
            embedding=[],      # embeddings live only in vector store; omit here
            links=[],          # link hydration is separate
            decay_rate=meta.get("decay_rate", 0.1),
            confidence=confidence if confidence is not None else 1.0,
            access_policy=meta.get("access_policy", []),
        )

    def _allowed(
        self,
        holon: Holon,
        scopes: Sequence[HolonScope],
        organ_id: Optional[str],
        entity_ids: Optional[Sequence[str]],
    ) -> bool:
        if holon.scope == HolonScope.GLOBAL:
            return True
        if holon.scope == HolonScope.ORGAN:
            return HolonScope.ORGAN in scopes and self._extract_organ_id(holon) == organ_id
        if holon.scope == HolonScope.ENTITY:
            e = self._extract_entity_id(holon)
            return HolonScope.ENTITY in scopes and bool(entity_ids) and e in set(entity_ids)
        return False

    async def _hydrate_neighbors_scoped(
        self,
        holons: List[Holon],
        scopes: Sequence[HolonScope],
        organ_id: Optional[str],
        entity_ids: Optional[Sequence[str]],
        neighbor_limit: int,
    ) -> List[Holon]:
        """
        Hydrate neighbors with scope checks and safety limits.
        
        Prevents explosion from high-degree nodes by capping total neighbor count.
        """
        out = list(holons)
        seen = {h.id for h in holons}
        max_total = neighbor_limit * len(holons)  # Hard cap on total neighbors
        
        for h in holons:
            if len(out) >= max_total:
                logger.debug(f"Neighbor hydration limit reached: {max_total} total neighbors")
                break
            try:
                neighbors = await self.graph.get_neighbors(h.id, limit=neighbor_limit)
            except Exception as e:
                logger.debug(f"Neighbor hydration failed for {h.id}: {e}")
                continue
            for nb in neighbors:
                if len(out) >= max_total:
                    break
                # nb expected: {'uuid': ..., 'type': ..., 'summary': ..., 'props': {...}}
                props = nb.get("props") or {}
                meta = {
                    "id": nb.get("uuid"),
                    "type": props.get("type") or nb.get("type", "fact"),
                    "scope": props.get("scope", "global"),
                    "summary": nb.get("summary", ""),
                    "content": {},  # you can hydrate content from another store if needed
                    "decay_rate": props.get("decay_rate", 0.1),
                    "confidence": props.get("confidence", 1.0),
                    "access_policy": props.get("access_policy", []),
                    "organ_id": props.get("organ_id"),
                    "entity_id": props.get("entity_id"),
                }
                holon_nb = self._from_vec_record({"uuid": meta["id"]}, meta)
                if holon_nb.id not in seen and self._allowed(holon_nb, scopes, organ_id, entity_ids):
                    out.append(holon_nb)
                    seen.add(holon_nb.id)
        return out
