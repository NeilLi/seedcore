"""
Task Enrichment Module: Deterministic Coordinator Enrichment

This module handles lightweight, deterministic enrichment of tasks before
cognitive planner execution. It implements the architectural principle:

    API captures reality
    Coordinator adds meaning
    Cognitive executes intent

Architecture Note:
This is a bootstrap/fallback intent normalizer for early-stage systems.
Long-term, intent extraction should be handled by:
- FAST LLM (structured intent output)
- Eventizer (speech → command templates)
- PKG (domain vocabularies, capability graphs)
- Holon memory (known command schemas)

The Coordinator should consume already-structured intent, not discover it.
This module serves as a transitional scaffold until those systems are mature.

Semantic Authority:
Every semantic signal carries authority level (HIGH/MEDIUM/LOW):
- HIGH: LLM / PKG / Eventizer / Holon (authoritative)
- MEDIUM: Hybrid consensus
- LOW: Regex / heuristics / bootstrap (advisory only)

The Coordinator respects authority levels:
- LOW authority: advisory only (soft hints, no hard constraints)
- HIGH authority: can drive routing and tool synthesis
"""

from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Protocol
from dataclasses import dataclass
from enum import Enum

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models.task import TaskType
from seedcore.models.cognitive import DecisionKind, CognitiveType

logger = ensure_serve_logger("seedcore.coordinator.core.enrichment")


class AuthorityLevel(str, Enum):
    """Semantic authority levels for intent signals."""
    HIGH = "HIGH"      # LLM / PKG / Eventizer / Holon (authoritative)
    MEDIUM = "MEDIUM"  # Hybrid consensus
    LOW = "LOW"        # Regex / heuristics / bootstrap (advisory only)


@dataclass
class EnrichmentResult:
    """Result of task enrichment operation."""
    
    task_type: str  # Updated task type (ACTION vs CHAT)
    routing_enrichments: Dict[str, Any]  # Routing envelope additions
    cognitive_enrichments: Dict[str, Any]  # Cognitive metadata additions
    multimodal_enrichments: Dict[str, Any]  # Multimodal context additions
    tool_calls: List[Dict[str, Any]]  # Extracted tool calls (if any)
    confidence: float  # Confidence score (0.0 - 1.0)
    reasoning: str  # Human-readable explanation of enrichment decisions


class IntentProvider(Protocol):
    """
    Protocol for intent extraction providers.
    
    This allows plugging in different intent sources:
    - RegexIntentProvider (current fallback, LOW authority)
    - LLMIntentProvider (future, HIGH authority)
    - EventizerIntentProvider (future, HIGH authority)
    - HybridIntentProvider (future, MEDIUM authority)
    """
    
    def extract_intent(self, description: str, context: Any) -> Dict[str, Any]:
        """
        Extract structured intent from description.
        
        Returns:
            Dict with keys: domain, action, value, urgency, confidence, source, authority
        """
        ...


@dataclass
class BootstrapIntentConfig:
    """Configuration for bootstrap intent extraction."""
    
    authority: str = AuthorityLevel.LOW.value
    domains: Dict[str, Dict[str, Any]] = None
    action_patterns: List[str] = None
    numeric_pattern: str = r'(\d+(?:\.\d+)?)'
    location_patterns: List[str] = None
    unit_patterns: Dict[str, List[str]] = None
    
    def __post_init__(self):
        if self.domains is None:
            self.domains = {}
        if self.action_patterns is None:
            self.action_patterns = []
        if self.location_patterns is None:
            self.location_patterns = []
        if self.unit_patterns is None:
            self.unit_patterns = {}


