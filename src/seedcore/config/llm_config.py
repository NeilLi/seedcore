"""
LLM configuration for SeedCore.
Supports OpenAI, Anthropic, and other LLM providers with flexible configuration.
"""

import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    AZURE = "azure"
    LOCAL = "local"


@dataclass
class LLMConfig:
    """Configuration for LLM services."""
    
    # Provider settings
    provider: LLMProvider = LLMProvider.OPENAI
    
    # API Configuration
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    
    # Model Configuration
    model: str = "gpt-4o"
    max_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    
    # Request Configuration
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # Streaming Configuration
    stream: bool = False
    stream_chunk_size: int = 1
    
    # Safety and Content Filtering
    safe_mode: bool = False
    content_filter: bool = True
    
    # Cost and Rate Limiting
    rate_limit_requests_per_minute: int = 60
    rate_limit_tokens_per_minute: int = 150000
    
    # Caching Configuration
    enable_caching: bool = True
    cache_ttl: int = 3600  # 1 hour
    
    # Logging and Monitoring
    log_requests: bool = True
    log_responses: bool = False
    log_tokens: bool = True
    
    # Advanced Configuration
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    
    # Provider-specific settings
    provider_config: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Set defaults and validate configuration."""
        # Set default system prompt for SeedCore
        if not self.system_prompt:
            self.system_prompt = (
                "You are SeedCore, an intelligent AI system designed to help with "
                "complex reasoning, planning, and task execution. Provide clear, "
                "accurate, and helpful responses."
            )
        
        # Set default user prompt template
        if not self.user_prompt_template:
            self.user_prompt_template = "{user_input}"
        
        # Note: Validation is now handled by the validate() method
        # to allow for more flexible configuration creation
    
    @classmethod
    def from_env(cls) -> 'LLMConfig':
        """Create configuration from environment variables."""
        provider_str = os.getenv('LLM_PROVIDER', 'openai').lower()
        provider_map = {
            'openai': LLMProvider.OPENAI,
            'anthropic': LLMProvider.ANTHROPIC,
            'google': LLMProvider.GOOGLE,
            'azure': LLMProvider.AZURE,
            'local': LLMProvider.LOCAL,
        }
        
        provider = provider_map.get(provider_str, LLMProvider.OPENAI)
        
        return cls(
            provider=provider,
            api_key=os.getenv('OPENAI_API_KEY') or os.getenv('ANTHROPIC_API_KEY') or os.getenv('LLM_API_KEY'),
            api_base=os.getenv('LLM_API_BASE'),
            api_version=os.getenv('LLM_API_VERSION'),
            model=os.getenv('LLM_MODEL', 'gpt-4o'),
            max_tokens=int(os.getenv('LLM_MAX_TOKENS', '1024')),
            temperature=float(os.getenv('LLM_TEMPERATURE', '0.7')),
            top_p=float(os.getenv('LLM_TOP_P', '1.0')),
            frequency_penalty=float(os.getenv('LLM_FREQUENCY_PENALTY', '0.0')),
            presence_penalty=float(os.getenv('LLM_PRESENCE_PENALTY', '0.0')),
            timeout=int(os.getenv('LLM_TIMEOUT', '60')),
            max_retries=int(os.getenv('LLM_MAX_RETRIES', '3')),
            retry_delay=float(os.getenv('LLM_RETRY_DELAY', '1.0')),
            stream=os.getenv('LLM_STREAM', 'false').lower() == 'true',
            stream_chunk_size=int(os.getenv('LLM_STREAM_CHUNK_SIZE', '1')),
            safe_mode=os.getenv('LLM_SAFE_MODE', 'false').lower() == 'true',
            content_filter=os.getenv('LLM_CONTENT_FILTER', 'true').lower() == 'true',
            rate_limit_requests_per_minute=int(os.getenv('LLM_RATE_LIMIT_REQUESTS_PER_MINUTE', '60')),
            rate_limit_tokens_per_minute=int(os.getenv('LLM_RATE_LIMIT_TOKENS_PER_MINUTE', '150000')),
            enable_caching=os.getenv('LLM_ENABLE_CACHING', 'true').lower() == 'true',
            cache_ttl=int(os.getenv('LLM_CACHE_TTL', '3600')),
            log_requests=os.getenv('LLM_LOG_REQUESTS', 'true').lower() == 'true',
            log_responses=os.getenv('LLM_LOG_RESPONSES', 'false').lower() == 'true',
            log_tokens=os.getenv('LLM_LOG_TOKENS', 'true').lower() == 'true',
            system_prompt=os.getenv('LLM_SYSTEM_PROMPT'),
            user_prompt_template=os.getenv('LLM_USER_PROMPT_TEMPLATE'),
        )
    
    @classmethod
    def openai(cls, model: str = "gpt-4o", **kwargs) -> 'LLMConfig':
        """Create configuration for OpenAI."""
        return cls(
            provider=LLMProvider.OPENAI,
            model=model,
            **kwargs
        )
    
    @classmethod
    def anthropic(cls, model: str = "claude-3-opus-20240229", **kwargs) -> 'LLMConfig':
        """Create configuration for Anthropic Claude."""
        return cls(
            provider=LLMProvider.ANTHROPIC,
            model=model,
            **kwargs
        )
    
    @classmethod
    def google(cls, model: str = "gemini-1.5-pro", **kwargs) -> 'LLMConfig':
        """Create configuration for Google Gemini."""
        return cls(
            provider=LLMProvider.GOOGLE,
            model=model,
            **kwargs
        )
    
    def get_request_params(self) -> Dict[str, Any]:
        """Get parameters for LLM API requests."""
        params = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
            'stream': self.stream,
        }
        
        # Add provider-specific parameters
        if self.provider_config:
            params.update(self.provider_config)
        
        return params
    
    def get_client_config(self) -> Dict[str, Any]:
        """Get configuration for LLM client initialization."""
        config = {
            'api_key': self.api_key,
            'timeout': self.timeout,
            'max_retries': self.max_retries,
        }
        
        if self.api_base:
            config['api_base'] = self.api_base
        if self.api_version:
            config['api_version'] = self.api_version
        
        return config
    
    def is_configured(self) -> bool:
        """Check if LLM is properly configured."""
        return (
            self.api_key is not None and
            self.model is not None and
            self.provider is not None
        )
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []
        
        if not self.api_key:
            errors.append("API key is required")
        
        if not self.model:
            errors.append("Model name is required")
        
        if self.temperature < 0.0 or self.temperature > 2.0:
            errors.append("Temperature must be between 0.0 and 2.0")
        
        if self.top_p < 0.0 or self.top_p > 1.0:
            errors.append("top_p must be between 0.0 and 1.0")
        
        if self.max_tokens <= 0:
            errors.append("max_tokens must be positive")
        
        return errors
    
    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"LLMConfig(provider={self.provider.value}, "
            f"model={self.model}, "
            f"max_tokens={self.max_tokens}, "
            f"temperature={self.temperature})"
        )


# Global configuration instance
_llm_config: Optional[LLMConfig] = None


def get_llm_config() -> LLMConfig:
    """Get the global LLM configuration."""
    global _llm_config
    if _llm_config is None:
        _llm_config = LLMConfig.from_env()
    return _llm_config


def set_llm_config(config: LLMConfig) -> None:
    """Set the global LLM configuration."""
    global _llm_config
    _llm_config = config


def configure_llm_openai(
    api_key: str,
    model: str = "gpt-4o",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    **kwargs
) -> None:
    """Configure LLM for OpenAI."""
    config = LLMConfig.openai(
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs
    )
    set_llm_config(config)


def configure_llm_anthropic(
    api_key: str,
    model: str = "claude-3-opus-20240229",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    **kwargs
) -> None:
    """Configure LLM for Anthropic Claude."""
    config = LLMConfig.anthropic(
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs
    )
    set_llm_config(config)


def configure_llm_google(
    api_key: str,
    model: str = "gemini-1.5-pro",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    **kwargs
) -> None:
    """Configure LLM for Google Gemini."""
    config = LLMConfig.google(
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs
    )
    set_llm_config(config) 