#!/usr/bin/env python3
"""
Eventizer Service (product-grade)

Deterministic, low-latency text processing pipeline for task classification & routing.
Refactored to be configuration-driven: attributes and tags are derived directly
from pattern metadata (loaded from eventizer_patterns.json), removing hardcoded heuristics.

Pipeline:
  1) Unicode-safe normalization
  2) PII detection/redaction
  3) Pattern matching (regex + keyword + entity)
  4) Config-driven Tag/Attribute aggregation
  5) Confidence scoring
"""
from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, Callable, Set
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import Request  # pyright: ignore[reportMissingImports]

from seedcore.models.eventizer import (
    EventizerRequest,
    EventizerResponse,
    EventTags,
    EventAttributes,
    EventSignals,
    EventizerConfig,
    PatternMatch,
    ConfidenceScore,
    ConfidenceLevel,
    EventType,
    EntitySpan,
)
from ..ops.eventizer.utils.text_normalizer import (
    TextNormalizer,
    SpanMap,
    NormalizationTier,
)
from ..ops.eventizer.utils.pattern_compiler import PatternCompiler
from ..ops.eventizer.clients.pii_client import PIIClient

# Logging
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.eventizer_service.driver")
logger = ensure_serve_logger("seedcore.eventizer_service", level="DEBUG")

# =========================
# Metrics / hooks
# =========================


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def default_metrics_sink(event: str, fields: Dict[str, Any]) -> None:
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


