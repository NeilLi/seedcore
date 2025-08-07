"""
Cognitive task registry and plugin system for SeedCore.

This module provides a comprehensive extensibility system for adding new
cognitive task types and signatures without modifying core code.
"""

import logging
from typing import Dict, Any, Optional, Type, Callable, List
from dataclasses import dataclass
from enum import Enum
import importlib
import inspect
from pathlib import Path

logger = logging.getLogger(__name__)


class CognitivePluginType(Enum):
    """Types of cognitive plugins."""
    SIGNATURE = "signature"
    HANDLER = "handler"
    VALIDATOR = "validator"
    PROCESSOR = "processor"


@dataclass
class CognitivePlugin:
    """Represents a cognitive plugin."""
    name: str
    plugin_type: CognitivePluginType
    task_type: str
    handler: Callable
    description: str
    version: str = "1.0.0"
    author: str = "unknown"
    dependencies: List[str] = None
    config_schema: Dict[str, Any] = None


class CognitiveRegistry:
    """
    Registry for cognitive task types and plugins.
    
    This class provides a plugin system for extending cognitive capabilities
    without modifying core code.
    """
    
    def __init__(self):
        self._plugins: Dict[str, CognitivePlugin] = {}
        self._task_handlers: Dict[str, Callable] = {}
        self._validators: Dict[str, Callable] = {}
        self._processors: Dict[str, Callable] = {}
        self._signatures: Dict[str, Type] = {}
        
        logger.info("✅ Cognitive registry initialized")
    
    def register_plugin(self, plugin: CognitivePlugin) -> bool:
        """
        Register a cognitive plugin.
        
        Args:
            plugin: The plugin to register
            
        Returns:
            True if registration was successful
        """
        try:
            # Validate plugin
            if not self._validate_plugin(plugin):
                return False
            
            # Register based on type
            if plugin.plugin_type == CognitivePluginType.SIGNATURE:
                self._signatures[plugin.task_type] = plugin.handler
            elif plugin.plugin_type == CognitivePluginType.HANDLER:
                self._task_handlers[plugin.task_type] = plugin.handler
            elif plugin.plugin_type == CognitivePluginType.VALIDATOR:
                self._validators[plugin.task_type] = plugin.handler
            elif plugin.plugin_type == CognitivePluginType.PROCESSOR:
                self._processors[plugin.task_type] = plugin.handler
            
            # Store plugin metadata
            self._plugins[plugin.name] = plugin
            
            logger.info(f"✅ Registered cognitive plugin: {plugin.name} ({plugin.plugin_type.value})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to register plugin {plugin.name}: {e}")
            return False
    
    def register_signature(self, task_type: str, signature_class: Type, **kwargs) -> bool:
        """
        Register a DSPy signature for a task type.
        
        Args:
            task_type: Type of cognitive task
            signature_class: DSPy signature class
            **kwargs: Additional plugin metadata
            
        Returns:
            True if registration was successful
        """
        plugin = CognitivePlugin(
            name=f"{task_type}_signature",
            plugin_type=CognitivePluginType.SIGNATURE,
            task_type=task_type,
            handler=signature_class,
            description=kwargs.get("description", f"Signature for {task_type}"),
            version=kwargs.get("version", "1.0.0"),
            author=kwargs.get("author", "unknown"),
            dependencies=kwargs.get("dependencies", []),
            config_schema=kwargs.get("config_schema", {})
        )
        
        return self.register_plugin(plugin)
    
    def register_handler(self, task_type: str, handler_func: Callable, **kwargs) -> bool:
        """
        Register a handler function for a task type.
        
        Args:
            task_type: Type of cognitive task
            handler_func: Handler function
            **kwargs: Additional plugin metadata
            
        Returns:
            True if registration was successful
        """
        plugin = CognitivePlugin(
            name=f"{task_type}_handler",
            plugin_type=CognitivePluginType.HANDLER,
            task_type=task_type,
            handler=handler_func,
            description=kwargs.get("description", f"Handler for {task_type}"),
            version=kwargs.get("version", "1.0.0"),
            author=kwargs.get("author", "unknown"),
            dependencies=kwargs.get("dependencies", []),
            config_schema=kwargs.get("config_schema", {})
        )
        
        return self.register_plugin(plugin)
    
    def register_validator(self, task_type: str, validator_func: Callable, **kwargs) -> bool:
        """
        Register a validator function for a task type.
        
        Args:
            task_type: Type of cognitive task
            validator_func: Validator function
            **kwargs: Additional plugin metadata
            
        Returns:
            True if registration was successful
        """
        plugin = CognitivePlugin(
            name=f"{task_type}_validator",
            plugin_type=CognitivePluginType.VALIDATOR,
            task_type=task_type,
            handler=validator_func,
            description=kwargs.get("description", f"Validator for {task_type}"),
            version=kwargs.get("version", "1.0.0"),
            author=kwargs.get("author", "unknown"),
            dependencies=kwargs.get("dependencies", []),
            config_schema=kwargs.get("config_schema", {})
        )
        
        return self.register_plugin(plugin)
    
    def register_processor(self, task_type: str, processor_func: Callable, **kwargs) -> bool:
        """
        Register a processor function for a task type.
        
        Args:
            task_type: Type of cognitive task
            processor_func: Processor function
            **kwargs: Additional plugin metadata
            
        Returns:
            True if registration was successful
        """
        plugin = CognitivePlugin(
            name=f"{task_type}_processor",
            plugin_type=CognitivePluginType.PROCESSOR,
            task_type=task_type,
            handler=processor_func,
            description=kwargs.get("description", f"Processor for {task_type}"),
            version=kwargs.get("version", "1.0.0"),
            author=kwargs.get("author", "unknown"),
            dependencies=kwargs.get("dependencies", []),
            config_schema=kwargs.get("config_schema", {})
        )
        
        return self.register_plugin(plugin)
    
    def get_signature(self, task_type: str) -> Optional[Type]:
        """Get signature class for a task type."""
        return self._signatures.get(task_type)
    
    def get_handler(self, task_type: str) -> Optional[Callable]:
        """Get handler function for a task type."""
        return self._task_handlers.get(task_type)
    
    def get_validator(self, task_type: str) -> Optional[Callable]:
        """Get validator function for a task type."""
        return self._validators.get(task_type)
    
    def get_processor(self, task_type: str) -> Optional[Callable]:
        """Get processor function for a task type."""
        return self._processors.get(task_type)
    
    def list_plugins(self, plugin_type: Optional[CognitivePluginType] = None) -> List[CognitivePlugin]:
        """List registered plugins, optionally filtered by type."""
        if plugin_type is None:
            return list(self._plugins.values())
        
        return [p for p in self._plugins.values() if p.plugin_type == plugin_type]
    
    def list_task_types(self) -> List[str]:
        """List all registered task types."""
        return list(set(p.task_type for p in self._plugins.values()))
    
    def unregister_plugin(self, plugin_name: str) -> bool:
        """
        Unregister a plugin.
        
        Args:
            plugin_name: Name of the plugin to unregister
            
        Returns:
            True if unregistration was successful
        """
        if plugin_name not in self._plugins:
            return False
        
        plugin = self._plugins[plugin_name]
        
        # Remove from appropriate registry
        if plugin.plugin_type == CognitivePluginType.SIGNATURE:
            self._signatures.pop(plugin.task_type, None)
        elif plugin.plugin_type == CognitivePluginType.HANDLER:
            self._task_handlers.pop(plugin.task_type, None)
        elif plugin.plugin_type == CognitivePluginType.VALIDATOR:
            self._validators.pop(plugin.task_type, None)
        elif plugin.plugin_type == CognitivePluginType.PROCESSOR:
            self._processors.pop(plugin.task_type, None)
        
        # Remove plugin metadata
        del self._plugins[plugin_name]
        
        logger.info(f"✅ Unregistered cognitive plugin: {plugin_name}")
        return True
    
    def _validate_plugin(self, plugin: CognitivePlugin) -> bool:
        """Validate a plugin before registration."""
        # Check required fields
        if not plugin.name or not plugin.task_type or not plugin.handler:
            logger.error(f"Plugin {plugin.name} missing required fields")
            return False
        
        # Check for name conflicts
        if plugin.name in self._plugins:
            logger.error(f"Plugin name {plugin.name} already registered")
            return False
        
        # Validate handler function
        if not callable(plugin.handler):
            logger.error(f"Plugin {plugin.name} handler is not callable")
            return False
        
        # Check dependencies if specified
        if plugin.dependencies:
            for dep in plugin.dependencies:
                try:
                    importlib.import_module(dep)
                except ImportError:
                    logger.error(f"Plugin {plugin.name} missing dependency: {dep}")
                    return False
        
        return True
    
    def load_plugins_from_directory(self, directory: str) -> int:
        """
        Load plugins from a directory.
        
        Args:
            directory: Directory containing plugin modules
            
        Returns:
            Number of plugins loaded
        """
        loaded_count = 0
        plugin_dir = Path(directory)
        
        if not plugin_dir.exists():
            logger.warning(f"Plugin directory does not exist: {directory}")
            return 0
        
        for plugin_file in plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            
            try:
                # Import plugin module
                module_name = plugin_file.stem
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Look for plugin registration functions
                if hasattr(module, "register_plugins"):
                    plugins = module.register_plugins()
                    for plugin in plugins:
                        if self.register_plugin(plugin):
                            loaded_count += 1
                
                logger.info(f"✅ Loaded plugin module: {module_name}")
                
            except Exception as e:
                logger.error(f"❌ Failed to load plugin from {plugin_file}: {e}")
        
        logger.info(f"✅ Loaded {loaded_count} plugins from {directory}")
        return loaded_count


