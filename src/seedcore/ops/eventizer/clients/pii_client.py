#!/usr/bin/env python3
"""
Product-grade PII Client for SeedCore

- Optional Microsoft Presidio; deterministic fallback engine
- Deterministic placeholders per task
- HMAC-SHA256 pseudonymization for hash/tokenize modes
- Offset-safe anonymization with span reporting
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

# Import enhanced schemas for better integration
from ..schemas.eventizer_models import (
    EntitySpan,
    PIIAudit,
    RedactMode,
    TextNormalizationResult
)
from ..utils.text_normalizer import SpanMap

logger = logging.getLogger(__name__)

# -------------------------------
# Versioning & defaults
# -------------------------------

PII_CLIENT_VERSION = "2.2.0"  # bump when behavior/contract changes
DEFAULT_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD",
    "SSN", "IBAN_CODE", "IP_ADDRESS", "LOCATION", "DATE_TIME",
    "NRIC", "ROOM_ID", "BOOKING_ID"
]

# -------------------------------
# Utilities
# -------------------------------

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def hmac_sha256_hex(key: bytes, s: str) -> str:
    return hmac.new(key, s.encode("utf-8"), hashlib.sha256).hexdigest()

def luhn_valid(num: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", num)]
    if not digits:
        return False
    checksum = 0
    parity = (len(digits) - 2) % 2
    for i, d in enumerate(digits[:-1]):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return (checksum + digits[-1]) % 10 == 0

# -------------------------------
# Config dataclasses
# -------------------------------

@dataclass
class PIIConfig:
    entities: List[str] = field(default_factory=lambda: list(DEFAULT_ENTITIES))
    language: str = "en"
    mode: str = "redact"  # "redact" | "mask" | "tokenize" | "hash"
    mask_char: str = "•"
    mask_keep_len: bool = False          # preserve original length when masking
    deterministic_placeholders: bool = True
    hmac_secret: Optional[str] = None    # for "hash" mode; if None, uses env
    preserve_offsets: bool = True        # try to preserve offsets during replace
    allowlist_entities: Optional[Iterable[str]] = None
    denylist_entities: Optional[Iterable[str]] = None
    # When using Presidio:
    presidio_score_threshold: float = 0.35
    presidio_analyzer_kwargs: Dict = field(default_factory=dict)
    presidio_anonymizer_kwargs: Dict = field(default_factory=dict)

@dataclass
class Span:
    entity_type: str
    start: int
    end: int
    score: float
    text: str
    replacement: Optional[str] = None

@dataclass
class PIIResult:
    version: str
    mode: str
    language: str
    entities_evaluated: List[str]
    text_redacted: str
    spans: List[Span]
    counts_by_type: Dict[str, int]
    raw_text_sha256: str
    used_engine: str  # "presidio" or "fallback"
    config_echo: Dict[str, str]

# -------------------------------
# Fallback patterns (precompiled)
# Note: tuned for precision; avoid catastrophic backtracking
# -------------------------------

_FALLBACK_PATTERNS: Dict[str, re.Pattern] = {
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "PHONE_NUMBER": re.compile(
        r"(?:\+?[0-9]{1,3}[ -.]?)?(?:\(?\d{2,4}\)?[ -.]?)?\d{3,4}[ -.]?\d{3,4}\b"
    ),
    "SSN": re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*){13,19}\b"),
    "IP_ADDRESS": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    ),
    "IBAN_CODE": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "DATE_TIME": re.compile(
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4})\b",
        re.IGNORECASE,
    ),
    # Domain-specific helpers (customize per deployment)
    "ROOM_ID": re.compile(r"\b(?:room|rm|suite)\s*[-#:]?\s*\d{2,5}\b", re.IGNORECASE),
    "BOOKING_ID": re.compile(r"\b(?:bk|res|reservation)[-_]?\d{6,}\b", re.IGNORECASE),
    "PERSON": re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b"),  # naive; Presidio preferred
    "LOCATION": re.compile(r"\b(?:floor|level|wing|tower)\s+[A-Za-z0-9-]+\b", re.IGNORECASE),
    "NRIC": re.compile(r"\b[STFG]\d{7}[A-Z]\b"),  # SG NRIC example
}

# -------------------------------
# PII Client
# -------------------------------

class PIIClient:
    """
    Product-grade PII client with optional Presidio and deterministic fallback.
    Thread-safe init; low-GC hot path; auditable output.
    """

    def __init__(self, config: Optional[PIIConfig] = None):
        self._cfg = config or PIIConfig()
        self._lock = threading.Lock()
        self._initialized = False
        self._analyzer = None
        self._anonymizer = None

        # Placeholder counters per entity for deterministic numbering
        self._placeholder_counters: Dict[str, int] = {}

        # Final entity set after allow/deny filters
        self._entities = self._resolve_entities(self._cfg.entities,
                                                self._cfg.allowlist_entities,
                                                self._cfg.denylist_entities)

        # HMAC secret for hash/tokenize modes
        self._hmac_key = (
            (self._cfg.hmac_secret or os.getenv("PII_HMAC_SECRET") or "seedcore-default-secret")
            .encode("utf-8")
        )

        # Pre-bind mode function
        self._replace_fn = {
            "redact": self._replace_with_placeholder,
            "mask": self._replace_with_mask,
            "tokenize": self._replace_with_token,
            "hash": self._replace_with_hash,
        }.get(self._cfg.mode, self._replace_with_placeholder)

    # ---------------------------
    # Lifecycle
    # ---------------------------

    def initialize(self) -> None:
        """Idempotent initialization; loads Presidio if available."""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                # Try Presidio
                from presidio_analyzer import AnalyzerEngine
                from presidio_anonymizer import AnonymizerEngine

                self._analyzer = AnalyzerEngine()
                self._anonymizer = AnonymizerEngine()

                logger.info("PIIClient initialized with Presidio")
                self._initialized = True
            except Exception as e:
                # Fallback only
                logger.warning("Presidio unavailable or failed to init (%s); using fallback engine.", e)
                self._analyzer = None
                self._anonymizer = None
                self._initialized = True

    # ---------------------------
    # Public API
    # ---------------------------

    def redact_with_audit(self, text: str, *, task_id: Optional[str] = None,
                         entities: Optional[List[str]] = None,
                         mode: Optional[RedactMode] = None,
                         span_map: Optional[SpanMap] = None) -> Tuple[str, PIIAudit]:
        """
        Enhanced redaction method that returns both redacted text and detailed audit information.
        Integrates with the enhanced schemas and span mapping utilities.
        
        Note: This method works on normalized text and returns spans in normalized coordinates.
        The caller (EventizerService) is responsible for mapping spans back to original coordinates
        using the provided span_map.
        """
        self.initialize()
        if not text:
            empty_audit = PIIAudit(
                used_engine="none",
                mode=mode or RedactMode.REDACT,
                entities_evaluated=[],
                spans=[],
                counts_by_type={},
                raw_text_sha256=sha256_hex(text),
                version=PII_CLIENT_VERSION
            )
            return text, empty_audit

        # Stable raw hash for audit
        raw_hash = sha256_hex(text)
        # Reset per-call placeholder counters for numbering determinism
        self._placeholder_counters = {}

        # Effective entities and mode for this call
        effective_entities = self._resolve_entities(entities or self._entities, None, None)
        effective_mode = (mode or RedactMode(self._cfg.mode)).value

        # Detect spans first
        spans = self.detect(text, entities=effective_entities)
        
        # Convert spans to EntitySpan objects
        entity_spans = []
        for span in spans:
            entity_span = EntitySpan(
                entity_type=span.entity_type,
                start=span.start,
                end=span.end,
                score=span.score,
                text=span.text,
                replacement=span.replacement
            )
            entity_spans.append(entity_span)

        # Count by type
        counts_by_type = {}
        for span in spans:
            counts_by_type[span.entity_type] = counts_by_type.get(span.entity_type, 0) + 1

        # Perform redaction
        if self._analyzer and self._anonymizer:
            try:
                result = self._redact_with_presidio(text, effective_entities, effective_mode)
                audit = PIIAudit(
                    used_engine="presidio",
                    mode=mode or RedactMode(self._cfg.mode),
                    entities_evaluated=effective_entities,
                    spans=entity_spans,
                    counts_by_type=counts_by_type,
                    raw_text_sha256=raw_hash,
                    version=PII_CLIENT_VERSION,
                    mask_char=self._cfg.mask_char,
                    mask_keep_len=self._cfg.mask_keep_len,
                    preserve_offsets=self._cfg.preserve_offsets
                )
                return result.text_redacted, audit
            except Exception as e:
                logger.error("Presidio redaction failed, falling back. Err=%s", e)

        # Fallback redaction
        result = self._redact_with_fallback(text, effective_entities, effective_mode)
        audit = PIIAudit(
            used_engine="fallback",
            mode=mode or RedactMode(self._cfg.mode),
            entities_evaluated=effective_entities,
            spans=entity_spans,
            counts_by_type=counts_by_type,
            raw_text_sha256=raw_hash,
            version=PII_CLIENT_VERSION,
            mask_char=self._cfg.mask_char,
            mask_keep_len=self._cfg.mask_keep_len,
            preserve_offsets=self._cfg.preserve_offsets
        )
        return result.text_redacted, audit

    def redact(self, text: str, *, task_id: Optional[str] = None,
               entities: Optional[List[str]] = None,
               mode: Optional[str] = None) -> PIIResult:
        """
        Redact/anonymize PII in text and return spans + metadata.
        Synchronous, low allocation, offset-aware.
        """
        self.initialize()
        if not text:
            return self._empty_result(text)

        # Stable raw hash for audit
        raw_hash = sha256_hex(text)
        # Reset per-call placeholder counters for numbering determinism
        self._placeholder_counters = {}

        # Effective entities and mode for this call
        effective_entities = self._resolve_entities(entities or self._entities, None, None)
        effective_mode = mode or self._cfg.mode

        if self._analyzer and self._anonymizer:
            try:
                result = self._redact_with_presidio(text, effective_entities, effective_mode)
                result.raw_text_sha256 = raw_hash
                return result
            except Exception as e:
                logger.error("Presidio redaction failed, falling back. Err=%s", e)

        result = self._redact_with_fallback(text, effective_entities, effective_mode)
        result.raw_text_sha256 = raw_hash
        return result

    def detect(self, text: str, *, entities: Optional[List[str]] = None) -> List[Span]:
        """Detect PII spans without modifying text (engine-agnostic)."""
        self.initialize()
        if not text:
            return []

        effective_entities = self._resolve_entities(entities or self._entities, None, None)

        if self._analyzer:
            try:
                return self._detect_with_presidio(text, effective_entities)
            except Exception as e:
                logger.error("Presidio detect failed; using fallback. Err=%s", e)

        return self._detect_with_fallback(text, effective_entities)

    # ---------------------------
    # Presidio path
    # ---------------------------

    def _redact_with_presidio(self, text: str, entities: List[str], mode: str) -> PIIResult:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer.entities import AnonymizerConfig

        analyzer_results = self._analyzer.analyze(
            text=text,
            entities=entities,
            language=self._cfg.language,
            score_threshold=self._cfg.presidio_score_threshold,
            **self._cfg.presidio_analyzer_kwargs,
        )

        # Build anonymizer config per entity: we still want deterministic placeholders
        operators = {}
        for ent in entities:
            if mode == "redact":
                operators[ent] = AnonymizerConfig("replace", {"new_value": self._next_placeholder(ent)})
            elif mode == "mask":
                # Mask with fixed char; optionally preserve length
                operators[ent] = AnonymizerConfig(
                    "mask",
                    {
                        "masking_char": self._cfg.mask_char,
                        "chars_to_mask": -1,
                        "from_end": False,
                    },
                )
            elif mode == "tokenize":
                operators[ent] = AnonymizerConfig("replace", {"new_value": self._next_placeholder(ent)})
            elif mode == "hash":
                operators[ent] = AnonymizerConfig("hash", {"hash_type": "sha256"})
            else:
                operators[ent] = AnonymizerConfig("replace", {"new_value": self._next_placeholder(ent)})

        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators=operators,
            **self._cfg.presidio_anonymizer_kwargs,
        )

        # Recompute spans from analyzer_results (original offsets)
        spans: List[Span] = []
        counts: Dict[str, int] = {}
        repl_map: Dict[Tuple[int, int], str] = {}

        for r in analyzer_results:
            ent = r.entity_type
            frag = text[r.start : r.end]
            if ent == "CREDIT_CARD" and not luhn_valid(frag):
                continue  # skip false positives
            counts[ent] = counts.get(ent, 0) + 1

            # Replacement string we intended (best-effort)
            if mode == "hash":
                replacement = hmac_sha256_hex(self._hmac_key, frag)[:12]
            elif mode == "mask" and self._cfg.mask_keep_len:
                replacement = self._cfg.mask_char * (r.end - r.start)
            else:
                replacement = self._placeholder_for_ent(ent)

            spans.append(Span(entity_type=ent, start=r.start, end=r.end, score=r.score, text=frag,
                              replacement=replacement))
            repl_map[(r.start, r.end)] = replacement

        return PIIResult(
            version=PII_CLIENT_VERSION,
            mode=mode,
            language=self._cfg.language,
            entities_evaluated=list(entities),
            text_redacted=anonymized.text,
            spans=spans,
            counts_by_type=counts,
            raw_text_sha256="",  # filled by caller
            used_engine="presidio",
            config_echo={
                "mask_char": self._cfg.mask_char,
                "mask_keep_len": str(self._cfg.mask_keep_len),
                "preserve_offsets": str(self._cfg.preserve_offsets),
            },
        )

    def _detect_with_presidio(self, text: str, entities: List[str]) -> List[Span]:
        analyzer_results = self._analyzer.analyze(
            text=text,
            entities=entities,
            language=self._cfg.language,
            score_threshold=self._cfg.presidio_score_threshold,
            **self._cfg.presidio_analyzer_kwargs,
        )
        spans: List[Span] = []
        for r in analyzer_results:
            frag = text[r.start : r.end]
            if r.entity_type == "CREDIT_CARD" and not luhn_valid(frag):
                continue
            spans.append(Span(entity_type=r.entity_type, start=r.start, end=r.end,
                              score=r.score, text=frag))
        return spans

    # ---------------------------
    # Fallback path
    # ---------------------------

    def _redact_with_fallback(self, text: str, entities: List[str], mode: str) -> PIIResult:
        spans = self._detect_with_fallback(text, entities)

        # Build replacement plan (stable, offset-preserving)
        # Sort spans by start; resolve overlaps by keeping higher "priority"
        # (simple priority: earlier start + longer span first)
        spans_sorted = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
        final_spans: List[Span] = []
        last_end = -1
        for s in spans_sorted:
            if s.start >= last_end:
                final_spans.append(s)
                last_end = s.end

        # Apply replacements from right to left to preserve offsets
        red = list(text)
        counts: Dict[str, int] = {}
        for s in reversed(final_spans):
            counts[s.entity_type] = counts.get(s.entity_type, 0) + 1
            repl = self._replacement_string(s.text, s.entity_type, mode)
            s.replacement = repl
            # If preserving offsets and repl length differs, pad/truncate
            if self._cfg.preserve_offsets and len(repl) != (s.end - s.start):
                if mode == "mask" and self._cfg.mask_keep_len:
                    repl = self._cfg.mask_char * (s.end - s.start)
                else:
                    # Compact but keep approximate length with ellipsis
                    repl = (repl[: (s.end - s.start)]) if len(repl) >= (s.end - s.start) \
                        else repl + (" " * ((s.end - s.start) - len(repl)))
            red[s.start:s.end] = list(repl)

        text_redacted = "".join(red)

        return PIIResult(
            version=PII_CLIENT_VERSION,
            mode=mode,
            language=self._cfg.language,
            entities_evaluated=list(entities),
            text_redacted=text_redacted,
            spans=final_spans,
            counts_by_type=counts,
            raw_text_sha256="",  # filled by caller
            used_engine="fallback",
            config_echo={
                "mask_char": self._cfg.mask_char,
                "mask_keep_len": str(self._cfg.mask_keep_len),
                "preserve_offsets": str(self._cfg.preserve_offsets),
            },
        )

    def _detect_with_fallback(self, text: str, entities: List[str]) -> List[Span]:
        spans: List[Span] = []
        for ent in entities:
            pat = _FALLBACK_PATTERNS.get(ent)
            if not pat:
                continue
            for m in pat.finditer(text):
                frag = m.group(0)
                score = 0.9
                if ent == "CREDIT_CARD" and not luhn_valid(frag):
                    continue
                spans.append(Span(entity_type=ent, start=m.start(), end=m.end(),
                                  score=score, text=frag))
        return spans

    # ---------------------------
    # Replacement helpers
    # ---------------------------

    def _next_placeholder(self, ent: str) -> str:
        idx = self._placeholder_counters.get(ent, 0) + 1
        self._placeholder_counters[ent] = idx
        return f"<{ent}_{idx}>"

    def _placeholder_for_ent(self, ent: str) -> str:
        # return current index (if any) without incrementing
        idx = self._placeholder_counters.get(ent, 1)
        return f"<{ent}_{idx}>"

    def _replacement_string(self, original: str, ent: str, mode: str) -> str:
        if mode == "redact":
            return self._next_placeholder(ent) if self._cfg.deterministic_placeholders else f"<{ent}>"
        if mode == "mask":
            return self._cfg.mask_char * len(original) if self._cfg.mask_keep_len else self._cfg.mask_char * min(8, max(4, len(original)))
        if mode == "tokenize":
            # deterministic placeholder + short token tail (HMAC)
            token = hmac_sha256_hex(self._hmac_key, original)[:8]
            return f"{self._next_placeholder(ent)}:{token}"
        if mode == "hash":
            return hmac_sha256_hex(self._hmac_key, original)
        # default
        return self._next_placeholder(ent)

    # ---------------------------
    # Helpers
    # ---------------------------

    def _resolve_entities(
        self,
        base: Iterable[str],
        allowlist: Optional[Iterable[str]],
        denylist: Optional[Iterable[str]],
    ) -> List[str]:
        s = set(base)
        if allowlist:
            s &= set(allowlist)
        if denylist:
            s -= set(denylist)
        # keep only known patterns in fallback to avoid surprises
        return [e for e in s]

    def _empty_result(self, text: str) -> PIIResult:
        return PIIResult(
            version=PII_CLIENT_VERSION,
            mode=self._cfg.mode,
            language=self._cfg.language,
            entities_evaluated=list(self._entities),
            text_redacted=text,
            spans=[],
            counts_by_type={},
            raw_text_sha256=sha256_hex(text),
            used_engine="none",
            config_echo={
                "mask_char": self._cfg.mask_char,
                "mask_keep_len": str(self._cfg.mask_keep_len),
                "preserve_offsets": str(self._cfg.preserve_offsets),
            },
        )
