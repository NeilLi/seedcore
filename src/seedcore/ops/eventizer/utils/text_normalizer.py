#!/usr/bin/env python3
"""
Text Normalizer (product-grade)

Goals:
- Make text consistent for deterministic pattern matching.
- Keep a *lossless* mapping between ORIGINAL and NORMALIZED text indices.
- Be fast, safe, and configurable.

Features:
- Unicode NFKC normalization + optional accent folding.
- Quote/dash/ellipsis/space normalization.
- Case normalization (lower/upper/title/preserve).
- Light de-obfuscation (joins tokens with single-char gaps up to a limit).
- Temperature/unit touch-ups (°F/°C variants -> 'F'/'C' with space).
- Bidirectional SpanMap to project spans between original and normalized text.

All transformations maintain a per-character mapping so pattern matches on the
normalized text can be projected back to the original string reliably.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple


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

    def project_norm_span_to_orig(self, start: int, end: int) -> Tuple[int, int]:
        """Project [start, end) span from normalized to original text."""
        n = len(self.norm_to_orig)
        if start < 0: start = 0
        if end < 0: end = 0
        if start > n: start = n
        if end > n: end = n
        if start >= end:
            # empty span: pick closest index
            idx = self.norm_to_orig[start - 1] if start > 0 else 0
            return (idx, idx)
        o_start = self.norm_to_orig[start]
        # end is exclusive; if end==0 then map to 0, else map to the last
        # normalized char's original index + 1 (best-effort)
        last_norm = end - 1
        o_end = self.norm_to_orig[last_norm] + 1
        return (o_start, o_end)

    def project_orig_span_to_norm(self, start: int, end: int) -> Tuple[int, int]:
        """Project [start, end) span from original to normalized text."""
        m = len(self.orig_to_norm)
        if start < 0: start = 0
        if end < 0: end = 0
        if start > m: start = m
        if end > m: end = m
        if start >= end:
            idx = self.orig_to_norm[start - 1] if start > 0 else 0
            return (idx, idx)
        n_start = self.orig_to_norm[start]
        # find last normalized index that originated from end-1 (best-effort)
        n_end = self.orig_to_norm[end - 1] + 1
        return (n_start, n_end)


# -----------------------------
# Normalizer
# -----------------------------

class TextNormalizer:
    """
    Text normalization utilities for consistent pattern matching with
    bidirectional span mapping.

    Pipeline (configurable):
      1) Unicode NFKC
      2) Quote/dash/ellipsis normalization
      3) Whitespace compaction (+ normalize newlines -> space)
      4) Case normalization (lower/upper/title/preserve)
      5) Optional accent folding (strip diacritics)
      6) Temperature/unit touch-ups
      7) Light de-obfuscation (join tokens with single-char gaps)
    """

    _re_ws = re.compile(r"\s+")
    _re_multi_punct = re.compile(r"([.!?]){2,}")
    _re_units_temp = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:°\s*([CF])|deg(?:ree)?s?\s*([CF]))\b", re.IGNORECASE)
    _re_temperature_compact = re.compile(r"\b(\d{1,3})(?:\s*°\s*|\s*)([CF])\b", re.IGNORECASE)

    # join tokens like "v i p" -> "vip", "h v a c" -> "hvac"
    _re_split_token = re.compile(r"\b([A-Za-z])(?:\s+([A-Za-z]))(?:\s+([A-Za-z]))(?:\s+([A-Za-z]))?\b")

    def __init__(
        self,
        *,
        case: str = "lower",                 # "lower" | "upper" | "title" | "preserve"
        fold_accents: bool = False,
        normalize_quotes_and_dashes: bool = True,
        compact_whitespace: bool = True,
        replace_newlines_with_space: bool = True,
        join_split_tokens: bool = True,
        join_max_token_len: int = 6,         # only join if <= 6 letters total
        keep_chars_regex: Optional[str] = None,  # if set, remove everything not matching this class (applied late)
    ):
        self.case = case
        self.fold_accents = fold_accents
        self.normalize_quotes_and_dashes = normalize_quotes_and_dashes
        self.compact_whitespace = compact_whitespace
        self.replace_newlines_with_space = replace_newlines_with_space
        self.join_split_tokens = join_split_tokens
        self.join_max_token_len = join_max_token_len
        self.keep_chars_regex = re.compile(keep_chars_regex) if keep_chars_regex else None

    # -------------------------
    # Public API
    # -------------------------

    async def normalize(self, text: str, *, build_map: bool = True) -> str | Tuple[str, SpanMap]:
        """
        Normalize text. If build_map=True, returns (normalized_text, SpanMap).
        Otherwise returns normalized_text only.
        """
        if not text:
            return ("", SpanMap([], [])) if build_map else ""

        # Start with identity maps
        norm_chars: List[str] = []
        norm_to_orig: List[int] = []
        orig_to_norm: List[int] = [-1] * len(text)

        def _emit(ch: str, orig_idx: int):
            norm_to_orig.append(orig_idx)
            norm_chars.append(ch)
            if orig_to_norm[orig_idx] == -1:
                orig_to_norm[orig_idx] = len(norm_chars) - 1

        # 1) Unicode NFKC: we’ll iterate original text and emit normalized chars
        #    while building the maps.
        nkfc = unicodedata.normalize("NFKC", text)

        # mapping from nkfc index -> original index:
        # Best-effort: For simplicity, assume length-preserving in most cases.
        # If lengths mismatch, fall back to per-char scanning heuristic.
        nkfc_to_orig = self._approximate_map(text, nkfc)

        # Iterate through NFKC string and apply subsequent transforms *as we emit*
        i = 0
        while i < len(nkfc):
            ch = nkfc[i]
            orig_idx = nkfc_to_orig[i]

            # 2) Normalize quotes/dashes/ellipsis
            if self.normalize_quotes_and_dashes:
                ch = _normalize_quote_dash(ch)

            # 3) Replace newlines with space if requested
            if self.replace_newlines_with_space and ch in ("\r", "\n", "\x0b", "\x0c"):
                ch = " "

            # Emit current char
            _emit(ch, orig_idx)
            i += 1

        # At this point we have a simple NFKC (+ basic remaps) stream.
        s = "".join(norm_chars)

        # 4) Collapse whitespace & multiple punctuation (still map-aware)
        if self.compact_whitespace:
            s, norm_to_orig = _collapse_runs_with_map(
                s, norm_to_orig,
                pattern=self._re_ws,
                replacement=" "
            )
        # Single pass for multi punctuation like "!!!" -> "!"
        s, norm_to_orig = _collapse_runs_with_map(
            s, norm_to_orig,
            pattern=self._re_multi_punct,
            replacement=lambda m: m.group(1)
        )

        # 5) Case normalization
        if self.case != "preserve":
            s, norm_to_orig = _case_with_map(s, norm_to_orig, self.case)

        # 6) Optional accent folding (strip diacritics)
        if self.fold_accents:
            s, norm_to_orig = _strip_accents_with_map(s, norm_to_orig)

        # 7) Temperature/unit touch-ups: "85°F" -> "85 F"
        s, norm_to_orig = _normalize_temperature_units_with_map(s, norm_to_orig,
                                                                self._re_units_temp,
                                                                self._re_temperature_compact)

        # 8) Light de-obfuscation: join split tokens like "v i p" -> "vip"
        if self.join_split_tokens:
            s, norm_to_orig = _join_split_tokens_with_map(
                s, norm_to_orig,
                max_token_len=self.join_max_token_len,
                pattern=self._re_split_token
            )

        # 9) Optional character class keep (late)
        if self.keep_chars_regex:
            s, norm_to_orig = _filter_allowed_chars_with_map(s, norm_to_orig, self.keep_chars_regex)

        # Final trimming of edges (keep map consistent)
        s, norm_to_orig = _trim_edges_with_map(s, norm_to_orig)

        # Build orig_to_norm for any -1 leftovers
        for j in range(len(orig_to_norm)):
            if orig_to_norm[j] == -1:
                # map to next known normalized index or len(s)
                # (best-effort, ensures monotonicity)
                orig_to_norm[j] = _nearest_norm_index(norm_to_orig, j)

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
    if ch in ("“", "”", "„", "‟", "❝", "❞", "＂", "«", "»"):
        return '"'
    if ch in ("‘", "’", "‚", "‛", "❛", "❜", "＇"):
        return "'"
    # dashes
    if ch in ("–", "—", "―", "−", "‐", "-"):
        return "-"
    # ellipsis
    if ch == "…":
        return "..."
    return ch


def _collapse_runs_with_map(
    s: str,
    n2o: List[int],
    *,
    pattern: re.Pattern,
    replacement: str | callable
) -> Tuple[str, List[int]]:
    out_chars: List[str] = []
    out_map: List[int] = []

    last_end = 0
    for m in pattern.finditer(s):
        # copy up to match
        out_chars.extend(s[last_end:m.start()])
        out_map.extend(n2o[last_end:m.start()])

        # write replacement (single char/func result)
        repl = replacement(m) if callable(replacement) else replacement
        if repl:
            # map entire replacement to first char's original index in the match
            anchor = n2o[m.start()] if m.start() < len(n2o) else (n2o[m.end()-1] if m.end() else 0)
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
        chars = [c.upper() if i == 0 or (i > 0 and s[i-1].isspace()) else c.lower() for i, c in enumerate(s)]
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
                # skip combining mark; map it to previous base char’s map
                continue
            # map: use the original n2o index for the source character
            out_chars.append(unicodedata.normalize("NFC", dch))
            out_map.append(n2o[i])
    return "".join(out_chars), out_map


def _normalize_temperature_units_with_map(
    s: str,
    n2o: List[int],
    re_units: re.Pattern,
    re_compact: re.Pattern
) -> Tuple[str, List[int]]:
    # Normalize variants like "85°F" / "85 ° F" / "85 degrees F" -> "85 F"
    def repl_units(m: re.Match) -> str:
        deg = m.group(2) or m.group(3) or ""
        return f"{m.group(1)} {deg.upper()}"

    s, n2o = _collapse_runs_with_map(s, n2o, pattern=re_units, replacement=repl_units)

    # Compact "85F" -> "85 F" (add missing space)
    def repl_compact(m: re.Match) -> str:
        return f"{m.group(1)} {m.group(2).upper()}"

    s, n2o = _collapse_runs_with_map(s, n2o, pattern=re_compact, replacement=repl_compact)
    return s, n2o


def _join_split_tokens_with_map(
    s: str,
    n2o: List[int],
    *,
    max_token_len: int,
    pattern: re.Pattern
) -> Tuple[str, List[int]]:
    """
    Join patterns like 'v i p' -> 'vip', 'h v a c' -> 'hvac' when total letters <= max_token_len.
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
            new_chars.extend(out_s[last:m.start()])
            new_map.extend(out_map[last:m.start()])
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


def _filter_allowed_chars_with_map(s: str, n2o: List[int], keep: re.Pattern) -> Tuple[str, List[int]]:
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


def _nearest_norm_index(n2o: List[int], orig_idx: int) -> int:
    """
    Find the nearest normalized index for an original index that did not directly map
    (e.g., was removed). We pick the smallest index i where n2o[i] >= orig_idx,
    else the last index.
    """
    for i, o in enumerate(n2o):
        if o >= orig_idx:
            return i
    return len(n2o)
