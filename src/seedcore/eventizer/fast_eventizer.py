#!/usr/bin/env python3
"""
Fast-Path Eventizer for SeedCore (hardened)

- Deterministic, sub-ms path for PKG inputs
- Minimal PII redaction with lower FP rate (Luhn for CC)
- No external deps; pure Python `re` (can swap for re2 if desired)
"""

from __future__ import annotations
import re
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

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

class EventType(Enum):
    EMERGENCY = "emergency"
    SECURITY = "security"
    MAINTENANCE = "maintenance"
    WARNING = "warning"
    NORMAL = "normal"

@dataclass(slots=True)
class FastEventTags:
    priority: int
    event_types: List[EventType]
    domain: Optional[str]
    confidence: float
    needs_ml_fallback: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "event_types": [e.value for e in self.event_types],
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

        if self._sec_re.search(text):
            ets.append(EventType.SECURITY)
            patterns_applied += 1

        if self._warn_re.search(text):
            ets.append(EventType.WARNING)
            patterns_applied += 1

        if self._maint_re.search(text):
            ets.append(EventType.MAINTENANCE)
            patterns_applied += 1

        if not ets:
            ets.append(EventType.NORMAL)

        return ets, patterns_applied

    def _determine_priority(self, ets: List[EventType]) -> int:
        if EventType.EMERGENCY in ets:
            return 10
        if EventType.SECURITY in ets:
            return 8
        if EventType.WARNING in ets:
            return 6
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
        priority = self._determine_priority(ets)
        attrs = self._extract_attributes(processed_text)
        conf, need_ml = self._confidence_and_fallback(pats, attrs.text_length)

        tags = FastEventTags(
            priority=priority,
            event_types=ets,
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
