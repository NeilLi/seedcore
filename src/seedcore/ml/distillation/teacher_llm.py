from typing import Dict, Any
import json
import logging

from .system_episode import SystemEpisode

logger = logging.getLogger(__name__)

ALLOWED_REGIMES = [
    "STABLE_NORMAL",
    "HIGH_LOAD_HEALTHY",
    "MEMORY_PRESSURE",
    "ANALYSIS_BOTTLENECK",
    "ROUTING_PATHOLOGY",
    "FAILURE_SPIRAL",
]

ALLOWED_ACTIONS = [
    "KEEP_CURRENT_POLICY",
    "SHIFT_ANALYSIS_TO_CLUSTER_C",
    "LIMIT_CRITIC_RECURSION",
    "INCREASE_PLANNER_FANOUT",
    "REDUCE_MEMORY_CONTEXT_LENGTH",
    "SCALE_OUT_ANALYZERS",
]


def build_distillation_prompt(ep: SystemEpisode) -> str:
    # compress episode a bit; no need to dump everything
    ep_dict = ep.dict()
    # Optionally truncate metrics lists
    ep_dict["system_metrics"] = ep_dict["system_metrics"][-20:]
    ep_json = json.dumps(ep_dict)

    return f"""
You are an expert AI operations analyst.
Classify the system regime and recommended action.

Allowed regime_label: {ALLOWED_REGIMES}
Allowed action_label: {ALLOWED_ACTIONS}

Return JSON only:
{{
  "regime_label": "...",
  "action_label": "...",
  "confidence": 0.0-1.0
}}

Episode:
{ep_json}
"""


async def label_episode_with_llm(ep: SystemEpisode) -> Dict[str, Any]:
    # Here you call your real LLM (OpenAI / internal) instead of the /chat stub.
    # For now, think of this as delegated to some CognitiveService.
    from seedcore.cognitive.client import cognitive_chat  # hypothetical

    prompt = build_distillation_prompt(ep)
    raw = await cognitive_chat(prompt)  # returns raw text

    try:
        parsed = json.loads(raw)
        return {
            "regime_label": parsed["regime_label"],
            "action_label": parsed["action_label"],
            "confidence": float(parsed.get("confidence", 0.5)),
        }
    except Exception as e:
        logger.error(f"Failed to parse LLM distillation JSON: {e}, raw={raw[:200]}")
        # Fallback
        return {
            "regime_label": "STABLE_NORMAL",
            "action_label": "KEEP_CURRENT_POLICY",
            "confidence": 0.1,
        }
