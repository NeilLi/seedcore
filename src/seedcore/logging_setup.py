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
        except json.JSONDecodeError:
            # Fall back to YAML
            import yaml  # ensure pyyaml is in your image
            dictConfig(yaml.safe_load(io.StringIO(text)))
        return

    # No external config → enforce stdout-only and remove any file handlers
    _nuke_file_handlers()
    dictConfig(_STDOUT_ONLY)
    # Defensive: If another library calls basicConfig later without 'force=True',
    # this initial call prevents it from silently adding a duplicate handler.
    # We explicitly set the handlers to ensure we only have one stream.
    logging.basicConfig(level=DEFAULT_LEVEL, force=True, handlers=[logging.StreamHandler(sys.stdout)])

def ensure_serve_logger(module: str,
                        level: str = "INFO",
                        fmt: str = "%(asctime)s %(levelname)s %(name)s %(message)s") -> logging.Logger:
    """
    Ensure a logger for a Ray Serve replica writes to stdout and is not silently dropped.
    
    Args:
        module (str): Logger name (e.g., "seedcore.ml")
        level (str): Log level (default: INFO)
        fmt (str): Formatter string
    
    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(module)

    # Only attach handler if none exist (avoids duplicate logs)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)

    # Normalize log level
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Allow propagation to root (so dictConfig / root handlers still see messages)
    logger.propagate = True

    # Emit a sentinel log to confirm logger is alive
    logger.info("✅ Serve logger initialized for module '%s'", module)

    return logger