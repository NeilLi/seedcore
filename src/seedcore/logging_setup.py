# src/seedcore/logging_setup.py
from __future__ import annotations
import os, sys, logging
from logging.config import dictConfig

DEFAULT_LEVEL = os.getenv("LOG_LEVEL", "INFO")

_STDOUT_ONLY = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "std",
            "level": DEFAULT_LEVEL,
        }
    },
    "root": {"level": DEFAULT_LEVEL, "handlers": ["stdout"]},
}

def _nuke_file_handlers():
    root = logging.getLogger()
    for h in list(root.handlers):
        try:
            if hasattr(h, "baseFilename"):
                root.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        except Exception:
            pass
    # Also sweep known children
    for name, lg in list(logging.Logger.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger):
            for h in list(lg.handlers):
                try:
                    if hasattr(h, "baseFilename"):
                        lg.removeHandler(h)
                        try:
                            h.close()
                        except Exception:
                            pass
                except Exception:
                    pass

def _discourage_dspy_file_logging_env():
    os.environ.setdefault("DSP_LOG_TO_FILE", "false")
    os.environ.setdefault("DSP_LOG_TO_STDOUT", "true")
    os.environ.setdefault("LOG_TO_FILE", "false")
    os.environ.setdefault("LOG_TO_STDOUT", "true")

def setup_logging(app_name: str = "", config_path_env: str = "SEEDCORE_LOGCFG"):
    """
    Call this as the FIRST thing in your entrypoint, before importing modules
    that might attach FileHandlers.
    - If SEEDCORE_LOGCFG points to a YAML/JSON dictConfig file, we load it.
    - Otherwise we force a stdout-only config and remove any pre-attached FileHandlers.
    """
    _discourage_dspy_file_logging_env()

    cfg_path = os.getenv(config_path_env, "").strip()
    if cfg_path and os.path.exists(cfg_path):
        # You can put a YAML/JSON dictConfig here; up to you to yaml.safe_load if YAML.
        import json, io
        text = open(cfg_path, "r", encoding="utf-8").read()
        try:
            # Try JSON first
            dictConfig(json.loads(text))
        except Exception:
            # Fall back to YAML
            import yaml  # ensure pyyaml is in your image
            dictConfig(yaml.safe_load(io.StringIO(text)))
        return

    # No external config → enforce stdout-only and remove any file handlers
    _nuke_file_handlers()
    dictConfig(_STDOUT_ONLY)
    # Defensive: make sure basicConfig can’t silently add duplicate handlers later
    logging.basicConfig(level=DEFAULT_LEVEL, force=True, handlers=[logging.StreamHandler(sys.stdout)])