class EventizerServiceImpl:
    """
    Deterministic eventizer service for text processing & classification.
    Now purely driven by pattern configuration metadata.
    """

    def __init__(
        self,
        config: Optional[EventizerConfig] = None,
        *,
        metrics_sink: Callable[[str, Dict[str, Any]], None] = default_metrics_sink,
        ml_fallback_hook: Optional[
            Callable[[EventizerRequest, EventizerResponse], Any]
        ] = None,
    ):
        self.config = config or EventizerConfig()
        self._initialized = False
        # TextNormalizer is created per-request with tiered normalization
        self._pattern_compiler: Optional[PatternCompiler] = None
        self._pii_client: Optional[PIIClient] = None
        self._ml_fallback_hook = ml_fallback_hook
        self._metrics = metrics_sink

        # Event type string mapping is handled dynamically now,
        # but we keep a fallback map if needed for legacy code.
        self._eventtype_alias: Dict[str, EventType] = {}

        logger.info("EventizerServiceImpl configured")

    # -----------------
    # Lifecycle
    # -----------------

    async def initialize(self) -> None:
        if self._initialized:
            return

        t0 = _now_ms()

        # TextNormalizer is created per-request with tiered normalization
        # No need to create a default instance here
        self._pattern_compiler = PatternCompiler(self.config)
        await self._pattern_compiler.initialize()

        if self.config.enable_pii_redaction:
            self._pii_client = PIIClient(self.config.pii_redaction_entities)
            await self._pii_client.initialize()

        # Load patterns (which now contain the logic)
        await self._load_patterns()

        self._initialized = True
        t1 = _now_ms()
        logger.info("EventizerServiceImpl initialized in %.2f ms", t1 - t0)

    # -----------------
    # Public API
    # -----------------

    async def process_text(self, request: EventizerRequest) -> EventizerResponse:
        if not self._initialized:
            await self.initialize()

        stats = ProcessingStats(start_ms=_now_ms())
        log: List[str] = []
        warnings: List[str] = []

        try:
            budget_ms = float(self.config.max_processing_time_ms)
            budget_deadline = stats.start_ms + budget_ms

            # 1. Normalize (with tiered normalization based on request context)
            norm_text, span_map = await self._normalize_with_map(request.text, request)

            # 2. PII Redaction
            redacted_text = norm_text
            pii_audit = None
            if self.config.enable_pii_redaction and self._pii_client:
                redacted_text, pii_audit = self._pii_client.redact_with_audit(
                    norm_text,
                    entities=request.pii_entities,
                    mode=request.redact_mode,
                    span_map=span_map,
                )
                if redacted_text != norm_text:
                    stats.pii_redacted = True
                # Fixup audit spans to original coordinates
                if pii_audit and pii_audit.spans:
                    pii_audit.spans = self._map_pii_spans_to_original(
                        pii_audit.spans, span_map, request.text
                    )

            # 3. Pattern Matching (Budgeted)
            time_left = max(0.0, budget_deadline - _now_ms())
            matches, compilation_res = await self._match_all_budgeted_with_compilation(
                redacted_text, time_left
            )

            # 4. Project Offsets
            projected_matches = self._project_matches(matches, span_map, request.text)
            stats.patterns_applied = len(projected_matches)

            # 5. Analysis: Aggregate Tags & Attributes (Config-Driven + Heuristic Fallback)
            tags, attrs = self._analyze_matches(projected_matches, request)

            # 6. Confidence
            conf = self._calculate_confidence(tags, attrs, stats)

            # 7. Signals: Populate multimodal anomaly and semantic drift signals
            signals = self._calculate_signals(tags, conf, request, stats)

            # 8. Response Construction
            stats.end_ms = _now_ms()

            return EventizerResponse(
                original_text=request.text,
                original_text_sha256=sha256_hex(request.text),
                normalized_text=norm_text,
                processed_text=redacted_text,
                pii=pii_audit,
                event_tags=tags,
                attributes=attrs,
                signals=signals,
                multimodal=request.media_context,  # Bridge multimodal context to response
                confidence=conf,
                processing_time_ms=stats.end_ms - stats.start_ms,
                patterns_applied=stats.patterns_applied,
                pii_redacted=stats.pii_redacted,
                warnings=warnings,
                processing_log=log,
                eventizer_version="1.2.0",
            )

        except Exception as e:
            logger.exception("Eventizer failed")
            return self._create_error_response(request, str(e), stats)

    # -----------------
    # Core Logic: Config-Driven Analysis
    # -----------------

    def _analyze_matches(
        self, matches: List[PatternMatch], request: EventizerRequest
    ) -> Tuple[EventTags, EventAttributes]:
        """
        Aggregates all signals from pattern matches.
        Prioritizes 'emits_attributes' from JSON config, then falls back to framework heuristics.
        """
        # Collections
        unique_event_types: Set[EventType] = set()
        keywords: Set[str] = set()
        entities: Set[str] = set()

        # Attribute accumulators
        collected_attrs: Dict[str, Any] = {}
        priority_scores: List[int] = []

        for m in matches:
            meta = m.metadata or {}

            # A. Event Types
            # Config: "event_types": ["hvac", "maintenance"]
            for et_str in meta.get("event_types", []):
                try:
                    # Convert string to enum, handling aliases if needed
                    et = EventType(et_str.lower())
                    unique_event_types.add(et)
                except ValueError:
                    pass

            # B. Keywords/Entities
            if m.pattern_type == "keyword":
                keywords.add(m.matched_text)
            elif m.pattern_type == "entity":
                ent_type = meta.get("entity_type", "UNKNOWN")
                val = meta.get("orig_span", {}).get("text", m.matched_text)
                entities.add(f"{ent_type}:{val}")

            # C. Dynamic Attributes (The "Payload")
            # Config: "emits_attributes": { "privacy_mode": "STRICT" }
            if "emits_attributes" in meta:
                for k, v in meta["emits_attributes"].items():
                    collected_attrs[k] = v

            # D. Priority Signal
            # Config: "priority": 90
            if "priority" in meta:
                priority_scores.append(meta["priority"])

        # F. Synthesize Priority/Urgency (Logic driven by max priority found)
        final_priority = max(priority_scores) if priority_scores else 0

        # Map numeric priority to semantic urgency (Configurable thresholds)
        if final_priority >= 90:
            urgency = "critical"
        elif final_priority >= 70:
            urgency = "high"
        else:
            urgency = "normal"

        # Build EventTags
        tags = EventTags(
            event_types=list(unique_event_types),
            keywords=list(keywords),
            entities=list(entities),
            patterns=matches,
            priority=final_priority,
            urgency=urgency,
        )

        # --- Hybrid Attribute Resolution ---

        # 1. Service & Organ: Config > Heuristic Fallback
        req_service = collected_attrs.get("required_service")
        if not req_service:
            req_service = self._default_service_heuristic(tags.event_types)

        target_organ = collected_attrs.get("target_organ")
        if not target_organ:
            target_organ = self._default_organ_heuristic(
                request.task_type, tags.event_types
            )

        # 2. Dynamic Calculations (Runtime State)
        # Config can override, but dynamic default is usually better
        timeout = collected_attrs.get("processing_timeout")
        if timeout is None:
            timeout = self._calculate_dynamic_timeout(tags, request.text)

        resources = collected_attrs.get("resource_requirements")
        if not resources:
            resources = self._calculate_dynamic_resources(tags, request.text)

        # 3. Hints (Always Dynamic)
        hints = self._generate_routing_hints(tags, request)
        if "routing_hints" in collected_attrs:
            hints.update(collected_attrs["routing_hints"])

        # Final Assembly
        attrs = EventAttributes(
            required_service=req_service,
            required_skill=collected_attrs.get(
                "required_skill"
            ),  # No fallback (Config only)
            target_organ=target_organ,
            processing_timeout=timeout,
            resource_requirements=resources,
            routing_hints=hints,
        )

        # Enrich routing hints with request context
        if request.domain:
            attrs.routing_hints["domain_context"] = request.domain

        return tags, attrs

    # -----------------
    # Framework Heuristics (The "Batteries Included" Logic)
    # -----------------

    def _default_service_heuristic(self, event_types: List[EventType]) -> Optional[str]:
        """Fallback: Map EventType enum to standard service names."""
        if EventType.HVAC in event_types:
            return "hvac_service"
        if EventType.SECURITY in event_types:
            return "security_service"
        if EventType.MAINTENANCE in event_types:
            return "maintenance_service"
        if EventType.EMERGENCY in event_types:
            return "emergency_service"
        if EventType.VIP in event_types:
            return "vip_service"
        return None

    def _default_organ_heuristic(
        self, task_type: Optional[str], event_types: List[EventType]
    ) -> Optional[str]:
        """Fallback: Map task/event types to standard organs."""
        if EventType.HVAC in event_types:
            return "hvac_organ"
        if EventType.SECURITY in event_types:
            return "security_organ"
        if task_type in ("graph_embed", "graph_rag_query"):
            return "graph_dispatcher"
        return None

    def _calculate_dynamic_timeout(self, tags: EventTags, text: str) -> float:
        """Dynamic: Longer text or critical events need more time."""
        base = 30.0
        if len(tags.patterns) > 5:
            base += 10.0
        if len(text) > 1000:
            base += 5.0
        if tags.urgency == "critical":
            base += 20.0
        return base

    def _calculate_dynamic_resources(
        self, tags: EventTags, text: str
    ) -> Dict[str, Any]:
        """Dynamic: Large payloads hint for more resources."""
        req = {"cpu_cores": 2 if len(tags.patterns) > 10 else 1}
        req["memory_mb"] = 512 if len(text) > 5000 else 256
        if tags.priority > 7:
            req["gpu_required"] = True
        return req

    def _generate_routing_hints(
        self, tags: EventTags, request: EventizerRequest
    ) -> Dict[str, Any]:
        """Dynamic: Runtime stats useful for the Router."""
        hints = {
            "confidence_threshold": self.config.ml_fallback_threshold,
            "pattern_count": len(tags.patterns),
            "event_type_count": len(tags.event_types),
            "priority": tags.priority,
            "urgency": tags.urgency,
        }
        if request.domain:
            hints["domain_context"] = request.domain
        if request.task_type:
            hints["task_type_context"] = request.task_type
        return hints

    # -----------------
    # Internals (Helpers)
    # -----------------

    async def _normalize_with_map(
        self, text: str, request: EventizerRequest
    ) -> Tuple[str, SpanMap]:
        """
        Normalize text with tiered normalization based on request context.
        
        - AGGRESSIVE tier: For fast-path pattern matching (default for Reflex Arc)
        - COGNITIVE tier: For deep reasoning paths that need sentiment preservation
        
        The tier is selected based on whether PKG hints are requested, indicating
        a Cognitive Agent path that benefits from preserved punctuation intensity.
        """
        # Select normalization tier based on request context
        # If PKG hints are requested, use COGNITIVE tier to preserve sentiment
        # Otherwise, use AGGRESSIVE tier for fast pattern matching
        # Select tier: COGNITIVE for deep reasoning (PKG hints), AGGRESSIVE for fast-path
        tier = (
            NormalizationTier.COGNITIVE
            if request.include_pkg_hint
            else NormalizationTier.AGGRESSIVE
        )

        # Create normalizer with multimodal support
        normalizer = TextNormalizer(
            tier=tier,
            case="lower",
            fold_accents=False,
            standardize_units=True,  # Essential for unit grounding ("6 PM" -> "18:00")
            strip_audio_tags=True,  # Essential for voice-to-text transcripts
            join_split_tokens=True,  # De-obfuscation for security bypass prevention
        )

        return normalizer.normalize(text, build_map=True)

    async def _match_all_budgeted_with_compilation(
        self, text: str, budget_ms: float
    ) -> Tuple[List[PatternMatch], Any]:
        if not self._pattern_compiler:
            return [], []
        matches = await self._pattern_compiler.match_all(text, budget_ms=budget_ms)
        return matches, []

    def _map_pii_spans_to_original(
        self, pii_spans: List[EntitySpan], span_map: SpanMap, original_text: str
    ) -> List[EntitySpan]:
        """
        Map PII spans from normalized text coordinates back to original text coordinates.
        
        Uses SpanMap.project_norm_span_to_orig() to project normalized spans
        back to original text indices for accurate PII audit reporting.
        """
        mapped_spans = []
        for span in pii_spans:
            try:
                # Project normalized span to original text coordinates
                original_start, original_end = span_map.project_norm_span_to_orig(
                    span.start, span.end, original_len=len(original_text)
                )

                if (
                    0 <= original_start < len(original_text)
                    and 0 <= original_end <= len(original_text)
                    and original_start <= original_end
                ):
                    mapped_span = EntitySpan(
                        entity_type=span.entity_type,
                        start=original_start,
                        end=original_end,
                        score=span.score,
                        text=original_text[original_start:original_end],
                        replacement=span.replacement,
                    )
                    mapped_spans.append(mapped_span)
                else:
                    # Fallback: keep original span if projection fails
                    mapped_spans.append(span)
            except Exception:
                # Fallback: keep original span on any error
                mapped_spans.append(span)
        return mapped_spans

    def _project_matches(
        self, matches: List[PatternMatch], span_map: SpanMap, original: str
    ) -> List[PatternMatch]:
        projected: List[PatternMatch] = []
        for m in matches:
            o_start, o_end = span_map.project_norm_span_to_orig(m.start_pos, m.end_pos)
            o_start = max(0, min(o_start, len(original)))
            o_end = max(o_start, min(o_end, len(original)))
            meta = dict(m.metadata or {})
            meta["orig_span"] = {
                "start": o_start,
                "end": o_end,
                "text": original[o_start:o_end],
            }
            projected.append(
                PatternMatch(
                    pattern_id=m.pattern_id,
                    pattern_type=m.pattern_type,
                    matched_text=m.matched_text,
                    start_pos=o_start,
                    end_pos=o_end,
                    confidence=m.confidence,
                    metadata=meta,
                )
            )
        return projected

    def _calculate_signals(
        self,
        tags: EventTags,
        confidence: ConfidenceScore,
        request: EventizerRequest,
        stats: ProcessingStats,
    ) -> EventSignals:
        """
        Calculate semantic drift and multimodal anomaly signals.
        
        Specifically flags x3_multimodal_anomaly when confidence is low despite
        high-intensity keywords, signaling a potential mismatch between
        "what was heard" and "what was meant."
        """
        signals = EventSignals()

        # x3_multimodal_anomaly: Low confidence despite high-intensity keywords
        # This indicates potential transcription errors or semantic mismatch
        has_intensity_keywords = any(
            kw in tags.keywords
            for kw in ["emergency", "urgent", "critical", "fire", "help", "911"]
        )
        if has_intensity_keywords and confidence.overall_confidence < 0.5:
            signals.x3_multimodal_anomaly = 1.0 - confidence.overall_confidence
            signals.drift_flag = True

        # x2_semantic_drift: Low pattern confidence suggests semantic drift
        if confidence.needs_ml_fallback:
            signals.x2_semantic_drift = 1.0 - confidence.overall_confidence

        # x1_cache_novelty: High pattern count suggests novel patterns
        if len(tags.patterns) > 10:
            signals.x1_cache_novelty = min(1.0, len(tags.patterns) / 20.0)

        # Set vector dimension based on multimodal context
        if request.media_context:
            signals.vector_dimension = 1024  # Multimodal embeddings use 1024d
            signals.embedding_model = "multimodal-perception-v1"
        else:
            signals.vector_dimension = 1024  # Default to 1024d for Unified Memory
            signals.embedding_model = "text-embedding-v1"

        return signals

    def _calculate_confidence(
        self, tags: EventTags, attrs: EventAttributes, stats: ProcessingStats
    ) -> ConfidenceScore:
        pattern_conf = 0.0
        if tags.patterns:
            pattern_conf = sum(p.confidence for p in tags.patterns) / max(
                1, len(tags.patterns)
            )

        complete_conf = 0.0
        if tags.event_types:
            complete_conf += 0.3
        if tags.keywords:
            complete_conf += 0.2
        if tags.entities:
            complete_conf += 0.2
        if attrs.required_service:
            complete_conf += 0.15
        if attrs.target_organ:
            complete_conf += 0.15
        complete_conf = min(complete_conf, 1.0)

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
            if pattern_conf < 0.5:
                reasons.append("low_pattern_confidence")
            if complete_conf < 0.5:
                reasons.append("incomplete_extraction")
            if not tags.patterns:
                reasons.append("no_patterns_matched")

        return ConfidenceScore(
            overall_confidence=overall,
            confidence_level=level,
            needs_ml_fallback=needs_fallback,
            fallback_reasons=reasons,
            processing_notes=["pii_redacted"] if stats.pii_redacted else [],
        )

    def _create_error_response(self, request, error_msg, stats):
        stats.end_ms = _now_ms()
        self._metrics("eventizer.err", {"ms": stats.end_ms - stats.start_ms})
        return EventizerResponse(
            original_text=request.text,
            processed_text=request.text,
            normalized_text=request.text,  # Fallback to original on error
            event_tags=EventTags(),
            attributes=EventAttributes(),
            signals=EventSignals(),  # Default signals on error
            multimodal=request.media_context,  # Preserve multimodal context even on error
            confidence=ConfidenceScore(
                overall_confidence=0.0,
                confidence_level=ConfidenceLevel.LOW,
                needs_ml_fallback=True,
                fallback_reasons=["exception"],
                processing_notes=[error_msg],
            ),
            processing_time_ms=stats.end_ms - stats.start_ms,
            patterns_applied=0,
            pii_redacted=False,
            errors=[error_msg],
        )

    async def _load_patterns(self) -> None:
        assert self._pattern_compiler is not None
        return

    async def process_dict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            request = EventizerRequest(**payload)
            response = await self.process_text(request)
            return response.model_dump()
        except Exception as e:
            logger.error(f"Error processing dict payload: {e}")
            return {"error": str(e), "success": False}


