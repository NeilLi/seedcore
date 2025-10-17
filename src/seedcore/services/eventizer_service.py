#!/usr/bin/env python3
"""
Eventizer Service (product-grade)

Deterministic, low-latency text processing pipeline for task classification & routing.

Pipeline:
  1) Unicode-safe normalization (with SpanMap for offset projection)
  2) PII detection/redaction (Presidio if available; hardened fallback otherwise)
  3) Pattern matching (regex + keyword + entity) with global time budget
  4) Tag/attribute extraction
  5) Confidence scoring & ML fallback hinting
  6) Provenance: every match includes original offsets & pattern metadata

This service is designed to sit in the OCPS hot path and feed the PKG rules plane.
"""

from __future__ import annotations

import asyncio
import time
import logging
import re
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, Callable

from ..ops.eventizer.schemas.eventizer_models import (
    EventizerRequest,
    EventizerResponse,
    EventTags,
    EventAttributes,
    EventizerConfig,
    PatternMatch,
    ConfidenceScore,
    ConfidenceLevel,
    EventType,
    TextNormalizationResult,
    PatternCompilationResult,
    PIIAudit,
    RedactMode,
    EntitySpan,
    PKGHint,
    PKGEnv,
    PKGSnapshot,
    PKGHelper
)
from ..ops.eventizer.utils.text_normalizer import TextNormalizer, SpanMap
from ..ops.eventizer.utils.pattern_compiler import PatternCompiler, CompiledRegex
from ..ops.eventizer.clients.pii_client import PIIClient, PIIConfig, RedactMode as PIIClientRedactMode
from ..ops.eventizer.clients.pkg_client import PKGClient, get_active_snapshot

logger = logging.getLogger(__name__)


# =========================
# Metrics / hooks (optional)
# =========================

def _now_ms() -> float:
    return time.perf_counter() * 1000.0