@dataclass
class AuthorityPolicy:
    """Policy for authority-aware routing decisions."""
    
    # LOW authority restrictions (advisory only)
    low_authority: Dict[str, bool] = None
    # HIGH authority permissions (authoritative)
    high_authority: Dict[str, bool] = None
    
    def __post_init__(self):
        if self.low_authority is None:
            self.low_authority = {
                "allow_task_promotion": True,
                "allow_specialization_hint": True,
                "allow_fast_path_suggestion": True,
                "allow_required_specialization": False,
                "allow_tool_injection": False,
                "allow_pkg_override": False,
            }
        if self.high_authority is None:
            self.high_authority = {
                "allow_required_specialization": True,
                "allow_tool_injection": True,
                "allow_pkg_override": False,  # PKG is still authoritative
            }
    
    def can_set_required_specialization(self, authority: str) -> bool:
        """Check if authority level allows setting required_specialization."""
        if authority == AuthorityLevel.HIGH.value:
            return self.high_authority.get("allow_required_specialization", False)
        return self.low_authority.get("allow_required_specialization", False)
    
    def can_inject_tools(self, authority: str) -> bool:
        """Check if authority level allows tool injection."""
        if authority == AuthorityLevel.HIGH.value:
            return self.high_authority.get("allow_tool_injection", False)
        return self.low_authority.get("allow_tool_injection", False)


@dataclass
class EnrichmentConfig:
    """Configuration for task enrichment."""
    
    bootstrap_intent_pack: BootstrapIntentConfig = None
    policy: AuthorityPolicy = None
    
    def __post_init__(self):
        if self.bootstrap_intent_pack is None:
            self.bootstrap_intent_pack = BootstrapIntentConfig()
        if self.policy is None:
            self.policy = AuthorityPolicy()
    
    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "EnrichmentConfig":
        """Load enrichment config from YAML data."""
        if not data:
            return cls()
        
        bootstrap_data = data.get("bootstrap_intent_pack", {})
        policy_data = data.get("policy", {})
        
        # Load bootstrap intent pack
        bootstrap = BootstrapIntentConfig(
            authority=bootstrap_data.get("authority", AuthorityLevel.LOW.value),
            domains=bootstrap_data.get("domains", {}),
            action_patterns=[
                p.get("pattern") if isinstance(p, dict) else p
                for p in bootstrap_data.get("action_patterns", [])
            ],
            numeric_pattern=bootstrap_data.get("numeric_pattern", r'(\d+(?:\.\d+)?)'),
            location_patterns=[
                p.get("pattern") if isinstance(p, dict) else p
                for p in bootstrap_data.get("location_patterns", [])
            ],
            unit_patterns=bootstrap_data.get("unit_patterns", {}),
        )
        
        # Load authority policy
        policy = AuthorityPolicy(
            low_authority=policy_data.get("low_authority", {}),
            high_authority=policy_data.get("high_authority", {}),
        )
        
        return cls(bootstrap_intent_pack=bootstrap, policy=policy)
    
    @classmethod
    def load_from_file(cls, config_path: Optional[str] = None) -> "EnrichmentConfig":
        """Load enrichment config from YAML file."""
        if config_path is None:
            config_path = os.getenv(
                "COORDINATOR_CONFIG_PATH",
                "/app/config/coordinator_config.yaml"
            )
        
        path = Path(config_path)
        if not path.exists() or not HAS_YAML:
            logger.debug(
                f"[EnrichmentConfig] Config file not found or YAML unavailable: {path}. "
                "Using defaults."
            )
            return cls()
        
        try:
            with open(path, "r") as f:
                raw_cfg = yaml.safe_load(f) or {}
            
            seedcore_cfg = raw_cfg.get("seedcore", {}) or {}
            coord_cfg = seedcore_cfg.get("coordinator", {}) or {}
            enrichment_cfg = coord_cfg.get("enrichment", {}) or {}
            
            return cls.from_yaml(enrichment_cfg)
        except Exception as e:
            logger.warning(
                f"[EnrichmentConfig] Failed to load config from {path}: {e}. Using defaults.",
                exc_info=True,
            )
            return cls()


