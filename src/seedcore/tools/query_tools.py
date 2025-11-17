#!/usr/bin/env python
# seedcore/tools/query_tools.py
"""
Query Tools for general queries, knowledge finding, and collaborative tasks.
These tools handle task-specific logic that was previously embedded in RayAgent.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import logging
import asyncio
import json
import time
import hashlib
import numpy as np

from ..models.cognitive import CognitiveType, DecisionKind

logger = logging.getLogger(__name__)


class GeneralQueryTool:
    """
    Tool for handling general queries via the Cognitive Service.
    Determines the required profile (fast/deep) based on task heuristics,
    calls the central cognitive service, and normalizes the response.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_agent_capabilities: callable,
        in_flight_tracker: Optional[Dict[str, asyncio.Task]] = None,
        in_flight_lock: Optional[asyncio.Lock] = None,
    ):
        """
        Initialize the GeneralQueryTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_agent_capabilities: Function that returns agent capabilities summary string
            in_flight_tracker: Optional dict for tracking in-flight requests (for deduplication)
            in_flight_lock: Optional lock for in_flight_tracker access
        """
        self._cog = cognitive_client
        self._cog_available = cognitive_client is not None
        self.agent_id = agent_id
        self._get_agent_capabilities = get_agent_capabilities
        self._cog_inflight = in_flight_tracker or {}
        self._cog_inflight_lock = in_flight_lock or asyncio.Lock()

    @property
    def name(self) -> str:
        return "general_query"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Handles general queries by routing them to the Cognitive Service with appropriate profile (fast/deep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "The query description or problem statement.",
                    },
                    "task_data": {
                        "type": "object",
                        "description": "Additional task metadata including params, task_id, etc.",
                    },
                },
                "required": ["description"],
            },
        }

    def _extract_formatted(self, payload: Dict[str, Any], description: str) -> str:
        """Extract formatted response from cognitive service payload."""
        formatted = payload.get("formatted_response")
        if not formatted:
            steps = payload.get("solution_steps")
            if isinstance(steps, list) and steps:
                first_step = steps[0]
                if isinstance(first_step, dict):
                    formatted = first_step.get("description")
        if not formatted:
            formatted = f"Cognitive analysis: {description}"
        return formatted

    def _normalize_cog_v2_response(
        self, cog_response: Dict[str, Any]
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Normalize cognitive service response."""
        if not isinstance(cog_response, dict):
            return None
        if not cog_response.get("success"):
            return None
        payload = cog_response.get("result") or cog_response.get("payload")
        if not isinstance(payload, dict):
            return None
        metadata = cog_response.get("metadata") or cog_response.get("meta") or {}
        return payload, metadata

    def _determine_profile(self, description: str, task_data: Dict[str, Any]) -> str:
        """Determine cognitive profile (fast/deep) based on heuristics."""
        description_lower = description.lower()
        params = task_data.get("params", {}) or {}
        needs_ml_fallback = params.get("needs_ml_fallback", False)

        if isinstance(params.get("confidence"), dict):
            confidence = params["confidence"].get("overall_confidence", 1.0)
        else:
            confidence = (
                params.get("confidence", 1.0)
                if isinstance(params.get("confidence"), (int, float))
                else 1.0
            )

        criticality = params.get("criticality", task_data.get("criticality", 0.5))
        drift_score = task_data.get("drift_score", 0.0)
        explicit_profile = params.get("cognitive_profile")

        if explicit_profile in ("fast", "deep"):
            return explicit_profile

        is_complex = (
            needs_ml_fallback
            or confidence < 0.5
            or criticality > 0.6
            or drift_score > 0.6
            or len(description.split()) > 15
            or any(
                word in description_lower
                for word in [
                    "complex",
                    "analysis",
                    "decompose",
                    "plan",
                    "strategy",
                    "reasoning",
                    "root cause",
                    "diagnose",
                    "mitigation",
                    "architecture",
                    "design a plan",
                ]
            )
            or task_data.get("force_decomposition")
        )

        return "deep" if is_complex else "fast"

    async def execute(
        self, description: str, task_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a general query.

        Args:
            description: The query description
            task_data: Optional task metadata

        Returns:
            Query result dictionary
        """
        task_data = task_data or {}
        profile = self._determine_profile(description, task_data)
        decision_kind = (
            DecisionKind.COGNITIVE if profile == "deep" else DecisionKind.FAST_PATH
        )

        # Check for cognitive service availability
        if not self._cog_available or not self._cog:
            logger.error(
                f"🚫 {self.agent_id}: cognitive service unavailable. Can't run {profile} reasoning for query='{description[:80]}'"
            )
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "result": {
                    "query_type": "cognitive_query_unserved",
                    "degraded_mode": True,
                    "reason": "central cognitive service unavailable",
                    "description": description,
                    "intended_profile": profile,
                },
                "mem_hits": 0,
                "used_cognitive_service": False,
                "cognitive_profile": profile,
            }

        # In-flight request deduplication
        task_id = task_data.get("task_id") or task_data.get("id")
        request_key = task_id if task_id else f"{description[:100]}:{profile}"

        async with self._cog_inflight_lock:
            if request_key in self._cog_inflight:
                existing_task = self._cog_inflight[request_key]
                if not existing_task.done():
                    logger.info(
                        f"🔄 Agent {self.agent_id} deduplicating cognitive request for {request_key[:50]}... "
                        f"(waiting for existing call to complete)"
                    )
                    try:
                        existing_response = await existing_task
                        normalized = self._normalize_cog_v2_response(existing_response)
                        if normalized:
                            payload, metadata = normalized
                            result = {
                                "query_type": (
                                    "complex_cognitive_query"
                                    if profile == "deep"
                                    else "fast_cognitive_query"
                                ),
                                "query": description,
                                "thought_process": payload.get("thought", ""),
                                "plan": payload.get("solution_steps", []),
                                "formatted": self._extract_formatted(payload, description),
                                "description": description,
                                "meta": metadata,
                                "profile_used": profile,
                            }
                            logger.info(
                                f"✅ Agent {self.agent_id} reused result from in-flight cognitive request (deduplicated)"
                            )
                            return {
                                "agent_id": self.agent_id,
                                "task_processed": True,
                                "success": True,
                                "quality": 0.9 if profile == "deep" else 0.8,
                                "result": result,
                                "mem_hits": 1,
                                "used_cognitive_service": True,
                                "cognitive_profile": profile,
                            }
                    except Exception as e:
                        logger.debug(
                            f"Error waiting for in-flight request: {e}, making new call"
                        )
                    finally:
                        self._cog_inflight.pop(request_key, None)

        # Cognitive Service Call
        try:
            logger.info(
                f"🧠 Agent {self.agent_id} using cognitive service (decision_kind={decision_kind.value}, complex={profile == 'deep'})"
            )
            params = task_data.get("params", {}) or {}

            async def _cog_call():
                input_data = {
                    "problem_statement": str(description or ""),
                    "constraints": params.get("constraints") or {},
                    "available_tools": params.get("available_tools") or {},
                }
                meta = {
                    "task_id": task_id,
                    "requested_profile": profile,
                    "agent_capabilities": self._get_agent_capabilities(),
                }
                return await self._cog.execute_async(
                    agent_id=self.agent_id,
                    cog_type=CognitiveType.PROBLEM_SOLVING,
                    decision_kind=decision_kind,
                    input_data=input_data,
                    meta=meta,
                )

            cog_task = asyncio.create_task(_cog_call())
            async with self._cog_inflight_lock:
                self._cog_inflight[request_key] = cog_task

            try:
                cog_response = await cog_task
            finally:
                async with self._cog_inflight_lock:
                    self._cog_inflight.pop(request_key, None)

            normalized = self._normalize_cog_v2_response(cog_response)
            if normalized:
                payload, metadata = normalized
                result = {
                    "query_type": (
                        "complex_cognitive_query"
                        if profile == "deep"
                        else "fast_cognitive_query"
                    ),
                    "query": description,
                    "thought_process": payload.get("thought", ""),
                    "plan": payload.get("solution_steps", []),
                    "formatted": self._extract_formatted(payload, description),
                    "description": description,
                    "meta": metadata,
                    "profile_used": profile,
                }
                logger.info(
                    f"✅ Agent {self.agent_id} cognitive service completed with profile={profile}"
                )
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 0.9 if profile == "deep" else 0.8,
                    "result": result,
                    "mem_hits": 1,
                    "used_cognitive_service": True,
                    "cognitive_profile": profile,
                }

            logger.warning(
                f"⚠️ Agent {self.agent_id} cognitive service returned unusable response (profile={profile}), falling back"
            )
        except Exception as e:
            import traceback

            logger.warning(
                f"⚠️ Agent {self.agent_id} cognitive service call failed (profile={profile}): {e}"
            )
            logger.debug("Traceback:\n%s", traceback.format_exc())

        # Fallback Error
        err_blob = {
            "query_type": "cognitive_query_failed",
            "description": description,
            "intended_profile": profile,
            "error": "cognitive service failure or unusable response",
        }
        return {
            "agent_id": self.agent_id,
            "task_processed": True,
            "success": False,
            "quality": 0.0,
            "result": err_blob,
            "mem_hits": 0,
            "used_cognitive_service": True,
            "cognitive_profile": profile,
        }


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