def sha256_hex(s: str) -> str:
    """Generate SHA256 hash of string for audit purposes."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def default_metrics_sink(event: str, fields: Dict[str, Any]) -> None:
    # No-op sink; wire Prometheus or StatsD externally if desired
    logger.debug("metrics.%s %s", event, fields)


# =========================
# Service
# =========================

@dataclass
class ProcessingStats:
    start_ms: float
    end_ms: float = 0.0
    patterns_applied: int = 0
    pii_redacted: bool = False
    warnings: List[str] = None
    errors: List[str] = None

    def __post_init__(self):
        self.warnings = self.warnings or []
        self.errors = self.errors or []


class EventizerService:
    """
    Deterministic eventizer service for text processing & classification.

    Thread-safe to call concurrently after `await initialize()`.
    """

    def __init__(
        self,
        config: Optional[EventizerConfig] = None,
        *,
        metrics_sink: Callable[[str, Dict[str, Any]], None] = default_metrics_sink,
        ml_fallback_hook: Optional[Callable[[EventizerRequest, EventizerResponse], Any]] = None,
    ):
        self.config = config or EventizerConfig()
        self._initialized = False
        self._text_normalizer: Optional[TextNormalizer] = None
        self._pattern_compiler: Optional[PatternCompiler] = None
        self._pii_client: Optional[PIIClient] = None
        self._pkg_client: Optional[PKGClient] = None
        self._active_snapshot: Optional[PKGSnapshot] = None
        self._ml_fallback_hook = ml_fallback_hook
        self._metrics = metrics_sink

        # Mapping regex/keyword hits to EventType (configurable)
        # You can extend this by loading from config files if desired.
        self._eventtype_alias: Dict[str, EventType] = {
            "hvac": EventType.HVAC,
            "security": EventType.SECURITY,
            "vip": EventType.VIP,
            "allergen": EventType.ALLERGEN,
            "emergency": EventType.EMERGENCY,
            "maintenance": EventType.MAINTENANCE,
        }

        logger.info("EventizerService configured: %s", self.config.model_dump())

    # -----------------
    # Lifecycle
    # -----------------

    async def initialize(self) -> None:
        if self._initialized:
            return

        t0 = _now_ms()
        logger.info("EventizerService initialization starting...")

        # Text normalizer
        self._text_normalizer = TextNormalizer(case="lower", fold_accents=False)

        # Pattern compiler
        self._pattern_compiler = PatternCompiler(self.config)
        await self._pattern_compiler.initialize()

        # PII client
        if self.config.enable_pii_redaction:
            self._pii_client = PIIClient(self.config.pii_redaction_entities)
            await self._pii_client.initialize()

        # PKG client
        if self.config.pkg_validation_enabled:
            self._pkg_client = PKGClient(self.config.pkg_environment)
            try:
                self._active_snapshot = await self._pkg_client.get_active_snapshot()
                if self._active_snapshot:
                    logger.info(f"PKG active snapshot loaded: {self._active_snapshot.version}")
                elif self.config.pkg_require_active_snapshot:
                    logger.warning("PKG validation enabled but no active snapshot found")
            except Exception as e:
                logger.error(f"Failed to load PKG active snapshot: {e}")
                if self.config.pkg_require_active_snapshot:
                    raise

        # Load patterns/dicts from config
        await self._load_patterns()

        self._initialized = True
        t1 = _now_ms()
        self._metrics("eventizer.init", {"ms": t1 - t0})
        logger.info("EventizerService initialization finished in %.2f ms", t1 - t0)

    # -----------------
    # Public API
    # -----------------

    async def process_text(self, request: EventizerRequest) -> EventizerResponse:
        """
        Run the deterministic pipeline for a single text input with enhanced utilities integration.
        """
        if not self._initialized:
            await self.initialize()

        stats = ProcessingStats(start_ms=_now_ms())
        log: List[str] = []
        warnings: List[str] = []
        errors: List[str] = []

        try:
            # Budget: global cap per request
            budget_ms = float(self.config.max_processing_time_ms)
            budget_deadline = stats.start_ms + budget_ms

            # 1) Normalize (with SpanMap) - Enhanced with TextNormalizationResult
            log.append("normalize:start")
            norm_text, span_map = await self._normalize_with_map(request.text)
            log.append(f"normalize:len={len(norm_text)}")
            
            # Create TextNormalizationResult for detailed tracking
            text_normalization = TextNormalizationResult(
                original_text=request.text,
                normalized_text=norm_text,
                span_map=span_map,
                normalization_applied=["unicode_nfkc", "case_lower", "whitespace_clean"],
                processing_time_ms=_now_ms() - stats.start_ms
            )

            # 2) PII detection/redaction with enhanced audit - Enhanced with PIIAudit
            # PII redaction happens AFTER text normalization to ensure consistent processing
            # but spans are mapped back to original coordinates for audit purposes
            redacted_text = norm_text
            pii_audit: Optional[PIIAudit] = None
            redacted_original_snapshot: Optional[str] = None
            
            if self.config.enable_pii_redaction and self._pii_client:
                time_left = max(0.0, budget_deadline - _now_ms())
                if time_left <= 0:
                    warnings.append("budget_exhausted_before_pii")
                else:
                    log.append("pii:start")
                    # Use enhanced redact_with_audit method on normalized text
                    # This ensures PII detection works on consistently normalized text
                    redacted_text, pii_audit = self._pii_client.redact_with_audit(
                        norm_text,
                        entities=request.pii_entities,
                        mode=request.redact_mode,
                        span_map=span_map
                    )
                    
                    # Map PII spans from normalized coordinates back to original text coordinates
                    # This preserves the audit trail with correct original text positions
                    if pii_audit and pii_audit.spans:
                        pii_audit.spans = self._map_pii_spans_to_original(
                            pii_audit.spans, span_map, request.text
                        )
                        
                        # Validate the mapping to ensure spans are correctly positioned
                        if not self._validate_pii_span_mapping(pii_audit.spans, request.text):
                            warnings.append("pii_span_mapping_validation_failed")
                    
                    if redacted_text != norm_text:
                        stats.pii_redacted = True
                        # Optionally store a minimally redacted copy for audit if preserve_pii
                        if request.preserve_pii:
                            redacted_original_snapshot = redacted_text
                    log.append("pii:done")

            # 3) Pattern matching (budget-aware) - Enhanced with PatternCompilationResult
            time_left = max(0.0, budget_deadline - _now_ms())
            pattern_compilation: Optional[List[PatternCompilationResult]] = None
            
            if time_left <= 0:
                warnings.append("budget_exhausted_before_matching")
                matches: List[PatternMatch] = []
            else:
                log.append("match:start")
                matches, compilation_results = await self._match_all_budgeted_with_compilation(
                    redacted_text, time_left
                )
                pattern_compilation = compilation_results
                log.append(f"match:count={len(matches)}")

            # 4) Project normalized offsets → original offsets for provenance
            projected_matches = self._project_matches(matches, span_map, request.text)

            # 5) Build EventTags & attributes
            tags = self._aggregate_tags(projected_matches)
            attrs = self._extract_attributes(redacted_text, tags, request)

            stats.patterns_applied = len(projected_matches)

            # 6) PKG policy evaluation and hint generation
            pkg_hint: Optional[PKGHint] = None
            if self._pkg_client and self._active_snapshot:
                try:
                    pkg_hint = await self._evaluate_pkg_policies(tags, attrs, request)
                    log.append(f"pkg:evaluated={len(pkg_hint.subtasks) if pkg_hint else 0}")
                except Exception as e:
                    logger.warning(f"PKG policy evaluation failed: {e}")
                    warnings.append(f"pkg_evaluation_failed:{e}")

            # 7) Confidence & fallback signal
            conf = self._calculate_confidence(tags, attrs, stats)

            # Optionally trigger ML fallback hook (non-blocking)
            if conf.needs_ml_fallback and self._ml_fallback_hook:
                try:
                    asyncio.create_task(self._async_call_fallback_hook(request, tags, attrs, conf))
                except Exception as e:
                    warnings.append(f"ml_fallback_hook_failed:{e}")

            stats.end_ms = _now_ms()
            resp = EventizerResponse(
                original_text=request.text,
                original_text_sha256=sha256_hex(request.text),
                normalized_text=norm_text,
                processed_text=redacted_text,
                
                # Enhanced text processing results
                text_normalization=text_normalization,
                pattern_compilation=pattern_compilation,
                
                # PII audit
                pii=pii_audit,
                
                # Semantic outputs
                event_tags=tags,
                attributes=attrs,
                confidence=conf,
                
                # PKG hints
                pkg_hint=pkg_hint,
                
                # Observability & governance
                processing_time_ms=stats.end_ms - stats.start_ms,
                patterns_applied=stats.patterns_applied,
                pii_redacted=stats.pii_redacted,
                warnings=warnings + (stats.warnings or []),
                errors=errors + (stats.errors or []),
                processing_log=log,
                
                # Versions / engines for audit
                eventizer_version="1.0.0",
                engines={
                    "text_normalizer": "1.0.0",
                    "pattern_compiler": "1.0.0", 
                    "pii_client": "2.2.0",
                    "pkg_client": "1.0.0"
                },
                
                # PKG integration metadata
                pkg_snapshot_version=self._active_snapshot.version if self._active_snapshot else None,
                pkg_snapshot_id=self._active_snapshot.id if self._active_snapshot else None,
                pkg_validation_status=True if pkg_hint and pkg_hint.is_valid_snapshot else False,
                pkg_deployment_info=self._get_pkg_deployment_info() if self._active_snapshot else None
            )
            self._metrics("eventizer.ok", {
                "ms": resp.processing_time_ms,
                "patterns": stats.patterns_applied,
                "pii": int(stats.pii_redacted),
                "conf": conf.overall_confidence,
                "lvl": conf.confidence_level.value,
                "pkg": 1 if pkg_hint else 0,
                "pkg_subtasks": len(pkg_hint.subtasks) if pkg_hint else 0,
            })
            return resp

        except Exception as e:
            stats.end_ms = _now_ms()
            err = f"{type(e).__name__}: {e}"
            logger.exception("Eventizer failed: %s", err)
            self._metrics("eventizer.err", {"ms": stats.end_ms - stats.start_ms})
            return EventizerResponse(
                original_text=request.text,
                processed_text=request.text,
                event_tags=EventTags(),
                attributes=EventAttributes(),
                confidence=ConfidenceScore(
                    overall_confidence=0.0,
                    confidence_level=ConfidenceLevel.LOW,
                    needs_ml_fallback=True,
                    fallback_reasons=["exception"],
                    processing_notes=[err],
                ),
                processing_time_ms=stats.end_ms - stats.start_ms,
                patterns_applied=0,
                pii_redacted=False,
                processing_log=log,
                warnings=warnings,
                errors=[err],
            )

    # -----------------
    # Internals
    # -----------------

    async def _normalize_with_map(self, text: str) -> Tuple[str, SpanMap]:
        assert self._text_normalizer is not None
        norm = await self._text_normalizer.normalize(text, build_map=True)
        # `normalize` returns (text, SpanMap)
        return norm  # type: ignore[return-value]

    async def _match_all_budgeted(self, text: str, time_left_ms: float) -> List[PatternMatch]:
        """
        Run all matching engines with a combined budget.
        PatternCompiler internally time-slices per engine and will stop when budget expires.
        """
        assert self._pattern_compiler is not None
        matches = await self._pattern_compiler.match_all(
            text,
            budget_ms=max(1.0, time_left_ms)  # keep a floor to avoid 0
        )
        return matches

    def _project_matches(self, matches: List[PatternMatch], span_map: SpanMap, original: str) -> List[PatternMatch]:
        """
        Project normalized offsets of PatternMatch → original offsets and attach source text.
        """
        projected: List[PatternMatch] = []
        for m in matches:
            o_start, o_end = span_map.project_norm_span_to_orig(m.start_pos, m.end_pos)
            # Clamp safely
            o_start = max(0, min(o_start, len(original)))
            o_end = max(o_start, min(o_end, len(original)))
            # Copy with updated metadata
            meta = dict(m.metadata or {})
            meta["orig_span"] = {"start": o_start, "end": o_end, "text": original[o_start:o_end]}
            projected.append(PatternMatch(
                pattern_id=m.pattern_id,
                pattern_type=m.pattern_type,
                matched_text=m.matched_text,  # normalized slice
                start_pos=o_start,
                end_pos=o_end,
                confidence=m.confidence,
                metadata=meta,
            ))
        return projected

    def _aggregate_tags(self, matches: List[PatternMatch]) -> EventTags:
        """
        Build EventTags (event_types, keywords, entities) from pattern matches.
        Uses pattern_id / metadata to infer EventType where possible.
        """
        event_types: List[EventType] = []
        keywords: List[str] = []
        entities: List[str] = []
        collected: List[PatternMatch] = []

        for m in matches:
            collected.append(m)

            # EventType from metadata or pattern family
            etype = None
            if "event_type" in (m.metadata or {}):
                etype = (m.metadata["event_type"] or "").lower()
            else:
                # Infer from pattern_id prefix (e.g., "hvac_temperature")
                prefix = m.pattern_id.split(":")[0].split("_")[0].lower()
                etype = prefix

            if etype in self._eventtype_alias:
                event_types.append(self._eventtype_alias[etype])

            if m.pattern_type == "keyword":
                keywords.append(m.matched_text)
            elif m.pattern_type == "entity":
                ent_type = (m.metadata or {}).get("entity_type")
                if ent_type:
                    entities.append(f"{ent_type}:{(m.metadata.get('orig_span',{}) or {}).get('text', m.matched_text)}")
                else:
                    entities.append(m.matched_text)

        # Priority & urgency rules
        priority = self._calculate_priority(collected)
        urgency = self._calculate_urgency(collected, event_types)

        # Deduplicate while preserving simple semantics
        def _uniq(seq: List[Any]) -> List[Any]:
            seen = set()
            out = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        return EventTags(
            event_types=_uniq(event_types),
            keywords=_uniq(keywords),
            entities=_uniq(entities),
            patterns=collected,
            priority=priority,
            urgency=urgency,
        )

    def _extract_attributes(self, text: str, tags: EventTags, request: EventizerRequest) -> EventAttributes:
        """
        Derive routing attributes deterministically from tags + context.
        """
        required_service = self._determine_required_service(tags.event_types)
        required_skill = self._determine_required_skill(tags, text)
        target_organ = self._suggest_target_organ(request.task_type, tags.event_types)
        processing_timeout = self._calculate_processing_timeout(tags, text)
        resource_requirements = self._extract_resource_requirements(tags, text)
        routing_hints = self._generate_routing_hints(tags, request)

        return EventAttributes(
            required_service=required_service,
            required_skill=required_skill,
            target_organ=target_organ,
            processing_timeout=processing_timeout,
            resource_requirements=resource_requirements,
            routing_hints=routing_hints,
        )

    def _calculate_confidence(self, tags: EventTags, attrs: EventAttributes, stats: ProcessingStats) -> ConfidenceScore:
        """
        Combine pattern strength and extraction completeness into a stable score.
        """
        pattern_conf = self._calculate_pattern_confidence(tags.patterns)
        complete_conf = self._calculate_completeness_confidence(tags, attrs)
        overall = (pattern_conf + complete_conf) / 2.0

        if overall >= self.config.high_confidence_threshold:
            level = ConfidenceLevel.HIGH
        elif overall >= self.config.medium_confidence_threshold:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        needs_fallback = overall < self.config.ml_fallback_threshold
        reasons: List[str] = []
        if needs_fallback:
            if pattern_conf < 0.5: reasons.append("low_pattern_confidence")
            if complete_conf < 0.5: reasons.append("incomplete_extraction")
            if not tags.patterns: reasons.append("no_patterns_matched")

        notes: List[str] = []
        if stats.pii_redacted: notes.append("pii_redacted")

        return ConfidenceScore(
            overall_confidence=overall,
            confidence_level=level,
            needs_ml_fallback=needs_fallback,
            fallback_reasons=reasons,
            processing_notes=notes,
        )

    async def _load_patterns(self) -> None:
        assert self._pattern_compiler is not None
        # Config-driven patterns handled inside PatternCompiler.initialize()
        # This hook is kept for future dynamic sources or remote bundles.
        return

    # -----------------
    # Heuristics & helpers used by attributes/confidence
    # -----------------

    def _calculate_priority(self, patterns: List[PatternMatch]) -> int:
        if not patterns:
            return 0
        emergency_kw = ("emergency", "alert", "critical")
        security_kw = ("security", "breach", "intrusion")
        for p in patterns:
            t = (p.metadata.get("orig_span", {}) or {}).get("text", p.matched_text).lower()
            if any(k in t for k in emergency_kw):
                return 10
            if any(k in t for k in security_kw):
                return 8
        return min(len(patterns), 5)

    def _calculate_urgency(self, patterns: List[PatternMatch], event_types: List[EventType]) -> str:
        if EventType.EMERGENCY in event_types:
            return "critical"
        urgent_kw = ("urgent", "asap", "immediately", "critical")
        for p in patterns:
            t = (p.metadata.get("orig_span", {}) or {}).get("text", p.matched_text).lower()
            if any(k in t for k in urgent_kw):
                return "high"
        if EventType.SECURITY in event_types:
            return "high"
        return "normal"

    def _determine_required_service(self, event_types: List[EventType]) -> Optional[str]:
        if EventType.HVAC in event_types: return "hvac_service"
        if EventType.SECURITY in event_types: return "security_service"
        if EventType.MAINTENANCE in event_types: return "maintenance_service"
        if EventType.EMERGENCY in event_types: return "emergency_service"
        if EventType.VIP in event_types: return "vip_service"
        return None

    def _determine_required_skill(self, tags: EventTags, text: str) -> Optional[str]:
        technical_kw = ("api", "database", "server", "network", "code", "algorithm")
        if any(k in text.lower() for k in technical_kw):
            return "technical"
        if EventType.HVAC in tags.event_types: return "hvac_technical"
        if EventType.SECURITY in tags.event_types: return "security_technical"
        return None

    def _suggest_target_organ(self, task_type: Optional[str], event_types: List[EventType]) -> Optional[str]:
        if EventType.HVAC in event_types: return "hvac_organ"
        if EventType.SECURITY in event_types: return "security_organ"
        if EventType.MAINTENANCE in event_types: return "maintenance_organ"
        if task_type in ("graph_embed", "graph_rag_query"): return "graph_dispatcher"
        if task_type in ("fact_search", "fact_store"): return "utility_organ_1"
        return None

    def _calculate_processing_timeout(self, tags: EventTags, text: str) -> float:
        base = 30.0
        if len(tags.patterns) > 5: base += 10.0
        if len(text) > 1000: base += 5.0
        if tags.urgency == "critical": base += 20.0
        return base

    def _extract_resource_requirements(self, tags: EventTags, text: str) -> Dict[str, Any]:
        req = {"cpu_cores": 2 if len(tags.patterns) > 10 else 1}
        req["memory_mb"] = 512 if len(text) > 5000 else 256
        if tags.priority > 7: req["gpu_required"] = True
        return req

    def _generate_routing_hints(self, tags: EventTags, request: EventizerRequest) -> Dict[str, Any]:
        hints = {
            "confidence_threshold": self.config.ml_fallback_threshold,
            "pattern_count": len(tags.patterns),
            "event_type_count": len(tags.event_types),
            "priority": tags.priority,
            "urgency": tags.urgency,
        }
        if request.domain: hints["domain_context"] = request.domain
        if request.task_type: hints["task_type_context"] = request.task_type
        return hints

    async def _match_all_budgeted_with_compilation(
        self, text: str, budget_ms: float
    ) -> Tuple[List[PatternMatch], List[PatternCompilationResult]]:
        """
        Enhanced pattern matching that returns both matches and compilation results.
        """
        matches: List[PatternMatch] = []
        compilation_results: List[PatternCompilationResult] = []
        
        if not self._pattern_compiler:
            return matches, compilation_results
        
        start_time = _now_ms()
        
        try:
            # Get regex matches with compilation info
            regex_matches = await self._pattern_compiler.match_regex(text)
            matches.extend(regex_matches)
            
            # Create compilation results for regex patterns
            for match in regex_matches:
                compilation_result = PatternCompilationResult(
                    pattern_id=match.pattern_id,
                    engine="re",  # Default engine
                    pattern_type=match.pattern_type,
                    priority=match.priority,
                    confidence=match.confidence,
                    whole_word=match.whole_word,
                    compilation_time_ms=0.0,  # Would be tracked during compilation
                    flags=0,
                    is_compiled=True
                )
                compilation_results.append(compilation_result)
            
            # Get keyword matches
            keyword_matches = await self._pattern_compiler.match_keywords(text)
            matches.extend(keyword_matches)
            
            # Create compilation results for keyword patterns
            for match in keyword_matches:
                compilation_result = PatternCompilationResult(
                    pattern_id=match.pattern_id,
                    engine="keyword",
                    pattern_type=match.pattern_type,
                    priority=match.priority,
                    confidence=match.confidence,
                    whole_word=match.whole_word,
                    compilation_time_ms=0.0,
                    flags=0,
                    is_compiled=True
                )
                compilation_results.append(compilation_result)
            
            # Get entity matches
            entity_matches = await self._pattern_compiler.match_entities(text)
            matches.extend(entity_matches)
            
            # Create compilation results for entity patterns
            for match in entity_matches:
                compilation_result = PatternCompilationResult(
                    pattern_id=match.pattern_id,
                    engine="entity",
                    pattern_type=match.pattern_type,
                    priority=match.priority,
                    confidence=match.confidence,
                    whole_word=match.whole_word,
                    compilation_time_ms=0.0,
                    flags=0,
                    is_compiled=True
                )
                compilation_results.append(compilation_result)
            
        except Exception as e:
            logger.error("Pattern matching failed: %s", e)
            # Add error compilation result
            error_result = PatternCompilationResult(
                pattern_id="error",
                engine="none",
                pattern_type="error",
                priority=1000,
                confidence=0.0,
                whole_word=False,
                compilation_time_ms=_now_ms() - start_time,
                flags=0,
                is_compiled=False,
                error_message=str(e)
            )
            compilation_results.append(error_result)
        
        return matches, compilation_results

    def _map_pii_spans_to_original(
        self, 
        pii_spans: List[EntitySpan], 
        span_map: SpanMap, 
        original_text: str
    ) -> List[EntitySpan]:
        """
        Map PII spans from normalized text coordinates back to original text coordinates.
        This ensures PII audit spans reference the correct positions in the original text.
        """
        mapped_spans = []
        
        for span in pii_spans:
            try:
                # Map start and end positions from normalized to original coordinates
                original_start = span_map.normalized_to_original(span.start)
                original_end = span_map.normalized_to_original(span.end)
                
                # Validate that the mapped positions are within bounds
                if (0 <= original_start < len(original_text) and 
                    0 <= original_end <= len(original_text) and 
                    original_start <= original_end):
                    
                    # Extract the actual text from original coordinates for verification
                    original_text_fragment = original_text[original_start:original_end]
                    
                    # Create mapped span with original coordinates
                    mapped_span = EntitySpan(
                        entity_type=span.entity_type,
                        start=original_start,
                        end=original_end,
                        score=span.score,
                        text=original_text_fragment,  # Use actual text from original
                        replacement=span.replacement
                    )
                    mapped_spans.append(mapped_span)
                    
                else:
                    # Log warning for invalid mapping
                    logger.warning(
                        "PII span mapping failed: normalized(%d,%d) -> original(%d,%d) "
                        "out of bounds for text length %d",
                        span.start, span.end, original_start, original_end, len(original_text)
                    )
                    
            except Exception as e:
                logger.warning(
                    "PII span mapping error for span %s: %s", 
                    span.entity_type, e
                )
                # Keep original span as fallback
                mapped_spans.append(span)
        
        return mapped_spans

    def _validate_pii_span_mapping(
        self, 
        original_spans: List[EntitySpan], 
        original_text: str
    ) -> bool:
        """
        Validate that PII spans are correctly mapped to original text coordinates.
        Returns True if all spans are valid, False otherwise.
        """
        for span in original_spans:
            try:
                # Check bounds
                if not (0 <= span.start < len(original_text) and 
                       0 <= span.end <= len(original_text) and 
                       span.start <= span.end):
                    logger.warning(
                        "PII span validation failed: span %s at (%d,%d) out of bounds for text length %d",
                        span.entity_type, span.start, span.end, len(original_text)
                    )
                    return False
                
                # Check that the text matches what we expect
                actual_text = original_text[span.start:span.end]
                if actual_text != span.text:
                    logger.warning(
                        "PII span text mismatch: expected '%s', got '%s' for span %s at (%d,%d)",
                        span.text, actual_text, span.entity_type, span.start, span.end
                    )
                    return False
                    
            except Exception as e:
                logger.warning("PII span validation error: %s", e)
                return False
        
        return True

    def _calculate_pattern_confidence(self, patterns: List[PatternMatch]) -> float:
        if not patterns:
            return 0.0
        return sum(p.confidence for p in patterns) / max(1, len(patterns))

    def _calculate_completeness_confidence(self, tags: EventTags, attrs: EventAttributes) -> float:
        score = 0.0
        if tags.event_types: score += 0.3
        if tags.keywords: score += 0.2
        if tags.entities: score += 0.2
        if attrs.required_service: score += 0.15
        if attrs.target_organ: score += 0.15
        return min(score, 1.0)

    async def _async_call_fallback_hook(
        self,
        req: EventizerRequest,
        tags: EventTags,
        attrs: EventAttributes,
        conf: ConfidenceScore,
    ) -> None:
        """
        Non-blocking notification for ML fallback orchestrator.
        """
        try:
            dummy_resp = EventizerResponse(
                original_text=req.text,
                processed_text=req.text,
                event_tags=tags,
                attributes=attrs,
                confidence=conf,
                processing_time_ms=0.0,
                patterns_applied=len(tags.patterns),
                pii_redacted=False,
            )
            self._ml_fallback_hook(req, dummy_resp)  # fire-and-forget
        except Exception as e:
            logger.warning("ML fallback hook error: %s", e)

    async def _evaluate_pkg_policies(
        self, 
        tags: EventTags, 
        attrs: EventAttributes, 
        request: EventizerRequest
    ) -> Optional[PKGHint]:
        """
        Evaluate PKG policies based on extracted tags and attributes.
        Returns PKG hint with subtasks and provenance if policies match.
        """
        if not self._pkg_client or not self._active_snapshot:
            return None

        try:
            # TODO: Implement actual policy evaluation logic
            # For now, create a basic PKG hint based on event types
            subtasks = []
            provenance = []
            
            # Simple policy: if we have high priority events, suggest specific subtasks
            if tags.priority >= 7:
                if EventType.EMERGENCY in tags.event_types:
                    subtask = PKGHelper.create_rule_provenance(
                        rule_id="emergency_response_rule",
                        snapshot_version=self._active_snapshot.version,
                        reason="Emergency event detected",
                        snapshot_id=self._active_snapshot.id,
                        weight=1.0,
                        rule_priority=10
                    )
                    provenance.append(subtask)
                    
                elif EventType.SECURITY in tags.event_types:
                    subtask = PKGHelper.create_rule_provenance(
                        rule_id="security_alert_rule",
                        snapshot_version=self._active_snapshot.version,
                        reason="Security event detected",
                        snapshot_id=self._active_snapshot.id,
                        weight=0.9,
                        rule_priority=8
                    )
                    provenance.append(subtask)

            # Create PKG hint
            if provenance:
                pkg_hint = PKGHelper.create_pkg_hint_from_snapshot(
                    snapshot=self._active_snapshot,
                    provenance=provenance,
                    deployment_target="router",
                    deployment_region="global",
                    deployment_percent=100
                )
                return pkg_hint

        except Exception as e:
            logger.error(f"PKG policy evaluation error: {e}")
            
        return None

    def _get_pkg_deployment_info(self) -> Dict[str, Any]:
        """Get PKG deployment information for metadata."""
        if not self._active_snapshot:
            return {}
            
        return {
            "snapshot_version": self._active_snapshot.version,
            "environment": self._active_snapshot.env.value,
            "checksum": self._active_snapshot.checksum,
            "is_active": self._active_snapshot.is_active,
            "created_at": self._active_snapshot.created_at.isoformat()
        }

    async def _load_patterns(self) -> None:
        """Load patterns from configuration files."""
        try:
            # Load patterns from the main configuration file
            patterns_file = "config/eventizer_patterns.json"
            if await self._pattern_compiler.load_patterns_from_file(patterns_file):
                logger.info(f"Loaded patterns from {patterns_file}")
            else:
                logger.warning(f"Failed to load patterns from {patterns_file}")
        except Exception as e:
            logger.error(f"Error loading patterns: {e}")
    
    async def process_dict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convenience method to process a dictionary payload (for HTTP endpoints).
        
        Args:
            payload: Dictionary containing eventizer request data
            
        Returns:
            Dictionary representation of the EventizerResponse
        """
        try:
            # Convert dict to EventizerRequest
            request = EventizerRequest(**payload)
            
            # Process through the main pipeline
            response = await self.process_text(request)
            
            # Convert response to dictionary for HTTP serialization
            return response.model_dump()
            
        except Exception as e:
            logger.error(f"Error processing dict payload: {e}")
            # Return error response
            return {
                "error": str(e),
                "success": False,
                "processing_time_ms": 0,
                "event_tags": {},
                "attributes": {},
                "confidence": {"overall_confidence": 0.0, "needs_ml_fallback": True}
            }
