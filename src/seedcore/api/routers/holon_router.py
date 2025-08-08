from typing import Dict, Any, List
import time
import uuid as _uuid
import numpy as np

from fastapi import APIRouter, HTTPException, Request

from ...memory.long_term_memory import LongTermMemoryManager
from ...memory.backends.pgvector_backend import Holon


router = APIRouter()


def _get_holon_fabric_from_app(request: Request):
    return getattr(request.app.state, "mem", None)


@router.post('/holons')
async def create_holon(request: Request, holon_data: Dict[str, Any]):
    try:
        # Prefer Holon Fabric if available on app state
        holon_fabric = _get_holon_fabric_from_app(request)
        if holon_fabric:
            embedding = np.array(holon_data.get("embedding", []))
            if embedding.size == 0:
                return {"success": False, "error": "No embedding provided"}

            # Pad or truncate to 768 dimensions
            if embedding.size < 768:
                embedding = np.pad(embedding, (0, 768 - embedding.size), mode='constant')
            else:
                embedding = embedding[:768]

            holon = Holon(
                uuid=holon_data.get("uuid", str(_uuid.uuid4())),
                embedding=embedding,
                meta=holon_data.get("meta", {})
            )
            await holon_fabric.insert_holon(holon)
            return {"success": True, "uuid": holon.uuid, "message": "Holon inserted successfully"}

        # Fallback to LTM manager saga if fabric not ready
        ltm_manager = LongTermMemoryManager()
        result = await ltm_manager.insert_holon(holon_data)
        return {"success": bool(result)}

    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get('/holons/{uuid}')
