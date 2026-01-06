# tests/test_pattern_compiler.py
import asyncio  # noqa: F401
import importlib.util
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest  # pyright: ignore[reportMissingImports]


# -----------------------------
# Robust module loader (adjust if needed)
# -----------------------------

def _load_compiler_module():
    """
    Loads PatternCompiler by searching common repo locations.
    Update candidates if your path differs.
    
    Properly sets up the module path so relative imports work correctly.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    
    # Add src directory to sys.path so Python can resolve imports
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    
    candidates = [
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "compiler.py",
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "pattern_compiler.py",
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "utils" / "pattern_compiler.py",
        repo_root / "src" / "seedcore" / "ops" / "eventizer" / "patterns" / "compiler.py",
    ]

    ignore_parts = {"site-packages", ".venv", "venv", "__pycache__", ".git", ".mypy_cache", "node_modules"}

    for path in candidates:
        if path.exists():
            # Use the proper module path based on file location
            # For utils/pattern_compiler.py, use seedcore.ops.eventizer.utils.pattern_compiler
            if "utils" in str(path):
                module_name = "seedcore.ops.eventizer.utils.pattern_compiler"
            else:
                module_name = "seedcore.ops.eventizer.pattern_compiler"
            
            # Ensure parent packages exist in sys.modules for relative imports
            # This is critical for relative imports like "from .aho_corasick import ..."
            parent_parts = module_name.split(".")
            for i in range(1, len(parent_parts)):
                parent_name = ".".join(parent_parts[:i])
                if parent_name not in sys.modules:
                    # Create a namespace module for parent packages
                    parent_module = type(sys)(parent_name)
                    # Set __path__ to the actual directory so Python can find sibling modules
                    if i == len(parent_parts) - 1:
                        # For the immediate parent (utils), set path to utils directory
                        parent_dir = path.parent
                    else:
                        # For other parents, construct path from repo_root
                        parent_dir = repo_root / "src" / "/".join(parent_parts[:i])
                    parent_module.__path__ = [str(parent_dir)]
                    sys.modules[parent_name] = parent_module
            
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            assert spec and spec.loader
            
            # Set __package__ attribute so relative imports work
            mod = importlib.util.module_from_spec(spec)
            mod.__package__ = ".".join(parent_parts[:-1]) if len(parent_parts) > 1 else None
            mod.__name__ = module_name
            
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
            return mod, path

    # fallback search
    for p in repo_root.rglob("*.py"):
        if any(part in ignore_parts for part in p.parts):
            continue
        if p.name in {"pattern_compiler.py", "compiler.py"} and "eventizer" in str(p):
            # Determine module name based on path
            rel_path = p.relative_to(repo_root / "src")
            module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            
            # Ensure parent packages exist in sys.modules for relative imports
            parent_parts = module_name.split(".")
            for i in range(1, len(parent_parts)):
                parent_name = ".".join(parent_parts[:i])
                if parent_name not in sys.modules:
                    # Create a namespace module for parent packages
                    parent_module = type(sys)(parent_name)
                    # Set __path__ to the actual directory so Python can find sibling modules
                    if i == len(parent_parts) - 1:
                        # For the immediate parent (utils), set path to utils directory
                        parent_dir = p.parent
                    else:
                        # For other parents, construct path from repo_root
                        parent_dir = repo_root / "src" / "/".join(parent_parts[:i])
                    parent_module.__path__ = [str(parent_dir)]
                    sys.modules[parent_name] = parent_module
            
            spec = importlib.util.spec_from_file_location(module_name, str(p))
            assert spec and spec.loader
            
            # Set __package__ attribute so relative imports work
            mod = importlib.util.module_from_spec(spec)
            mod.__package__ = ".".join(parent_parts[:-1]) if len(parent_parts) > 1 else None
            mod.__name__ = module_name
            
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
            return mod, p

    raise ImportError("Could not locate PatternCompiler module. Update candidates in _load_compiler_module().")


MOD, MOD_PATH = _load_compiler_module()
PatternCompiler = MOD.PatternCompiler


# -----------------------------
# Helpers
# -----------------------------

def _make_min_config(**overrides):
    """
    PatternCompiler only uses a handful of config fields.
    Provide a minimal object with those attributes.
    """
    defaults = dict(
        enable_aho_corasick=False,   # keep tests deterministic (use fallback matcher)
        enable_re2=False,
        enable_hyperscan=False,
        pattern_files=[],
        keyword_dictionaries=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _write_patterns(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    p = tmp_path / "patterns.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


@pytest.fixture()
def compiler(monkeypatch):
    """
    Creates a PatternCompiler instance with schema validation bypassed.
    Also clears bootstrap defaults so tests are fully controlled.
    """
    cfg = _make_min_config()
    c = PatternCompiler(cfg)

    # bypass schema validation (unit tests shouldn't depend on repo config files)
    monkeypatch.setattr(c, "_validate_patterns_file", lambda _p: True)

    # ensure no bootstrap noise interferes
    c.clear_patterns()
    return c


# -----------------------------
# Tests
# -----------------------------

@pytest.mark.asyncio
async def test_load_and_match_regex_patterns_with_metadata(compiler, tmp_path):
    payload = {
        "version": "1.0.0",
        "regex_patterns": [
            {
                "id": "rx_hvac",
                "pattern": r"\bhvac\b",
                "flags": ["IGNORECASE"],
                "priority": 10,
                "confidence": 0.9,
                "whole_word": True,
                "enabled": True,
                "event_types": ["hvac"],
                "emits_tags": ["hvac_fault"],
                "emits_attributes": {"severity": "high"},
                "metadata": {"source": "unit_test"},
            }
        ],
        "keyword_patterns": [],
        "entity_patterns": [],
    }

    fp = _write_patterns(tmp_path, payload)
    ok = await compiler.load_patterns_from_file(str(fp))
    assert ok is True

    text = "We detected HVAC failure."
    matches = await compiler.match_all(text, include_keywords=False, include_entities=False)

    assert len(matches) == 1
    m = matches[0]
    assert m.pattern_type == "regex"
    assert m.pattern_id == "rx_hvac"
    assert m.matched_text.lower() == "hvac"
    assert text[m.start_pos:m.end_pos].lower() == "hvac"
    assert m.metadata["event_types"] == ["hvac"]
    assert m.metadata["emits_tags"] == ["hvac_fault"]
    assert m.metadata["emits_attributes"] == {"severity": "high"}
    assert m.metadata["priority"] == 10
    assert m.confidence == 0.9
    assert m.metadata["engine"] in {"re", "re2", "hyperscan", "hyperscan+re", "hyperscan+re2"}


@pytest.mark.asyncio
async def test_keyword_matching_fallback_whole_word_respected(compiler, tmp_path):
    """
    We set enable_aho_corasick=False, so compiler uses _match_keywords_simple().
    Ensure whole_word prevents matching inside other words.
    """
    payload = {
        "version": "1.0.0",
        "regex_patterns": [],
        "keyword_patterns": [
            {
                "id": "kw_art",
                "keywords": ["art"],
                "priority": 100,
                "confidence": 0.7,
                "whole_word": True,
                "case_sensitive": False,
                "enabled": True,
                "event_types": ["topic_art"],
                "emits_tags": ["tag_art"],
                "emits_attributes": {"kind": "noun"},
                "metadata": {},
            }
        ],
        "entity_patterns": [],
    }

    fp = _write_patterns(tmp_path, payload)
    ok = await compiler.load_patterns_from_file(str(fp))
    assert ok is True

    # inside word should NOT match
    text = "cartoon"
    matches = await compiler.match_all(text, include_regex=False, include_entities=False)
    assert matches == []

    # standalone should match
    text2 = "modern art is cool"
    matches2 = await compiler.match_all(text2, include_regex=False, include_entities=False)
    assert len(matches2) == 1
    m = matches2[0]
    assert m.pattern_type == "keyword"
    assert m.pattern_id == "kw_art"
    assert m.matched_text.lower() == "art"
    assert text2[m.start_pos:m.end_pos].lower() == "art"
    assert m.metadata["priority"] == 100


@pytest.mark.asyncio
async def test_dedup_prefers_higher_confidence_then_higher_priority_rank(compiler, tmp_path):
    """
    Two regex patterns matching the same span. Dedup should keep:
      - higher confidence
      - if tie confidence, lower priority number wins (higher priority)
    """
    payload = {
        "version": "1.0.0",
        "regex_patterns": [
            {
                "id": "rx_a",
                "pattern": r"\bhvac\b",
                "flags": ["IGNORECASE"],
                "priority": 50,        # worse priority rank
                "confidence": 0.9,     # higher confidence
                "whole_word": True,
                "enabled": True,
                "event_types": ["hvac_a"],
            },
            {
                "id": "rx_b",
                "pattern": r"\bhvac\b",
                "flags": ["IGNORECASE"],
                "priority": 10,        # better priority rank
                "confidence": 0.8,     # lower confidence
                "whole_word": True,
                "enabled": True,
                "event_types": ["hvac_b"],
            }
        ],
        "keyword_patterns": [],
        "entity_patterns": [],
    }

    fp = _write_patterns(tmp_path, payload)
    ok = await compiler.load_patterns_from_file(str(fp))
    assert ok is True

    text = "HVAC"
    matches = await compiler.match_all(text, include_keywords=False, include_entities=False)
    assert len(matches) == 1
    assert matches[0].pattern_id == "rx_a"  # higher confidence wins

    # Now make confidence equal and ensure priority rank wins (lower number)
    compiler.clear_patterns()
    payload["regex_patterns"][0]["confidence"] = 0.8
    fp2 = _write_patterns(tmp_path, payload)
    ok2 = await compiler.load_patterns_from_file(str(fp2))
    assert ok2 is True

    matches2 = await compiler.match_all(text, include_keywords=False, include_entities=False)
    assert len(matches2) == 1
    assert matches2[0].pattern_id == "rx_b"  # lower priority number wins


@pytest.mark.asyncio
async def test_entity_patterns_multiple_subpatterns_return_multiple_matches(compiler, tmp_path):
    """
    This test enforces the recommended fix:
    entity patterns should NOT overwrite each other when multiple sub-regex exist.
    If your compiler still overwrites per entity_type, this test will fail (good).
    """
    payload = {
        "version": "1.0.0",
        "regex_patterns": [],
        "keyword_patterns": [],
        "entity_patterns": [
            {
                "id": "ent_room",
                "entity_type": "room",
                "patterns": [
                    {"regex": r"\broom\s+(\d{3})\b", "flags": ["IGNORECASE"]},
                    {"regex": r"\b(rm)\s*(\d{3})\b", "flags": ["IGNORECASE"]},
                ],
                "priority": 20,
                "confidence": 0.95,
                "enabled": True,
                "event_types": ["entity_room"],
            }
        ],
    }

    fp = _write_patterns(tmp_path, payload)
    ok = await compiler.load_patterns_from_file(str(fp))
    assert ok is True

    text = "Please check room 101 and rm102 ASAP."
    matches = await compiler.match_all(text, include_regex=False, include_keywords=False, include_entities=True)

    # Expect at least two entity matches (room 101, rm102)
    # If your current implementation overwrites entity_type, you'll likely get only 1.
    assert len(matches) >= 2
    assert any("room 101" in m.matched_text.lower() for m in matches)
    assert any("rm102" in m.matched_text.lower() for m in matches)
    for m in matches:
        assert m.pattern_type == "entity"
        assert m.pattern_id.startswith("entity:room")


@pytest.mark.asyncio
async def test_budget_cutoff_returns_partial_results(compiler, tmp_path, monkeypatch):
    """
    Smoke test: if budget is exceeded mid-flight, compiler returns partial deduped results.
    We simulate time passing by monkeypatching time.perf_counter.
    """
    payload = {
        "version": "1.0.0",
        "regex_patterns": [
            {"id": "rx1", "pattern": r"\bfoo\b", "flags": ["IGNORECASE"], "priority": 10, "confidence": 0.9, "enabled": True, "event_types": ["t1"]},
            {"id": "rx2", "pattern": r"\bbar\b", "flags": ["IGNORECASE"], "priority": 20, "confidence": 0.9, "enabled": True, "event_types": ["t2"]},
        ],
        "keyword_patterns": [],
        "entity_patterns": [],
    }
    fp = _write_patterns(tmp_path, payload)
    ok = await compiler.load_patterns_from_file(str(fp))
    assert ok is True

    # Simulate time perf_counter jumping after first family
    import time as _time_mod
    t0 = _time_mod.perf_counter()
    calls = {"n": 0}

    def fake_perf_counter():
        calls["n"] += 1
        # first call: start; later calls jump ahead
        return t0 if calls["n"] <= 2 else t0 + 999

    monkeypatch.setattr(_time_mod, "perf_counter", fake_perf_counter)

    text = "foo bar"
    matches = await compiler.match_all(text, budget_ms=1.0, include_keywords=False, include_entities=False)

    # Could be 1 or 2 depending on where cutoff hits, but should not crash.
    assert len(matches) >= 1
    assert all(m.pattern_type == "regex" for m in matches)
