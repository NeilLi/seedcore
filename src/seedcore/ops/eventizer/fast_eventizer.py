#!/usr/bin/env python3
"""
Fast-Path Eventizer for SeedCore (hardened)

- Deterministic, sub-ms path for PKG inputs
- Minimal PII redaction with lower FP rate (Luhn for CC)
- No external deps; pure Python `re` (can swap for re2 if desired)
- Uses unified EventType from eventizer.py for PKG compatibility
"""

from __future__ import annotations
import re
import time
import uuid
import hashlib
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass

# Import unified EventType from eventizer models for PKG compatibility
from seedcore.models.eventizer import EventType

if TYPE_CHECKING:
    from seedcore.models.eventizer import EventizerResponse

# -------------------------
# Helpers
# -------------------------

def _luhn_ok(num: str) -> bool:
    s = 0
    dbl = False
    for ch in reversed(num):
        if not ch.isdigit():
            continue
        d = ord(ch) - 48
        if dbl:
            d = d * 2
            if d > 9:
                d -= 9
        s += d
        dbl = not dbl
    return s % 10 == 0

def _clip_text(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    # don’t cut mid-word if possible
    cut = s.rfind(" ", 0, limit)
    return s[: max(1, cut)].rstrip() + " …"

# -------------------------
# Types
# -------------------------
# EventType is now imported from seedcore.models.eventizer for unified PKG compatibility

@dataclass(slots=True)
class FastEventTags:
    """FastEventizer tags with keyword extraction for semantic mapping."""
    priority: int
    event_types: List[EventType]  # Hard tags from regex patterns
    keywords: List[str]  # Extracted keywords for vector search and PKG evaluation
    domain: Optional[str]
    confidence: float
    needs_ml_fallback: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "event_types": [e.value for e in self.event_types],
            "keywords": self.keywords,
            "domain": self.domain,
            "confidence": self.confidence,
            "needs_ml_fallback": self.needs_ml_fallback,
        }

@dataclass(slots=True)
class FastAttributes:
    has_urgency: bool
    has_location: bool
    has_timestamp: bool
    text_length: int
    word_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_urgency": self.has_urgency,
            "has_location": self.has_location,
            "has_timestamp": self.has_timestamp,
            "text_length": self.text_length,
            "word_count": self.word_count,
        }

@dataclass(slots=True)
class FastEventizerResult:
    event_tags: FastEventTags
    attributes: FastAttributes
    processing_time_ms: float
    patterns_applied: int
    pii_redacted: bool
    original_text: Optional[str]  # gated; can be None
    processed_text: str

# -------------------------
# Fast Eventizer
# -------------------------

