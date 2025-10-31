"""
SeedCore ML Driver Package
==========================

This package provides NIM (NVIDIA Inference Microservices) driver implementations
for connecting to OpenAI-compatible inference endpoints.

Available Drivers
-----------------
- **NimDriverSDK** : High-level driver using the official OpenAI SDK
- **NimClient** : Low-level driver using direct HTTP calls via `httpx`

Quick Start
-----------
```python
from seedcore.ml.driver import get_driver

# Automatically selects the best driver (SDK preferred)
driver = get_driver(
    base_url="http://your-nim-endpoint:8000/v1",
    model="meta/llama-3.1-8b-base"
)

messages = [{"role": "user", "content": "Hello from SeedCore!"}]
response = driver.chat(messages)
print(response)
```

Configuration
-------------
You can control which backend to use with:

* Environment variable: `SEEDCORE_USE_SDK=true|false`
* Or parameter: `get_driver(use_sdk=True)`

Module Layout
-------------
seedcore.ml.driver/
├── nim_driver.py        # Low-level HTTP driver  
├── nim_driver_sdk.py    # High-level SDK driver
└── __init__.py          # Entry point & driver selector
"""

import os
import logging
from typing import Union, Optional

from .nim_driver_sdk import NimDriverSDK
from .nim_driver import NimClient
from .nim_retrieval_sdk import NimRetrievalSDK
from .nim_retrieval import NimRetrievalHTTP

# ---------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------

__all__ = [
    "NimDriverSDK",
    "NimClient", 
    "get_driver",
    "create_fallback_driver",
    "NIMDriver",
    "NIM",
    "NimRetrievalSDK",
    "NimRetrievalHTTP",
    "get_retriever",
]

__version__ = "0.2.0"
__author__ = "Neil"
__description__ = "SeedCore NIM driver implementations for OpenAI-compatible inference endpoints"

# ---------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------

logger = logging.getLogger("seedcore.ml.driver")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------

NIMDriver = NimDriverSDK     # Recommended high-level interface
NIM = NimClient              # Lightweight HTTP-based interface

# ---------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------

def get_driver(
    use_sdk: Optional[bool] = None,
    base_url: Optional[str] = None, 
    api_key: Optional[str] = None,
    model: str = "meta/llama-3.1-8b-base",
    timeout: int = 60,
    auto_fallback: bool = True,
) -> Union[NimDriverSDK, NimClient]:
    """
    Factory function that returns the appropriate NIM driver instance.
    
    Parameters
    ----------
    use_sdk : bool | None
        If True, uses the OpenAI SDK-based driver. If False, uses direct HTTP client.
        If None, auto-detects based on environment variable `SEEDCORE_USE_SDK`.
    base_url : str
        Base URL for the NIM or inference service endpoint.
    api_key : str | None  
        API key, if required by the endpoint (defaults to "none").
    model : str
        Model identifier (e.g. "meta/llama-3.1-8b-base").
    timeout : int
        Request timeout in seconds.
    auto_fallback : bool
        If True, automatically fallback to HTTP client if SDK fails.
        
    Returns
    -------
    NimDriverSDK | NimClient
        A configured driver instance.
    """
    if use_sdk is None:
        use_sdk_env = os.getenv("SEEDCORE_USE_SDK", "true").lower()
        use_sdk = use_sdk_env in ("1", "true", "yes")
    
    # Default base_url if not provided
    if base_url is None:
        base_url = os.getenv("NIM_LLM_BASE_URL", "http://localhost:8000/v1")
        
    # Default api_key if not provided
    if api_key is None:
        api_key = os.getenv("NIM_LLM_API_KEY", "none")
    
    driver_cls = NimDriverSDK if use_sdk else NimClient
    driver_name = driver_cls.__name__
    
    logger.info(f"Initializing SeedCore driver: {driver_name} (model={model})")
    
    try:
        return driver_cls(
            base_url=base_url,
            api_key=api_key, 
            model=model,
            timeout=timeout,
        )
    except Exception as e:
        if auto_fallback and use_sdk:
            logger.warning(f"SDK driver failed ({e}), falling back to HTTP client")
            return NimClient(
                base_url=base_url,
                api_key=api_key,
                model=model, 
                timeout=timeout,
            )
        raise


def create_fallback_driver(
    base_url: str,
    api_key: Optional[str] = None,
    model: str = "meta/llama-3.1-8b-base", 
    timeout: int = 60,
) -> Union[NimDriverSDK, NimClient]:
    """
    Creates a driver with automatic fallback logic for maximum reliability.
    
    This function attempts to create an SDK-based driver first, and if that fails
    for any reason (missing dependencies, initialization errors, etc.), it 
    automatically falls back to the HTTP-based client.
    
    Parameters
    ----------
    base_url : str
        Base URL for the NIM endpoint
    api_key : str | None
        API key for authentication
    model : str  
        Model identifier
    timeout : int
        Request timeout in seconds
        
    Returns
    -------
    Union[NimDriverSDK, NimClient]
        A working driver instance (SDK preferred, HTTP fallback)
    """
    return get_driver(
        use_sdk=True,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        auto_fallback=True,
    )


def get_retriever(
    use_sdk: Optional[bool] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: str = "nvidia/nv-embedqa-e5-v5",
    timeout: int = 60,
):
    """
    Factory for NIM retrieval (embeddings) drivers.
    Respects env SEEDCORE_USE_SDK and NIM_LLM_BASE_URL/API_KEY.
    """
    if use_sdk is None:
        use_sdk = os.getenv("SEEDCORE_USE_SDK", "true").lower() in ("1", "true", "yes")

    base_url = base_url or os.getenv("NIM_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    api_key = api_key or os.getenv("NIM_LLM_API_KEY", "none")

    if use_sdk:
        return NimRetrievalSDK(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
    else:
        return NimRetrievalHTTP(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
