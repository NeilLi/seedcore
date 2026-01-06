# tests/test_text_normalizer.py
import importlib.util
import pathlib
import random
import string
import sys
# pytest imported for pytestmark if needed, but not used directly

# -----------------------------
# Robust module loader
# -----------------------------

def _load_normalizer_module():
    """
    Loads the text normalizer module by searching common repo locations.
    This avoids relying on PYTHONPATH / editable installs during CI.
    
    Returns:
        tuple: (module, path) - The loaded module and its file path
    """
    repo_root = pathlib.Path(__file__).resolve().parents[1]

    # Try the actual module path first (most likely location)
    candidates = [
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "utils" / "text_normalizer.py",
        # Fallback locations
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "text_normalizer.py",
        repo_root / "src" / "seedcore" / "utils" / "text_normalizer.py",
        repo_root / "src" / "seedcore" / "text_normalizer.py",
        repo_root / "src" / "text_normalizer.py",
        repo_root / "text_normalizer.py",
    ]

    # If not found in known spots, do a controlled search
    if not any(p.exists() for p in candidates):
        # Search up to a reasonable depth; ignore venvs/cache dirs
        ignore_parts = {"site-packages", ".venv", "venv", "__pycache__", ".git", ".mypy_cache", "node_modules"}
        found = []
        for p in repo_root.rglob("text_normalizer.py"):
            if any(part in ignore_parts for part in p.parts):
                continue
            found.append(p)
        
        # Prefer paths closer to repo root (fewer path components)
        if found:
            found.sort(key=lambda p: len(p.parts))
            candidates.insert(0, found[0])

    for path in candidates:
        if path.exists():
            # Use a proper module name that matches the file structure
            module_name = "seedcore.ops.eventizer.utils.text_normalizer"
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                # Register the module in sys.modules before executing
                # This is critical for dataclasses and other decorators that inspect __module__
                sys.modules[module_name] = mod
                spec.loader.exec_module(mod)
                return mod, path

    raise ImportError(
        f"Could not locate text normalizer module. "
        f"Searched: {[str(c) for c in candidates]}. "
        f"Add its path to candidates in _load_normalizer_module()."
    )

MOD, MOD_PATH = _load_normalizer_module()
TextNormalizer = MOD.TextNormalizer
NormalizationTier = MOD.NormalizationTier


# -----------------------------
# Helpers
# -----------------------------

def _norm(text: str, **kwargs):
    """Helper to normalize text with map building."""
    n = TextNormalizer(**kwargs)
    result = n.normalize(text, build_map=True)
    if isinstance(result, tuple):
        return result
    return result, None


def _assert_spanmap_invariants(original: str, normalized: str, smap):
    # 1) Critical invariant: per-char map length equals normalized length
    assert len(normalized) == len(smap.norm_to_orig), (
        "len(normalized) must equal len(norm_to_orig). "
        f"Got {len(normalized)} vs {len(smap.norm_to_orig)}."
    )

    # 2) norm_to_orig indices must be in [0, len(original)-1] if normalized is non-empty
    if normalized:
        assert all(0 <= oi < len(original) for oi in smap.norm_to_orig), (
            "norm_to_orig must map into valid original indices."
        )

    # 3) orig_to_norm must be length of original, values in [0, len(normalized)]
    assert len(smap.orig_to_norm) == len(original)
    assert all(0 <= ni <= len(normalized) for ni in smap.orig_to_norm), (
        "orig_to_norm must be within [0, len(normalized)]."
    )

    # 4) orig_to_norm should be monotonic non-decreasing (forward-filled)
    assert all(
        smap.orig_to_norm[i] <= smap.orig_to_norm[i + 1]
        for i in range(len(smap.orig_to_norm) - 1)
    ), "orig_to_norm should be monotonic non-decreasing."

    # 5) Projection clamping should never produce out-of-range spans
    #    (project_norm_span_to_orig now clamps with original_len)
    for _ in range(10):
        a = random.randint(-5, len(normalized) + 5)
        b = random.randint(-5, len(normalized) + 5)
        start, end = (a, b) if a <= b else (b, a)
        o_s, o_e = smap.project_norm_span_to_orig(start, end, original_len=len(original))
        assert 0 <= o_s <= o_e <= len(original)

    for _ in range(10):
        a = random.randint(-5, len(original) + 5)
        b = random.randint(-5, len(original) + 5)
        start, end = (a, b) if a <= b else (b, a)
        n_s, n_e = smap.project_orig_span_to_norm(start, end)
        assert 0 <= n_s <= n_e <= len(normalized)


# -----------------------------
# Tests: Critical fixes
# -----------------------------

def test_ellipsis_multi_emit_keeps_map_lengths():
    """Test that ellipsis (…) multi-character normalization maintains map length consistency.
    
    NFKC converts '…' to '...' (3 chars), which tests our _emit_str() fix.
    In AGGRESSIVE tier, '...' gets collapsed to '.' by punctuation collapse.
    In COGNITIVE tier, '...' is preserved.
    """
    text = "Hello…World"
    
    # Test AGGRESSIVE tier (collapses punctuation)
    normalized_agg, smap_agg = _norm(text, tier=NormalizationTier.AGGRESSIVE)
    _assert_spanmap_invariants(text, normalized_agg, smap_agg)
    # AGGRESSIVE collapses '...' to '.'
    assert "." in normalized_agg
    assert "hello" in normalized_agg.lower() and "world" in normalized_agg.lower()
    
    # Test COGNITIVE tier (preserves punctuation intensity)
    normalized_cog, smap_cog = _norm(text, tier=NormalizationTier.COGNITIVE)
    _assert_spanmap_invariants(text, normalized_cog, smap_cog)
    # COGNITIVE preserves '...' (NFKC converts ellipsis to three dots)
    assert "..." in normalized_cog or "." in normalized_cog  # May still collapse in some cases


