#!/usr/bin/env python3
"""
Example usage of SeedCore LLM configuration.

This script demonstrates how to configure and use the LLM configuration
system with different providers and settings.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from seedcore.config.llm_config import (
    LLMConfig, 
    LLMProvider,
    get_llm_config,
    set_llm_config,
    configure_llm_openai,
    configure_llm_anthropic,
    configure_llm_google
)


def example_basic_configuration():
    """Example of basic LLM configuration."""
    print("=== Basic LLM Configuration Example ===")
    
    # Create a basic OpenAI configuration
    config = LLMConfig.openai(
        api_key="your-api-key-here",
        model="gpt-4o",
        max_tokens=1024,
        temperature=0.7
    )
    
    print(f"Provider: {config.provider.value}")
    print(f"Model: {config.model}")
    print(f"Max Tokens: {config.max_tokens}")
    print(f"Temperature: {config.temperature}")
    print(f"Is Configured: {config.is_configured()}")
    print()


def example_environment_configuration():
    """Example of configuration from environment variables."""
    print("=== Environment Configuration Example ===")
    
    # Set some environment variables for demonstration
    os.environ['LLM_PROVIDER'] = 'openai'
    os.environ['LLM_MODEL'] = 'gpt-4o'
    os.environ['LLM_MAX_TOKENS'] = '2048'
    os.environ['LLM_TEMPERATURE'] = '0.5'
    
    # Create configuration from environment
    config = LLMConfig.from_env()
    
    print(f"Provider: {config.provider.value}")
    print(f"Model: {config.model}")
    print(f"Max Tokens: {config.max_tokens}")
    print(f"Temperature: {config.temperature}")
    print()


def example_global_configuration():
    """Example of global configuration management."""
    print("=== Global Configuration Example ===")
    
    # Configure OpenAI globally
    configure_llm_openai(
        api_key="your-openai-key",
        model="gpt-4o",
        max_tokens=1024,
        temperature=0.7
    )
    
    # Get the global configuration
    config = get_llm_config()
    print(f"Global Provider: {config.provider.value}")
    print(f"Global Model: {config.model}")
    
    # Change to Anthropic
    configure_llm_anthropic(
        api_key="your-anthropic-key",
        model="claude-3-opus-20240229",
        max_tokens=2048,
        temperature=0.5
    )
    
    config = get_llm_config()
    print(f"Updated Global Provider: {config.provider.value}")
    print(f"Updated Global Model: {config.model}")
    print()


def example_validation():
    """Example of configuration validation."""
    print("=== Configuration Validation Example ===")
    
    # Test validation with a valid configuration first
    valid_config = LLMConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
        temperature=0.7,
        top_p=1.0,
        max_tokens=1024
    )
    
    errors = valid_config.validate()
    print("Valid Configuration Errors:")
    if errors:
        for error in errors:
            print(f"  - {error}")
    else:
        print("  - No errors (configuration is valid)")
    
    # Test individual validation scenarios
    print("\nTesting individual validation scenarios:")
    
    # Test missing API key
    config_no_key = LLMConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
        temperature=0.7
    )
    errors = config_no_key.validate()
    print("Missing API key errors:")
    for error in errors:
        print(f"  - {error}")
    
    # Test invalid temperature (we'll catch this in validation, not __post_init__)
    try:
        config_invalid_temp = LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4o",
            temperature=0.7  # Start with valid value
        )
        # Manually set invalid value after creation
        config_invalid_temp.temperature = 3.0
        errors = config_invalid_temp.validate()
        print("Invalid temperature errors:")
        for error in errors:
            print(f"  - {error}")
    except Exception as e:
        print(f"  - Caught exception: {e}")
    
    print()


def example_request_parameters():
    """Example of getting request parameters."""
    print("=== Request Parameters Example ===")
    
    config = LLMConfig.openai(
        api_key="your-key",
        model="gpt-4o",
        max_tokens=1024,
        temperature=0.7,
        stream=True
    )
    
    # Get parameters for API request
    params = config.get_request_params()
    print("Request Parameters:")
    for key, value in params.items():
        print(f"  {key}: {value}")
    
    # Get client configuration
    client_config = config.get_client_config()
    print("\nClient Configuration:")
    for key, value in client_config.items():
        if key == 'api_key':
            print(f"  {key}: {'*' * 10}")  # Hide API key
        else:
            print(f"  {key}: {value}")
    print()


def example_provider_specific_configs():
    """Example of provider-specific configurations."""
    print("=== Provider-Specific Configurations ===")
    
    # OpenAI configuration
    openai_config = LLMConfig.openai(
        api_key="your-openai-key",
        model="gpt-4o",
        max_tokens=1024
    )
    print(f"OpenAI: {openai_config}")
    
    # Anthropic configuration
    anthropic_config = LLMConfig.anthropic(
        api_key="your-anthropic-key",
        model="claude-3-opus-20240229",
        max_tokens=2048
    )
    print(f"Anthropic: {anthropic_config}")
    
    # Google configuration
    google_config = LLMConfig.google(
        api_key="your-google-key",
        model="gemini-1.5-pro",
        max_tokens=1024
    )
    print(f"Google: {google_config}")
    print()


def main():
    """Run all examples."""
    print("SeedCore LLM Configuration Examples")
    print("=" * 50)
    print()
    
    try:
        example_basic_configuration()
        example_environment_configuration()
        example_global_configuration()
        example_validation()
        example_request_parameters()
        example_provider_specific_configs()
        
        print("All examples completed successfully!")
        
    except Exception as e:
        print(f"Error running examples: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 