class RegexIntentProvider:
    """
    Bootstrap intent provider using regex patterns loaded from config.
    
    This is a transitional implementation with LOW authority.
    Long-term, intent should come from FAST LLM, Eventizer, or PKG capability graphs.
    """
    
    def __init__(self, config: Optional[BootstrapIntentConfig] = None):
        """
        Initialize provider with config.
        
        Args:
            config: BootstrapIntentConfig (if None, uses defaults)
        """
        self.config = config or BootstrapIntentConfig()
        self.authority = self.config.authority
    
    def extract_intent(self, description: str, context: Any) -> Dict[str, Any]:
        """
        Extract intent from description using regex patterns from config.
        
        Returns:
            Dict with keys: domain, action, value, urgency, confidence, source, authority
        """
        desc_lower = description.lower()
        
        domain = None
        action = None
        value = None
        
        # Check domains from config
        for domain_name, domain_config in self.config.domains.items():
            keywords = domain_config.get("keywords", [])
            if any(re.search(rf'\b({kw})\b', desc_lower) for kw in keywords):
                domain = domain_name
                
                # Extract numeric value if pattern matches
                if domain_name == "temperature":
                    match = re.search(self.config.numeric_pattern, description)
                    if match:
                        value = float(match.group(1))
                
                # Extract action verb from config patterns
                for pattern_str in self.config.action_patterns:
                    match = re.search(pattern_str, desc_lower)
                    if match:
                        action = match.group(1) if match.groups() else match.group(0)
                        break
                
                break
        
        # Determine urgency
        urgency = "normal"
        if any(word in desc_lower for word in ["urgent", "immediately", "now", "asap"]):
            urgency = "high"
        
        # Compute confidence based on pattern matches
        confidence = 0.98 if domain else 0.5
        
        return {
            "domain": domain,
            "action": action,
            "value": value,
            "urgency": urgency,
            "confidence": confidence,
            "source": "regex_fallback",
            "authority": self.authority,
        }