# Global registry instance
_cognitive_registry: Optional[CognitiveRegistry] = None


def get_cognitive_registry() -> CognitiveRegistry:
    """Get the global cognitive registry instance."""
    global _cognitive_registry
    if _cognitive_registry is None:
        _cognitive_registry = CognitiveRegistry()
    return _cognitive_registry


def register_cognitive_signature(task_type: str, signature_class: Type, **kwargs) -> bool:
    """Register a cognitive signature."""
    registry = get_cognitive_registry()
    return registry.register_signature(task_type, signature_class, **kwargs)


def register_cognitive_handler(task_type: str, handler_func: Callable, **kwargs) -> bool:
    """Register a cognitive handler."""
    registry = get_cognitive_registry()
    return registry.register_handler(task_type, handler_func, **kwargs)


def register_cognitive_validator(task_type: str, validator_func: Callable, **kwargs) -> bool:
    """Register a cognitive validator."""
    registry = get_cognitive_registry()
    return registry.register_validator(task_type, validator_func, **kwargs)


def register_cognitive_processor(task_type: str, processor_func: Callable, **kwargs) -> bool:
    """Register a cognitive processor."""
    registry = get_cognitive_registry()
    return registry.register_processor(task_type, processor_func, **kwargs)


def get_cognitive_signature(task_type: str) -> Optional[Type]:
    """Get a cognitive signature."""
    registry = get_cognitive_registry()
    return registry.get_signature(task_type)


