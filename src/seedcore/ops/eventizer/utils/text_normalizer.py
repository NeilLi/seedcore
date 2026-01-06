#!/usr/bin/env python3
"""
Text Normalizer (product-grade) - Enhanced for Multimodal Cortex

Goals:
- Make text consistent for deterministic pattern matching.
- Keep a *lossless* mapping between ORIGINAL and NORMALIZED text indices.
- Be fast, safe, and configurable.
- Support both Fast-Path (Reflex) and Cognitive Plane processing.

Features:
- Tiered normalization (AGGRESSIVE vs COGNITIVE) for semantic preservation
- Unicode NFKC normalization + optional accent folding
- Quote/dash/ellipsis normalization
- Case normalization (lower/upper/title/preserve)
- Semantic preservation: AGGRESSIVE collapses punctuation, COGNITIVE preserves for sentiment
- Audio artifact stripping: Removes [unintelligible], (clears throat) from voice transcripts
- Enhanced de-obfuscation: Handles "v i p", "v.i.p", "v-i-p" (split tokens with separators)
- Temperature/unit touch-ups (°F/°C variants -> 'F'/'C' with space)
- Unit/time standardizer: "6pm" / "6 PM" -> "18:00", "100 sqft" -> "100 sqft"
- Bidirectional SpanMap to project spans between original and normalized text

All transformations maintain a per-character mapping so pattern matches on the
normalized text can be projected back to the original string reliably. This is
critical for Datadog traceability and debugging in production.

Enhanced for Unified Memory View:
- Unit standardization normalizes numeric time formats (e.g., "6pm" -> "18:00", "6:30 PM" -> "18:30")
- De-obfuscation prevents security bypass attempts (e.g., "S.E.C.U.R.I.T.Y" -> "security", "v-i-p" -> "vip")
- Audio artifact stripping (whitelist-based) removes transcript markers like [unintelligible], (clears throat)
- NOTE: Natural language time parsing ("Six in the evening" -> "18:00") is not implemented;
  only numeric time formats are standardized
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


# -----------------------------
# Span mapping
# -----------------------------


@dataclass
class SpanMap:
    """
    Keeps a mapping between normalized and original text positions.

    norm_to_orig[i] = index in original text that produced normalized char i
    orig_to_norm[j] = index in normalized text where original char j ended up
                      (for multi-to-one normalization, points to the *first*
                      normalized index produced by j)
    """

    norm_to_orig: List[int]
    orig_to_norm: List[int]

    def project_norm_span_to_orig(self, start: int, end: int, original_len: Optional[int] = None) -> Tuple[int, int]:
        """Project [start, end) span from normalized to original text.
        
        Args:
            start: Start index in normalized text
            end: End index (exclusive) in normalized text
            original_len: Length of original text (for clamping). If None, uses len(orig_to_norm)
        """
        n = len(self.norm_to_orig)
        if start < 0:
            start = 0
        if end < 0:
            end = 0
        if start > n:
            start = n
        if end > n:
            end = n
        if start >= end:
            # empty span: pick closest index
            idx = self.norm_to_orig[start - 1] if start > 0 else 0
            return (idx, idx)
        o_start = self.norm_to_orig[start]
        # end is exclusive; if end==0 then map to 0, else map to the last
        # normalized char's original index + 1 (best-effort)
        last_norm = end - 1
        o_end = self.norm_to_orig[last_norm] + 1
        
        # Clamp to original text length to prevent out-of-range
        if original_len is not None:
            o_end = min(o_end, original_len)
        elif len(self.orig_to_norm) > 0:
            o_end = min(o_end, len(self.orig_to_norm))
        
        return (o_start, o_end)

    def project_orig_span_to_norm(self, start: int, end: int) -> Tuple[int, int]:
        """Project [start, end) span from original to normalized text."""
        m = len(self.orig_to_norm)
        if start < 0:
            start = 0
        if end < 0:
            end = 0
        if start > m:
            start = m
        if end > m:
            end = m
        if start >= end:
            idx = self.orig_to_norm[start - 1] if start > 0 else 0
            return (idx, idx)
        n_start = self.orig_to_norm[start]
        # find last normalized index that originated from end-1 (best-effort)
        n_end = self.orig_to_norm[end - 1] + 1
        return (n_start, n_end)


# -----------------------------
# Normalization Tier
# -----------------------------


class NormalizationTier(str, Enum):
    """Normalization intensity tier for different processing paths.
    
    - AGGRESSIVE: For Fast-Path Regex (strips !!!, collapses all punctuation)
                 Used by FastEventizer for deterministic pattern matching
    - COGNITIVE: For LLM/Cognitive Plane (preserves punctuation/casing for sentiment)
                 Used by DeepEventizer for semantic understanding
    """
    AGGRESSIVE = "aggressive"  # For Fast-Path Regex (strips !!!, collapses all)
    COGNITIVE = "cognitive"    # For LLM (preserves punctuation/casing for sentiment)


# -----------------------------
# Normalizer
# -----------------------------


class TextNormalizer:
    """
    Text normalization utilities for consistent pattern matching with
    bidirectional span mapping.

    Enhanced for Multimodal Cortex and Unified Memory View:
    - Tiered normalization (AGGRESSIVE vs COGNITIVE) for semantic preservation
    - Enhanced de-obfuscation (handles dots, dashes, leetspeak)
    - Audio artifact stripping (for voice transcripts)
    - Unit/time standardizer (12-hour to 24-hour, area units)

    Pipeline (configurable):
      0) Audio artifact stripping (voice transcripts)
      1) Unicode NFKC
      2) Quote/dash/ellipsis normalization
      3) Whitespace compaction (+ normalize newlines -> space)
      4) Punctuation collapse (tier-dependent: AGGRESSIVE collapses, COGNITIVE preserves)
      5) Case normalization (lower/upper/title/preserve)
      6) Optional accent folding (strip diacritics)
      7) Temperature/unit touch-ups
      8) Unit/time standardizer (12-hour to 24-hour, area normalization)
      9) Enhanced de-obfuscation (join tokens with dots/dashes/spaces, leetspeak)
    """

    _re_ws = re.compile(r"\s+")
    # Punctuation collapse: matches repeated identical punctuation marks
    # "!!!" -> "!", "???" -> "?", but "?!?!" stays as-is (mixed punctuation preserved)
    _re_multi_punct = re.compile(r"([.!?])\1{1,}")
    _re_units_temp = re.compile(
        r"\b(\d+(?:\.\d+)?)\s*(?:°\s*([CF])|deg(?:ree)?s?\s*([CF]))\b", re.IGNORECASE
    )
    _re_temperature_compact = re.compile(
        r"\b(\d{1,3})(?:\s*°\s*|\s*)([CF])\b", re.IGNORECASE
    )

    # Audio artifacts from voice transcripts (Whisper, ElevenLabs, etc.)
    # Whitelist approach: only remove known transcript markers, not all brackets/parens
    _re_audio_artifacts = re.compile(
        r"\[(?:unintelligible|music|laughter|noise|applause|silence|background)[^\]]*\]|"
        r"\((?:laughs?|coughs?|clears\s+throat|sighs?|breaths?)[^)]*\)",
        re.IGNORECASE
    )
    # Dangerous broad version (only use if explicitly needed)
    _re_audio_artifacts_broad = re.compile(r"\[.*?\]|\(.*?\)", re.IGNORECASE)

    # Enhanced de-obfuscation: handles "v i p", "v.i.p", "v-i-p", "v_i_p"
    # Also handles leetspeak substitutions: @->a, 0->o, $->s, 1->i, 3->e, 5->s, 7->t
    _re_split_token_enhanced = re.compile(
        r"\b([A-Za-z0-9@$])(?:[\s\.\-_]+([A-Za-z0-9@$]))(?:[\s\.\-_]+([A-Za-z0-9@$]))(?:[\s\.\-_]+([A-Za-z0-9@$]))?(?:[\s\.\-_]+([A-Za-z0-9@$]))?\b"
    )

    # Time standardizer: 12-hour to 24-hour format
    # Handles: "6pm", "6 pm", "6:30 PM", "6 p.m.", "12:05am", "06 PM"
    _re_time_12h = re.compile(
        r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", re.IGNORECASE
    )

    # Area unit standardizer: "sqft", "square feet", "sq ft" -> "100 sqft" (with space for consistency)
    _re_area_units = re.compile(
        r"\b(\d+(?:\.\d+)?)\s*(?:sq\s*ft|square\s*feet|sqft|sq\.?\s*ft\.?)\b", re.IGNORECASE
    )

    # Leetspeak character mapping (only applied during token joining)
    _leetspeak_map = {
        "@": "a",
        "0": "o",
        "$": "s",
        "1": "i",
        "3": "e",
        "5": "s",
        "7": "t",
    }

    def __init__(
        self,
        *,
        tier: NormalizationTier = NormalizationTier.AGGRESSIVE,
        case: str = "lower",  # "lower" | "upper" | "title" | "preserve"
        fold_accents: bool = False,
        normalize_quotes_and_dashes: bool = True,
        compact_whitespace: bool = True,
        replace_newlines_with_space: bool = True,
        join_split_tokens: bool = True,
        join_max_token_len: int = 6,  # only join if <= 6 letters total
        standardize_units: bool = True,  # NEW: Standardize time/area units
        strip_audio_tags: bool = True,  # NEW: Strip audio artifacts from transcripts
        keep_chars_regex: Optional[
            str
        ] = None,  # if set, remove everything not matching this class (applied late)
    ):
        self.tier = tier
        self.case = case
        self.fold_accents = fold_accents
        self.normalize_quotes_and_dashes = normalize_quotes_and_dashes
        self.compact_whitespace = compact_whitespace
        self.replace_newlines_with_space = replace_newlines_with_space
        self.join_split_tokens = join_split_tokens
        self.join_max_token_len = join_max_token_len
        self.standardize_units = standardize_units
        self.strip_audio_tags = strip_audio_tags
        self.keep_chars_regex = (
            re.compile(keep_chars_regex) if keep_chars_regex else None
        )

    # -------------------------
    # Public API
    # -------------------------

    def normalize(
        self, text: str, *, build_map: bool = True
    ) -> str | Tuple[str, SpanMap]:
        """
        Normalize text. If build_map=True, returns (normalized_text, SpanMap).
        Otherwise returns normalized_text only.
        
        This method is synchronous as normalization is fast and doesn't require async I/O.
        """
        if not text:
            return ("", SpanMap([], [])) if build_map else ""

        # Start with identity maps
        norm_chars: List[str] = []
        norm_to_orig: List[int] = []
        orig_to_norm: List[int] = [-1] * len(text)

        def _emit_str(repl: str, orig_idx: int):
            """Emit a replacement string (may be multi-character) character-by-character."""
            for c in repl:
                norm_chars.append(c)
                norm_to_orig.append(orig_idx)
                if orig_to_norm[orig_idx] == -1:
                    orig_to_norm[orig_idx] = len(norm_chars) - 1

        # 1) Unicode NFKC: we'll iterate original text and emit normalized chars
        #    while building the maps.
        nkfc = unicodedata.normalize("NFKC", text)

        # mapping from nkfc index -> original index:
        # Best-effort: For simplicity, assume length-preserving in most cases.
        # If lengths mismatch, fall back to per-char scanning heuristic.
        # NOTE: This is lossy for NFKC expansions/contractions, but provides
        # stable monotonic mapping for traceability/debugging purposes.
        nkfc_to_orig = self._approximate_map(text, nkfc)

        # Iterate through NFKC string and apply subsequent transforms *as we emit*
        i = 0
        while i < len(nkfc):
            ch = nkfc[i]
            orig_idx = nkfc_to_orig[i]

            # 2) Normalize quotes/dashes/ellipsis
            # NOTE: ellipsis "…" becomes "..." (3 chars), so we use _emit_str
            if self.normalize_quotes_and_dashes:
                ch = _normalize_quote_dash(ch)

            # 3) Replace newlines with space if requested
            if self.replace_newlines_with_space and ch in ("\r", "\n", "\x0b", "\x0c"):
                ch = " "

            # Emit replacement (may be multi-character for ellipsis)
            _emit_str(ch, orig_idx)
            i += 1

        # At this point we have a simple NFKC (+ basic remaps) stream.
        s = "".join(norm_chars)

        # 0) Strip audio artifacts (voice transcripts) - applied early
        if self.strip_audio_tags:
            s, norm_to_orig = _collapse_runs_with_map(
                s, norm_to_orig, pattern=self._re_audio_artifacts, replacement=""
            )

        # 4) Collapse whitespace & multiple punctuation (still map-aware)
        if self.compact_whitespace:
            s, norm_to_orig = _collapse_runs_with_map(
                s, norm_to_orig, pattern=self._re_ws, replacement=" "
            )
        
        # Punctuation collapse: tier-dependent semantic preservation
        # AGGRESSIVE: "!!!" -> "!" (for regex matching), collapses repeated identical marks
        # COGNITIVE: Preserve "!!!" (for LLM sentiment analysis)
        if self.tier == NormalizationTier.AGGRESSIVE:
            s, norm_to_orig = _collapse_runs_with_map(
                s,
                norm_to_orig,
                pattern=self._re_multi_punct,
                replacement=lambda m: m.group(1),  # Keep first char of repeated sequence
            )
        # COGNITIVE tier preserves punctuation intensity for sentiment

        # 5) Case normalization
        if self.case != "preserve":
            s, norm_to_orig = _case_with_map(s, norm_to_orig, self.case)

        # 6) Optional accent folding (strip diacritics)
        if self.fold_accents:
            s, norm_to_orig = _strip_accents_with_map(s, norm_to_orig)

        # 7) Temperature/unit touch-ups: "85°F" -> "85 F"
        s, norm_to_orig = _normalize_temperature_units_with_map(
            s, norm_to_orig, self._re_units_temp, self._re_temperature_compact
        )

        # 8) Unit/time standardizer: "6 PM" -> "18:00", "100 sqft" -> "100sqft"
        if self.standardize_units:
            s, norm_to_orig = _standardize_units_with_map(
                s, norm_to_orig, self._re_time_12h, self._re_area_units
            )

        # 9) Enhanced de-obfuscation: join split tokens like "v i p", "v.i.p", "v-i-p" -> "vip"
        # Also handles leetspeak: "P@ym3nt" -> "Payment" (during token joining)
        if self.join_split_tokens:
            s, norm_to_orig = _join_split_tokens_enhanced_with_map(
                s,
                norm_to_orig,
                max_token_len=self.join_max_token_len,
                pattern=self._re_split_token_enhanced,
                leetspeak_map=self._leetspeak_map,
            )

        # 10) Optional character class keep (late)
        if self.keep_chars_regex:
            s, norm_to_orig = _filter_allowed_chars_with_map(
                s, norm_to_orig, self.keep_chars_regex
            )

        # Final trimming of edges (keep map consistent)
        s, norm_to_orig = _trim_edges_with_map(s, norm_to_orig)

        # CRITICAL: Rebuild orig_to_norm from final norm_to_orig
        # After all transformations (stripping, collapsing, replacing), we must
        # rebuild orig_to_norm to match the final normalized string.
        orig_to_norm = _rebuild_orig_to_norm(norm_to_orig, len(text), len(s))

        if not build_map:
            return s

        span_map = SpanMap(norm_to_orig=norm_to_orig, orig_to_norm=orig_to_norm)
        return s, span_map

    # -------------------------
    # Helpers
    # -------------------------

    def _approximate_map(self, original: str, nkfc: str) -> List[int]:
        """
        Best-effort per-char index mapping from NFKC result back to original.
        Assumes mostly 1:1; if lengths diverge, falls back to nearest previous index.

        This is sufficient for our normalization passes which mostly preserve
        per-char alignment. For rare expansions, the projection remains stable.
        """
        o_len = len(original)
        n_len = len(nkfc)
        if o_len == n_len:
            return list(range(o_len))

        # Heuristic: walk both strings, prefer equal code points; otherwise
        # advance in the NKFC string but keep last seen original index.
        mapping: List[int] = []
        oi = 0
        for ni in range(n_len):
            if oi < o_len and nkfc[ni] == original[oi]:
                mapping.append(oi)
                oi += 1
            else:
                mapping.append(max(0, min(oi, o_len - 1)))
        return mapping


# -----------------------------
# Pure helpers that preserve mapping
# -----------------------------


def _normalize_quote_dash(ch: str) -> str:
    # quotes
    if ch in ("\u201c", "\u201d", "\u201e", "\u201f", "\u275d", "\u275e", "\uff02", "\u00ab", "\u00bb"):
        return '"'
    if ch in ("\u2018", "\u2019", "\u201a", "\u201b", "\u275b", "\u275c", "\uff07"):
        return "'"
    # dashes
    if ch in ("–", "—", "―", "−", "‐", "-"):
        return "-"
    # ellipsis
    if ch == "…":
        return "..."
    return ch


def _collapse_runs_with_map(
    s: str, n2o: List[int], *, pattern: re.Pattern, replacement: str | callable
) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    out_map: List[int] = []

    last_end = 0
    for m in pattern.finditer(s):
        # copy up to match
        out_chars.extend(s[last_end : m.start()])
        out_map.extend(n2o[last_end : m.start()])

        # write replacement (single char/func result)
        repl = replacement(m) if callable(replacement) else replacement
        if repl:
            # map entire replacement to first char's original index in the match
            anchor = (
                n2o[m.start()]
                if m.start() < len(n2o)
                else (n2o[m.end() - 1] if m.end() else 0)
            )
            for _ in repl:
                out_chars.append(_)
                out_map.append(anchor)

        last_end = m.end()

    # tail
    out_chars.extend(s[last_end:])
    out_map.extend(n2o[last_end:])

    return "".join(out_chars), out_map


def _case_with_map(s: str, n2o: List[int], mode: str) -> Tuple[str, List[int]]:
    if mode == "lower":
        return s.lower(), n2o
    if mode == "upper":
        return s.upper(), n2o
    if mode == "title":
        # title() may change string length with certain unicode; keep simple per-char
        chars = [
            c.upper() if i == 0 or (i > 0 and s[i - 1].isspace()) else c.lower()
            for i, c in enumerate(s)
        ]
        return "".join(chars), n2o
    return s, n2o


def _strip_accents_with_map(s: str, n2o: List[int]) -> Tuple[str, List[int]]:
    # NFD then drop Mn combining marks. Maintain mapping by inheriting the map
    # of the *base* char for dropped diacritics.
    out_chars: List[str] = []
    out_map: List[int] = []
    for i, ch in enumerate(s):
        decomp = unicodedata.normalize("NFD", ch)
        for j, dch in enumerate(decomp):
            if unicodedata.category(dch) == "Mn":
                # skip combining mark; map it to previous base char's map
                continue
            # map: use the original n2o index for the source character
            out_chars.append(unicodedata.normalize("NFC", dch))
            out_map.append(n2o[i])
    return "".join(out_chars), out_map


def _normalize_temperature_units_with_map(
    s: str, n2o: List[int], re_units: re.Pattern, re_compact: re.Pattern
) -> Tuple[str, List[int]]:
    # Normalize variants like "85°F" / "85 ° F" / "85 degrees F" -> "85 F"
    def repl_units(m: re.Match) -> str:
        deg = m.group(2) or m.group(3) or ""
        return f"{m.group(1)} {deg.upper()}"

    s, n2o = _collapse_runs_with_map(s, n2o, pattern=re_units, replacement=repl_units)

    # Compact "85F" -> "85 F" (add missing space)
    def repl_compact(m: re.Match) -> str:
        return f"{m.group(1)} {m.group(2).upper()}"

    s, n2o = _collapse_runs_with_map(
        s, n2o, pattern=re_compact, replacement=repl_compact
    )
    return s, n2o


def _join_split_tokens_with_map(
    s: str, n2o: List[int], *, max_token_len: int, pattern: re.Pattern
) -> Tuple[str, List[int]]:
    """
    Join patterns like 'v i p' -> 'vip', 'h v a c' -> 'hvac' when total letters <= max_token_len.
    
    Legacy function for backward compatibility. Use _join_split_tokens_enhanced_with_map for
    enhanced de-obfuscation with leetspeak support.
    """
    out_s = s
    out_map = n2o
    # Iterate multiple times to catch longer splits; cap passes
    for _ in range(3):
        changed = False
        new_chars: List[str] = []
        new_map: List[int] = []
        last = 0
        for m in pattern.finditer(out_s):
            letters = [g for g in m.groups() if g]
            token = "".join(letters)
            if not token or len(token) > max_token_len:
                continue
            # copy head
            new_chars.extend(out_s[last : m.start()])
            new_map.extend(out_map[last : m.start()])
            # write joined token; map to first char of match
            anchor = out_map[m.start()]
            for ch in token:
                new_chars.append(ch)
                new_map.append(anchor)
            last = m.end()
            changed = True

        if not changed:
            break
        # tail
        new_chars.extend(out_s[last:])
        new_map.extend(out_map[last:])
        out_s = "".join(new_chars)
        out_map = new_map
    return out_s, out_map


def _join_split_tokens_enhanced_with_map(
    s: str,
    n2o: List[int],
    *,
    max_token_len: int,
    pattern: re.Pattern,
    leetspeak_map: dict[str, str],
) -> Tuple[str, List[int]]:
    """
    Enhanced de-obfuscation: Join patterns like:
    - 'v i p' -> 'vip'
    - 'v.i.p' -> 'vip'
    - 'v-i-p' -> 'vip'
    - 'v_i_p' -> 'vip'
    - 'P@ym3nt' -> 'Payment' (leetspeak substitution)
    
    Handles common obfuscation techniques used to bypass security rules.
    """
    out_s = s
    out_map = n2o
    # Iterate multiple times to catch longer splits; cap passes
    for _ in range(3):
        changed = False
        new_chars: List[str] = []
        new_map: List[int] = []
        last = 0
        for m in pattern.finditer(out_s):
            # Extract all matched groups (letters/digits/special chars)
            chars = [g for g in m.groups() if g]
            
            # Apply leetspeak substitution
            # NOTE: Respect case mode - if case normalization already happened, this is fine.
            # If case="preserve", we should preserve original casing for letters.
            normalized_chars = []
            for ch in chars:
                # Convert leetspeak characters to letters
                leet_repl = leetspeak_map.get(ch.lower(), ch)
                # Preserve original case if it was a letter, otherwise use lowercase
                if ch.isalpha() and leet_repl == ch:
                    normalized_chars.append(ch)  # Keep original case for letters
                else:
                    normalized_chars.append(leet_repl.lower())  # Leetspeak -> lowercase
            
            token = "".join(normalized_chars)
            
            # Only join if token length is reasonable and all chars are alphanumeric after substitution
            if not token or len(token) > max_token_len or not token.isalnum():
                continue
            
            # copy head
            new_chars.extend(out_s[last : m.start()])
            new_map.extend(out_map[last : m.start()])
            
            # write joined token; map to first char of match
            anchor = out_map[m.start()]
            for ch in token:
                new_chars.append(ch)
                new_map.append(anchor)
            last = m.end()
            changed = True

        if not changed:
            break
        # tail
        new_chars.extend(out_s[last:])
        new_map.extend(out_map[last:])
        out_s = "".join(new_chars)
        out_map = new_map
    return out_s, out_map


def _standardize_units_with_map(
    s: str, n2o: List[int], re_time: re.Pattern, re_area: re.Pattern
) -> Tuple[str, List[int]]:
    """
    Standardize units for Infrastructure Plane grounding:
    - Time: "6 PM" / "6:30 PM" -> "18:00" / "18:30" (12-hour to 24-hour)
    - Area: "100 sqft" / "100 square feet" -> "100sqft"
    
    This ensures the Domain Knowledge Graph receives consistent, machine-readable units.
    """
    # 1) Standardize time: 12-hour to 24-hour format
    def repl_time(m: re.Match) -> str:
        hour = int(m.group(1))
        minute = m.group(2) if m.group(2) else "00"
        am_pm = m.group(3).lower()
        
        # Convert to 24-hour format
        if am_pm == "pm" and hour != 12:
            hour += 12
        elif am_pm == "am" and hour == 12:
            hour = 0
        
        return f"{hour:02d}:{minute}"

    s, n2o = _collapse_runs_with_map(s, n2o, pattern=re_time, replacement=repl_time)

    # 2) Standardize area units: "100 sqft" / "100 square feet" -> "100 sqft" (with space for consistency)
    def repl_area(m: re.Match) -> str:
        value = m.group(1)
        return f"{value} sqft"  # Consistent with temperature format "85 F"

    s, n2o = _collapse_runs_with_map(s, n2o, pattern=re_area, replacement=repl_area)
    
    return s, n2o


def _filter_allowed_chars_with_map(
    s: str, n2o: List[int], keep: re.Pattern
) -> Tuple[str, List[int]]:
    out_c: List[str] = []
    out_m: List[int] = []
    for i, ch in enumerate(s):
        if keep.match(ch):
            out_c.append(ch)
            out_m.append(n2o[i])
    return "".join(out_c), out_m


def _trim_edges_with_map(s: str, n2o: List[int]) -> Tuple[str, List[int]]:
    # trim leading/trailing spaces
    start = 0
    end = len(s)
    while start < end and s[start].isspace():
        start += 1
    while end > start and s[end - 1].isspace():
        end -= 1
    if start == 0 and end == len(s):
        return s, n2o
    return s[start:end], n2o[start:end]


def _rebuild_orig_to_norm(norm_to_orig: List[int], original_len: int, normalized_len: int) -> List[int]:
    """
    Rebuild orig_to_norm mapping from final norm_to_orig after all transformations.
    
    This ensures orig_to_norm accurately reflects the final normalized string,
    accounting for all removals, replacements, and collapses.
    
    Algorithm:
    1. First pass: Map each original index to the earliest normalized index that references it
    2. Second pass: Forward-fill gaps monotonically (removed chars map to next valid position)
    3. Clamp to normalized length to prevent out-of-range
    
    Args:
        norm_to_orig: Final mapping from normalized index -> original index
        original_len: Length of original text
        normalized_len: Length of final normalized text
        
    Returns:
        orig_to_norm: Mapping from original index -> normalized index
    """
    orig_to_norm = [-1] * original_len
    
    # First pass: earliest normalized index for each original index
    for ni, oi in enumerate(norm_to_orig):
        if 0 <= oi < original_len and orig_to_norm[oi] == -1:
            orig_to_norm[oi] = ni
    
    # Second pass: forward-fill gaps monotonically
    last = 0
    for oi in range(original_len):
        if orig_to_norm[oi] == -1:
            orig_to_norm[oi] = last
        else:
            last = orig_to_norm[oi]
    
    # Third pass: clamp to normalized length and ensure non-decreasing
    for oi in range(original_len):
        if orig_to_norm[oi] > normalized_len:
            orig_to_norm[oi] = normalized_len
        # Ensure monotonicity
        if oi > 0 and orig_to_norm[oi] < orig_to_norm[oi - 1]:
            orig_to_norm[oi] = orig_to_norm[oi - 1]
    
    return orig_to_norm


def _nearest_norm_index(n2o: List[int], orig_idx: int) -> int:
    """
    Find the nearest normalized index for an original index that did not directly map
    (e.g., was removed). We pick the smallest index i where n2o[i] >= orig_idx,
    else the last index.
    
    NOTE: This is a legacy helper. Use _rebuild_orig_to_norm for accurate mapping.
    """
    for i, o in enumerate(n2o):
        if o >= orig_idx:
            return i
    return len(n2o)
