from __future__ import annotations
import os
import logging
from logging.config import dictConfig
from logging import Filter

DEFAULT_LEVEL = os.getenv("LOG_LEVEL", "INFO")


class RayServeMetricsFilter(Filter):
    """
    Filter to suppress non-critical Ray Serve metrics errors and Ray Client cleanup noise.

    Ray Serve's internal metrics system sometimes tries to use Ray Client API
    which can fail when using ray:// addresses. This is non-critical and doesn't
    affect functionality, so we suppress the error to reduce log noise.

    Also suppresses Ray Client streaming RPC cleanup errors that occur during shutdown.
    """

    def filter(self, record):
        msg = record.getMessage()
        pathname = record.pathname or ""
        
        # Suppress "Ray Client is not connected" errors from metrics_utils
        if "metrics_utils.py" in pathname or "router.py" in pathname:
            if "Ray Client is not connected" in msg:
                return False
            if "push_metrics_to_controller" in msg:
                return False

        # Suppress Ray Client cleanup errors (harmless threading exceptions and callback errors)
        if "ray_client_streaming_rpc" in msg:
            return False
        
        # Suppress dataclient callback errors (harmless race condition when futures are cancelled)
        if "ray/util/client" in pathname or "dataclient" in pathname.lower():
            if (
                "InvalidStateError" in msg
                or "CANCELLED" in msg
                or "Callback error" in msg
                or "set_result" in msg
            ):
                return False
        
        # Suppress queue length deadline warnings (can be configured via env var)
        if "queue length" in msg.lower() or "RAY_SERVE_QUEUE_LENGTH_RESPONSE_DEADLINE_S" in msg:
            return False

        return True


_STDOUT_ONLY = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "std",
            # CHANGE: Set this to DEBUG so it allows all levels through.
            # The individual loggers (like your Router) will control the actual threshold.
            "level": "DEBUG",
            "filters": ["ray_serve_metrics_filter"],
        }
    },
    "filters": {
        "ray_serve_metrics_filter": {
            "()": "seedcore.logging_setup.RayServeMetricsFilter",
        }
    },
    # Root level also needs to be low enough to catch the traffic
    "root": {"level": "DEBUG", "handlers": ["stdout"]},
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
        import json
        import io

        text = open(cfg_path, "r", encoding="utf-8").read()
        try:
            # Try JSON first
            dictConfig(json.loads(text))
        except json.JSONDecodeError:
            # Fall back to YAML
            import yaml  # ensure pyyaml is in your image  # pyright: ignore[reportMissingModuleSource]

            dictConfig(yaml.safe_load(io.StringIO(text)))
        return

    # No external config → enforce stdout-only and remove any file handlers
    _nuke_file_handlers()
    dictConfig(_STDOUT_ONLY)

    # Apply filter to suppress non-critical Ray Serve metrics errors
    metrics_filter = RayServeMetricsFilter()
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(metrics_filter)

    # Also apply to Ray's internal loggers
    ray_loggers = [
        logging.getLogger("ray.serve"),
        logging.getLogger("ray.serve._private"),
        logging.getLogger("ray.serve._private.metrics_utils"),
        logging.getLogger("ray.serve._private.router"),
        logging.getLogger("ray.util.client"),
        logging.getLogger("ray.util.client.dataclient"),
        logging.getLogger("ray.util.client.common"),  # Also catches set_future errors
    ]
    for logger in ray_loggers:
        logger.addFilter(metrics_filter)

    # Suppress unhandled exceptions in Ray Client background threads
    # This is a known Ray issue where cleanup threads try to set exceptions on cancelled futures
    import threading

    original_excepthook = threading.excepthook

    def filtered_excepthook(args):
        # Suppress harmless Ray Client cleanup errors
        # This includes both thread exceptions and callback errors from dataclient
        exc_type_str = str(args.exc_type)
        exc_value_str = str(args.exc_value) if args.exc_value else ""
        thread_str = str(args.thread) if hasattr(args, 'thread') else ""
        
        # Check if it's from Ray's client/dataclient (harmless cleanup race condition)
        if (
            "ray_client_streaming_rpc" in thread_str 
            or "ray/util/client" in exc_type_str
            or "dataclient" in exc_type_str.lower()
            or "dataclient" in exc_value_str.lower()
        ):
            if "InvalidStateError" in exc_value_str or "CANCELLED" in exc_value_str:
                # This is a harmless cleanup race condition, suppress it
                return
        # Call original handler for all other exceptions
        original_excepthook(args)

    threading.excepthook = filtered_excepthook

    # ***REMOVED BUGGY BASICCONFIG CALL***
    # The dictConfig call above is sufficient and correct.
    # The old basicConfig call was overwriting the 'ext://sys.stdout'
    # handler with a raw 'sys.stdout' handler.
    #
    # logging.basicConfig(level=DEFAULT_LEVEL, force=True, handlers=[logging.StreamHandler(sys.stdout)]) # <-- THIS WAS THE BUG


def ensure_serve_logger(
    module: str,
    level: str = "INFO",
    fmt: str = "%(asctime)s %(levelname)s %(name)s %(message)s",
) -> logging.Logger:
    """
    Gets a logger for a Ray Serve replica and sets its level.

    Assumes `setup_logging()` has already been called in this process
    to configure the root handler. This function just sets the *level*
    for the specified module.

    Args:
        module (str): Logger name (e.g., "seedcore.ml")
        level (str): Log level (default: INFO)
        fmt: str: (This is now unused, as the root formatter is used)

    Returns:
        logging.Logger: Configured logger
    """
    logger = logging.getLogger(module)

    # ***REMOVED HANDLER LOGIC***
    # We should not add a handler here. We want logs to propagate
    # to the root logger, which setup_logging() has already
    # configured to point to 'ext://sys.stdout'.
    #
    # if not logger.handlers:
    #     handler = logging.StreamHandler(sys.stdout) # <-- This was the bug
    #     handler.setFormatter(logging.Formatter(fmt))
    #     logger.addHandler(handler)

    # Just set the level for this specific module
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Allow propagation to root (so dictConfig / root handlers still see messages)
    logger.propagate = True

    # Emit a sentinel log to confirm logger is alive
    logger.info(
        "✅ Serve logger configured for module '%s' (propagating to root)", module
    )

    return logger