class CollaborativeTaskTool:
    """
    Tool for executing collaborative tasks that may require finding knowledge.
    This tool implements the core logic for collaborative task execution with knowledge finding integration.
    """

    def __init__(
        self,
        find_knowledge_tool: FindKnowledgeTool,
        mw_manager: Any,
        ltm_manager: Any,
        agent_id: str,
        get_energy_slice: callable,
    ):
        """
        Initialize the CollaborativeTaskTool.

        Args:
            find_knowledge_tool: FindKnowledgeTool instance for knowledge finding
            mw_manager: MwManager instance for artifact storage
            ltm_manager: LongTermMemoryManager instance for promotion
            agent_id: ID of the agent using this tool
            get_energy_slice: Function that returns current energy slice value
        """
        self.find_knowledge_tool = find_knowledge_tool
        self.mw_manager = mw_manager
        self.mlt_manager = ltm_manager
        self.agent_id = agent_id
        self._get_energy_slice = get_energy_slice

    @property
    def name(self) -> str:
        return "task.collaborative"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Executes a collaborative task that may require finding knowledge. Returns task execution result with success status and details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_info": {
                        "type": "object",
                        "description": "Dictionary containing task information including name, required_fact, complexity, etc.",
                    }
                },
                "required": ["task_info"],
            },
        }

    async def _promote_to_mlt(
        self, key: str, obj: Dict[str, Any], compression: bool = True
    ) -> bool:
        """Promote an object to Mlt by creating a Holon."""
        if not self.mlt_manager:
            return False

        try:
            payload = obj
            if compression and isinstance(obj, dict):
                # Simple "compression": drop large fields
                pruned = {
                    k: v
                    for k, v in obj.items()
                    if k not in ("raw", "tokens", "trace", "result")
                }
                if "raw" in obj:
                    pruned["raw_size"] = len(str(obj["raw"]))
                if "result" in obj:
                    pruned["result_preview"] = str(obj["result"])[:200]
                payload = pruned

            # Create a placeholder embedding
            text_to_embed = json.dumps(payload, sort_keys=True)
            hash_bytes = hashlib.md5(text_to_embed.encode()).digest()
            vec = np.frombuffer(hash_bytes, dtype=np.uint8).astype(np.float32)
            vec = np.pad(vec, (0, 768 - len(vec)), mode="constant")
            embedding = vec / (np.linalg.norm(vec) + 1e-6)

            # Build the holon dict for the LTM manager
            holon_data = {
                "vector": {
                    "id": key,
                    "embedding": embedding,
                    "meta": payload,
                },
                "graph": {
                    "src_uuid": key,
                    "rel": "GENERATED_BY",
                    "dst_uuid": self.agent_id,
                },
            }

            return await self.mlt_manager.insert_holon_async(holon_data)
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mlt promote failed for {key}: {e}")
            return False

    def _mw_put_json_local(self, key: str, obj: Dict[str, Any]) -> bool:
        """L0 only (organ-local)."""
        if not self.mw_manager:
            return False
        try:
            self.mw_manager.set_item(key, json.dumps(obj))
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mw L0 put failed for {key}: {e}")
            return False

    def _mw_put_json_global(
        self,
        kind: str,
        scope: str,
        item_id: str,
        obj: Dict[str, Any],
        ttl_s: int = 600,
    ) -> bool:
        """Write-through L0/L1/L2 using normalized global key."""
        if not self.mw_manager:
            return False
        try:
            payload = (
                obj
                if isinstance(obj, (dict, list, str, int, float, bool, type(None)))
                else str(obj)
            )
            self.mw_manager.set_global_item_typed(
                kind, scope, item_id, payload, ttl_s=ttl_s
            )
            return True
        except Exception as e:
            logger.debug(
                f"[{self.agent_id}] Mw global put failed for {kind}:{scope}:{item_id}: {e}"
            )
            return False

    async def execute(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a collaborative task.

        Args:
            task_info: Dictionary containing task information including required_fact

        Returns:
            Task execution result with success status and details
        """
        task_name = task_info.get("name", "Unknown Task")
        required_fact = task_info.get("required_fact")

        logger.info(
            f"[{self.agent_id}] 🚀 Starting collaborative task '{task_name}'..."
        )

        # Capture energy before task execution
        E_before = self._get_energy_slice()

        knowledge = None
        if required_fact:
            logger.info(f"[{self.agent_id}] 📚 Task requires fact: {required_fact}")
            knowledge = await self.find_knowledge_tool.execute(required_fact)

        # Determine task success based on knowledge availability
        if required_fact and not knowledge:
            success = False
            quality = 0.1
            logger.error(
                f"[{self.agent_id}] 🚨 Task failed: could not find required fact '{required_fact}'."
            )
        else:
            success = True
            quality = 0.9 if knowledge else 0.7  # Higher quality if knowledge was found

        logger.info(f"[{self.agent_id}] ✅ Task completed successfully.")
        if knowledge:
            logger.info(
                f"[{self.agent_id}] 📖 Used knowledge: {knowledge.get('content', 'Unknown content')}"
            )

        # Calculate energy after task execution
        E_after = self._get_energy_slice()
        delta_e = E_after - E_before

        result = {
            "agent_id": self.agent_id,
            "task_name": task_name,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get("content", None) if knowledge else None,
            "delta_e_realized": delta_e,
            "E_before": E_before,
            "E_after": E_after,
        }

        # --- Mw/Mlt write path and promotion ---
        artifact_key = f"task:{task_info.get('task_id', task_name)}"
        artifact = {
            "agent_id": self.agent_id,
            "type": "collab_task",
            "ts": time.time(),
            "required_fact": required_fact,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get("content") if knowledge else None,
            "success": success,
            "quality": quality,
        }

        # Use normalized helpers
        self._mw_put_json_local(artifact_key, artifact)  # L0 for immediate local use
        self._mw_put_json_global(
            "collab_task", "global", artifact_key, artifact, ttl_s=900
        )

        if success and quality >= 0.8:
            await self._promote_to_mlt(artifact_key, artifact, compression=True)

        return result


class ReasonAboutFailureTool:
    """
    Tool for analyzing agent failures using cognitive reasoning.
    """

    def __init__(
        self,
        cognitive_client: Any,
        mfb_client: Any,
        agent_id: str,
        get_memory_context: callable,
        normalize_cog_resp: callable,
        get_energy_state: callable,
        update_energy_state: callable,
    ):
        """
        Initialize the ReasonAboutFailureTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            mfb_client: FlashbulbClient instance
            agent_id: ID of the agent using this tool
            get_memory_context: Function that returns memory context dict
            normalize_cog_resp: Function that normalizes cognitive service responses
            get_energy_state: Function that returns current energy state
            update_energy_state: Function that updates energy state
        """
        self._cog = cognitive_client
        self.mfb_client = mfb_client
        self.agent_id = agent_id
        self._get_memory_context = get_memory_context
        self._normalize_cog_resp = normalize_cog_resp
        self._get_energy_state = get_energy_state
        self._update_energy_state = update_energy_state

    @property
    def name(self) -> str:
        return "cognitive.reason_about_failure"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Analyze agent failures using cognitive reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "ID of the incident to analyze",
                    }
                },
                "required": ["incident_id"],
            },
        }

    async def execute(self, incident_id: str) -> Dict[str, Any]:
        """
        Analyze a failure incident.

        Args:
            incident_id: ID of the incident to analyze

        Returns:
            Analysis results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}
        if not self.mfb_client:
            return {"success": False, "reason": "Memory client not available."}

        try:
            # Get incident context from memory
            incident_context_dict = self.mfb_client.get_incident(incident_id)
            if not incident_context_dict:
                return {"success": False, "reason": "Incident not found."}

            # Call cognitive service via HTTP client
            resp = await self._cog.reason_about_failure(
                agent_id=self.agent_id,
                incident_context=incident_context_dict,
                knowledge_context=self._get_memory_context(),
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            # Calculate energy cost for reasoning
            reg_delta = 0.01 * len(str(payload.get("thought", "")))

            # Update energy state
            current_energy = self._get_energy_state()
            current_energy["cognitive_cost"] = (
                current_energy.get("cognitive_cost", 0.0) + reg_delta
            )
            self._update_energy_state(current_energy)

            return {
                "success": True,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "thought_process": payload.get("thought", ""),
                "proposed_solution": payload.get("proposed_solution", ""),
                "confidence_score": payload.get("confidence_score", 0.0),
                "energy_cost": reg_delta,
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(f"Error in failure reasoning for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "error": str(e),
            }


class MakeDecisionTool:
    """
    Tool for making decisions using cognitive reasoning.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_memory_context: callable,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the MakeDecisionTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_memory_context: Function that returns memory context dict
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._get_memory_context = get_memory_context
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.make_decision"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Make decisions using cognitive reasoning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "decision_context": {
                        "type": "object",
                        "description": "Context for the decision",
                    },
                    "historical_data": {
                        "type": "object",
                        "description": "Historical data to inform the decision",
                    },
                },
                "required": ["decision_context"],
            },
        }

    async def execute(
        self, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a decision.

        Args:
            decision_context: Context for the decision
            historical_data: Optional historical data

        Returns:
            Decision results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.make_decision(
                agent_id=self.agent_id,
                decision_context=decision_context,
                historical_data=historical_data or {},
                knowledge_context=self._get_memory_context(),
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "reasoning": payload.get("reasoning", ""),
                "decision": payload.get("decision", ""),
                "confidence": payload.get("confidence", 0.0),
                "meta": norm["meta"],
                "error": norm["error"],
                "alternative_options": payload.get("alternative_options", ""),
            }
        except Exception as e:
            logger.error(f"Error in decision making for agent {self.agent_id}: {e}")
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}


class SynthesizeMemoryTool:
    """
    Tool for synthesizing information from multiple memory sources.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the SynthesizeMemoryTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.synthesize_memory"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Synthesize information from multiple memory sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_fragments": {
                        "type": "array",
                        "description": "List of memory fragments to synthesize",
                    },
                    "synthesis_goal": {
                        "type": "string",
                        "description": "Goal of the synthesis",
                    },
                },
                "required": ["memory_fragments", "synthesis_goal"],
            },
        }

    async def execute(
        self, memory_fragments: List[Dict[str, Any]], synthesis_goal: str
    ) -> Dict[str, Any]:
        """
        Synthesize memory fragments.

        Args:
            memory_fragments: List of memory fragments to synthesize
            synthesis_goal: Goal of the synthesis

        Returns:
            Synthesis results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.synthesize_memory(
                agent_id=self.agent_id,
                memory_fragments=memory_fragments,
                synthesis_goal=synthesis_goal,
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "synthesized_insight": payload.get("synthesized_insight", ""),
                "confidence_level": payload.get("confidence_level", 0.0),
                "related_patterns": payload.get("related_patterns", ""),
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(f"Error in memory synthesis for agent {self.agent_id}: {e}")
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}


class AssessCapabilitiesTool:
    """
    Tool for assessing agent capabilities and suggesting improvements.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_performance_data: callable,
        get_agent_capabilities: callable,
        normalize_cog_resp: callable,
    ):
        """
        Initialize the AssessCapabilitiesTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_performance_data: Function that returns performance data dict
            get_agent_capabilities: Function that returns agent capabilities dict
            normalize_cog_resp: Function that normalizes cognitive service responses
        """
        self._cog = cognitive_client
        self.agent_id = agent_id
        self._get_performance_data = get_performance_data
        self._get_agent_capabilities = get_agent_capabilities
        self._normalize_cog_resp = normalize_cog_resp

    @property
    def name(self) -> str:
        return "cognitive.assess_capabilities"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Assess agent capabilities and suggest improvements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_capabilities": {
                        "type": "object",
                        "description": "Target capabilities to assess against",
                    },
                },
            },
        }

    async def execute(
        self, target_capabilities: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Assess capabilities.

        Args:
            target_capabilities: Optional target capabilities to assess against

        Returns:
            Assessment results dictionary
        """
        if not self._cog:
            return {"success": False, "reason": "Cognitive service not available."}

        try:
            # Call cognitive service via HTTP client
            resp = await self._cog.assess_capabilities(
                agent_id=self.agent_id,
                performance_data=self._get_performance_data(),
                current_capabilities=self._get_agent_capabilities(),
                target_capabilities=target_capabilities or {},
            )

            norm = self._normalize_cog_resp(resp)
            payload = norm["payload"]

            return {
                "success": True,
                "agent_id": self.agent_id,
                "capability_gaps": payload.get("capability_gaps", ""),
                "improvement_plan": payload.get("improvement_plan", ""),
                "priority_recommendations": payload.get("priority_recommendations", ""),
                "meta": norm["meta"],
                "error": norm["error"],
            }
        except Exception as e:
            logger.error(
                f"Error in capability assessment for agent {self.agent_id}: {e}"
            )
            return {"success": False, "agent_id": self.agent_id, "error": str(e)}


# ============================================================
# Registration
# ============================================================

async def register_query_tools(
    tool_manager: Any,
    *,
    agent_id: str,
    get_agent_capabilities: callable,
    get_energy_slice: callable,
    get_memory_context: Optional[callable] = None,
    normalize_cog_resp: Optional[callable] = None,
    get_energy_state: Optional[callable] = None,
    update_energy_state: Optional[callable] = None,
    get_performance_data: Optional[callable] = None,
    get_agent_capabilities_dict: Optional[callable] = None,
    mfb_client: Optional[Any] = None,
    in_flight_tracker: Optional[Dict[str, asyncio.Task]] = None,
    in_flight_lock: Optional[asyncio.Lock] = None,
) -> None:
    """
    Register all query tools with the ToolManager.

    This function uses ToolManager's internal dependencies (mw_manager, ltm_manager, mcp_client)
    and only requires agent-specific context functions.

    Args:
        tool_manager: The ToolManager instance to register with (must have mw_manager, ltm_manager, mcp_client)
        agent_id: ID of the agent using these tools
        get_agent_capabilities: Function that returns agent capabilities summary string
        get_energy_slice: Function that returns current energy slice value
        get_memory_context: Optional function that returns memory context dict
        normalize_cog_resp: Optional function that normalizes cognitive responses
        get_energy_state: Optional function that returns energy state
        update_energy_state: Optional function that updates energy state
        get_performance_data: Optional function that returns performance data
        get_agent_capabilities_dict: Optional function that returns capabilities dict
        mfb_client: Optional FlashbulbClient instance
        in_flight_tracker: Optional dict for tracking in-flight requests (falls back to empty dict if None)
        in_flight_lock: Optional lock for in_flight_tracker access (falls back to new lock if None)
    """
    # Extract dependencies from ToolManager (single source of truth)
    # Note: mw_manager and ltm_manager come from ToolManager to avoid duplication
    mw_manager = tool_manager.mw_manager
    ltm_manager = tool_manager.ltm_manager

    # Note: cognitive_client is different from mcp_client (MCP service vs Cognitive service)
    # For now, we use mcp_client, but this may need to be updated if ToolManager
    # should store cognitive_client separately. Since cognitive_client is agent-specific
    # (from agent.cog.client), it may remain as a parameter.
    # TODO: Consider adding cognitive_client to ToolManager if it should be shared
    cognitive_client = tool_manager._mcp_client

    # Register FindKnowledgeTool first (it's a dependency)
    find_knowledge_tool = FindKnowledgeTool(mw_manager, ltm_manager, agent_id)
    await tool_manager.register("knowledge.find", find_knowledge_tool)

    # Register GeneralQueryTool
    general_query_tool = GeneralQueryTool(
        cognitive_client,
        agent_id,
        get_agent_capabilities,
        in_flight_tracker,
        in_flight_lock,
    )
    await tool_manager.register("general_query", general_query_tool)

    # Register CollaborativeTaskTool (depends on FindKnowledgeTool)
    collaborative_task_tool = CollaborativeTaskTool(
        find_knowledge_tool,
        mw_manager,
        ltm_manager,
        agent_id,
        get_energy_slice,
    )
    await tool_manager.register("task.collaborative", collaborative_task_tool)

    # Register cognitive reasoning tools if dependencies are provided
    if cognitive_client and normalize_cog_resp:
        if mfb_client and get_memory_context and get_energy_state and update_energy_state:
            reason_about_failure_tool = ReasonAboutFailureTool(
                cognitive_client,
                mfb_client,
                agent_id,
                get_memory_context,
                normalize_cog_resp,
                get_energy_state,
                update_energy_state,
            )
            await tool_manager.register("cognitive.reason_about_failure", reason_about_failure_tool)

        if get_memory_context:
            make_decision_tool = MakeDecisionTool(
                cognitive_client,
                agent_id,
                get_memory_context,
                normalize_cog_resp,
            )
            await tool_manager.register("cognitive.make_decision", make_decision_tool)

        synthesize_memory_tool = SynthesizeMemoryTool(
            cognitive_client,
            agent_id,
            normalize_cog_resp,
        )
        await tool_manager.register("cognitive.synthesize_memory", synthesize_memory_tool)

        if get_performance_data and get_agent_capabilities_dict:
            assess_capabilities_tool = AssessCapabilitiesTool(
                cognitive_client,
                agent_id,
                get_performance_data,
                get_agent_capabilities_dict,
                normalize_cog_resp,
            )
            await tool_manager.register("cognitive.assess_capabilities", assess_capabilities_tool)

    logger.info(f"Registered query tools for agent {agent_id}")
