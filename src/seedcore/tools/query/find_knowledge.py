#!/usr/bin/env python
# seedcore/tools/query/find_knowledge.py
"""
Tool for finding knowledge using Mw -> Mlt escalation.
Implements the Mw -> Mlt workflow with negative caching and single-flight guards.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import logging
import asyncio
import json

logger = logging.getLogger(__name__)


class FindKnowledgeTool:
    """
    Tool for finding knowledge using Mw -> Mlt escalation.
    Implements the Mw -> Mlt workflow with negative caching and single-flight guards.
    """

    def __init__(
        self,
        mw_manager: Any,
        ltm_manager: Any,
        agent_id: str,
    ):
        """
        Initialize the FindKnowledgeTool.

        Args:
            mw_manager: MwManager instance for working memory
            ltm_manager: LongTermMemoryManager instance for long-term memory
            agent_id: ID of the agent using this tool
        """
        self.mw_manager = mw_manager
        self.mlt_manager = ltm_manager
        self.agent_id = agent_id

    @property
    def name(self) -> str:
        return "knowledge.find"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Finds a piece of knowledge by searching working memory (Mw) first, then escalating to long-term memory (Mlt) if not found.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_id": {
                        "type": "string",
                        "description": "The ID of the fact/knowledge to find.",
                    }
                },
                "required": ["fact_id"],
            },
        }

    async def execute(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Find knowledge by fact_id.

        Args:
            fact_id: The ID of the fact to find

        Returns:
            The found knowledge or None if not found
        """
        logger.info(f"[{self.agent_id}] 🔍 Searching for '{fact_id}'...")

        # Check if memory managers are available
        if not self.mw_manager or not self.mlt_manager:
            logger.error(f"[{self.agent_id}] ❌ Memory managers not available")
            return None

        # Check negative cache first (avoid stampede on cold misses)
        if await self.mw_manager.check_negative_cache("fact", "global", fact_id):
            logger.info(f"[{self.agent_id}] NEG-HIT for {fact_id}; skipping Mlt lookup")
            return None

        # Try to acquire single-flight sentinel atomically
        sentinel_key = f"_inflight:fact:global:{fact_id}"
        sentinel_acquired = await self.mw_manager.try_set_inflight(
            sentinel_key, ttl_s=5
        )

        if not sentinel_acquired:
            logger.info(
                f"[{self.agent_id}] Another worker is fetching {fact_id}, waiting briefly..."
            )
            # Wait briefly for the other worker to complete
            await asyncio.sleep(0.05)  # Brief backoff

            # Try to get the result that might have been cached
            cached_data = await self.mw_manager.get_item_typed_async(
                "fact", "global", fact_id
            )
            if cached_data:
                logger.info(
                    f"[{self.agent_id}] ✅ Found '{fact_id}' after waiting (cache hit)."
                )
                try:
                    return (
                        json.loads(cached_data)
                        if isinstance(cached_data, str)
                        else cached_data
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON"
                    )
                    return {"raw_data": cached_data}
            return None

        try:
            # 1. Query Working Memory (Mw) first using typed key format
            logger.info(f"[{self.agent_id}] 📋 Querying Working Memory (Mw)...")
            try:
                cached_data = await self.mw_manager.get_item_typed_async(
                    "fact", "global", fact_id
                )
                if cached_data:
                    logger.info(
                        f"[{self.agent_id}] ✅ Found '{fact_id}' in Mw (cache hit)."
                    )
                    try:
                        return (
                            json.loads(cached_data)
                            if isinstance(cached_data, str)
                            else cached_data
                        )
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON"
                        )
                        return {"raw_data": cached_data}
            except Exception as e:
                logger.error(f"[{self.agent_id}] ❌ Error querying Mw: {e}")

            # 2. On a miss, escalate to Long-Term Memory (Mlt)
            logger.info(
                f"[{self.agent_id}] ⚠️ '{fact_id}' not in Mw (cache miss). Escalating to Mlt..."
            )
            long_term_data = await self.mlt_manager.query_holon_by_id_async(fact_id)

            if long_term_data:
                logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' in Mlt.")

                # 3. Cache the retrieved data back into Mw
                logger.info(f"[{self.agent_id}] 💾 Caching '{fact_id}' back to Mw...")
                try:
                    self.mw_manager.set_global_item_typed(
                        "fact", "global", fact_id, long_term_data, ttl_s=900
                    )
                except Exception as e:
                    logger.error(f"[{self.agent_id}] ❌ Failed to cache to Mw: {e}")

                return long_term_data
            else:
                # On total miss: write negative cache
                logger.info(
                    f"[{self.agent_id}] ❌ '{fact_id}' not found in Mlt. Setting negative cache."
                )
                try:
                    self.mw_manager.set_negative_cache(
                        "fact", "global", fact_id, ttl_s=30
                    )
                except Exception as e:
                    logger.error(
                        f"[{self.agent_id}] ❌ Failed to set negative cache: {e}"
                    )
                return None

        except Exception as e:
            logger.error(f"[{self.agent_id}] ❌ Error querying Mlt: {e}")
            return None
        finally:
            # Always clear in-flight sentinel
            try:
                await self.mw_manager.del_global_key(sentinel_key)
            except Exception:
                pass

        logger.warning(
            f"[{self.agent_id}] 🚨 Could not find '{fact_id}' in any memory tier."
        )
        return None

