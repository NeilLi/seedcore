"""
Security and secrets management for SeedCore.

This module provides secure handling of API keys and sensitive configuration.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    """Security configuration settings."""
    require_api_keys: bool = True
    validate_api_keys: bool = True
    mask_logs: bool = True
    max_key_length: int = 8  # Characters to show in logs


class SecurityManager:
    """Manages security and secrets for SeedCore."""
    
    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()
        self._validated_keys: Dict[str, bool] = {}
    
    def validate_api_key(self, key_name: str, key_value: Optional[str]) -> bool:
        """
        Validate that an API key is properly set and formatted.
        
        Args:
            key_name: Name of the API key (e.g., 'OPENAI_API_KEY')
            key_value: The API key value
            
        Returns:
            True if valid, False otherwise
        """
        if not key_value:
            logger.error(f"❌ {key_name} is not set")
            return False
        
        if not key_value.startswith(('sk-', 'pk-', 'Bearer ')):
            logger.warning(f"⚠️ {key_name} format may be incorrect (should start with 'sk-', 'pk-', or 'Bearer ')")
            # Don't fail on format warning, just log it
        
        # Basic length validation
        if len(key_value) < 10:
            logger.error(f"❌ {key_name} appears to be too short")
            return False
        
        self._validated_keys[key_name] = True
        logger.info(f"✅ {key_name} validated successfully")
        return True
    
    def get_api_key(self, key_name: str, required: bool = True) -> Optional[str]:
        """
        Get an API key from environment with validation.
        
        Args:
            key_name: Name of the environment variable
            required: Whether the key is required
            
        Returns:
            The API key value or None if not found/valid
        """
        key_value = os.getenv(key_name)
        
        if not key_value and required:
            logger.error(f"❌ Required API key {key_name} is not set")
            return None
        
        if self.config.validate_api_keys and key_value:
            if not self.validate_api_key(key_name, key_value):
                return None
        
        return key_value
    
    def mask_sensitive_data(self, data: str, key_name: str = "API_KEY") -> str:
        """
        Mask sensitive data in logs.
        
        Args:
            data: The data to mask
            key_name: Type of data being masked
            
        Returns:
            Masked version of the data
        """
        if not self.config.mask_logs or not data:
            return data
        
        if len(data) <= self.config.max_key_length:
            return "*" * len(data)
        
        return data[:self.config.max_key_length] + "*" * (len(data) - self.config.max_key_length)
    
    def validate_environment(self) -> Dict[str, bool]:
        """
        Validate all required API keys and environment variables.
        
        Returns:
            Dictionary of validation results
        """
        required_keys = [
            "OPENAI_API_KEY",
            # Add other required keys as needed
        ]
        
        optional_keys = [
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "LLM_API_KEY",
        ]
        
        results = {}
        
        # Validate required keys
        for key in required_keys:
            results[key] = self.get_api_key(key, required=True) is not None
        
        # Check optional keys
        for key in optional_keys:
            results[key] = self.get_api_key(key, required=False) is not None
        
        # Log summary
        failed_required = [k for k, v in results.items() if k in required_keys and not v]
        if failed_required:
            logger.error(f"❌ Failed to validate required API keys: {failed_required}")
        
        successful_optional = [k for k, v in results.items() if k in optional_keys and v]
        if successful_optional:
            logger.info(f"✅ Optional API keys found: {successful_optional}")
        
        return results
    
    def get_validation_status(self) -> Dict[str, Any]:
        """
        Get current validation status.
        
        Returns:
            Dictionary with validation status information
        """
        return {
            "validated_keys": self._validated_keys.copy(),
            "config": {
                "require_api_keys": self.config.require_api_keys,
                "validate_api_keys": self.config.validate_api_keys,
                "mask_logs": self.config.mask_logs
            }
        }


# Global security manager instance
_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """Get the global security manager instance."""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager


def validate_security_environment() -> Dict[str, bool]:
    """
    Validate the security environment.
    
    Returns:
        Dictionary of validation results
    """
    manager = get_security_manager()
    return manager.validate_environment()


def secure_log(message: str, sensitive_data: Optional[str] = None, key_name: str = "SENSITIVE") -> None:
    """
    Log a message with secure handling of sensitive data.
    
    Args:
        message: The message to log
        sensitive_data: Any sensitive data to mask
        key_name: Type of sensitive data
    """
    manager = get_security_manager()
    
    if sensitive_data:
        masked_data = manager.mask_sensitive_data(sensitive_data, key_name)
        message = message.replace(sensitive_data, masked_data)
    
    logger.info(message) 