def get_cognitive_handler(task_type: str) -> Optional[Callable]:
    """Get a cognitive handler."""
    registry = get_cognitive_registry()
    return registry.get_handler(task_type)


def list_cognitive_plugins(plugin_type: Optional[CognitivePluginType] = None) -> List[CognitivePlugin]:
    """List cognitive plugins."""
    registry = get_cognitive_registry()
    return registry.list_plugins(plugin_type)


def list_cognitive_task_types() -> List[str]:
    """List cognitive task types."""
    registry = get_cognitive_registry()
    return registry.list_task_types()


# Example plugin decorators for easy registration
def cognitive_signature(task_type: str, **kwargs):
    """Decorator to register a DSPy signature."""
    def decorator(signature_class: Type):
        register_cognitive_signature(task_type, signature_class, **kwargs)
        return signature_class
    return decorator


def cognitive_handler(task_type: str, **kwargs):
    """Decorator to register a handler function."""
    def decorator(handler_func: Callable):
        register_cognitive_handler(task_type, handler_func, **kwargs)
        return handler_func
    return decorator


def cognitive_validator(task_type: str, **kwargs):
    """Decorator to register a validator function."""
    def decorator(validator_func: Callable):
        register_cognitive_validator(task_type, validator_func, **kwargs)
        return validator_func
    return decorator


def cognitive_processor(task_type: str, **kwargs):
    """Decorator to register a processor function."""
    def decorator(processor_func: Callable):
        register_cognitive_processor(task_type, processor_func, **kwargs)
        return processor_func
    return decorator


# Example plugin module structure
"""
Example plugin module (plugins/custom_analysis.py):

import dspy
from seedcore.agents.cognitive_registry import (
    cognitive_signature, cognitive_handler, cognitive_validator
)

@cognitive_signature("custom_analysis", description="Custom analysis signature")
class CustomAnalysisSignature(dspy.Signature):
    input_data = dspy.InputField(desc="Input data for analysis")
    analysis_result = dspy.OutputField(desc="Analysis result")
    confidence = dspy.OutputField(desc="Confidence score")

@cognitive_handler("custom_analysis", description="Custom analysis handler")
def custom_analysis_handler(context):
    # Custom analysis logic
    return {"result": "analysis complete"}

@cognitive_validator("custom_analysis", description="Custom analysis validator")
def custom_analysis_validator(input_data):
    # Validation logic
    return True

def register_plugins():
    # Alternative registration method
    return [
        CognitivePlugin(
            name="custom_analysis_complete",
            plugin_type=CognitivePluginType.PROCESSOR,
            task_type="custom_analysis",
            handler=custom_processor,
            description="Complete custom analysis processor"
        )
    ]
""" 