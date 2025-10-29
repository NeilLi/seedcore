#!/usr/bin/env python3
"""
Global OpenAI Token Usage Logger

Automatically logs token usage for all OpenAI API calls made through:
- Direct OpenAI client usage
- DSPy OpenAI integration
- Any OpenAI-compatible API calls

Usage:
    from seedcore.utils.token_logger import enable_token_logging
    
    enable_token_logging()  # Enable globally
    
Or set environment variable:
    ENABLE_OPENAI_TOKEN_LOGGING=true
"""

import os
import logging
from typing import Optional, Any
from functools import wraps

logger = logging.getLogger(__name__)

# Global state
_token_logging_enabled = False
_original_openai_create = None
_original_openai_acreate = None


def _log_token_usage(response: Any, context: str = "") -> None:
    """
    Log token usage from an OpenAI API response.
    
    Args:
        response: OpenAI response object with .usage attribute
        context: Optional context string (e.g., task type, model name)
    """
    try:
        usage_found = False
        
        # Try direct .usage attribute (standard OpenAI response)
        if hasattr(response, 'usage') and response.usage:
            usage = response.usage
            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            model_name = getattr(response, 'model', 'unknown')
            usage_found = True
        # Try .response.usage (nested in some wrappers)
        elif hasattr(response, 'response') and hasattr(response.response, 'usage'):
            usage = response.response.usage
            prompt_tokens = getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0)
            model_name = getattr(response.response, 'model', getattr(response, 'model', 'unknown'))
            usage_found = True
        # Try dict access (JSON response)
        elif isinstance(response, dict):
            if 'usage' in response:
                usage = response['usage']
                prompt_tokens = usage.get('prompt_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'completion_tokens', 0)
                total_tokens = usage.get('total_tokens', 0) if isinstance(usage, dict) else getattr(usage, 'total_tokens', 0)
                model_name = response.get('model', 'unknown')
                usage_found = True
        
        if usage_found:
            log_msg = (
                f"🔹 OpenAI Token Usage {context}(model={model_name}): "
                f"prompt={prompt_tokens}, completion={completion_tokens}, "
                f"total={total_tokens}"
            )
            logger.info(log_msg)
        else:
            logger.debug(f"No usage information found in response {context} (type: {type(response)})")
            # Debug: log what attributes the response has
            if hasattr(response, '__dict__'):
                logger.debug(f"Response attributes: {list(response.__dict__.keys())}")
    except Exception as e:
        logger.warning(f"Failed to log token usage {context}: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")


def _wrap_chat_completions_create(original_method):
    """Wrap OpenAI client's chat.completions.create method."""
    @wraps(original_method)
    def wrapper(*args, **kwargs):
        # Get model from kwargs or args for context
        model = kwargs.get('model', 'unknown')
        if args and len(args) > 0:
            # If first arg is a dict (messages), check for model
            if isinstance(args[0], dict):
                model = args[0].get('model', model)
        
        context = f"[{model}] "
        
        response = original_method(*args, **kwargs)
        _log_token_usage(response, context)
        return response
    
    return wrapper


def _wrap_chat_completions_acreate(original_method):
    """Wrap OpenAI client's chat.completions.create async method."""
    @wraps(original_method)
    async def wrapper(*args, **kwargs):
        # Get model from kwargs or args for context
        model = kwargs.get('model', 'unknown')
        if args and len(args) > 0:
            if isinstance(args[0], dict):
                model = args[0].get('model', model)
        
        context = f"[{model}] "
        
        response = await original_method(*args, **kwargs)
        _log_token_usage(response, context)
        return response
    
    return wrapper


def _patch_openai_client(client: Any) -> bool:
    """
    Patch an OpenAI client instance to log token usage.
    
    Args:
        client: OpenAI client instance (openai.OpenAI or openai.AsyncOpenAI)
    
    Returns:
        True if patching was successful, False otherwise
    """
    try:
        # Check if this is a ChatCompletion client (openai.OpenAI or openai.AsyncOpenAI)
        if hasattr(client, 'chat'):
            chat_obj = client.chat
            if hasattr(chat_obj, 'completions'):
                completions_obj = chat_obj.completions
                
                # Patch synchronous create method
                if hasattr(completions_obj, 'create'):
                    original_create = completions_obj.create
                    if not hasattr(original_create, '_token_logger_wrapped'):
                        completions_obj.create = _wrap_chat_completions_create(original_create)
                        completions_obj.create._token_logger_wrapped = True
                        logger.debug("Patched chat.completions.create")
                
                # Patch async create method if available
                if hasattr(completions_obj, 'acreate'):
                    original_acreate = completions_obj.acreate
                    if not hasattr(original_acreate, '_token_logger_wrapped'):
                        completions_obj.acreate = _wrap_chat_completions_acreate(original_acreate)
                        completions_obj.acreate._token_logger_wrapped = True
                        logger.debug("Patched chat.completions.acreate")
                
                return True
        return False
    except Exception as e:
        logger.warning(f"Failed to patch OpenAI client: {e}")
        return False


def _patch_dspy_openai():
    """
    Patch DSPy's OpenAI integration to log token usage.
    
    This intercepts calls at the DSPy level by patching:
    1. The __init__ to patch the underlying OpenAI client
    2. The __call__ method to intercept responses directly
    """
    try:
        import dspy
        
        # Check if dspy.OpenAI exists
        if hasattr(dspy, 'OpenAI'):
            # Patch __init__ to catch client creation
            original_init = None
            if hasattr(dspy.OpenAI, '__init__'):
                original_init = dspy.OpenAI.__init__
                # Check if already patched
                if hasattr(original_init, '_token_logger_wrapped'):
                    logger.debug("dspy.OpenAI.__init__ already patched")
                else:
                    def patched_init(self, *args, **kwargs):
                        # Call original init
                        original_init(self, *args, **kwargs)
                        
                        # Try to patch the underlying client
                        # DSPy stores it in different places depending on version
                        patched = False
                        for attr_name in ['_OpenAI__client', 'client', '_client', 'lm']:
                            if hasattr(self, attr_name):
                                client = getattr(self, attr_name)
                                if _patch_openai_client(client):
                                    patched = True
                                    logger.debug(f"Patched DSPy OpenAI client via {attr_name}")
                                    break
                        
                        if not patched:
                            logger.debug("Could not find DSPy OpenAI client to patch via attributes")
                    
                    patched_init._token_logger_wrapped = True
                    dspy.OpenAI.__init__ = patched_init
                    logger.debug("Patched dspy.OpenAI.__init__")
            
            # Also patch __call__ method to intercept responses at DSPy level
            if hasattr(dspy.OpenAI, '__call__'):
                original_call = dspy.OpenAI.__call__
                if not hasattr(original_call, '_token_logger_wrapped'):
                    def patched_call(self, *args, **kwargs):
                        # Call original method
                        result = original_call(self, *args, **kwargs)
                        
                        # Try to extract usage from result
                        # DSPy returns different structures, try common patterns
                        try:
                            if hasattr(result, 'usage'):
                                _log_token_usage(result, f"[DSPy OpenAI {getattr(self, 'model', 'unknown')}] ")
                            elif isinstance(result, dict) and 'usage' in result:
                                usage = result['usage']
                                if usage:
                                    prompt_tokens = getattr(usage, 'prompt_tokens', usage.get('prompt_tokens', 0))
                                    completion_tokens = getattr(usage, 'completion_tokens', usage.get('completion_tokens', 0))
                                    total_tokens = getattr(usage, 'total_tokens', usage.get('total_tokens', 0))
                                    model = getattr(self, 'model', 'unknown')
                                    logger.info(f"🔹 OpenAI Token Usage [DSPy {model}]: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")
                        except Exception as e:
                            logger.debug(f"Could not extract usage from DSPy result: {e}")
                        
                        return result
                    
                    patched_call._token_logger_wrapped = True
                    dspy.OpenAI.__call__ = patched_call
                    logger.debug("Patched dspy.OpenAI.__call__")
            
            # Also patch basic_request if it exists (some DSPy versions)
            if hasattr(dspy.OpenAI, 'basic_request'):
                original_basic_request = dspy.OpenAI.basic_request
                if not hasattr(original_basic_request, '_token_logger_wrapped'):
                    def patched_basic_request(self, prompt: str, **kwargs):
                        result = original_basic_request(self, prompt, **kwargs)
                        # Try to extract usage - basic_request might return different format
                        try:
                            if isinstance(result, dict) and 'usage' in result:
                                usage = result['usage']
                                model = getattr(self, 'model', 'unknown')
                                prompt_tokens = usage.get('prompt_tokens', 0)
                                completion_tokens = usage.get('completion_tokens', 0)
                                total_tokens = usage.get('total_tokens', 0)
                                logger.info(f"🔹 OpenAI Token Usage [DSPy basic_request {model}]: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")
                        except Exception as e:
                            logger.debug(f"Could not extract usage from basic_request: {e}")
                        return result
                    
                    patched_basic_request._token_logger_wrapped = True
                    dspy.OpenAI.basic_request = patched_basic_request
                    logger.debug("Patched dspy.OpenAI.basic_request")
            
            return True
        
        return False
    except ImportError:
        logger.debug("dspy not available - skipping DSPy patching")
        return False
    except Exception as e:
        logger.warning(f"Failed to patch DSPy OpenAI: {e}")
        return False


def _patch_openai_module():
    """
    Patch the global OpenAI module to intercept all client instantiations.
    
    This is a more aggressive approach that patches at the module level.
    Patches BEFORE any clients are created, so it catches DSPy's internal client creation.
    """
    try:
        import openai
        
        # Patch OpenAI class if it exists
        if hasattr(openai, 'OpenAI'):
            original_openai_class = openai.OpenAI
            
            # Check if already patched
            if hasattr(original_openai_class, '_token_logger_patched'):
                logger.debug("openai.OpenAI already patched")
                return True
            
            class PatchedOpenAI(original_openai_class):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    # Patch the client immediately after creation
                    _patch_openai_client(self)
                    logger.debug("Patched OpenAI client instance in PatchedOpenAI.__init__")
            
            # Mark as patched
            PatchedOpenAI._token_logger_patched = True
            PatchedOpenAI.__name__ = original_openai_class.__name__
            PatchedOpenAI.__module__ = original_openai_class.__module__
            
            # Replace the class - this will affect all future instantiations
            openai.OpenAI = PatchedOpenAI
            logger.debug("Patched openai.OpenAI class (module-level)")
            
            # Also patch AsyncOpenAI if available
            if hasattr(openai, 'AsyncOpenAI'):
                original_async_class = openai.AsyncOpenAI
                
                if not hasattr(original_async_class, '_token_logger_patched'):
                    class PatchedAsyncOpenAI(original_async_class):
                        def __init__(self, *args, **kwargs):
                            super().__init__(*args, **kwargs)
                            _patch_openai_client(self)
                            logger.debug("Patched AsyncOpenAI client instance")
                    
                    PatchedAsyncOpenAI._token_logger_patched = True
                    PatchedAsyncOpenAI.__name__ = original_async_class.__name__
                    PatchedAsyncOpenAI.__module__ = original_async_class.__module__
                    
                    openai.AsyncOpenAI = PatchedAsyncOpenAI
                    logger.debug("Patched openai.AsyncOpenAI class")
            
            # Also patch chat.completions directly at module level if possible
            # This catches cases where the module is accessed before class instantiation
            try:
                # Try to access and patch the default client if it exists
                if hasattr(openai, 'chat') and hasattr(openai.chat, 'completions'):
                    completions = openai.chat.completions
                    if hasattr(completions, 'create'):
                        original_create = completions.create
                        if not hasattr(original_create, '_token_logger_wrapped'):
                            completions.create = _wrap_chat_completions_create(original_create)
                            completions.create._token_logger_wrapped = True
                            logger.debug("Patched openai.chat.completions.create at module level")
            except Exception as e:
                logger.debug(f"Could not patch module-level chat.completions: {e}")
            
            return True
        
        return False
    except ImportError:
        logger.debug("openai module not available - skipping module patching")
        return False
    except Exception as e:
        logger.warning(f"Failed to patch OpenAI module: {e}")
        return False


def _patch_existing_dspy_instances():
    """
    Try to patch any existing dspy.OpenAI instances that were created before patching.
    
    This is best-effort and may not catch all instances.
    """
    try:
        import dspy
        import gc
        
        # Check if settings.lm is a dspy.OpenAI instance
        if hasattr(dspy, 'settings') and hasattr(dspy.settings, 'lm'):
            lm = dspy.settings.lm
            if lm and hasattr(lm, '__class__') and 'OpenAI' in str(lm.__class__):
                logger.debug("Found existing dspy.settings.lm instance, attempting to patch")
                # Try to patch the underlying client
                for attr_name in ['_OpenAI__client', 'client', '_client', 'lm']:
                    if hasattr(lm, attr_name):
                        client = getattr(lm, attr_name)
                        if _patch_openai_client(client):
                            logger.debug(f"Patched existing DSPy LM client via {attr_name}")
                            return True
        
        # Also check all objects in memory (best-effort)
        try:
            for obj in gc.get_objects():
                if hasattr(obj, '__class__') and 'OpenAI' in str(obj.__class__):
                    # Check if it's a dspy.OpenAI instance
                    if hasattr(obj, 'model') or hasattr(obj, '_OpenAI__client'):
                        for attr_name in ['_OpenAI__client', 'client', '_client']:
                            if hasattr(obj, attr_name):
                                client = getattr(obj, attr_name)
                                if _patch_openai_client(client):
                                    logger.debug(f"Patched existing DSPy OpenAI instance in memory")
                                    break
        except Exception:
            pass  # gc.get_objects() can fail in some environments
        
        return False
    except Exception as e:
        logger.debug(f"Could not patch existing DSPy instances: {e}")
        return False


def enable_token_logging(enable: bool = True) -> bool:
    """
    Enable or disable global OpenAI token usage logging.
    
    This will patch:
    - OpenAI client instances (openai.OpenAI)
    - DSPy OpenAI integration (dspy.OpenAI)
    - Module-level OpenAI class
    
    IMPORTANT: Call this BEFORE creating any DSPy OpenAI instances for best results.
    
    Args:
        enable: If True, enable token logging; if False, disable it
    
    Returns:
        True if logging was enabled successfully, False otherwise
    
    Example:
        >>> from seedcore.utils.token_logger import enable_token_logging
        >>> enable_token_logging()  # Enable globally
        >>> # Now all OpenAI calls will log token usage automatically
    """
    global _token_logging_enabled
    
    if enable == _token_logging_enabled:
        # Already in desired state, but try to patch any new instances
        if enable:
            _patch_existing_dspy_instances()
        return True
    
    _token_logging_enabled = enable
    
    if enable:
        logger.info("🔧 Enabling OpenAI token usage logging globally...")
        
        # CRITICAL: Patch module FIRST before any clients are created
        # This ensures DSPy's internal client creation is caught
        patched_module = _patch_openai_module()
        
        # Then patch DSPy class-level
        patched_dspy = _patch_dspy_openai()
        
        # Try to patch any existing instances (best-effort)
        _patch_existing_dspy_instances()
        
        if patched_module or patched_dspy:
            logger.info("✅ OpenAI token usage logging enabled successfully")
            logger.info("   Token usage will be logged for all OpenAI API calls")
            logger.info("   Logs will appear as: 🔹 OpenAI Token Usage [...]")
            logger.info("   Note: Only DEEP profile uses OpenAI (FAST uses NIM)")
            logger.info("   To see logs, trigger DEEP profile calls or set LLM_PROVIDER_FAST=openai")
            return True
        else:
            logger.warning("⚠️ Could not patch OpenAI clients - token logging may not work")
            logger.warning("   Make sure openai package is installed and importable")
            return False
    else:
        # Disable logging (note: we can't easily unpatch, but future clients won't be patched)
        logger.info("🔧 Disabling OpenAI token usage logging...")
        logger.info("   (Note: Already-patched clients will continue logging)")
        return True


def is_token_logging_enabled() -> bool:
    """Check if token logging is currently enabled."""
    return _token_logging_enabled


# Auto-enable on import if environment variable is set
if os.getenv("ENABLE_OPENAI_TOKEN_LOGGING", "").lower() in ("1", "true", "yes", "on"):
    enable_token_logging(True)

