#!/usr/bin/env python3
"""
Pattern Compiler (product-grade)

- Compiles & matches patterns via multiple engines: Python 're', optional 're2', optional 'hyperscan'
- Supports regex, keyword dictionaries (Aho-Corasick-like), and entity patterns
- Deterministic offsets on ORIGINAL text, Unicode-aware, word-boundary helpers
- Deduplication & overlap merging, per-pattern priority/confidence, time-budget cutoff
- Pattern cache with soft reloads; JSON schema validation for pattern files
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

from ..schemas.eventizer_models import EventizerConfig, PatternMatch
from .aho_corasick import create_keyword_matcher, OptimizedAhoCorasickMatcher
from .json_schema_validator import validate_patterns_file, ValidationResult

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
    pattern: Any               # re.Pattern | re2.Pattern | compiled hs db (for groups of patterns)
    flags: int
    priority: int = 100        # lower is higher priority
    confidence: float = 1.0    # default confidence when matched
    whole_word: bool = False   # wrap with word boundaries if True


def _safe_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def _word_wrap(p: str) -> str:
    # anchor to word boundaries if not already explicit; best-effort
    if not p.startswith(r"\b"):
        p = r"\b" + p
    if not p.endswith(r"\b"):
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
        self._keyword_maps: Dict[str, List[str]] = {}
        
        # Aho-Corasick keyword matchers
        self._keyword_matchers: Dict[str, OptimizedAhoCorasickMatcher] = {}
        self._use_aho_corasick = True  # Enable by default

        # Hyperscan db for batch regex (optional)
        self._hs_db = None
        self._hs_ids: Dict[int, str] = {}  # hs_id -> pattern_id

        # Version / telemetry
        self._engines: Dict[str, str] = {}
        self._pattern_file_hashes: Dict[str, str] = {}

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

        Returns deduplicated, priority-ordered matches with stable offsets.
        """
        start = time.perf_counter()
        matches: List[PatternMatch] = []

        try:
            if include_regex and self._compiled_regex:
                matches.extend(self._match_regex(text, start, budget_ms))
                if _time_exceeded(start, budget_ms):
                    return self._dedup_and_sort(matches)

            if include_keywords and self._keyword_maps:
                matches.extend(self._match_keywords(text))
                if _time_exceeded(start, budget_ms):
                    return self._dedup_and_sort(matches)

            if include_entities and self._compiled_entities:
                matches.extend(self._match_entities(text, start, budget_ms))
        except Exception as e:
            logger.exception("Pattern match failed: %s", e)

        return self._dedup_and_sort(matches)

    async def load_patterns_from_file(self, file_path: str) -> None:
        """
        Load patterns from a JSON file with JSON Schema validation.
        
        The file should conform to the eventizer_patterns_schema.json schema.
        """
        p = Path(file_path)
        if not p.exists():
            logger.warning("Pattern file not found: %s", file_path)
            return

        # Validate file against JSON Schema
        if not self._validate_patterns_file(p):
            logger.error("Pattern file validation failed, skipping load: %s", file_path)
            return

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Invalid JSON in %s: %s", file_path, e)
            return

        # Track file hash for hot reload guards
        self._pattern_file_hashes[file_path] = _safe_hash(p.read_text(encoding="utf-8"))

        # Regex patterns
        for item in data.get("regex_patterns", []) or []:
            try:
                if not item.get("enabled", True):
                    continue
                    
                pid = str(item["id"]).strip()
                pat = str(item["pattern"])
                flags = self._decode_flags(item.get("flags"))
                prio = int(item.get("priority", 100))
                conf = float(item.get("confidence", 1.0))
                whole = bool(item.get("whole_word", False))
                self._add_regex_compiled(pid, pat, flags, prio, conf, whole)
            except Exception as e:
                logger.warning("Skip bad regex pattern in %s: %s", file_path, e)

        # Keyword patterns (new structure)
        for item in data.get("keyword_patterns", []) or []:
            try:
                if not item.get("enabled", True):
                    continue
                    
                pattern_id = str(item["id"]).strip()
                keywords = [str(k) for k in (item.get("keywords") or []) if str(k).strip()]
                if pattern_id and keywords:
                    # Extract event types to create category-based keyword maps
                    event_types = item.get("event_types", [])
                    for event_type in event_types:
                        if event_type not in self._keyword_maps:
                            self._keyword_maps[event_type] = []
                        self._keyword_maps[event_type].extend(keywords)
            except Exception as e:
                logger.warning("Skip bad keyword pattern in %s: %s", file_path, e)

        # Legacy keyword dictionaries (for backward compatibility)
        for item in data.get("keyword_dictionaries", []) or []:
            try:
                name = str(item["name"]).strip()
                kws = [str(k) for k in (item.get("keywords") or []) if str(k).strip()]
                if name and kws:
                    self._keyword_maps[name] = kws
            except Exception as e:
                logger.warning("Skip bad keyword dict in %s: %s", file_path, e)

        # Entity patterns
        for item in data.get("entity_patterns", []) or []:
            try:
                if not item.get("enabled", True):
                    continue
                    
                et = str(item["entity_type"]).strip()
                patterns = item.get("patterns", [])
                
                # Process each sub-pattern
                for sub_pattern in patterns:
                    if "regex" in sub_pattern:
                        pat = str(sub_pattern["regex"])
                        flags = self._decode_flags(sub_pattern.get("flags"))
                        prio = int(item.get("priority", 100))
                        conf = float(item.get("confidence", 0.9))
                        self._add_entity_compiled(et, pat, flags, prio, conf)
            except Exception as e:
                logger.warning("Skip bad entity pattern in %s: %s", file_path, e)

        logger.info("Loaded patterns: %s", file_path)
        # Rebuild hyperscan DB if enabled
        self._build_hyperscan_db_if_needed()
        
        return True

    async def load_keywords_from_file(self, file_path: str) -> None:
        """Load keywords (one per line) into a dictionary named after the file stem."""
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
            self._keyword_maps[p.stem] = kws
            logger.info("Loaded keyword dictionary: %s (%d keywords)", p.stem, len(kws))

    def add_regex_pattern(self, pattern_id: str, pattern_text: str, flags: int = 0,
                          *, priority: int = 100, confidence: float = 1.0, whole_word: bool = False) -> bool:
        """Add a single regex pattern (runtime)."""
        try:
            self._add_regex_compiled(pattern_id, pattern_text, flags, priority, confidence, whole_word)
            self._build_hyperscan_db_if_needed()
            return True
        except Exception as e:
            logger.warning("Invalid regex pattern %s: %s", pattern_id, e)
            return False

    def add_keyword_dictionary(self, dict_name: str, keywords: List[str]) -> None:
        self._keyword_maps[dict_name] = [k for k in keywords if k]
        logger.debug("Added keyword dictionary: %s (%d keywords)", dict_name, len(keywords))

    def add_entity_pattern(self, entity_type: str, pattern_text: str, flags: int = 0,
                           *, priority: int = 100, confidence: float = 0.9) -> bool:
        try:
            self._add_entity_compiled(entity_type, pattern_text, flags, priority, confidence)
            return True
        except Exception as e:
            logger.warning("Invalid entity pattern %s: %s", entity_type, e)
            return False

    def get_pattern_count(self) -> Dict[str, int]:
        return {
            "regex_patterns": len(self._compiled_regex),
            "keyword_dictionaries": len(self._keyword_maps),
            "entity_patterns": len(self._compiled_entities),
            "hyperscan_groups": 1 if self._hs_db is not None else 0,
        }

    def clear_patterns(self) -> None:
        self._compiled_regex.clear()
        self._compiled_entities.clear()
        self._keyword_maps.clear()
        self._hs_db = None
        self._hs_ids.clear()
        logger.info("Cleared all patterns")

    # -----------------------------
    # Internal: compilation
    # -----------------------------
    def _add_regex_compiled(
        self, pattern_id: str, pattern_text: str, flags: int, priority: int, confidence: float, whole_word: bool
    ) -> None:
        if whole_word:
            pattern_text = _word_wrap(pattern_text)

        engine_used = "re"
        compiled: Any
        if self.config.enable_re2 and _has_re2:
            try:
                compiled = re2.compile(pattern_text, flags)
                engine_used = "re2"
            except Exception as e:
                logger.debug("re2 compile failed for %s, fallback to re: %s", pattern_id, e)
                compiled = re.compile(pattern_text, flags)
        else:
            compiled = re.compile(pattern_text, flags)

        self._compiled_regex[pattern_id] = CompiledRegex(
            pattern_id=pattern_id,
            engine=engine_used,
            pattern=compiled,
            flags=flags,
            priority=priority,
            confidence=confidence,
            whole_word=whole_word,
        )

    def _add_entity_compiled(self, entity_type: str, pattern_text: str, flags: int,
                             priority: int, confidence: float) -> None:
        engine_used = "re"
        compiled: Any
        if self.config.enable_re2 and _has_re2:
            try:
                compiled = re2.compile(pattern_text, flags)
                engine_used = "re2"
            except Exception as e:
                logger.debug("re2 entity compile failed for %s, fallback to re: %s", entity_type, e)
                compiled = re.compile(pattern_text, flags)
        else:
            compiled = re.compile(pattern_text, flags)

        self._compiled_entities[entity_type] = CompiledRegex(
            pattern_id=f"entity:{entity_type}",
            engine=engine_used,
            pattern=compiled,
            flags=flags,
            priority=priority,
            confidence=confidence,
            whole_word=False,
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
            # Best-effort heuristic: skip patterns with capture groups (?P<...) etc.
            if "(" in pat and not r"\(" in pat:
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
    def _match_regex(self, text: str, start_ts: float, budget_ms: Optional[float]) -> List[PatternMatch]:
        out: List[PatternMatch] = []

        # Fast path: Hyperscan multi-scan to get candidate spans, then confirm/expand via native engine if needed.
        if self._hs_db is not None and self._hs_ids:
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
                            out.append(PatternMatch(
                                pattern_id=pid,
                                pattern_type="regex",
                                matched_text=text[ms:me],
                                start_pos=ms,
                                end_pos=me,
                                confidence=max(0.0, min(1.0, comp.confidence)),
                                metadata={
                                    "engine": "hyperscan+%s" % comp.engine,
                                    "priority": comp.priority,
                                    "groups": m.groups(),
                                },
                            ))
                    except Exception:
                        # Fallback: trust HS span
                        out.append(PatternMatch(
                            pattern_id=pid,
                            pattern_type="regex",
                            matched_text=text[s:e],
                            start_pos=s,
                            end_pos=e,
                            confidence=max(0.0, min(1.0, comp.confidence)),
                            metadata={"engine": "hyperscan", "priority": comp.priority},
                        ))
                if _time_exceeded(start_ts, budget_ms):
                    return out
            except Exception as e:
                logger.debug("Hyperscan scan failed, fallback to native regex: %s", e)

        # Native per-pattern scan
        for pid, comp in self._compiled_regex.items():
            try:
                for m in comp.pattern.finditer(text):
                    out.append(PatternMatch(
                        pattern_id=pid,
                        pattern_type="regex",
                        matched_text=m.group(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                        confidence=max(0.0, min(1.0, comp.confidence)),
                        metadata={"engine": comp.engine, "priority": comp.priority, "groups": m.groups()},
                    ))
                if _time_exceeded(start_ts, budget_ms):
                    break
            except Exception as e:
                logger.warning("Regex match error for %s: %s", pid, e)
        return out

    def _match_keywords(self, text: str) -> List[PatternMatch]:
        """Match keywords using Aho-Corasick if available, fallback to simple search."""
        if self._use_aho_corasick and self._keyword_matchers:
            # Use Aho-Corasick for efficient keyword matching
            import asyncio
            try:
                # Run async method in sync context
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're in an async context, we need to handle this differently
                    # For now, fall back to simple matching
                    return self._match_keywords_simple(text)
                else:
                    return loop.run_until_complete(self.match_keywords_aho_corasick(text))
            except Exception as e:
                logger.warning(f"Aho-Corasick keyword matching failed, falling back to simple: {e}")
                return self._match_keywords_simple(text)
        else:
            return self._match_keywords_simple(text)
    
    def _match_keywords_simple(self, text: str) -> List[PatternMatch]:
        """Simple keyword matching fallback."""
        out: List[PatternMatch] = []
        tl = text.lower()

        for dict_name, keywords in self._keyword_maps.items():
            for kw in keywords:
                if not kw:
                    continue
                needle = kw.lower()
                start = 0
                while True:
                    pos = tl.find(needle, start)
                    if pos < 0:
                        break
                    end = pos + len(needle)
                    out.append(PatternMatch(
                        pattern_id=f"{dict_name}:{kw}",
                        pattern_type="keyword",
                        matched_text=text[pos:end],
                        start_pos=pos,
                        end_pos=end,
                        confidence=1.0,
                        metadata={"dictionary": dict_name, "keyword": kw, "priority": 80, "engine": "simple"},
                    ))
                    start = pos + 1  # allow overlaps for robustness
        return out

    def _match_entities(self, text: str, start_ts: float, budget_ms: Optional[float]) -> List[PatternMatch]:
        out: List[PatternMatch] = []
        for etype, comp in self._compiled_entities.items():
            try:
                for m in comp.pattern.finditer(text):
                    out.append(PatternMatch(
                        pattern_id=f"entity:{etype}",
                        pattern_type="entity",
                        matched_text=m.group(),
                        start_pos=m.start(),
                        end_pos=m.end(),
                        confidence=max(0.0, min(1.0, comp.confidence)),
                        metadata={"entity_type": etype, "engine": comp.engine, "priority": comp.priority, "groups": m.groups()},
                    ))
                if _time_exceeded(start_ts, budget_ms):
                    break
            except Exception as e:
                logger.warning("Entity match error for %s: %s", etype, e)
        return out

    # -----------------------------
    # Internal: utilities
    # -----------------------------
    def _dedup_and_sort(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Deduplicate overlaps (prefer higher confidence, then higher priority; keep deterministic order)."""
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
                # Prefer higher confidence; if tie, prefer lower 'priority' in metadata (lower = higher priority)
                prev_prio = int(prev.metadata.get("priority", 100))
                m_prio = int(m.metadata.get("priority", 100))
                if (m.confidence, -m_prio) > (prev.confidence, -prev_prio):
                    by_span[key] = m

        deduped = list(by_span.values())
        # Sort by: start_pos, then end_pos, then descending confidence, then priority
        deduped.sort(key=lambda m: (m.start_pos, m.end_pos, -m.confidence, int(m.metadata.get("priority", 100))))
        return deduped

    def _decode_flags(self, flags: Optional[Iterable[str]]) -> int:
        if not flags:
            return 0
        acc = 0
        for f in flags:
            try:
                acc |= getattr(re, f.upper())
            except Exception:
                logger.debug("Unknown regex flag: %s", f)
        return acc

    async def _load_configured_patterns(self) -> None:
        # JSON pattern files
        for pf in self.config.pattern_files:
            try:
                await self.load_patterns_from_file(pf)
            except Exception as e:
                logger.error("Failed loading pattern file %s: %s", pf, e)

        # Keyword lists (one per line)
        for kf in self.config.keyword_dictionaries:
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
    # Aho-Corasick keyword matching
    # -----------------------------
    def _build_aho_corasick_matchers(self) -> None:
        """Build Aho-Corasick matchers for keyword patterns."""
        if not self._use_aho_corasick:
            return
        
        for category, keywords in self._keyword_maps.items():
            if not keywords:
                continue
            
            # Create matcher for this category
            matcher = create_keyword_matcher(
                case_sensitive=False,  # Default to case-insensitive
                whole_word=True       # Default to whole-word matching
            )
            
            # Add keywords to matcher
            for i, keyword in enumerate(keywords):
                pattern_id = f"{category}_keyword_{i}"
                matcher.add_pattern(
                    keyword,
                    pattern_id,
                    category=category,
                    keyword=keyword,
                    priority=50,  # Default priority
                    confidence=0.7  # Default confidence
                )
            
            # Build the matcher
            matcher.build()
            self._keyword_matchers[category] = matcher
            
            logger.debug(f"Built Aho-Corasick matcher for {category} with {len(keywords)} keywords")
    
    async def match_keywords_aho_corasick(self, text: str) -> List[PatternMatch]:
        """Match keywords using Aho-Corasick algorithm."""
        matches = []
        
        for category, matcher in self._keyword_matchers.items():
            try:
                for match in matcher.search(text):
                    # Convert Aho-Corasick match to PatternMatch
                    pattern_match = PatternMatch(
                        pattern_id=match.pattern_id,
                        pattern_type="keyword",
                        start=match.start,
                        end=match.end,
                        text=match.text,
                        confidence=match.value.get("confidence", 0.7),
                        priority=match.value.get("priority", 50),
                        whole_word=match.value.get("whole_word", True),
                        metadata={
                            "category": category,
                            "keyword": match.value.get("keyword", match.pattern),
                            "engine": "aho_corasick"
                        }
                    )
                    matches.append(pattern_match)
            except Exception as e:
                logger.warning(f"Aho-Corasick matching failed for category {category}: {e}")
        
        return matches
    
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

    # -----------------------------
    # Pattern compilation helpers
    # -----------------------------
    def _add_regex_compiled(self, pattern_id: str, pattern: str, flags: int, 
                           priority: int, confidence: float, whole_word: bool) -> None:
        """Add a compiled regex pattern."""
        try:
            if _has_re2 and self.config.enable_re2:
                compiled = re2.compile(pattern, flags)
                engine = "re2"
            else:
                compiled = re.compile(pattern, flags)
                engine = "re"
            
            self._compiled_regex[pattern_id] = CompiledRegex(
                pattern_id=pattern_id,
                pattern=compiled,
                engine=engine,
                priority=priority,
                confidence=confidence,
                whole_word=whole_word
            )
        except Exception as e:
            logger.warning(f"Failed to compile regex pattern {pattern_id}: {e}")
    
    def _add_entity_compiled(self, entity_type: str, pattern: str, flags: int,
                            priority: int, confidence: float) -> None:
        """Add a compiled entity pattern."""
        try:
            if _has_re2 and self.config.enable_re2:
                compiled = re2.compile(pattern, flags)
                engine = "re2"
            else:
                compiled = re.compile(pattern, flags)
                engine = "re"
            
            self._compiled_entities[entity_type] = CompiledRegex(
                pattern_id=entity_type,
                pattern=compiled,
                engine=engine,
                priority=priority,
                confidence=confidence,
                whole_word=False
            )
        except Exception as e:
            logger.warning(f"Failed to compile entity pattern {entity_type}: {e}")
    
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
    # Default seed patterns
    # -----------------------------
    def _load_default_patterns(self) -> None:
        """Default patterns covering hotel ops baseline (safe to extend)."""
        # Regex: event types
        default_regex = [
            ("hvac_temperature",
             r"(?:temperature|temp|hvac|ac|heating|cooling)\s*(?:is|at|reaches?|drops?|rises?)\s*(\d+)",
             re.IGNORECASE, 50, 1.0, False),
            ("hvac_issue",
             r"(?:hvac|air\s*conditioning|heating|cooling|thermostat)\s*(?:problem|issue|broken|not\s*working|malfunction)",
             re.IGNORECASE, 60, 1.0, False),
            ("security_alert",
             r"(?:security|alarm|breach|intrusion|unauthorized|suspicious)\s*(?:alert|warning|detected|found)",
             re.IGNORECASE, 60, 1.0, False),
            ("emergency",
             r"(?:emergency|urgent|critical|immediate|asap|help|assistance)\s*(?:needed|required|situation)",
             re.IGNORECASE, 40, 1.0, False),
            ("maintenance",
             r"(?:maintenance|repair|fix|service|check|inspect)\s*(?:needed|required|scheduled|due)",
             re.IGNORECASE, 70, 1.0, False),
            ("vip_access",
             r"(?:vip|executive|presidential\s*suite|ceo|director)\s*(?:access|visit|arrival|departure)",
             re.IGNORECASE, 30, 1.0, False),
            ("allergen_alert",
             r"(?:allergen|allergy|peanut|nuts|dairy|gluten|shellfish)",
             re.IGNORECASE, 55, 1.0, False),
            ("luggage_chain",
             r"(?:luggage|baggage|bag).*(?:wrong\s*room|misdeliver|lost|mishandled)",
             re.IGNORECASE, 55, 1.0, False),
        ]
        for pid, pat, flags, prio, conf, whole in default_regex:
            try:
                self._add_regex_compiled(pid, pat, flags, prio, conf, whole)
            except Exception as e:
                logger.debug("Skip default regex %s: %s", pid, e)

        # Keywords
        self._keyword_maps["hvac"] = [
            "temperature", "thermostat", "hvac", "air conditioning", "heating", "cooling",
            "ventilation", "fan", "filter", "compressor"
        ]
        self._keyword_maps["security"] = [
            "security", "alarm", "breach", "intrusion", "unauthorized", "suspicious",
            "camera", "keycard", "badge", "perimeter"
        ]
        self._keyword_maps["emergency"] = [
            "emergency", "urgent", "critical", "immediate", "asap", "help", "assistance",
            "fire", "medical", "evacuation", "alert", "warning"
        ]

        # Entities
        default_entities = [
            ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.IGNORECASE, 80, 0.9),
            ("phone", r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b", re.IGNORECASE, 80, 0.9),
            ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b", re.IGNORECASE, 90, 0.9),
            ("url", r"https?://[^\s<>'\"{}|\\^`[\]]+", re.IGNORECASE, 90, 0.9),
            ("room_number", r"\b(?:room|rm|suite|office)\s*#?\s*[A-Za-z0-9-]+\b", re.IGNORECASE, 75, 0.9),
            ("temperature", r"\b\d+(?:\.\d+)?\s*(?:°[CF]|degrees?)\b", re.IGNORECASE, 70, 0.9),
        ]
        for et, pat, flags, prio, conf in default_entities:
            try:
                self._add_entity_compiled(et, pat, flags, prio, conf)
            except Exception as e:
                logger.debug("Skip default entity %s: %s", et, e)
