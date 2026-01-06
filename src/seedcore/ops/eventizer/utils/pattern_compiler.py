#!/usr/bin/env python3
"""
Pattern Compiler (product-grade)

- Compiles & matches patterns via multiple engines: Python 're', optional 're2', optional 'hyperscan'
- Supports regex, keyword dictionaries (Aho-Corasick-like), and entity patterns
- Deterministic offsets on ORIGINAL text, Unicode-aware, word-boundary helpers
- Deduplication & overlap merging, per-pattern priority/confidence, time-budget cutoff
- Pattern cache with soft reloads; JSON schema validation for pattern files
- METADATA AWARE: Preserves 'emits_attributes' and 'emits_tags' for downstream logic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from seedcore.ops.eventizer.utils.json_schema_validator import EventizerPatternsValidator

from seedcore.models.eventizer import EventizerConfig, PatternMatch
from .aho_corasick import create_keyword_matcher, OptimizedAhoCorasickMatcher
from .text_normalizer import TextNormalizer, SpanMap, NormalizationTier

logger = logging.getLogger(__name__)

# -----------------------------
# Optional engines (graceful import)
# -----------------------------
_has_re2 = False
_has_hyperscan = False
try:  # RE2 (safe regex)
    import re2 as re2  # type: ignore
    _has_re2 = True
except Exception:
    pass

try:  # Hyperscan (ultra-fast multi-regex)
    import hyperscan  # type: ignore
    _has_hyperscan = True
except Exception:
    pass


# -----------------------------
# Data classes / helpers
# -----------------------------
@dataclass(frozen=True)
class CompiledRegex:
    pattern_id: str
    engine: str                # "re" | "re2" | "hyperscan"
    pattern: Any               # re.Pattern | re2.Pattern | compiled hs db
    flags: int
    priority: int = 100        
    confidence: float = 1.0    
    whole_word: bool = False   
    # Rich Metadata for configuration-driven logic
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KeywordSet:
    """Holds configuration for a set of keywords before compilation."""
    id: str
    keywords: List[str]
    priority: int
    confidence: float
    whole_word: bool
    case_sensitive: bool = False  # Add case_sensitive field
    metadata: Dict[str, Any] = field(default_factory=dict)


def _safe_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def _word_wrap(p: str) -> str:
    # anchor to word boundaries if not already explicit; best-effort
    if not p.startswith(r"\b") and not p.startswith("^"):
        p = r"\b" + p
    if not p.endswith(r"\b") and not p.endswith("$"):
        p = p + r"\b"
    return p


def _time_exceeded(start: float, budget_ms: Optional[float]) -> bool:
    if not budget_ms:
        return False
    return (time.perf_counter() - start) * 1000.0 > budget_ms


# -----------------------------
# Main compiler
# -----------------------------
class PatternCompiler:
    """
    Pattern compilation and matching utilities.

    Supports:
      - Regex (re / re2 / hyperscan multi-db)
      - Keyword dictionary matching (Aho-Corasick-like)
      - Entity recognition via regex
    """

    def __init__(self, config: EventizerConfig):
        self.config = config

        # Compiled state
        self._compiled_regex: Dict[str, CompiledRegex] = {}
        self._compiled_entities: Dict[str, CompiledRegex] = {}
        
        # Keyword definitions (Intermediate state)
        self._keyword_sets: List[KeywordSet] = []
        
        # Aho-Corasick matchers (Final state)
        # Keyed by 'scope' (usually 'global', but extensible)
        self._keyword_matchers: Dict[str, OptimizedAhoCorasickMatcher] = {}
        self._use_aho_corasick = self.config.enable_aho_corasick

        # Hyperscan db for batch regex (optional)
        self._hs_db = None
        self._hs_ids: Dict[int, str] = {}  # hs_id -> pattern_id

        # Version / telemetry
        self._engines: Dict[str, str] = {}
        self._pattern_file_hashes: Dict[str, str] = {}
        
        # Normalization support (optional, controlled by config)
        self._normalize_before_match: bool = getattr(config, 'normalize_before_match', False)
        self._normalization_tier: NormalizationTier = getattr(
            config, 'normalization_tier', NormalizationTier.AGGRESSIVE
        )

        # Load defaults immediately (safe)
        self._load_default_patterns()

    # -----------------------------
    # Public API
    # -----------------------------
    async def initialize(self) -> None:
        """Initialize from config files and build optional high-perf engines."""
        logger.info("PatternCompiler init: re2=%s hyperscan=%s aho_corasick=%s",
                    _has_re2 and self.config.enable_re2, 
                    _has_hyperscan and self.config.enable_hyperscan,
                    self._use_aho_corasick)
        await self._load_configured_patterns()
        self._build_aho_corasick_matchers()
        self._build_hyperscan_db_if_needed()
        self._engines = self._collect_engine_versions()
        logger.info("PatternCompiler ready: %s", self.get_pattern_count())

    async def match_all(
        self,
        text: str,
        *,
        budget_ms: Optional[float] = None,
        include_regex: bool = True,
        include_keywords: bool = True,
        include_entities: bool = True,
    ) -> List[PatternMatch]:
        """
        Match all enabled pattern families with optional time budget.

        Returns deduplicated, priority-ordered matches with stable offsets on ORIGINAL text.
        
        If normalization is enabled (via config.normalize_before_match), patterns are matched
        against normalized text, then spans are projected back to original using SpanMap.
        """
        start = time.perf_counter()
        matches: List[PatternMatch] = []
        original_text = text
        span_map: Optional[SpanMap] = None
        
        # Optional normalization pass
        if self._normalize_before_match:
            try:
                normalizer = TextNormalizer(
                    tier=self._normalization_tier,
                    case="lower",
                    fold_accents=False,
                    standardize_units=True,
                    strip_audio_tags=True,
                    join_split_tokens=True,
                )
                normalized_result = normalizer.normalize(text, build_map=True)
                if isinstance(normalized_result, tuple):
                    text, span_map = normalized_result
                else:
                    text = normalized_result
                    span_map = None
            except Exception as e:
                logger.warning("Normalization failed, using original text: %s", e)
                span_map = None

        try:
            if include_regex and self._compiled_regex:
                matches.extend(self._match_regex(text, start, budget_ms, original_text, span_map))
                if _time_exceeded(start, budget_ms):
                    return self._dedup_and_sort(matches)

            if include_keywords and (self._keyword_matchers or self._keyword_sets):
                matches.extend(self._match_keywords(text, original_text, span_map))
                if _time_exceeded(start, budget_ms):
                    return self._dedup_and_sort(matches)

            if include_entities and self._compiled_entities:
                matches.extend(self._match_entities(text, start, budget_ms, original_text, span_map))
        except Exception as e:
            logger.exception("Pattern match failed: %s", e)

        return self._dedup_and_sort(matches)

    async def load_patterns_from_file(self, file_path: str) -> bool:
        """
        Load patterns from a JSON file with JSON Schema validation.
        Extracts rich metadata for attribute injection.
        """
        p = Path(file_path)
        if not p.exists():
            logger.warning("Pattern file not found: %s", file_path)
            return False

        # Validate file against JSON Schema
        if not self._validate_patterns_file(p):
            logger.error("Pattern file validation failed, skipping load: %s", file_path)
            return False

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Invalid JSON in %s: %s", file_path, e)
            return False

        self._pattern_file_hashes[file_path] = _safe_hash(p.read_text(encoding="utf-8"))

        # 1. Regex Patterns
        for item in data.get("regex_patterns", []) or []:
            if not item.get("enabled", True):
                continue
            
            # Build metadata payload
            meta = item.get("metadata", {}).copy()
            meta.update({
                "event_types": item.get("event_types", []),
                "emits_tags": item.get("emits_tags", []),
                "emits_attributes": item.get("emits_attributes", {}),
                "priority": item.get("priority", 100),
                "description": item.get("description", "")
            })
            
            self._add_regex_compiled(
                pattern_id=str(item["id"]).strip(),
                pattern_text=str(item["pattern"]),
                flags=self._decode_flags(item.get("flags")),
                priority=int(item.get("priority", 100)),
                confidence=float(item.get("confidence", 1.0)),
                whole_word=bool(item.get("whole_word", False)),
                metadata=meta
            )

        # 2. Keyword Patterns (New Rich Structure)
        for item in data.get("keyword_patterns", []) or []:
            if not item.get("enabled", True):
                continue
            
            meta = item.get("metadata", {}).copy()
            meta.update({
                "event_types": item.get("event_types", []),
                "emits_tags": item.get("emits_tags", []),
                "emits_attributes": item.get("emits_attributes", {}),
                "priority": item.get("priority", 100),
                "description": item.get("description", "")
            })

            self._keyword_sets.append(KeywordSet(
                id=str(item["id"]).strip(),
                keywords=[str(k) for k in (item.get("keywords") or []) if str(k).strip()],
                priority=int(item.get("priority", 100)),
                confidence=float(item.get("confidence", 0.7)),
                whole_word=bool(item.get("whole_word", True)),
                case_sensitive=bool(item.get("case_sensitive", False)),
                metadata=meta
            ))

        # 3. Entity Patterns
        for item in data.get("entity_patterns", []) or []:
            if not item.get("enabled", True):
                continue
            
            et = str(item["entity_type"]).strip()
            base_meta = item.get("metadata", {}).copy()
            base_meta.update({
                "entity_type": et,
                "event_types": item.get("event_types", []),
                "emits_tags": item.get("emits_tags", []),
                "emits_attributes": item.get("emits_attributes", {}),
                "description": item.get("description", "")
            })
            
            for idx, sub in enumerate(item.get("patterns", [])):
                if "regex" in sub:
                    # Use unique pattern_id to avoid overwriting: entity:{entity_type}:{index}
                    pattern_id = f"entity:{et}:{idx}"
                    self._add_entity_compiled(
                        pattern_id=pattern_id,
                        entity_type=et,
                        pattern_text=str(sub["regex"]),
                        flags=self._decode_flags(sub.get("flags")),
                        priority=int(item.get("priority", 100)),
                        confidence=float(item.get("confidence", 0.9)),
                        metadata=base_meta
                    )

        logger.info("Loaded patterns from %s", file_path)
        return True

    async def load_keywords_from_file(self, file_path: str) -> None:
        """Load keywords (one per line) into a KeywordSet named after the file stem."""
        p = Path(file_path)
        if not p.exists():
            logger.warning("Keyword file not found: %s", file_path)
            return

        kws: List[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                kws.append(s)
        if kws:
            self._keyword_sets.append(KeywordSet(
                id=p.stem,
                keywords=kws,
                priority=100,
                confidence=0.7,
                whole_word=True,
                case_sensitive=False,
                metadata={}
            ))
            logger.info("Loaded keyword dictionary: %s (%d keywords)", p.stem, len(kws))

    def add_regex_pattern(self, pattern_id: str, pattern_text: str, flags: int = 0,
                          *, priority: int = 100, confidence: float = 1.0, whole_word: bool = False,
                          metadata: Dict[str, Any] = None) -> bool:
        """Add a single regex pattern (runtime)."""
        try:
            self._add_regex_compiled(pattern_id, pattern_text, flags, priority, confidence, whole_word, metadata)
            self._build_hyperscan_db_if_needed()
            return True
        except Exception as e:
            logger.warning("Invalid regex pattern %s: %s", pattern_id, e)
            return False

    def add_keyword_dictionary(self, dict_name: str, keywords: List[str]) -> None:
        # Legacy method - convert to KeywordSet
        self._keyword_sets.append(KeywordSet(
            id=dict_name,
            keywords=[k for k in keywords if k],
            priority=100,
            confidence=0.7,
            whole_word=True,
            case_sensitive=False,
            metadata={}
        ))
        logger.debug("Added keyword dictionary: %s (%d keywords)", dict_name, len(keywords))

    def add_entity_pattern(self, entity_type: str, pattern_text: str, flags: int = 0,
                           *, priority: int = 100, confidence: float = 0.9,
                           metadata: Dict[str, Any] = None) -> bool:
        try:
            # Generate unique pattern_id to avoid overwriting
            pattern_id = f"entity:{entity_type}:{len(self._compiled_entities)}"
            self._add_entity_compiled(pattern_id, entity_type, pattern_text, flags, priority, confidence, metadata)
            return True
        except Exception as e:
            logger.warning("Invalid entity pattern %s: %s", entity_type, e)
            return False

    def get_pattern_count(self) -> Dict[str, int]:
        return {
            "regex_patterns": len(self._compiled_regex),
            "keyword_sets": len(self._keyword_sets),
            "entity_patterns": len(self._compiled_entities),
            "hyperscan_groups": 1 if self._hs_db is not None else 0,
        }

    def clear_patterns(self) -> None:
        self._compiled_regex.clear()
        self._compiled_entities.clear()
        self._keyword_sets.clear()
        self._keyword_matchers.clear()
        self._hs_db = None
        self._hs_ids.clear()
        logger.info("Cleared all patterns")

    # -----------------------------
    # Compilation Helpers
    # -----------------------------
    def _add_regex_compiled(self, pattern_id: str, pattern_text: str, flags: int,
                          priority: int, confidence: float, whole_word: bool, 
                          metadata: Dict[str, Any] = None) -> None:
        if whole_word:
            pattern_text = _word_wrap(pattern_text)

        # ... (Engine selection logic re/re2) ...
        # Default to standard re
        compiled = re.compile(pattern_text, flags)
        engine_used = "re"
        
        if self.config.enable_re2 and _has_re2:
            try:
                compiled = re2.compile(pattern_text, flags)
                engine_used = "re2"
            except Exception as e:
                logger.debug("re2 compile failed for %s, fallback to re: %s", pattern_id, e)

        self._compiled_regex[pattern_id] = CompiledRegex(
            pattern_id=pattern_id,
            engine=engine_used,
            pattern=compiled,
            flags=flags,
            priority=priority,
            confidence=confidence,
            whole_word=whole_word,
            metadata=metadata or {}
        )

    def _add_entity_compiled(self, pattern_id: str, entity_type: str, pattern_text: str, flags: int,
                            priority: int, confidence: float, metadata: Dict[str, Any] = None) -> None:
        """Compile entity pattern with unique pattern_id to avoid overwriting."""
        # Similar to regex, but stored in _compiled_entities
        compiled = re.compile(pattern_text, flags)
        engine_used = "re"
        
        if self.config.enable_re2 and _has_re2:
            try:
                compiled = re2.compile(pattern_text, flags)
                engine_used = "re2"
            except Exception as e:
                logger.debug("re2 entity compile failed for %s, fallback to re: %s", pattern_id, e)
        
        self._compiled_entities[pattern_id] = CompiledRegex(
            pattern_id=pattern_id,
            engine=engine_used,
            pattern=compiled,
            flags=flags,
            priority=priority,
            confidence=confidence,
            metadata=metadata or {}
        )

    def _build_hyperscan_db_if_needed(self) -> None:
        """Build a single Hyperscan db for all eligible regex (no capturing groups required)."""
        if not (self.config.enable_hyperscan and _has_hyperscan):
            self._hs_db = None
            self._hs_ids = {}
            return

        # Hyperscan can't handle all PCRE features—filter cautiously.
        exprs: List[bytes] = []
        flags: List[int] = []
        ids: List[int] = []

        def hs_flags(py_flags: int) -> int:
            f = hyperscan.HS_FLAG_DOTALL if (py_flags & re.DOTALL) else 0
            if py_flags & re.IGNORECASE:
                f |= hyperscan.HS_FLAG_CASELESS
            # Multiline often safe; add as needed
            return f

        next_id = 1
        for pid, comp in self._compiled_regex.items():
            pat = getattr(comp.pattern, "pattern", None)
            if not isinstance(pat, str):
                # re2 returns pattern as .pattern too; guard regardless
                try:
                    pat = comp.pattern.pattern  # type: ignore
                except Exception:
                    pat = None
            if not pat:
                continue
            # Hyperscan eligibility: reject patterns with capture groups (but allow non-capturing groups)
            # Reject: (?P<name>...) or plain ( without non-capturing prefix
            # Allow: (?:...) (?=...) (?!...) (?<=...) (?<!...) and escaped \(
            if "(" in pat:
                # Check for escaped parentheses
                import re as re_module
                # Remove escaped parentheses for analysis
                pat_unescaped = pat.replace(r"\(", "").replace(r"\)", "")
                # Reject if contains capture groups: (?P< or plain ( not followed by ?: = ! <
                if "(?P<" in pat_unescaped or re_module.search(r"\((?!\?[:=!<>])", pat_unescaped):
                    continue
            try:
                exprs.append(pat.encode("utf-8"))
                flags.append(hs_flags(comp.flags))
                ids.append(next_id)
                self._hs_ids[next_id] = pid
                next_id += 1
            except Exception:
                continue

        if not exprs:
            self._hs_db = None
            self._hs_ids = {}
            return

        try:
            db = hyperscan.Database()
            db.compile(expressions=exprs, ids=ids, elements=len(exprs), flags=flags)
            self._hs_db = db
            logger.info("Hyperscan database compiled for %d patterns", len(exprs))
        except Exception as e:
            logger.warning("Hyperscan compile failed, disabling: %s", e)
            self._hs_db = None
            self._hs_ids = {}

    # -----------------------------
    # Internal: matching
    # -----------------------------
    def _match_regex(self, text: str, start_ts: float, budget_ms: Optional[float],
                     original_text: Optional[str] = None, span_map: Optional[SpanMap] = None) -> List[PatternMatch]:
        out: List[PatternMatch] = []
        
        # Hyperscan Path
        if self._hs_db:
            # ... (Hyperscan logic remains similar, but needs to fetch metadata) ...
            # Since Hyperscan only returns IDs, we look up self._compiled_regex[pid].metadata
            try:
                spans: List[Tuple[int, int, int]] = []  # (id, from, to)
                def on_match(id_: int, from_: int, to_: int, flags: int, context: Any) -> None:
                    spans.append((id_, from_, to_))
                    return

                self._hs_db.scan(text.encode("utf-8", "ignore"), match_event_handler=on_match)
                for id_, s, e in spans:
                    pid = self._hs_ids.get(id_)
                    if not pid:
                        continue
                    comp = self._compiled_regex.get(pid)
                    if not comp:
                        continue
                    # Optionally confirm span using original engine (to get groups/true span)
                    try:
                        for m in comp.pattern.finditer(text[s:e]):
                            ms = s + m.start()
                            me = s + m.end()
                            
                            # Project normalized spans back to original if span_map available
                            if span_map and original_text:
                                orig_span = span_map.project_norm_span_to_orig(ms, me, original_len=len(original_text))
                                orig_start, orig_end = orig_span
                                matched_text = original_text[orig_start:orig_end]
                            else:
                                orig_start, orig_end = ms, me
                                matched_text = text[ms:me]
                            
                            # Merge capture groups into metadata
                            meta = comp.metadata.copy()
                            meta["priority"] = comp.priority
                            meta["engine"] = "hyperscan+%s" % comp.engine
                            meta["groups"] = m.groups()
                            meta["groupdict"] = m.groupdict()
                            
                            out.append(PatternMatch(
                                pattern_id=pid,
                                pattern_type="regex",
                                matched_text=matched_text,
                                start_pos=orig_start,
                                end_pos=orig_end,
                                confidence=max(0.0, min(1.0, comp.confidence)),
                                metadata=meta,
                            ))
                    except Exception:
                        # Fallback: trust HS span
                        if span_map and original_text:
                            orig_span = span_map.project_norm_span_to_orig(s, e, original_len=len(original_text))
                            orig_start, orig_end = orig_span
                            matched_text = original_text[orig_start:orig_end]
                        else:
                            orig_start, orig_end = s, e
                            matched_text = text[s:e]
                        
                        meta = comp.metadata.copy()
                        meta["engine"] = "hyperscan"
                        meta["priority"] = comp.priority
                        out.append(PatternMatch(
                            pattern_id=pid,
                            pattern_type="regex",
                            matched_text=matched_text,
                            start_pos=orig_start,
                            end_pos=orig_end,
                            confidence=max(0.0, min(1.0, comp.confidence)),
                            metadata=meta,
                        ))
                if _time_exceeded(start_ts, budget_ms):
                    return out
            except Exception as e:
                logger.debug("Hyperscan scan failed, fallback to native regex: %s", e)

        # Python/RE2 Path
        for pid, comp in self._compiled_regex.items():
            try:
                for m in comp.pattern.finditer(text):
                    ns, ne = m.start(), m.end()
                    
                    # Project normalized spans back to original if span_map available
                    if span_map and original_text:
                        orig_span = span_map.project_norm_span_to_orig(ns, ne, original_len=len(original_text))
                        orig_start, orig_end = orig_span
                        matched_text = original_text[orig_start:orig_end]
                    else:
                        orig_start, orig_end = ns, ne
                        matched_text = m.group()
                    
                    # Merge capture groups into metadata
                    meta = comp.metadata.copy()
                    meta["priority"] = comp.priority
                    meta["engine"] = comp.engine
                    meta["groups"] = m.groups()
                    meta["groupdict"] = m.groupdict()

                    out.append(PatternMatch(
                        pattern_id=pid,
                        pattern_type="regex",
                        matched_text=matched_text,
                        start_pos=orig_start,
                        end_pos=orig_end,
                        confidence=comp.confidence,
                        metadata=meta
                    ))
                if _time_exceeded(start_ts, budget_ms):
                    break
            except Exception:
                pass
        return out

    def _match_keywords(self, text: str, original_text: Optional[str] = None, span_map: Optional[SpanMap] = None) -> List[PatternMatch]:
        """Match keywords using Aho-Corasick with metadata hydration.
        
        Matches across all bucketized matchers (respecting per-set case_sensitive/whole_word).
        """
        matches = []
        
        # Fast Path: Aho-Corasick (try all buckets)
        if self._use_aho_corasick and self._keyword_matchers:
            for bucket_key, matcher in self._keyword_matchers.items():
                try:
                    # Sync call to C++ extension or optimized python wrapper
                    for m in matcher.search(text):
                        # m.value contains the payload we injected in _build
                        meta = {}
                        if isinstance(m.value, dict):
                            meta = m.value.get("metadata", {}).copy()
                        elif hasattr(m.value, "get"):
                            meta = m.value.get("metadata", {}).copy()
                        meta["matched_keyword"] = m.pattern
                        
                        # Project normalized spans back to original if span_map available
                        if span_map and original_text:
                            orig_span = span_map.project_norm_span_to_orig(m.start, m.end, original_len=len(original_text))
                            orig_start, orig_end = orig_span
                            matched_text = original_text[orig_start:orig_end]
                        else:
                            orig_start, orig_end = m.start, m.end
                            matched_text = m.pattern
                        
                        matches.append(PatternMatch(
                            pattern_id=m.pattern_id,
                            pattern_type="keyword",
                            matched_text=matched_text,
                            start_pos=orig_start,
                            end_pos=orig_end,
                            confidence=m.value.get("confidence", 0.7) if isinstance(m.value, dict) else 0.7,
                            # Priority semantics: lower number = higher priority (classic Unix-style)
                            # Schema default is 100. Lower values (e.g., 50) are higher priority.
                            metadata={
                                "priority": m.value.get("priority", 100) if isinstance(m.value, dict) else 100, 
                                **meta
                            }
                        ))
                except Exception as e:
                    logger.warning(f"AC matching failed for bucket {bucket_key}: {e}. Continuing with other buckets.")
            
            if matches:
                return matches
        
        # Fallback: Simple Iteration
        return self._match_keywords_simple(text)

    def _match_keywords_simple(self, text: str, original_text: Optional[str] = None, span_map: Optional[SpanMap] = None) -> List[PatternMatch]:
        """Fallback keyword matching that respects per-set case_sensitive and whole_word."""
        out = []
        for kset in self._keyword_sets:
            meta = kset.metadata.copy()
            meta["priority"] = kset.priority
            
            # Respect case_sensitive: use original text or lowercased version
            search_text = text if getattr(kset, 'case_sensitive', False) else text.lower()
            
            for kw in kset.keywords:
                if not kw:
                    continue
                # Respect case_sensitive for needle
                needle = kw if getattr(kset, 'case_sensitive', False) else kw.lower()
                start = 0
                while True:
                    pos = search_text.find(needle, start)
                    if pos < 0:
                        break
                    
                    # Manual whole word check
                    if kset.whole_word:
                        if (pos > 0 and search_text[pos-1].isalnum()) or \
                           (pos + len(needle) < len(search_text) and search_text[pos+len(needle)].isalnum()):
                            start = pos + 1
                            continue

                    # Project normalized spans back to original if span_map available
                    if span_map and original_text:
                        orig_span = span_map.project_norm_span_to_orig(pos, pos+len(kw), original_len=len(original_text))
                        orig_start, orig_end = orig_span
                        matched_text = original_text[orig_start:orig_end]
                    else:
                        orig_start, orig_end = pos, pos+len(kw)
                        matched_text = text[pos:pos+len(kw)]
                    
                    out.append(PatternMatch(
                        pattern_id=kset.id,
                        pattern_type="keyword",
                        matched_text=matched_text,
                        start_pos=orig_start,
                        end_pos=orig_end,
                        confidence=kset.confidence,
                        metadata=meta
                    ))
                    start = pos + 1
        return out

    def _match_entities(self, text: str, start_ts: float, budget_ms: Optional[float],
                        original_text: Optional[str] = None, span_map: Optional[SpanMap] = None) -> List[PatternMatch]:
        out: List[PatternMatch] = []
        for pattern_id, comp in self._compiled_entities.items():
            try:
                for m in comp.pattern.finditer(text):
                    ns, ne = m.start(), m.end()
                    
                    # Project normalized spans back to original if span_map available
                    if span_map and original_text:
                        orig_span = span_map.project_norm_span_to_orig(ns, ne, original_len=len(original_text))
                        orig_start, orig_end = orig_span
                        matched_text = original_text[orig_start:orig_end]
                    else:
                        orig_start, orig_end = ns, ne
                        matched_text = m.group()
                    
                    meta = comp.metadata.copy()
                    meta["priority"] = comp.priority
                    meta["engine"] = comp.engine
                    meta["groups"] = m.groups()
                    meta["groupdict"] = m.groupdict()
                    # entity_type is available in metadata if needed
                    
                    out.append(PatternMatch(
                        pattern_id=pattern_id,
                        pattern_type="entity",
                        matched_text=matched_text,
                        start_pos=orig_start,
                        end_pos=orig_end,
                        confidence=max(0.0, min(1.0, comp.confidence)),
                        metadata=meta,
                    ))
                if _time_exceeded(start_ts, budget_ms):
                    break
            except Exception as e:
                logger.warning("Entity match error for %s: %s", pattern_id, e)
        return out

    # -----------------------------
    # Internal: utilities
    # -----------------------------
    def _dedup_and_sort(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Deduplicate overlaps (prefer higher confidence, then higher priority; keep deterministic order).
        
        Priority semantics: Lower number = higher priority (classic Unix-style).
        Example: priority 50 beats priority 100.
        """
        if not matches:
            return []

        # Key by (start,end) and pick best
        by_span: Dict[Tuple[int, int], PatternMatch] = {}
        for m in matches:
            key = (m.start_pos, m.end_pos)
            prev = by_span.get(key)
            if prev is None:
                by_span[key] = m
            else:
                # Prefer higher confidence; if tie, prefer lower 'priority' (lower = higher priority)
                prev_prio = int(prev.metadata.get("priority", 100))
                m_prio = int(m.metadata.get("priority", 100))
                if (m.confidence, -m_prio) > (prev.confidence, -prev_prio):
                    by_span[key] = m

        deduped = list(by_span.values())
        # Sort by: start_pos, then end_pos, then descending confidence, then ascending priority (lower = better)
        deduped.sort(key=lambda m: (m.start_pos, m.end_pos, -m.confidence, int(m.metadata.get("priority", 100))))
        return deduped

    async def _load_configured_patterns(self) -> None:
        # JSON pattern files
        for pf in self.config.pattern_files:
            try:
                await self.load_patterns_from_file(pf)
            except Exception as e:
                logger.error("Failed loading pattern file %s: %s", pf, e)

        # Keyword lists (one per line) - legacy support
        for kf in getattr(self.config, 'keyword_dictionaries', []):
            try:
                await self.load_keywords_from_file(kf)
            except Exception as e:
                logger.error("Failed loading keyword file %s: %s", kf, e)

    def _collect_engine_versions(self) -> Dict[str, str]:
        engines = {"regex": "re"}
        if self.config.enable_re2 and _has_re2:
            try:
                engines["regex"] = f"re2/{getattr(re2, '__version__', 'unknown')}"
            except Exception:
                engines["regex"] = "re2"
        if self.config.enable_hyperscan and _has_hyperscan:
            try:
                engines["hyperscan"] = f"hs/{getattr(hyperscan, '__version__', 'unknown')}"
            except Exception:
                engines["hyperscan"] = "hs"
        return engines

    # -----------------------------
    # Aho-Corasick Optimization
    # -----------------------------
    def _build_aho_corasick_matchers(self) -> None:
        """
        Compiles all keyword sets into optimized automatons, bucketized by (case_sensitive, whole_word).
        This ensures per-set settings are respected while maintaining performance.
        """
        if not self._use_aho_corasick or not self._keyword_sets:
            return
        
        # Bucketize keyword sets by (case_sensitive, whole_word) to respect per-set settings
        buckets: Dict[Tuple[bool, bool], List[KeywordSet]] = {}
        for kset in self._keyword_sets:
            key = (kset.case_sensitive, kset.whole_word)
            if key not in buckets:
                buckets[key] = []
            buckets[key].append(kset)
        
        total_count = 0
        for (case_sensitive, whole_word), sets in buckets.items():
            matcher = create_keyword_matcher(case_sensitive=case_sensitive, whole_word=whole_word)
            count = 0
            
            for kset in sets:
                # Attach rich payload to every keyword
                payload = {
                    "id": kset.id,
                    "priority": kset.priority,
                    "confidence": kset.confidence,
                    "metadata": kset.metadata or {}  # This contains the emits_attributes!
                }
                
                for kw in kset.keywords:
                    # Add pattern with payload
                    matcher.add_pattern(
                        kw, 
                        pattern_id=kset.id,
                        # Inject payload attributes directly into match value
                        **payload
                    )
                    count += 1
            
            matcher.build()
            bucket_key = f"cs_{case_sensitive}_ww_{whole_word}"
            self._keyword_matchers[bucket_key] = matcher
            total_count += count
            logger.debug(f"Built Aho-Corasick matcher bucket {bucket_key} with {count} keywords from {len(sets)} sets")
        
        logger.info(f"Built {len(buckets)} Aho-Corasick matcher buckets with {total_count} total keywords from {len(self._keyword_sets)} sets")
    
    
    def _validate_patterns_file(self, file_path: Path) -> bool:
        """Validate patterns file against JSON Schema."""
        try:
            # Use the schema in the config directory
            project_root = Path(__file__).parent.parent.parent.parent.parent
            schema_path = project_root / "config" / "eventizer_patterns_schema.json"
            
            validator = EventizerPatternsValidator(schema_path)
            result = validator.validate_file(file_path)
            
            if not result.is_valid:
                logger.error(f"Patterns file validation failed: {file_path}")
                for error in result.errors:
                    logger.error(f"  - {error.path}: {error.message}")
                return False
            
            if result.warnings:
                logger.warning(f"Patterns file has warnings: {file_path}")
                for warning in result.warnings:
                    logger.warning(f"  - {warning.path}: {warning.message}")
            
            logger.info(f"Patterns file validated successfully: {file_path}")
            logger.info(f"Validation stats: {result.stats}")
            return True
            
        except Exception as e:
            logger.error(f"Patterns file validation error: {e}")
            return False

    
    def _decode_flags(self, flags: Any) -> int:
        """Decode regex flags from various formats."""
        if isinstance(flags, int):
            return flags
        if isinstance(flags, str):
            # Handle string flags like "IGNORECASE"
            flag_map = {
                "IGNORECASE": re.IGNORECASE,
                "MULTILINE": re.MULTILINE,
                "DOTALL": re.DOTALL,
                "VERBOSE": re.VERBOSE,
                "ASCII": re.ASCII,
                "LOCALE": re.LOCALE,
                "UNICODE": re.UNICODE
            }
            return flag_map.get(flags.upper(), 0)
        if isinstance(flags, list):
            # Handle list of flag strings
            result = 0
            for flag_str in flags:
                if isinstance(flag_str, str):
                    flag_map = {
                        "IGNORECASE": re.IGNORECASE,
                        "MULTILINE": re.MULTILINE,
                        "DOTALL": re.DOTALL,
                        "VERBOSE": re.VERBOSE,
                        "ASCII": re.ASCII,
                        "LOCALE": re.LOCALE,
                        "UNICODE": re.UNICODE
                    }
                    result |= flag_map.get(flag_str.upper(), 0)
            return result
        return 0

    # -----------------------------
    # Default Loading (Bootstrap)
    # -----------------------------
    def _load_default_patterns(self) -> None:
        """Bootstraps critical patterns if config files fail."""
        # Inject basic Hvac/Security patterns with metadata
        # This ensures the system works "out of the box" even without JSON
        
        self._add_regex_compiled(
            "bootstrap_hvac", 
            r"(?i)\bhvac\b", 
            0, 50, 1.0, False,
            {"event_types": ["hvac"], "emits_tags": ["hvac_fault"]}
        )
        
        self._keyword_sets.append(KeywordSet(
            id="bootstrap_alert",
            keywords=["alert", "emergency"],
            priority=90,
            confidence=1.0,
            whole_word=True,
            metadata={"event_types": ["emergency"], "emits_attributes": {"priority": "critical"}}
        ))