class RoutingPolicy:
    """
    Policy-driven routing enrichment with authority awareness.
    
    This class applies routing policy based on intent, but does NOT hardcode
    tool mappings or skill requirements. Those should come from:
    - PKG (capability → tool graph)
    - RoleProfile (allowed tools, default skills)
    - Task type definitions
    """
    
    def __init__(self, config: Optional[EnrichmentConfig] = None):
        """
        Initialize routing policy with config.
        
        Args:
            config: EnrichmentConfig (if None, uses defaults)
        """
        self.config = config or EnrichmentConfig()
        self.policy = self.config.policy
    
    def enrich_routing(
        self,
        intent_class: Dict[str, Any],
        existing_routing: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Enrich routing envelope with soft hints (not hard constraints).
        
        Policy: Use 'specialization' (soft hint) by default.
        Only use 'required_specialization' (hard constraint) if:
        - Authority is HIGH and policy allows it
        - Task type explicitly requires it
        - PKG policy mandates it
        - User explicitly sets it
        
        This enricher respects authority levels and policy restrictions.
        """
        enrichments = {}
        domain = intent_class.get("domain")
        authority = intent_class.get("authority", AuthorityLevel.LOW.value)
        
        if not domain:
            return enrichments
        
        # Get specialization hint from config
        domain_config = self.config.bootstrap_intent_pack.domains.get(domain, {})
        spec_hint = domain_config.get("specialization_hint")
        
        if spec_hint:
            # Check if we can set required_specialization (hard constraint)
            if self.policy.can_set_required_specialization(authority):
                if not existing_routing.get("required_specialization"):
                    enrichments["required_specialization"] = spec_hint
            # Otherwise, set specialization (soft hint)
            elif not existing_routing.get("specialization"):
                enrichments["specialization"] = spec_hint
        
        # Add routing tags (for observability and filtering)
        routing_tags = []
        if domain:
            routing_tags.append(domain)
        if intent_class.get("action"):
            routing_tags.append(intent_class["action"])
        if domain == "temperature":
            routing_tags.extend(["temperature", "iot"])
        elif domain == "lighting":
            routing_tags.extend(["lighting", "iot"])
        
        if routing_tags:
            existing_tags = existing_routing.get("routing_tags", [])
            merged_tags = list(set(existing_tags + routing_tags))
            if merged_tags != existing_tags:
                enrichments["routing_tags"] = merged_tags
        
        return enrichments
    
    def resolve_location(
        self,
        description: str,
        multimodal: Dict[str, Any],
        task_context: Any,
    ) -> Optional[str]:
        """
        Resolve location context from description, multimodal, or task context.
        
        Returns location identifier (e.g., "room_401") or None if unknown.
        """
        # Check multimodal first (most reliable)
        location = multimodal.get("location_context")
        if location:
            return location
        
        # Try extracting from description using config patterns
        desc_lower = description.lower()
        for pattern_str in self.config.bootstrap_intent_pack.location_patterns:
            match = re.search(pattern_str, desc_lower, re.IGNORECASE)
            if match:
                # Extract room number
                if len(match.groups()) >= 2:
                    room_type = match.group(1).lower()
                    room_num = match.group(2)
                    return f"{room_type}_{room_num}"
                elif len(match.groups()) == 1:
                    room_num = match.group(1)
                    return f"room_{room_num}"
        
        # Check task context attributes
        if hasattr(task_context, "attributes"):
            location = task_context.attributes.get("location_context")
            if location:
                return location
        
        # Unknown location - do not guess
        return None


class CognitivePolicy:
    """
    Policy for cognitive mode decisions with authority awareness.
    
    Uses effective routing (existing + enrichments) to make decisions.
    """
    
    def __init__(self, config: Optional[EnrichmentConfig] = None):
        """
        Initialize cognitive policy with config.
        
        Args:
            config: EnrichmentConfig (if None, uses defaults)
        """
        self.config = config or EnrichmentConfig()
        self.policy = self.config.policy
    
    def decide_mode(
        self,
        task_type: str,
        intent_class: Dict[str, Any],
        effective_routing: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Decide cognitive mode: FAST vs PLANNER.
        
        Rule: Single action + high confidence + clear routing -> FAST path.
        Respects authority levels: LOW authority can only suggest, not mandate.
        
        Args:
            task_type: Current task type
            intent_class: Intent classification result (with authority)
            effective_routing: Merged routing (existing + enrichments)
        """
        enrichments = {}
        authority = intent_class.get("authority", AuthorityLevel.LOW.value)
        
        # If task is ACTION with high confidence intent, use FAST path
        if task_type == TaskType.ACTION.value:
            confidence = intent_class.get("confidence", 0.5)
            
            # Use effective routing (existing + enrichments) for gating
            has_specialization = (
                effective_routing.get("specialization") or
                effective_routing.get("required_specialization")
            )
            
            # LOW authority can only suggest FAST path (advisory only)
            # HIGH/MEDIUM authority can mandate it
            if confidence >= 0.85 and has_specialization:
                enrichments["cog_type"] = CognitiveType.CHAT.value
                if authority in (AuthorityLevel.HIGH.value, AuthorityLevel.MEDIUM.value):
                    # MEDIUM+ authority can set FAST path
                    enrichments["decision_kind"] = DecisionKind.FAST_PATH.value
                    enrichments["skip_retrieval"] = True
                elif self.policy.low_authority.get("allow_fast_path_suggestion", False):
                    # LOW authority: suggest but don't mandate (advisory only)
                    # The routing logic in execute.py will override this if PKG is empty
                    # or if other escalation conditions are met
                    enrichments["decision_kind"] = DecisionKind.FAST_PATH.value
                    enrichments["skip_retrieval"] = True
                    # Store authority in metadata so routing logic can check it
                    if "metadata" not in enrichments:
                        enrichments["metadata"] = {}
                    enrichments["metadata"]["intent_class"] = intent_class
            else:
                # Lower confidence or ambiguous -> let PKG decide
                enrichments["cog_type"] = CognitiveType.CHAT.value
                # decision_kind will be set by routing decision logic
        
        return enrichments


class TaskEnricher:
    """
    Deterministic task enricher for Coordinator.
    
    This class implements lightweight, rule-based enrichment that does NOT
    require LLM reasoning. It uses pattern matching, heuristics, and
    domain knowledge to enrich incomplete task payloads.
    
    Architecture: This is a bootstrap/fallback implementation. Long-term,
    intent should come from FAST LLM, Eventizer, or PKG capability graphs.
    """
    
    def __init__(
        self,
        intent_provider: Optional[IntentProvider] = None,
        config: Optional[EnrichmentConfig] = None,
    ):
        """
        Initialize enricher with optional intent provider and config.
        
        Args:
            intent_provider: Intent extraction provider (defaults to RegexIntentProvider)
            config: EnrichmentConfig (if None, loads from file)
        """
        self.config = config or EnrichmentConfig.load_from_file()
        self.intent_provider = intent_provider or RegexIntentProvider(
            self.config.bootstrap_intent_pack
        )
        self.routing_policy = RoutingPolicy(self.config)
        self.cognitive_policy = CognitivePolicy(self.config)
    
    def enrich_task(
        self,
        task_payload: Dict[str, Any],
        task_context: Any,  # TaskContext from execute.py
    ) -> EnrichmentResult:
        """
        Enrich a task payload with missing operational intent.
        
        Args:
            task_payload: TaskPayload as dict (from task.model_dump())
            task_context: TaskContext from _process_task_input
            
        Returns:
            EnrichmentResult with all enrichment decisions
        """
        description = task_context.description or task_payload.get("description", "")
        task_type = task_payload.get("type", "chat")
        params = task_payload.get("params", {})
        existing_routing = params.get("routing", {})
        
        # 1. Intent Classification (via provider, includes authority)
        intent_class = self.intent_provider.extract_intent(description, task_context)
        
        # 2. Task Nature Decision: ACTION vs CHAT (respects authority)
        new_task_type = self._decide_task_nature(
            current_type=task_type,
            description=description,
            intent_class=intent_class,
        )
        
        # 3. Routing Envelope Enrichment (authority-aware)
        routing_enrichments = self.routing_policy.enrich_routing(
            intent_class=intent_class,
            existing_routing=existing_routing,
        )
        
        # Compute effective routing (existing + enrichments) for downstream use
        effective_routing = {**existing_routing, **routing_enrichments}
        
        # 4. Location Context Resolution
        location_context = self.routing_policy.resolve_location(
            description=description,
            multimodal=params.get("multimodal", {}),
            task_context=task_context,
        )
        
        # 5. Cognitive Mode Decision (authority-aware)
        cognitive_enrichments = self.cognitive_policy.decide_mode(
            task_type=new_task_type,
            intent_class=intent_class,
            effective_routing=effective_routing,
        )
        
        # 6. Tool Calls Extraction (authority-aware)
        tool_calls = self._extract_tool_calls(
            description=description,
            intent_class=intent_class,
            effective_routing=effective_routing,
        )
        
        # 7. Multimodal Enrichments
        multimodal_enrichments = self._enrich_multimodal(
            existing_multimodal=params.get("multimodal", {}),
            location_context=location_context,
            intent_class=intent_class,
        )
        
        # 8. Compute confidence and reasoning
        confidence = self._compute_confidence(
            intent_class=intent_class,
            routing_enrichments=routing_enrichments,
            tool_calls=tool_calls,
        )
        
        reasoning = self._generate_reasoning(
            task_type=new_task_type,
            intent_class=intent_class,
            routing_enrichments=routing_enrichments,
            cognitive_enrichments=cognitive_enrichments,
        )
        
        return EnrichmentResult(
            task_type=new_task_type,
            routing_enrichments=routing_enrichments,
            cognitive_enrichments=cognitive_enrichments,
            multimodal_enrichments=multimodal_enrichments,
            tool_calls=tool_calls,
            confidence=confidence,
            reasoning=reasoning,
        )
    
    def _decide_task_nature(
        self,
        current_type: str,
        description: str,
        intent_class: Dict[str, Any],
    ) -> str:
        """
        Decide if task should be ACTION vs CHAT.
        
        Rule: If utterance is imperative + device-affecting, treat as ACTION.
        Respects authority: LOW authority can only suggest promotion.
        """
        authority = intent_class.get("authority", AuthorityLevel.LOW.value)
        
        # If already explicitly set to ACTION, keep it
        if current_type == TaskType.ACTION.value:
            return TaskType.ACTION.value
        
        # If already explicitly set to CHAT but has imperative + device-affecting
        if current_type == TaskType.CHAT.value:
            desc_lower = description.lower()
            
            # Check for imperative patterns from config
            has_imperative = any(
                re.search(pattern_str, desc_lower)
                for pattern_str in self.config.bootstrap_intent_pack.action_patterns
            )
            
            # Check for device-affecting patterns (any domain match)
            has_device_affecting = bool(intent_class.get("domain"))
            
            # If imperative + device-affecting, promote to ACTION
            # LOW authority can suggest, HIGH authority can mandate
            if has_imperative and has_device_affecting:
                if authority == AuthorityLevel.HIGH.value:
                    logger.info(
                        "[Enrichment] Promoting CHAT -> ACTION (HIGH authority): "
                        "imperative + device-affecting"
                    )
                    return TaskType.ACTION.value
                elif self.config.policy.low_authority.get("allow_task_promotion", False):
                    logger.info(
                        "[Enrichment] Promoting CHAT -> ACTION (LOW authority, advisory): "
                        "imperative + device-affecting"
                    )
                    return TaskType.ACTION.value
        
        # Default: keep current type
        return current_type
    
    def _extract_tool_calls(
        self,
        description: str,
        intent_class: Dict[str, Any],
        effective_routing: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Extract tool calls from description if applicable.
        
        Note: This is a bootstrap implementation. Long-term, tool selection
        should be handled by Cognitive engine based on:
        - PKG capability → tool graph
        - RoleProfile allowed tools
        - Task requirements
        
        Respects authority: Only HIGH authority can inject tools.
        """
        tool_calls = []
        domain = intent_class.get("domain")
        value = intent_class.get("value")
        authority = intent_class.get("authority", AuthorityLevel.LOW.value)
        
        # Check if authority allows tool injection
        if not self.config.policy.can_inject_tools(authority):
            return tool_calls
        
        # Only extract if we have high confidence
        if intent_class.get("confidence", 0.0) < 0.85:
            return tool_calls
        
        # Environment control tool calls
        if domain == "temperature" and value is not None:
            # Determine unit using config patterns
            desc_lower = description.lower()
            unit = "F"  # Default
            
            # Check Celsius patterns from config
            celsius_patterns = self.config.bootstrap_intent_pack.unit_patterns.get("celsius", [])
            if any(re.search(p, desc_lower) for p in celsius_patterns):
                unit = "C"
            
            tool_calls.append({
                "name": "iot.write.environment",
                "args": {
                    "parameter": "temperature",
                    "value": value,
                    "unit": unit,
                }
            })
        
        return tool_calls
    
    @classmethod
    def _enrich_multimodal(
        cls,
        existing_multimodal: Dict[str, Any],
        location_context: Optional[str],
        intent_class: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Enrich multimodal context with location and confidence.
        """
        enrichments = {}
        
        # Add location context if resolved
        if location_context and not existing_multimodal.get("location_context"):
            enrichments["location_context"] = location_context
        
        # Add confidence if high
        confidence = intent_class.get("confidence", 0.0)
        if confidence >= 0.85 and not existing_multimodal.get("confidence"):
            enrichments["confidence"] = confidence
        
        # Mark as real-time if voice source
        if existing_multimodal.get("source") == "voice":
            enrichments["is_real_time"] = True
        
        return enrichments
    
    @classmethod
    def _compute_confidence(
        cls,
        intent_class: Dict[str, Any],
        routing_enrichments: Dict[str, Any],
        tool_calls: List[Dict[str, Any]],
    ) -> float:
        """
        Compute overall confidence score for enrichment.
        """
        base_confidence = intent_class.get("confidence", 0.5)
        
        # Boost confidence if we have routing enrichments
        if routing_enrichments.get("specialization") or routing_enrichments.get("required_specialization"):
            base_confidence = min(1.0, base_confidence + 0.1)
        
        # Boost confidence if we extracted tool calls
        if tool_calls:
            base_confidence = min(1.0, base_confidence + 0.05)
        
        return base_confidence
    
    @classmethod
    def _generate_reasoning(
        cls,
        task_type: str,
        intent_class: Dict[str, Any],
        routing_enrichments: Dict[str, Any],
        cognitive_enrichments: Dict[str, Any],
    ) -> str:
        """
        Generate human-readable reasoning for enrichment decisions.
        """
        parts = []
        
        domain = intent_class.get("domain")
        authority = intent_class.get("authority", AuthorityLevel.LOW.value)
        source = intent_class.get("source", "unknown")
        
        if domain:
            parts.append(f"Detected {domain} control intent")
        
        if source:
            parts.append(f"source={source} (authority={authority})")
        
        if routing_enrichments.get("required_specialization"):
            parts.append(
                f"routed to {routing_enrichments['required_specialization']} specialization (hard constraint)"
            )
        elif routing_enrichments.get("specialization"):
            parts.append(
                f"routed to {routing_enrichments['specialization']} specialization (soft hint)"
            )
        
        if cognitive_enrichments.get("decision_kind") == DecisionKind.FAST_PATH.value:
            parts.append("using FAST path (single action, high confidence)")
        
        return ". ".join(parts) if parts else "No enrichment applied"


# Global enricher instance (can be replaced with custom provider/config)
_default_enricher: Optional[TaskEnricher] = None


def get_default_enricher() -> TaskEnricher:
    """Get or create default enricher instance (lazy initialization)."""
    global _default_enricher
    if _default_enricher is None:
        _default_enricher = TaskEnricher()
    return _default_enricher


def enrich_task_payload(
    task_payload: Dict[str, Any],
    task_context: Any,
) -> Dict[str, Any]:
    """
    Public API: Enrich task payload with missing fields.
    
    This function applies enrichment to the task payload and returns
    the enriched payload dict. It should be called early in the
    Coordinator flow, after Eventizer processing but before PKG evaluation.
    
    Args:
        task_payload: TaskPayload as dict (from task.model_dump())
        task_context: TaskContext from _process_task_input
        
    Returns:
        Enriched task payload dict (mutates task_payload in place and returns it)
    """
    try:
        enricher = get_default_enricher()
        result = enricher.enrich_task(task_payload, task_context)
        
        # Apply enrichments to task_payload
        # 1. Update task type
        if result.task_type != task_payload.get("type"):
            task_payload["type"] = result.task_type
            logger.info(
                f"[Enrichment] Updated task type: {task_payload.get('type')} -> {result.task_type}"
            )
        
        # 2. Merge routing enrichments
        params = task_payload.setdefault("params", {})
        routing = params.setdefault("routing", {})
        routing.update(result.routing_enrichments)
        
        # 3. Merge cognitive enrichments
        cognitive = params.setdefault("cognitive", {})
        cognitive.update(result.cognitive_enrichments)
        
        # 4. Merge multimodal enrichments
        multimodal = params.setdefault("multimodal", {})
        multimodal.update(result.multimodal_enrichments)
        
        # 5. Add tool calls if extracted (allow multiple calls, dedup by name+args)
        if result.tool_calls:
            tool_calls = params.setdefault("tool_calls", [])
            # Allow multiple tool calls, but deduplicate exact matches
            existing_calls = {
                (tc.get("name"), str(tc.get("args", {})))
                for tc in tool_calls
                if isinstance(tc, dict)
            }
            for tc in result.tool_calls:
                call_key = (tc.get("name"), str(tc.get("args", {})))
                if call_key not in existing_calls:
                    tool_calls.append(tc)
                    existing_calls.add(call_key)
        
        # 6. Set interaction mode if not set
        interaction = params.setdefault("interaction", {})
        if not interaction.get("mode"):
            interaction["mode"] = "coordinator_routed"
        
        logger.info(
            f"[Enrichment] Enriched task {task_context.task_id}: "
            f"confidence={result.confidence:.2f}, reasoning={result.reasoning}"
        )
        
        return task_payload
        
    except Exception as e:
        logger.warning(
            f"[Enrichment] Failed to enrich task {task_context.task_id}: {e}",
            exc_info=True,
        )
        # Return original payload on error (non-fatal)
        return task_payload
