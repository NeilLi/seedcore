#!/usr/bin/env python
# seedcore/tools/memory_tools.py

from __future__ import annotations
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# ============================================================
# MwManager Tools
# ============================================================

class MwReadTool:
    def __init__(self, mw_manager: Any):
        self.mw_manager = mw_manager

    async def execute(self, item_id: str, is_global: bool = False) -> Optional[Any]:
        if not self.mw_manager:
            raise ValueError("MwManager not available")
        return await self.mw_manager.get_item_async(item_id, is_global=is_global)

    def schema(self):
        return {
            "name": "memory.mw.read",
            "description": "Reads an item from working memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "is_global": {"type": "boolean", "default": False},
                },
                "required": ["item_id"],
            }
        }


class MwWriteTool:
    def __init__(self, mw_manager: Any):
        self.mw_manager = mw_manager

    async def execute(self, item_id: str, value: Any, is_global: bool = False, ttl_s: Optional[int] = None):
        if not self.mw_manager:
            raise ValueError("MwManager not available")

        # Unified API: support both sync + async backends
        if is_global:
            fn = getattr(self.mw_manager, "set_global_item_async", None)
            if callable(fn):
                await fn(item_id, value, ttl_s)
            else:
                self.mw_manager.set_global_item(item_id, value, ttl_s)
        else:
            fn = getattr(self.mw_manager, "set_item_async", None)
            if callable(fn):
                await fn(item_id, value)
            else:
                self.mw_manager.set_item(item_id, value)

        return {"status": "success", "item_id": item_id}

    def schema(self):
        return {
            "name": "memory.mw.write",
            "description": "Writes an item to working memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "value": {"type": "object"},
                    "is_global": {"type": "boolean", "default": False},
                    "ttl_s": {"type": "integer", "default": None},
                },
                "required": ["item_id", "value"],
            }
        }


class MwHotItemsTool:
    def __init__(self, mw_manager: Any):
        self.mw_manager = mw_manager

    async def execute(self, top_n: int = 5):
        if not self.mw_manager:
            raise ValueError("MwManager not available")
        items = await self.mw_manager.get_hot_items_async(top_n)
        return [{"item_id": k, "count": v} for k, v in items]

    def schema(self):
        return {
            "name": "memory.mw.hot_items",
            "description": "Gets most frequently accessed working memory items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "default": 5},
                }
            }
        }

# ============================================================
# LongTermMemory Tools
# ============================================================

class LtmQueryTool:
    def __init__(self, ltm_manager: Any):
        self.ltm_manager = ltm_manager

    async def execute(self, holon_id: str):
        return await self.ltm_manager.query_holon_by_id_async(holon_id)

    def schema(self):
        return {
            "name": "memory.ltm.query",
            "description": "Query LTM holon by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "holon_id": {"type": "string"},
                },
                "required": ["holon_id"],
            }
        }


class LtmSearchTool:
    def __init__(self, ltm_manager: Any):
        self.ltm_manager = ltm_manager

    async def execute(self, embedding: List[float], limit: int = 5):
        return await self.ltm_manager.query_similar_holons_async(embedding, limit)

    def schema(self):
        return {
            "name": "memory.ltm.search",
            "description": "Vector similarity search in LTM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "embedding": {"type": "array", "items": {"type": "number"}},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["embedding"],
            }
        }


class LtmStoreTool:
    def __init__(self, ltm_manager: Any):
        self.ltm_manager = ltm_manager

    async def execute(self, holon_data: Dict[str, Any]):
        success = await self.ltm_manager.insert_holon_async(holon_data)
        return {
            "status": "success" if success else "failed",
            "holon_id": holon_data.get("vector", {}).get("id"),
            "_reflection": {
                "skill": "memory_management",
                "delta": 0.01,
                "note": "Holon stored",
            } if success else None
        }

    def schema(self):
        return {
            "name": "memory.ltm.store",
            "description": "Store holon into LTM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "holon_data": {"type": "object"},
                },
                "required": ["holon_data"],
            }
        }


class LtmRelationshipsTool:
    def __init__(self, ltm_manager: Any):
        self.ltm_manager = ltm_manager

    async def execute(self, holon_id: str):
        return await self.ltm_manager.get_holon_relationships(holon_id)

    def schema(self):
        return {
            "name": "memory.graph.relationships",
            "description": "Get holon relationships from graph store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "holon_id": {"type": "string"},
                },
                "required": ["holon_id"],
            }
        }