async def get_holon(request: Request, uuid: str):
    try:
        holon_fabric = _get_holon_fabric_from_app(request)
        if not holon_fabric:
            return {"success": False, "error": "Holon Fabric not initialized"}

        result = await holon_fabric.query_exact(uuid)
        if result:
            return {"success": True, "holon": result}
        else:
            return {"success": False, "error": "Holon not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get('/holons/stats')
async def holon_stats(request: Request):
    try:
        sc = request.app.state.stats
        errors: Dict[str, str] = {}

        # Mw stats
        try:
            mw = sc.mw_stats()
        except Exception as e:
            mw = {"error": str(e)}
            errors["Mw"] = str(e)

        # PGVector (Mlt) stats
        try:
            mlt = await sc.mlt_stats()
        except Exception as e:
            mlt = {"error": str(e)}
            errors["Mlt"] = str(e)

        # Neo4j relationship stats
        try:
            rel = sc.rel_stats()
        except Exception as e:
            rel = {"error": str(e)}
            errors["Neo4j"] = str(e)

        # Prometheus energy stats
        try:
            energy = sc.energy_stats()
        except Exception as e:
            energy = {"error": str(e)}
            errors["Prometheus"] = str(e)

        body: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tiers": {
                "Mw": mw,
                "Mlt": mlt
            },
            "vector_dimensions": getattr(sc, "EMB_DIM", 768),
            "energy": energy,
            "status": "healthy" if not errors else "unhealthy"
        }
        if isinstance(rel, dict):
            body.update(rel)
        if errors:
            body["errors"] = errors
        if isinstance(mw, dict) and mw.get("avg_staleness_s", 0) > 3:
            body["status"] = "unhealthy"
        return body
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/holons/relationships')
async def create_relationship(request: Request, rel_data: Dict[str, Any]):
    try:
        holon_fabric = _get_holon_fabric_from_app(request)
        if not holon_fabric:
            return {"success": False, "error": "Holon Fabric not initialized"}

        src_uuid = rel_data.get("src_uuid")
        rel = rel_data.get("rel")
        dst_uuid = rel_data.get("dst_uuid")
        if not all([src_uuid, rel, dst_uuid]):
            return {"success": False, "error": "Missing required fields: src_uuid, rel, dst_uuid"}

        await holon_fabric.create_relationship(src_uuid, rel, dst_uuid)
        return {"success": True, "message": "Relationship created successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post('/holons/search/similarity')
async def search_holons_by_similarity(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        embedding = body.get("embedding", [])
        limit = int(body.get("limit", 5))

        if not isinstance(embedding, list) or len(embedding) == 0:
            return {"success": False, "error": "embedding must be a non-empty list"}

        holon_fabric = _get_holon_fabric_from_app(request)
        if holon_fabric:
            emb = np.array(embedding)
            if emb.size < 768:
                emb = np.pad(emb, (0, 768 - emb.size), mode='constant')
            else:
                emb = emb[:768]
            results = await holon_fabric.query_fuzzy(emb, k=limit)
            return {"success": True, "results": results, "source": "fabric"}

        # Fallback to LTM manager
        ltm_manager = LongTermMemoryManager()
        results = await ltm_manager.query_holons_by_similarity(embedding, limit)
        return {"success": True, "results": results, "source": "mlt"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post('/holons/search/rag')
async def rag_search(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    """RAG endpoint for fuzzy search with holon expansion (moved from server)."""
    try:
        holon_fabric = _get_holon_fabric_from_app(request)
        if not holon_fabric:
            return {"error": "Holon Fabric not initialized"}

        embedding = np.array(body.get("embedding", []))
        k = body.get("k", 10)
        if len(embedding) == 0:
            return {"error": "No embedding provided"}

        if len(embedding) < 768:
            embedding = np.pad(embedding, (0, 768 - len(embedding)), mode='constant')
        else:
            embedding = embedding[:768]

        holons = await holon_fabric.query_fuzzy(embedding, k=k)
        return {"holons": holons}
    except Exception as e:
        return {"error": str(e)}


@router.get('/holons/{uuid}/relationships')
async def get_holon_relationships(uuid: str) -> Dict[str, Any]:
    try:
        ltm_manager = LongTermMemoryManager()
        relationships = await ltm_manager.get_holon_relationships(uuid)
        return {"success": True, "relationships": relationships}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post('/holons/batch')
async def create_holons_batch(request: Request, holons: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        if not isinstance(holons, list) or len(holons) == 0:
            return {"success": False, "error": "Request body must be a non-empty list of holon objects"}

        holon_fabric = _get_holon_fabric_from_app(request)
        ltm_manager = None if holon_fabric else LongTermMemoryManager()

        results: List[Dict[str, Any]] = []
        success_count = 0

        for entry in holons:
            try:
                if holon_fabric:
                    emb = np.array(entry.get("embedding", []))
                    if emb.size == 0:
                        raise ValueError("No embedding provided")
                    if emb.size < 768:
                        emb = np.pad(emb, (0, 768 - emb.size), mode='constant')
                    else:
                        emb = emb[:768]
                    holon = Holon(
                        uuid=entry.get("uuid", str(_uuid.uuid4())),
                        embedding=emb,
                        meta=entry.get("meta", {})
                    )
                    await holon_fabric.insert_holon(holon)
                    results.append({"uuid": holon.uuid, "success": True, "source": "fabric"})
                    success_count += 1
                else:
                    ok = await ltm_manager.insert_holon(entry) if hasattr(ltm_manager, 'insert_holon') else False
                    results.append({"uuid": entry.get("uuid"), "success": bool(ok), "source": "mlt"})
                    if ok:
                        success_count += 1
            except Exception as e:
                results.append({"uuid": entry.get("uuid"), "success": False, "error": str(e)})

        return {
            "success": success_count == len(holons),
            "inserted": success_count,
            "total": len(holons),
            "results": results
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Backward-compatible aliases (hidden from schema)

@router.post('/holon/insert', include_in_schema=False)
async def create_holon_legacy_alias(request: Request, holon_data: Dict[str, Any]):
    return await create_holon(request, holon_data)


@router.post('/mlt/insert_holon', include_in_schema=False)
async def mlt_insert_holon_legacy_alias(request: Request, holon_data: Dict[str, Any]):
    return await create_holon(request, holon_data)


@router.post('/rag', include_in_schema=False)
async def rag_legacy_alias(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    return await rag_search(request, body)