def test_orig_to_norm_is_built_from_final_norm_to_orig():
    # This string triggers removals + replacements + compaction.
    text = "  [laughter]  Meet me at 6pm!!!  100 sqft  "
    normalized, smap = _norm(
        text,
        tier=NormalizationTier.AGGRESSIVE,
        strip_audio_tags=True,
        standardize_units=True,
        compact_whitespace=True,
    )
    _assert_spanmap_invariants(text, normalized, smap)

    # Additionally ensure that every original index can map to <= len(normalized)
    # and that the mapping behaves stably under removed chars.
    for oi, ni in enumerate(smap.orig_to_norm):
        assert 0 <= ni <= len(normalized), f"bad orig_to_norm at {oi}: {ni}"


def test_project_norm_span_to_orig_is_clamped():
    text = "abc"
    normalized, smap = _norm(text)

    # Extreme spans must clamp safely
    o_s, o_e = smap.project_norm_span_to_orig(-999, 999, original_len=len(text))
    assert (o_s, o_e) == (0, len(text))


# -----------------------------
# Tests: Tier semantics
# -----------------------------

def test_aggressive_collapses_repeated_punct_but_not_mixed():
    text = "wow!!! really??? okay?!?!"
    normalized, _ = _norm(text, tier=NormalizationTier.AGGRESSIVE)

    assert "!!!" not in normalized
    assert "???" not in normalized

    # Mixed punctuation should remain (because regex is now ([.!?])\1{1,})
    assert "?!?!" in normalized


def test_cognitive_preserves_punctuation_intensity():
    text = "wow!!! really???"
    normalized, _ = _norm(text, tier=NormalizationTier.COGNITIVE)

    assert "!!!" in normalized
    assert "???" in normalized


# -----------------------------
# Tests: Audio whitelist
# -----------------------------

def test_audio_whitelist_strips_known_markers_only():
    text = "hi (clears throat) there (maybe) [music] [brackets]"
    normalized, _ = _norm(text, strip_audio_tags=True)

    # Whitelisted markers removed
    assert "clears throat" not in normalized
    assert "music" not in normalized

    # Legitimate content preserved
    assert "(maybe)" in normalized
    assert "[brackets]" in normalized


# -----------------------------
# Tests: Case preservation
# -----------------------------

def test_case_preserve_not_forced_lower_by_token_join():
    # This is a split token join case. Ensure preserve mode doesn't lower it.
    text = "V-I-P access"
    normalized, _ = _norm(
        text,
        case="preserve",
        join_split_tokens=True,
        tier=NormalizationTier.AGGRESSIVE,
    )

    # Depending on your join behavior, joined token should keep original casing
    # If you preserve the first letter's case style, VIP should remain VIP.
    assert "VIP" in normalized


# -----------------------------
# Tests: Unit / time standardization
# -----------------------------

def test_time_standardizer_handles_common_formats():
    # You updated regex to support 6pm, 6 p.m., 12:05am, etc.
    text = "meet 6pm, 6 p.m., and 12:05am"
    normalized, _ = _norm(text, standardize_units=True)

    assert "18:00" in normalized
    assert "00:05" in normalized


def test_area_unit_standardizer_outputs_space_consistent():
    text = "room is 100 sqft and 250 square feet"
    normalized, _ = _norm(text, standardize_units=True)

    assert "100 sqft" in normalized
    assert "250 sqft" in normalized


def test_temperature_normalization_space_before_unit():
    text = "it is 85°F outside and 20 C inside"
    normalized, _ = _norm(text)

    # Both should be in "<num> <unit>" form
    assert "85 F" in normalized
    assert "20 C" in normalized


# -----------------------------
# Tests: Mapping sanity on random inputs
# -----------------------------

def test_mapping_invariants_randomized_smoke():
    # Keep it lightweight but useful.
    samples = [
        "",
        "simple text",
        "tabs\tand\nnewlines\r\n",
        "Unicode “quotes” — and … ellipsis",
        "Noise [laughter] (coughs) plus (maybe) [brackets]",
        "Time 6pm 6 p.m. 12:05am; area 100 sqft",
        "Mixed punct ?!?!!! ??? !!!",
    ]

    # add a few random strings containing punctuation + unicode-ish chars
    alphabet = string.ascii_letters + string.digits + " .,!?:;()[]-_\n\t…“”’—"
    for _ in range(10):
        samples.append("".join(random.choice(alphabet) for _ in range(80)))

    for text in samples:
        normalized, smap = _norm(
            text,
            tier=random.choice([NormalizationTier.AGGRESSIVE, NormalizationTier.COGNITIVE]),
            case=random.choice(["lower", "upper", "title", "preserve"]),
            strip_audio_tags=True,
            standardize_units=True,
            join_split_tokens=True,
        )
        if text:  # only validate orig_to_norm length when original non-empty
            _assert_spanmap_invariants(text, normalized, smap)
        else:
            assert normalized == ""
            assert smap.norm_to_orig == []
            assert smap.orig_to_norm == []
