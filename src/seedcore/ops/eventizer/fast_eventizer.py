#!/usr/bin/env python3
"""
SeedCore Fast Eventizer (framework-grade)

Goals:
- Deterministic (<1ms p95 typical)
- Data-driven via fast_eventizer_patterns.json
- Unified EventType output for PKG compatibility
- Minimal PII redaction (Luhn for CC) with low FP rate
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Iterable

from seedcore.models.eventizer import (
    EventType,
    EventizerResponse,
    EventTags,
    EventAttributes,
    EventSignals,
    ConfidenceScore,
    ConfidenceLevel,
    RouteDecision,
    Urgency,
)
import hashlib
# Architecture: Normalization happens BEFORE FastEventizer (Coordinator layer)
# FastEventizer receives pre-normalized text as a reflex sensor


# -------------------------
# Helpers
# -------------------------

_FLAG_MAP: Dict[str, int] = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "UNICODE": re.UNICODE,
}

def _luhn_ok(num: str) -> bool:
    s = 0
    dbl = False
    for ch in reversed(num):
        if not ch.isdigit():
            continue
        d = ord(ch) - 48
        if dbl:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        dbl = not dbl
    return s % 10 == 0

def _clip_text(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s.rfind(" ", 0, limit)
    return s[: max(1, cut)].rstrip() + " …"

def _pack_checksum(raw_json_bytes: bytes) -> str:
    return hashlib.sha256(raw_json_bytes).hexdigest()

def _to_event_type(name: str) -> EventType:
    # Accept either enum value strings or names; fallback to CUSTOM if unknown.
    try:
        return EventType(name)
    except Exception:
        try:
            return EventType(name.lower())
        except Exception:
            return EventType.CUSTOM


# -------------------------
# Data Model
# -------------------------

@dataclass(frozen=True, slots=True)
class PatternEmit:
    event_types: Tuple[EventType, ...]
    priority: int

@dataclass(frozen=True, slots=True)
class PatternSpec:
    id: str
    regex: str
    flags: int
    emit: PatternEmit
    keywords: Tuple[str, ...]
    early_exit: bool = False

@dataclass(frozen=True, slots=True)
class RedactionRule:
    id: str
    regex: str
    flags: int
    replacement: str
    validator: Optional[str] = None  # e.g., "luhn"

@dataclass(frozen=True, slots=True)
class CompiledPack:
    pack_id: str
    pack_version: str
    schema_version: str
    checksum: str
    max_chars: int
    time_budget_ms: float
    fallback_event_type: EventType

    pii_rules: Tuple[Tuple[RedactionRule, re.Pattern], ...]
    patterns: Tuple[Tuple[PatternSpec, re.Pattern], ...]

    keyword_lexicon: Set[str]
    loc_res: Tuple[re.Pattern, ...]
    ts_res: Tuple[re.Pattern, ...]


@dataclass(slots=True)
class FastEventTags:
    priority: int
    event_types: List[EventType]
    keywords: List[str]
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

# Architecture: FastEventizer now returns EventizerResponse directly (no separate result class)
# This removes conversion bugs and simplifies the codebase


# -------------------------
# Pack Loader
# -------------------------

def load_pattern_pack(path: str) -> CompiledPack:
    raw = open(path, "rb").read()
    checksum = _pack_checksum(raw)
    doc = json.loads(raw.decode("utf-8"))

    defaults = doc.get("defaults", {})
    max_chars = int(defaults.get("max_chars", 16384))
    time_budget_ms = float(defaults.get("time_budget_ms", 2.0))
    fallback_event_type = _to_event_type(defaults.get("fallback_event_type", "routine"))

    # PII rules
    pii_rules: List[Tuple[RedactionRule, re.Pattern]] = []
    for rr in doc.get("pii_redaction", []) or []:
        flags = 0
        for f in rr.get("flags", []) or []:
            flags |= _FLAG_MAP.get(f, 0)
        rule = RedactionRule(
            id=str(rr["id"]),
            regex=str(rr["regex"]),
            flags=flags,
            replacement=str(rr["replacement"]),
            validator=(rr.get("validator") or {}).get("type") if isinstance(rr.get("validator"), dict) else rr.get("validator"),
        )
        pii_rules.append((rule, re.compile(rule.regex, rule.flags)))

    # Main patterns (evaluation order = file order; keep deterministic)
    patterns: List[Tuple[PatternSpec, re.Pattern]] = []
    for p in doc.get("patterns", []) or []:
        flags = 0
        for f in p.get("flags", []) or []:
            flags |= _FLAG_MAP.get(f, 0)

        emit = p.get("emit") or {}
        evs = tuple(_to_event_type(x) for x in (emit.get("event_types") or []))
        pri = int(emit.get("priority", 0))
        spec = PatternSpec(
            id=str(p["id"]),
            regex=str(p["regex"]),
            flags=flags,
            emit=PatternEmit(event_types=evs, priority=pri),
            keywords=tuple(str(x).lower() for x in (p.get("keywords") or [])),
            early_exit=bool(p.get("early_exit", False)),
        )
        patterns.append((spec, re.compile(spec.regex, spec.flags)))

    # Keyword lexicon
    lex_terms = ((doc.get("keyword_lexicon") or {}).get("terms") or [])
    keyword_lexicon: Set[str] = {str(t).lower() for t in lex_terms}

    # Location/timestamp regexes
    loc_res = tuple(
        re.compile(x["regex"], sum(_FLAG_MAP.get(f, 0) for f in (x.get("flags") or [])))
        for x in (doc.get("location_patterns") or [])
    )
    ts_res = tuple(
        re.compile(x["regex"], sum(_FLAG_MAP.get(f, 0) for f in (x.get("flags") or [])))
        for x in (doc.get("timestamp_patterns") or [])
    )

    return CompiledPack(
        pack_id=str(doc.get("pack_id", "unknown")),
        pack_version=str(doc.get("pack_version", "0.0.0")),
        schema_version=str(doc.get("schema_version", "0")),
        checksum=checksum,
        max_chars=max_chars,
        time_budget_ms=time_budget_ms,
        fallback_event_type=fallback_event_type,
        pii_rules=tuple(pii_rules),
        patterns=tuple(patterns),
        keyword_lexicon=keyword_lexicon,
        loc_res=loc_res,
        ts_res=ts_res,
    )


# -------------------------
# Fast Eventizer Engine
# -------------------------

class FastEventizer:
    """
    Data-driven, deterministic fast eventizer.
    
    Focus: Emergency detection and fast routing decisions.
    - Basic text normalization (AGGRESSIVE tier) for consistent pattern matching
    - Minimal PII redaction (optional, emergency-focused)
    - Fast pattern matching for emergency detection
    - Designed to complement EventizerService (comprehensive processing)
    """

    __slots__ = ("_pack",)

    def __init__(self, pack: CompiledPack):
        self._pack = pack
        # Architecture: FastEventizer is a reflex sensor that receives pre-normalized text.
        # Normalization happens BEFORE FastEventizer in the pipeline (Coordinator layer).
        # This ensures single normalization point and consistent pattern matching.

    def _detect_pii_indicators(self, text: str) -> Dict[str, bool]:
        """
        Detect PII presence without redaction (reflex sensor).
        
        Architecture: FastEventizer is a reflex sensor, not an interpreter.
        It detects PII presence and emits flags for PKG/routing decisions.
        Actual PII redaction is performed by EventizerService (comprehensive, policy-driven).
        
        Args:
            text: Input text (normalized)
        
        Returns:
            Dictionary of PII detection flags (e.g., {"possible_email": True, "possible_cc": False})
        """
        indicators: Dict[str, bool] = {}
        
        if not self._pack.pii_rules:
            return indicators
        
        for rule, rx in self._pack.pii_rules:
            hits = list(rx.finditer(text))
            if not hits:
                indicators[f"possible_{rule.id}"] = False
                continue
            
            # Special validation hook (Luhn for CC candidates)
            # This is critical for emergency detection to avoid false positives
            if rule.validator == "luhn":
                validated = False
                for m in hits:
                    seg = text[m.start():m.end()]
                    digits = "".join(ch for ch in seg if ch.isdigit())
                    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                        validated = True
                        break
                indicators[f"possible_{rule.id}"] = validated
            else:
                # Simple detection (regex match found)
                indicators[f"possible_{rule.id}"] = True
        
        return indicators

    def _extract_keywords(self, processed_text: str, matched_specs: Iterable[PatternSpec]) -> List[str]:
        kw: List[str] = []
        seen: Set[str] = set()

        # 1) Add pattern-provided keywords first (cheap + high precision)
        for spec in matched_specs:
            for k in spec.keywords:
                if k and k not in seen:
                    kw.append(k)
                    seen.add(k)

        # 2) Optional lexicon scan (still cheap; word boundary only)
        if self._pack.keyword_lexicon:
            words = re.findall(r"\b\w+\b", processed_text.lower())
            for w in words:
                if w in self._pack.keyword_lexicon and w not in seen:
                    kw.append(w)
                    seen.add(w)

        return kw

    def _extract_event_types(self, processed_text: str) -> Tuple[List[EventType], int, List[PatternSpec], int]:
        """
        Returns:
          - event_types
          - patterns_applied
          - matched_specs
          - computed_priority
        """
        ets: List[EventType] = []
        matched: List[PatternSpec] = []
        patterns_applied = 0
        priority = 0

        # Deterministic evaluation order (file order)
        for spec, rx in self._pack.patterns:
            if rx.search(processed_text):
                patterns_applied += 1
                matched.append(spec)

                # Emit hard tags
                for et in spec.emit.event_types:
                    if et not in ets:
                        ets.append(et)

                # Priority = max of matched emits (simple + deterministic)
                if spec.emit.priority > priority:
                    priority = spec.emit.priority

                # Emergency fast exit
                if spec.early_exit:
                    break

        if not ets:
            ets = [self._pack.fallback_event_type]
            if priority == 0:
                priority = 5 if self._pack.fallback_event_type.value == "routine" else 2

        return ets, patterns_applied, matched, priority

    def _extract_attributes(self, processed_text: str, ets: List[EventType]) -> FastAttributes:
        tl = len(processed_text)
        wc = len(processed_text.split())
        has_location = any(p.search(processed_text) for p in self._pack.loc_res) if self._pack.loc_res else False
        has_timestamp = any(p.search(processed_text) for p in self._pack.ts_res) if self._pack.ts_res else False
        has_urgency = EventType.EMERGENCY in ets
        return FastAttributes(
            has_urgency=has_urgency,
            has_location=has_location,
            has_timestamp=has_timestamp,
            text_length=tl,
            word_count=wc,
        )

    def _confidence_and_fallback(
        self, 
        patterns_applied: int, 
        text_length: int,
        priority: int = 0,
        event_types: List[EventType] = None
    ) -> Tuple[float, bool]:
        """
        Calculate confidence and ML fallback decision.
        
        Architecture: Emergency/high-priority cases get high confidence and no ML fallback.
        This ensures reflex sensor can route emergencies immediately without deep reasoning.
        """
        # Emergency/high-priority cases: high confidence, no ML fallback
        is_emergency = EventType.EMERGENCY in (event_types or [])
        is_high_priority = priority >= 9
        
        if is_emergency or is_high_priority:
            # Emergency detection: high confidence, no ML fallback (reflex sensor can route immediately)
            return 0.95, False
        
        # Normal pattern-based confidence calculation
        if patterns_applied >= 3:
            conf, need_ml = 0.90, False
        elif patterns_applied >= 1:
            conf, need_ml = 0.70, False
        else:
            conf, need_ml = 0.30, True

        # Very long text → encourage deep path (you already did this)
        if text_length > 2000:
            conf *= 0.80
            need_ml = True
        return conf, need_ml

    def process_text(
        self,
        normalized_text: str,
        original_text: str = "",
        task_type: str = "",
        domain: str = "",
        task_id: Optional[str] = None,
        *,
        enable_pii_detection: bool = True,
    ) -> EventizerResponse:
        """
        Process normalized text through fast eventizer pipeline (reflex sensor).
        
        Architecture: FastEventizer is a reflex sensor that receives pre-normalized text.
        Normalization happens BEFORE FastEventizer in the pipeline (Coordinator layer).
        This ensures single normalization point and consistent pattern matching.
        
        Returns partial EventizerResponse that can be enriched by EventizerService.
        
        Args:
            normalized_text: Pre-normalized text (from TextNormalizer, AGGRESSIVE tier)
            original_text: Original raw text (required for EventizerResponse)
            task_type: Task type hint
            domain: Domain hint
            task_id: Optional task ID for correlation
            enable_pii_detection: Whether to detect PII (default: True)
                                 FastEventizer detects but doesn't redact
        
        Returns:
            Partial EventizerResponse (reflex sensor output, ready for EventizerService refinement)
        """
        t0 = time.perf_counter()

        clipped = _clip_text(normalized_text, self._pack.max_chars)
        
        # Step 1: PII detection (reflex sensor - no redaction)
        # FastEventizer detects PII presence and emits flags for PKG/routing
        # Actual PII redaction is performed by EventizerService (comprehensive, policy-driven)
        pii_indicators = self._detect_pii_indicators(clipped) if enable_pii_detection else {}
        # FastEventizer doesn't redact - processed_text = normalized_text
        processed_text = clipped

        ets, pats, matched_specs, priority = self._extract_event_types(processed_text)
        keywords = self._extract_keywords(processed_text, matched_specs)
        attrs = self._extract_attributes(processed_text, ets)
        conf, need_ml = self._confidence_and_fallback(pats, attrs.text_length, priority, ets)

        dt_ms = (time.perf_counter() - t0) * 1000.0
        
        # Calculate SHA256 of original text
        original_text_sha256 = hashlib.sha256(original_text.encode('utf-8')).hexdigest()
        
        # Build EventTags from FastEventTags
        # Use Urgency enum for type consistency across FastEventizer, EventizerService, PKG, and Agents
        urgency = (
            Urgency.CRITICAL if priority >= 9
            else Urgency.HIGH if priority >= 8
            else Urgency.NORMAL
        )
        
        event_tags = EventTags(
            hard_tags=ets,  # Emergency/safety tags only (reflex sensor)
            event_types=ets,  # Also set for backward compatibility
            keywords=keywords,
            patterns=[],  # Empty (EventizerService populates this)
            entities=[],  # Empty (EventizerService populates this)
            priority=priority,
            urgency=urgency,  # Use Urgency enum for type consistency
        )
        
        # Build EventAttributes from FastAttributes
        # EventAttributes only has: required_service, required_skill, target_organ,
        # processing_timeout, resource_requirements, routing_hints
        # Put FastEventizer's extracted attributes into routing_hints for downstream use
        routing_hints = {
            "has_urgency": attrs.has_urgency,
            "has_location": attrs.has_location,
            "has_timestamp": attrs.has_timestamp,
            "text_length": attrs.text_length,
            "word_count": attrs.word_count,
        }
        if domain:
            routing_hints["domain"] = domain
        if task_type:
            routing_hints["task_type"] = task_type
        
        event_attributes = EventAttributes(
            routing_hints=routing_hints,  # FastEventizer attributes stored here
        )
        
        # Build ConfidenceScore
        confidence = ConfidenceScore(
            overall_confidence=conf,
            confidence_level=(
                ConfidenceLevel.HIGH if conf >= 0.9
                else ConfidenceLevel.MEDIUM if conf >= 0.7
                else ConfidenceLevel.LOW
            ),
            needs_ml_fallback=need_ml,
            fallback_reasons=["low_confidence"] if need_ml else [],
        )
        
        # Return partial EventizerResponse (reflex sensor output)
        return EventizerResponse(
            original_text=original_text,
            original_text_sha256=original_text_sha256,
            normalized_text=normalized_text,
            processed_text=processed_text,  # No PII redaction (FastEventizer doesn't redact)
            pii=None,  # Empty (EventizerService populates this with comprehensive PII audit)
            pii_detected=pii_indicators,  # PII detection flags from reflex sensor
            event_tags=event_tags,
            attributes=event_attributes,
            signals=EventSignals(),  # Empty (EventizerService generates signals)
            confidence=confidence,
            processing_time_ms=dt_ms,
            patterns_applied=pats,
            pii_redacted=False,  # FastEventizer doesn't redact
            decision_kind=RouteDecision.FAST,  # Explicit decision kind for routing
            engines={
                "fast_eventizer": self._pack.pack_id,
                "pack_version": self._pack.pack_version,
            },
            eventizer_version=self._pack.pack_version,
            task_id=task_id or "",
        )


# Architecture: FastEventizer now returns EventizerResponse directly
# No conversion function needed - removes entire class of bugs


# -------------------------
# Singleton Loader
# -------------------------

_fast_eventizer: Optional[FastEventizer] = None
_compiled_pack: Optional[CompiledPack] = None

def get_fast_eventizer(pattern_pack_path: str) -> FastEventizer:
    global _fast_eventizer, _compiled_pack
    if _fast_eventizer is None:
        _compiled_pack = load_pattern_pack(pattern_pack_path)
        _fast_eventizer = FastEventizer(_compiled_pack)
    return _fast_eventizer