class FastEventizer:
    """
    Lightweight, in-process eventizer optimized for <1ms p95.
    """

    __slots__ = (
        "_max_chars",
        "_time_budget_ms",
        "_email_re",
        "_phone_re",
        "_ssn_re",
        "_cc16_re",
        "_emerg_re",
        "_sec_re",
        "_warn_re",
        "_maint_re",
        "_vip_re",
        "_privacy_re",
        "_allergen_re",
        "_hvac_re",
        "_luggage_re",
        "_loc_res",
        "_ts_res",
    )

    def __init__(self, *, max_chars: int = 16384, time_budget_ms: float = 2.0):
        self._max_chars = int(max_chars)
        self._time_budget_ms = float(time_budget_ms)
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        # --- PII (minimal) ---
        self._email_re = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
        # common US and flexible separators; avoid greedy digits elsewhere
        self._phone_re = re.compile(
            r'\b(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b'
        )
        self._ssn_re = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
        # 13–19 digits with spaces/dashes; we’ll Luhn-filter extracted digits
        self._cc16_re = re.compile(
            r'\b(?:\d[ -]?){13,19}\b'
        )

        # --- Categories (grouped alternations, one search each) ---
        self._emerg_re = re.compile(
            r'\b(emergency|urgent|critical|fire|evacuate|evacuation|immediate|asap|help|assistance|911)\b',
            re.IGNORECASE,
        )
        self._sec_re = re.compile(
            r'\b(security|breach|unauthorized|intrusion|hack|attack|access\s+denied|permission|credential|password|suspicious|malware|virus|threat)\b',
            re.IGNORECASE,
        )
        self._warn_re = re.compile(
            r'\b(warning|caution|alert|notice|issue|problem|high|elevated|increased|spike|surge|failing|degraded|slow|timeout|error)\b',
            re.IGNORECASE,
        )
        self._maint_re = re.compile(
            r'\b(maintenance|update|upgrade|patch|fix|schedule|planned|routine|preventive|backup|restore|recovery|cleanup)\b',
            re.IGNORECASE,
        )
        
        # --- Domain-specific patterns (for fallback planner) ---
        self._vip_re = re.compile(
            r'\b(vip|executive|presidential\s*suite|ceo|director|cxo|concierge|priority\s*guest)\b',
            re.IGNORECASE,
        )
        self._privacy_re = re.compile(
            r'\b(privacy|confidential|private|sensitive|restricted|classified)\b',
            re.IGNORECASE,
        )
        self._allergen_re = re.compile(
            r'\b(allergen|allergy|peanut|nuts|dairy|gluten|shellfish|sesame|food\s*safety)\b',
            re.IGNORECASE,
        )
        # HVAC pattern: Look for HVAC keywords anywhere in text that also has fault indicators
        # More flexible to catch "HVAC system malfunction" or "temperature too high"
        self._hvac_re = re.compile(
            r'(?=.*\b(hvac|temperature|thermostat|heating|cooling|air\s*conditioning|ventilation)\b)(?=.*\b(fault|issue|problem|malfunction|broken|not\s*working|too\s*(?:hot|cold|high|low))\b)',
            re.IGNORECASE | re.DOTALL,
        )
        self._luggage_re = re.compile(
            r'\b(luggage|baggage|bag).*\b(lost|mishandled|wrong\s*room|misdeliver|custody|chain)\b',
            re.IGNORECASE,
        )

        # --- Location / timestamp ---
        self._loc_res = [
            re.compile(r'\b(room|floor|building|office|suite)\s+([A-Za-z0-9-]+)\b', re.IGNORECASE),
            re.compile(r'\b(server|host|node)\s+([A-Za-z0-9.-]+)\b', re.IGNORECASE),
            re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),  # IPv4 as location-ish
        ]
        self._ts_res = [
            re.compile(r'\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b'),   # 2025-10-16 12:34:56
            re.compile(r'\b\d{2}:\d{2}(:\d{2})?\s*(am|pm)?\b', re.IGNORECASE),  # 12:34 or 12:34:56 AM
            re.compile(r'\b\d{1,2}/\d{1,2}/\d{4}\b'),                     # 10/16/2025
        ]

    # ----- PII -----

    def _redact_pii(self, text: str) -> Tuple[str, bool]:
        redacted = False

        # Emails
        if self._email_re.search(text):
            text = self._email_re.sub('[EMAIL_REDACTED]', text)
            redacted = True

        # Phones
        if self._phone_re.search(text):
            text = self._phone_re.sub('[PHONE_REDACTED]', text)
            redacted = True

        # SSN
        if self._ssn_re.search(text):
            text = self._ssn_re.sub('[SSN_REDACTED]', text)
            redacted = True

        # Credit cards: Luhn-validate extracted digits
        cc_hits = list(self._cc16_re.finditer(text))
        if cc_hits:
            new_text = []
            last = 0
            for m in cc_hits:
                span = m.span()
                segment = text[span[0]:span[1]]
                digits = ''.join(ch for ch in segment if ch.isdigit())
                if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                    new_text.append(text[last:span[0]])
                    new_text.append('[CC_REDACTED]')
                    last = span[1]
                    redacted = True
            if redacted:
                new_text.append(text[last:])
                text = ''.join(new_text)

        return text, redacted

    # ----- Classification -----

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract significant keywords from text for semantic mapping and PKG evaluation.
        
        Keywords are extracted from matched patterns and important terms, enabling
        vector search against v_unified_cortex_memory and PKG rule evaluation.
        """
        keywords: List[str] = []
        text_lower = text.lower()
        
        # Extract keywords from matched patterns (non-overlapping, significant terms)
        # This is a simple extraction - can be enhanced with NLP libraries if needed
        significant_words = {
            # Emergency/urgency indicators
            "emergency", "urgent", "critical", "fire", "evacuate", "help", "911",
            # Security indicators
            "security", "breach", "unauthorized", "intrusion", "suspicious", "threat",
            # Maintenance indicators
            "maintenance", "update", "fix", "broken", "malfunction", "issue", "problem",
            # Domain-specific
            "vip", "executive", "presidential", "concierge",
            "privacy", "confidential", "private", "sensitive",
            "allergen", "allergy", "peanut", "nuts", "dairy", "gluten",
            "hvac", "temperature", "thermostat", "heating", "cooling", "air", "stuffy",
            "luggage", "baggage", "lost", "mishandled",
            # Location indicators
            "room", "floor", "building", "lobby", "suite",
            # Temporal indicators
            "now", "immediate", "asap", "soon",
        }
        
        # Extract words that match significant terms (simple word boundary matching)
        words = re.findall(r'\b\w+\b', text_lower)
        for word in words:
            if word in significant_words and word not in keywords:
                keywords.append(word)
        
        return keywords

    def _extract_event_types(self, text: str, start_ms: float, budget_ms: float) -> Tuple[List[EventType], int]:
        patterns_applied = 0
        ets: List[EventType] = []

        # Emergency first, early exit if found
        if self._emerg_re.search(text):
            ets.append(EventType.EMERGENCY)
            patterns_applied += 1
            # still check security quickly (can be both)
            if self._sec_re.search(text):
                ets.append(EventType.SECURITY)
                patterns_applied += 1
            return ets, patterns_applied

        # Domain-specific patterns BEFORE generic ones (higher priority for fallback planner)
        # These patterns are more specific and should override generic classifications
        if self._vip_re.search(text):
            ets.append(EventType.VIP)
            patterns_applied += 1
        
        if self._privacy_re.search(text):
            ets.append(EventType.PRIVACY)
            patterns_applied += 1
        
        if self._allergen_re.search(text):
            ets.append(EventType.ALLERGEN)
            patterns_applied += 1
        
        if self._hvac_re.search(text):
            # Map HVAC fault to HVAC (unified EventType)
            ets.append(EventType.HVAC)
            patterns_applied += 1
        
        if self._luggage_re.search(text):
            # Map LUGGAGE_CUSTODY to LUGGAGE (unified EventType uses "luggage_custody" value)
            ets.append(EventType.LUGGAGE)
            patterns_applied += 1

        # Generic patterns (lower priority - these are less specific)
        # Skip these if we already found domain-specific tags
        if not ets:
            if self._sec_re.search(text):
                ets.append(EventType.SECURITY)
                patterns_applied += 1

            if self._warn_re.search(text):
                # Map WARNING to ROUTINE (unified EventType doesn't have WARNING)
                ets.append(EventType.ROUTINE)
                patterns_applied += 1

            if self._maint_re.search(text):
                ets.append(EventType.MAINTENANCE)
                patterns_applied += 1

        if not ets:
            # Map NORMAL to ROUTINE (unified EventType doesn't have NORMAL)
            ets.append(EventType.ROUTINE)

        return ets, patterns_applied

    def _determine_priority(self, ets: List[EventType]) -> int:
        if EventType.EMERGENCY in ets:
            return 10
        if EventType.SECURITY in ets:
            return 8
        # Domain-specific types get elevated priority
        if EventType.ALLERGEN in ets:
            return 9  # Food safety is critical
        if EventType.VIP in ets or EventType.PRIVACY in ets:
            return 7  # VIP/Privacy needs elevated priority
        if EventType.HVAC in ets:
            return 6  # HVAC issues need prompt attention
        if EventType.LUGGAGE in ets:
            return 6  # Lost luggage needs quick resolution
        if EventType.ROUTINE in ets:
            return 5  # Routine/warning events
        if EventType.MAINTENANCE in ets:
            return 4
        return 2

    def _extract_attributes(self, text: str) -> FastAttributes:
        tl = len(text)
        wc = len(text.split())
        has_urgency = bool(self._emerg_re.search(text))
        has_location = any(p.search(text) for p in self._loc_res)
        has_timestamp = any(p.search(text) for p in self._ts_res)
        return FastAttributes(
            has_urgency=has_urgency,
            has_location=has_location,
            has_timestamp=has_timestamp,
            text_length=tl,
            word_count=wc,
        )

    def _confidence_and_fallback(self, pats: int, tl: int) -> Tuple[float, bool]:
        if pats > 2:
            conf, need_ml = 0.9, False
        elif pats > 0:
            conf, need_ml = 0.7, False
        else:
            conf, need_ml = 0.3, True
        if tl > 2000:
            conf *= 0.8
            need_ml = True
        return conf, need_ml

    # ----- Public API -----

    def process_text(
        self,
        text: str,
        task_type: str = "",
        domain: str = "",
        *,
        include_original_text: bool = False,   # safer default
    ) -> FastEventizerResult:
        start = time.perf_counter()

        # Hard cap text to keep p95 tight
        clipped = _clip_text(text, self._max_chars)

        # PII redaction (fast)
        processed_text, pii_redacted = self._redact_pii(clipped)

        # Classify
        ets, pats = self._extract_event_types(processed_text, start, self._time_budget_ms)
        keywords = self._extract_keywords(processed_text)  # Extract keywords for semantic mapping
        priority = self._determine_priority(ets)
        attrs = self._extract_attributes(processed_text)
        conf, need_ml = self._confidence_and_fallback(pats, attrs.text_length)

        tags = FastEventTags(
            priority=priority,
            event_types=ets,
            keywords=keywords,  # Keywords for vector search and PKG evaluation
            domain=domain or None,
            confidence=conf,
            needs_ml_fallback=need_ml,
        )

        dt_ms = (time.perf_counter() - start) * 1000.0

        return FastEventizerResult(
            event_tags=tags,
            attributes=attrs,
            processing_time_ms=dt_ms,
            patterns_applied=pats,
            pii_redacted=pii_redacted,
            original_text=text if include_original_text else None,
            processed_text=processed_text,
        )

# -------------------------
# Conversion to EventizerResponse
# -------------------------

def fast_result_to_eventizer_response(
    result: FastEventizerResult,
    original_text: str,
    *,
    task_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> "EventizerResponse":
    """
    Convert FastEventizerResult to EventizerResponse for unified Coordinator interface.
    
    This allows the Coordinator to work with a single, unified EventizerResponse object
    regardless of whether the event was processed by FastEventizer or DeepEventizer.
    """
    from seedcore.models.eventizer import (
        EventizerResponse,
        EventTags,
        EventAttributes,
        EventSignals,
        ConfidenceScore,
        ConfidenceLevel,
        RouteDecision,
        Urgency,
    )
    
    # Calculate SHA256 of original text
    original_text_sha256 = hashlib.sha256(original_text.encode()).hexdigest()
    
    # Convert event types to unified EventType enum values (hard tags)
    hard_tags = [et for et in result.event_tags.event_types]
    
    # Extract keywords (for vector search and PKG evaluation)
    keywords = getattr(result.event_tags, 'keywords', [])
    
    # Determine urgency from priority
    if result.event_tags.priority >= 9:
        urgency = Urgency.CRITICAL
    elif result.event_tags.priority >= 7:
        urgency = Urgency.HIGH
    elif result.event_tags.priority >= 5:
        urgency = Urgency.NORMAL
    else:
        urgency = Urgency.LOW
    
    # Build EventTags with new flexible structure
    # resolved_type defaults to first hard tag or "routine" - PKG will override this
    resolved_type = hard_tags[0].value if hard_tags else "routine"
    
    event_tags = EventTags(
        hard_tags=hard_tags,  # Deterministic tags from regex patterns
        soft_tags=[],  # Will be populated by PKG/vector search
        resolved_type=resolved_type,  # Default to hard tag, PKG will resolve final type
        event_types=hard_tags,  # Backward compatibility
        keywords=keywords,  # Keywords for semantic mapping
        entities=[],  # FastEventizer doesn't extract entities
        patterns=[],  # FastEventizer doesn't return PatternMatch objects
        priority=result.event_tags.priority,
        urgency=urgency,
    )
    
    # Build EventAttributes
    attributes = EventAttributes(
        required_service=None,
        required_skill=None,
        target_organ=None,
        processing_timeout=None,
        resource_requirements={},
        routing_hints={
            "has_urgency": result.attributes.has_urgency,
            "has_location": result.attributes.has_location,
            "has_timestamp": result.attributes.has_timestamp,
            "text_length": result.attributes.text_length,
            "word_count": result.attributes.word_count,
        },
    )
    
    # Build ConfidenceScore
    confidence = ConfidenceScore(
        overall_confidence=result.event_tags.confidence,
        confidence_level=(
            ConfidenceLevel.HIGH
            if result.event_tags.confidence >= 0.9
            else ConfidenceLevel.MEDIUM
            if result.event_tags.confidence >= 0.7
            else ConfidenceLevel.LOW
        ),
        needs_ml_fallback=result.event_tags.needs_ml_fallback,
        fallback_reasons=(
            ["low_confidence", "needs_deep_analysis"]
            if result.event_tags.needs_ml_fallback
            else []
        ),
        processing_notes=[f"fast_eventizer: {result.patterns_applied} patterns applied"],
    )
    
    # Determine decision_kind based on confidence and needs_ml_fallback
    if result.event_tags.needs_ml_fallback:
        decision_kind = RouteDecision.PLANNER
    elif result.event_tags.confidence >= 0.9:
        decision_kind = RouteDecision.FAST
    else:
        decision_kind = RouteDecision.FAST
    
    return EventizerResponse(
        original_text=original_text,
        original_text_sha256=original_text_sha256,
        normalized_text=result.processed_text,  # FastEventizer doesn't normalize separately
        processed_text=result.processed_text,
        text_normalization=None,  # FastEventizer doesn't provide normalization details
        pattern_compilation=None,  # FastEventizer doesn't provide compilation details
        pii=None,  # FastEventizer doesn't provide detailed PII audit
        event_tags=event_tags,
        attributes=attributes,
        signals=EventSignals(),  # FastEventizer doesn't compute OCPS signals, use defaults
        multimodal=None,  # FastEventizer doesn't handle multimodal
        pkg_hint=None,  # FastEventizer doesn't compute PKG hints
        decision_hint=None,
        decision_kind=decision_kind,
        task_id=task_id or str(uuid.uuid4()),
        confidence=confidence,
        processing_time_ms=result.processing_time_ms,
        patterns_applied=result.patterns_applied,
        pii_redacted=result.pii_redacted,
        warnings=[],
        errors=[],
        processing_log=[f"fast_eventizer: {result.patterns_applied} patterns applied"],
        eventizer_version="1.2.0",
        engines={"fast_eventizer": "1.0.0"},
        pkg_snapshot_version=None,
        pkg_snapshot_id=None,
        pkg_validation_status=None,
        pkg_deployment_info=None,
    )


# -------------------------
# Singleton & convenience
# -------------------------

_fast_eventizer: Optional[FastEventizer] = None

def get_fast_eventizer() -> FastEventizer:
    global _fast_eventizer
    if _fast_eventizer is None:
        _fast_eventizer = FastEventizer()
    return _fast_eventizer

def process_text_fast(text: str, task_type: str = "", domain: str = "", *, include_original_text: bool = False) -> Dict[str, Any]:
    ev = get_fast_eventizer()
    res = ev.process_text(text, task_type, domain, include_original_text=include_original_text)
    return {
        "event_tags": res.event_tags.to_dict(),
        "attributes": res.attributes.to_dict(),
        "confidence": {
            "overall_confidence": res.event_tags.confidence,
            "needs_ml_fallback": res.event_tags.needs_ml_fallback,
        },
        "processing_time_ms": res.processing_time_ms,
        "patterns_applied": res.patterns_applied,
        "pii_redacted": res.pii_redacted,
        "original_text": res.original_text,     # likely None unless explicitly enabled
        "processed_text": res.processed_text,
        "processing_log": [f"fast_eventizer: {res.patterns_applied} patterns applied"],
        "fast_path": True,
    }
