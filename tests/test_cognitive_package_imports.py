from __future__ import annotations

import importlib
import sys

import pytest


def _clear_seedcore_cognitive_modules() -> None:
    for name in list(sys.modules):
        if name == "seedcore.cognitive" or name.startswith("seedcore.cognitive."):
            sys.modules.pop(name, None)


def test_cognitive_package_import_is_safe_without_dspy(monkeypatch):
    _clear_seedcore_cognitive_modules()
    monkeypatch.delitem(sys.modules, "dspy", raising=False)

    cognitive = importlib.import_module("seedcore.cognitive")

    assert cognitive.DSpyCognitiveClient is not None
    assert callable(cognitive.for_env)


def test_cognitive_core_export_raises_clear_error_without_dspy(monkeypatch):
    _clear_seedcore_cognitive_modules()
    monkeypatch.delitem(sys.modules, "dspy", raising=False)

    cognitive = importlib.import_module("seedcore.cognitive")

    with pytest.raises(ModuleNotFoundError, match="optional 'dspy' dependency"):
        _ = cognitive.CognitiveCore
