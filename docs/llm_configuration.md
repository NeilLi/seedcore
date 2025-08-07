# LLM Configuration Guide

This document describes how to configure and use the LLM (Large Language Model) system in SeedCore.

## Overview

The LLM configuration system provides a flexible way to configure different LLM providers (OpenAI, Anthropic, Google, etc.) with comprehensive settings for model parameters, API configuration, and advanced features.

## Quick Start

### Basic Configuration

```python
from seedcore.config.llm_config import configure_llm_openai

# Configure OpenAI with basic settings
configure_llm_openai(
    api_key="your-openai-api-key",
    model="gpt-4o",
    max_tokens=1024,
    temperature=0.7
)
```

### Using Environment Variables

Set environment variables in your `.env` file:

```bash
# LLM Provider Configuration
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_MAX_TOKENS=1024
LLM_TEMPERATURE=0.7
OPENAI_API_KEY=your-api-key-here
```

Then use the configuration:

```python
from seedcore.config.llm_config import get_llm_config

config = get_llm_config()
print(f"Using {config.provider.value} with model {config.model}")
```

## Configuration Options

### Provider Settings

- **LLM_PROVIDER**: The LLM provider to use (`openai`, `anthropic`, `google`, `azure`, `local`)
- **OPENAI_API_KEY**: Your OpenAI API key
- **ANTHROPIC_API_KEY**: Your Anthropic API key (for Claude models)
- **LLM_API_KEY**: Generic API key (used if provider-specific key not set)

### Model Configuration

- **LLM_MODEL**: The model name (e.g., `gpt-4o`, `claude-3-opus-20240229`, `gemini-1.5-pro`)
- **LLM_MAX_TOKENS**: Maximum number of tokens to generate (default: 1024)
- **LLM_TEMPERATURE**: Controls randomness (0.0-2.0, default: 0.7)
- **LLM_TOP_P**: Nucleus sampling parameter (0.0-1.0, default: 1.0)
- **LLM_FREQUENCY_PENALTY**: Reduces repetition (-2.0 to 2.0, default: 0.0)
- **LLM_PRESENCE_PENALTY**: Encourages new topics (-2.0 to 2.0, default: 0.0)

### API Configuration

- **LLM_API_BASE**: Custom API base URL
- **LLM_API_VERSION**: API version
- **LLM_TIMEOUT**: Request timeout in seconds (default: 60)
- **LLM_MAX_RETRIES**: Maximum retry attempts (default: 3)
- **LLM_RETRY_DELAY**: Delay between retries in seconds (default: 1.0)

### Streaming Configuration

- **LLM_STREAM**: Enable streaming responses (default: false)
- **LLM_STREAM_CHUNK_SIZE**: Number of tokens per chunk (default: 1)

### Safety and Content Filtering

- **LLM_SAFE_MODE**: Enable safe mode (default: false)
- **LLM_CONTENT_FILTER**: Enable content filtering (default: true)

### Rate Limiting

- **LLM_RATE_LIMIT_REQUESTS_PER_MINUTE**: Rate limit for requests (default: 60)
- **LLM_RATE_LIMIT_TOKENS_PER_MINUTE**: Rate limit for tokens (default: 150000)

### Caching Configuration

- **LLM_ENABLE_CACHING**: Enable response caching (default: true)
- **LLM_CACHE_TTL**: Cache TTL in seconds (default: 3600)

### Logging Configuration

- **LLM_LOG_REQUESTS**: Log API requests (default: true)
- **LLM_LOG_RESPONSES**: Log API responses (default: false)
- **LLM_LOG_TOKENS**: Log token usage (default: true)

### Advanced Configuration

- **LLM_SYSTEM_PROMPT**: Default system prompt
- **LLM_USER_PROMPT_TEMPLATE**: Template for user prompts (default: `{user_input}`)

## Supported Providers

### OpenAI

```python
from seedcore.config.llm_config import configure_llm_openai

configure_llm_openai(
    api_key="your-key",
    model="gpt-4o",
    max_tokens=1024,
    temperature=0.7
)
```

### Anthropic (Claude)

```python
from seedcore.config.llm_config import configure_llm_anthropic

configure_llm_anthropic(
    api_key="your-key",
    model="claude-3-opus-20240229",
    max_tokens=2048,
    temperature=0.5
)
```

### Google (Gemini)

```python
from seedcore.config.llm_config import configure_llm_google

configure_llm_google(
    api_key="your-key",
    model="gemini-1.5-pro",
    max_tokens=1024,
    temperature=0.7
)
```

## Advanced Usage

### Custom Configuration

```python
from seedcore.config.llm_config import LLMConfig, LLMProvider

# Create a custom configuration
config = LLMConfig(
    provider=LLMProvider.OPENAI,
    api_key="your-key",
    model="gpt-4o",
    max_tokens=1024,
    temperature=0.7,
    stream=True,
    enable_caching=True,
    system_prompt="You are a helpful AI assistant."
)

# Validate configuration
errors = config.validate()
if errors:
    print("Configuration errors:", errors)
```

### Getting Request Parameters

```python
config = get_llm_config()

# Get parameters for API request
params = config.get_request_params()
# Returns: {'model': 'gpt-4o', 'max_tokens': 1024, 'temperature': 0.7, ...}

# Get client configuration
client_config = config.get_client_config()
# Returns: {'api_key': 'your-key', 'timeout': 60, 'max_retries': 3, ...}
```

### Environment-Based Configuration

```python
from seedcore.config.llm_config import LLMConfig

# Configuration automatically reads from environment variables
config = LLMConfig.from_env()
```

## Validation

The configuration system includes built-in validation:

```python
config = LLMConfig(
    provider=LLMProvider.OPENAI,
    model="gpt-4o",
    temperature=3.0,  # Invalid: should be 0-2
    top_p=1.5,        # Invalid: should be 0-1
    max_tokens=-100    # Invalid: should be positive
)

errors = config.validate()
# Returns: ['Temperature must be between 0.0 and 2.0', 'top_p must be between 0.0 and 1.0', 'max_tokens must be positive']
```

## Best Practices

1. **Use Environment Variables**: Store sensitive information like API keys in environment variables
2. **Validate Configuration**: Always validate configuration before using it
3. **Use Appropriate Models**: Choose models based on your use case and budget
4. **Monitor Usage**: Enable logging to monitor API usage and costs
5. **Cache Responses**: Enable caching for repeated requests to reduce costs
6. **Set Rate Limits**: Configure appropriate rate limits to avoid API quota issues

## Examples

See `examples/llm_config_example.py` for comprehensive examples of how to use the LLM configuration system.

## Troubleshooting

### Common Issues

1. **API Key Not Set**: Ensure your API key is properly set in environment variables
2. **Invalid Model Name**: Check that the model name is correct for your provider
3. **Rate Limiting**: Adjust rate limits if you're hitting API quotas
4. **Timeout Issues**: Increase timeout values for complex requests

### Debug Mode

Enable debug logging to troubleshoot configuration issues:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

config = get_llm_config()
print(f"Configuration: {config}")
```

## Migration from Previous Versions

If you're upgrading from a previous version:

1. Update your environment variables to use the new `LLM_*` prefixes
2. Replace direct API client configuration with the new config system
3. Update your code to use `get_llm_config()` instead of direct configuration
4. Test your configuration with the validation methods

## API Reference

For detailed API documentation, see the docstrings in `src/seedcore/config/llm_config.py`. 