@serve.deployment(route_prefix=None)  # No direct public route; called via handle
class EventizerService:
    """Ray Serve wrapper for EventizerService."""

    def __init__(self) -> None:
        self.impl = EventizerServiceImpl()
        self._initialized = False

    async def __call__(self, request: Request) -> Dict[str, Any]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "eventizer"}

    async def initialize(self) -> None:
        """Initialize the underlying service."""
        if not self._initialized:
            await self.impl.initialize()
            self._initialized = True
            logger.info("EventizerService initialized")

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process text through eventizer pipeline.

        Uses the dict interface which handles EventizerRequest construction
        and returns a dict representation of EventizerResponse.
        """
        try:
            if not self._initialized:
                await self.initialize()

            # Process through eventizer using dict interface
            # This handles EventizerRequest construction and returns dict response
            response = await self.impl.process_dict(payload)

            # Check if process_dict returned an error response
            if isinstance(response, dict) and response.get("success") is False:
                error_msg = response.get("error", "Unknown error")
                logger.error(f"Eventizer processing failed: {error_msg}")
                # Return error response in EventizerResponse format
                return {
                    "original_text": payload.get("text", ""),
                    "processed_text": payload.get("text", ""),
                    "event_tags": {
                        "event_types": [],
                        "keywords": [],
                        "entities": [],
                        "patterns": [],
                        "priority": 0,
                        "urgency": "normal",
                    },
                    "attributes": {},
                    "confidence": {
                        "overall_confidence": 0.0,
                        "confidence_level": "low",
                        "needs_ml_fallback": True,
                        "fallback_reasons": ["exception"],
                        "processing_notes": [error_msg],
                    },
                    "processing_time_ms": 0.0,
                    "patterns_applied": 0,
                    "pii_redacted": False,
                    "errors": [error_msg],
                    "success": False,
                }

            # Response is already a dict (EventizerResponse.model_dump())
            return response

        except Exception as e:
            logger.exception(f"Eventizer processing failed: {e}")
            # Return error response matching EventizerResponse structure
            return {
                "original_text": payload.get("text", ""),
                "processed_text": payload.get("text", ""),
                "event_tags": {
                    "event_types": [],
                    "keywords": [],
                    "entities": [],
                    "patterns": [],
                    "priority": 0,
                    "urgency": "normal",
                },
                "attributes": {},
                "confidence": {
                    "overall_confidence": 0.0,
                    "confidence_level": "low",
                    "needs_ml_fallback": True,
                    "fallback_reasons": ["exception"],
                    "processing_notes": [str(e)],
                },
                "processing_time_ms": 0.0,
                "patterns_applied": 0,
                "pii_redacted": False,
                "errors": [str(e)],
                "success": False,
            }

    async def health(self) -> Dict[str, Any]:
        """Health check."""
        return {
            "status": "healthy",
            "service": "eventizer",
            "initialized": self._initialized,
        }
