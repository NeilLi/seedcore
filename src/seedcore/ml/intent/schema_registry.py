"""
Function Schema Registry for Intent Compilation

Manages function signatures and validation schemas for intent compilation.
This registry defines what functions are available and how to validate
generated function calls.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FunctionSchema:
    """Schema definition for a function that can be called via intent compilation."""

    function_name: str
    description: str
    parameters: Dict[str, Dict[str, Any]]  # JSON Schema format
    required: List[str] = None
    domain: str = "general"  # e.g., "device", "robot", "energy", "automation"
    vendor: Optional[str] = None  # e.g., "tuya", "matter", "knx"

    def __post_init__(self):
        if self.required is None:
            self.required = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary."""
        return asdict(self)

    def to_minified_string(self) -> str:
        """
        Convert schema to minified string representation for FunctionGemma prompts.
        
        This reduces token consumption by removing whitespace and formatting.
        Critical for low-latency inference.
        """
        # Minified format: name(required_params)[optional_params] description
        required_str = ",".join(self.required) if self.required else ""
        optional = [p for p in self.parameters.keys() if p not in (self.required or [])]
        optional_str = f"[{','.join(optional)}]" if optional else ""
        
        # Include parameter types in compact format
        param_types = ",".join([
            f"{name}:{spec.get('type','any')}" 
            for name, spec in self.parameters.items()
        ])
        
        return f"{self.function_name}({required_str}){optional_str}|{param_types}|{self.description}"

    def validate_arguments(self, arguments: Dict[str, Any]) -> tuple:
        """
        Validate arguments against this schema.
        Returns (is_valid, error_message).
        """
        # Check required parameters
        for param in self.required:
            if param not in arguments:
                return False, f"Missing required parameter: {param}"

        # Check parameter types (basic validation)
        for param_name, param_spec in self.parameters.items():
            if param_name in arguments:
                param_type = param_spec.get("type")
                value = arguments[param_name]

                if param_type == "string" and not isinstance(value, str):
                    return False, f"Parameter {param_name} must be a string"
                elif param_type == "integer" and not isinstance(value, int):
                    return False, f"Parameter {param_name} must be an integer"
                elif param_type == "number" and not isinstance(value, (int, float)):
                    return False, f"Parameter {param_name} must be a number"
                elif param_type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter {param_name} must be a boolean"
                elif param_type == "array" and not isinstance(value, list):
                    return False, f"Parameter {param_name} must be an array"
                elif param_type == "object" and not isinstance(value, dict):
                    return False, f"Parameter {param_name} must be an object"

        return True, None


class SchemaRegistry:
    """
    Registry for function schemas used in intent compilation.

    Loads schemas from:
    1. Built-in default schemas (device control, etc.)
    2. Config file (if provided)
    3. Runtime registration
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize schema registry with optional config file."""
        self.schemas: Dict[str, FunctionSchema] = {}
        self._load_default_schemas()
        if config_path:
            self._load_from_file(config_path)

    def _load_default_schemas(self):
        """Load default function schemas for common device/automation operations."""
        # Tuya device control schema
        self.register(
            FunctionSchema(
                function_name="tuya.send_command",
                description="Send command to Tuya smart device",
                parameters={
                    "device_id": {
                        "type": "string",
                        "description": "Tuya device ID",
                    },
                    "commands": {
                        "type": "array",
                        "description": "List of command objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "value": {"type": "any"},
                            },
                        },
                    },
                },
                required=["device_id", "commands"],
                domain="device",
                vendor="tuya",
            )
        )

        # Generic device control schema
        self.register(
            FunctionSchema(
                function_name="device.control",
                description="Control a smart device",
                parameters={
                    "device_id": {
                        "type": "string",
                        "description": "Device identifier",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action to perform (on, off, set, etc.)",
                    },
                    "value": {
                        "type": "any",
                        "description": "Optional value for the action",
                    },
                },
                required=["device_id", "action"],
                domain="device",
            )
        )

        # Energy policy schema
        self.register(
            FunctionSchema(
                function_name="energy.set_policy",
                description="Set energy management policy",
                parameters={
                    "policy_name": {
                        "type": "string",
                        "description": "Name of the policy",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Policy parameters",
                    },
                },
                required=["policy_name"],
                domain="energy",
            )
        )

        # EdgeGuardian alarm zone schema (T5 board)
        self.register(
            FunctionSchema(
                function_name="edgeguardian.trigger_alarm_zone",
                description="Trigger alarm zone on EdgeGuardian T5 board",
                parameters={
                    "zone_id": {
                        "type": "integer",
                        "description": "Alarm zone ID (0-7)",
                    },
                    "severity": {
                        "type": "string",
                        "description": "Severity level (low, medium, high, critical)",
                    },
                    "duration_ms": {
                        "type": "integer",
                        "description": "Alarm duration in milliseconds",
                    },
                },
                required=["zone_id", "severity"],
                domain="edgeguardian",
            )
        )

        # Vision stream analysis schema (OV2640)
        self.register(
            FunctionSchema(
                function_name="vision.analyze_stream",
                description="Analyze video stream from OV2640 camera",
                parameters={
                    "duration": {
                        "type": "integer",
                        "description": "Analysis duration in seconds",
                    },
                    "object_filter": {
                        "type": "array",
                        "description": "List of object classes to detect",
                        "items": {"type": "string"},
                    },
                    "confidence_threshold": {
                        "type": "number",
                        "description": "Minimum confidence threshold (0.0-1.0)",
                    },
                },
                required=["duration"],
                domain="vision",
            )
        )

        # Power management schema (Tuya Cloud energy APIs)
        self.register(
            FunctionSchema(
                function_name="power.set_energy_policy",
                description="Set energy policy mode via Tuya Cloud APIs",
                parameters={
                    "mode": {
                        "type": "string",
                        "description": "Energy mode (eco, balanced, performance)",
                    },
                    "device_ids": {
                        "type": "array",
                        "description": "List of device IDs to apply policy to",
                        "items": {"type": "string"},
                    },
                    "max_power_watts": {
                        "type": "integer",
                        "description": "Maximum power consumption in watts",
                    },
                },
                required=["mode"],
                domain="power",
                vendor="tuya",
            )
        )

        logger.info(f"✅ Loaded {len(self.schemas)} default function schemas")

    def _load_from_file(self, config_path: str):
        """Load schemas from JSON config file."""
        try:
            path = Path(config_path)
            if not path.exists():
                logger.warning(f"Schema config file not found: {config_path}")
                return

            with open(path, "r") as f:
                data = json.load(f)

            schemas = data.get("schemas", [])
            for schema_data in schemas:
                schema = FunctionSchema(**schema_data)
                self.register(schema)

            logger.info(f"✅ Loaded {len(schemas)} schemas from {config_path}")
        except Exception as e:
            logger.error(f"Failed to load schemas from {config_path}: {e}")

    def register(self, schema: FunctionSchema):
        """Register a function schema."""
        self.schemas[schema.function_name] = schema
        logger.debug(f"Registered schema: {schema.function_name}")

    def get(self, function_name: str) -> Optional[FunctionSchema]:
        """Get schema for a function name."""
        return self.schemas.get(function_name)

    def list_all(self) -> List[FunctionSchema]:
        """List all registered schemas."""
        return list(self.schemas.values())

    def list_by_domain(self, domain: str) -> List[FunctionSchema]:
        """List schemas for a specific domain."""
        return [s for s in self.schemas.values() if s.domain == domain]

    def list_by_vendor(self, vendor: str) -> List[FunctionSchema]:
        """List schemas for a specific vendor."""
        return [s for s in self.schemas.values() if s.vendor == vendor]

    def get_schema_dict(self, function_name: str) -> Optional[Dict[str, Any]]:
        """Get schema as dictionary."""
        schema = self.get(function_name)
        return schema.to_dict() if schema else None

    def get_schemas_as_minified_strings(self, domain: Optional[str] = None) -> List[str]:
        """
        Get all schemas (or filtered by domain) as minified strings for FunctionGemma prompts.
        
        This is critical for prompt efficiency - passing raw JSON consumes unnecessary tokens.
        """
        schemas = self.list_by_domain(domain) if domain else self.list_all()
        return [s.to_minified_string() for s in schemas]


# Singleton instance
_schema_registry: Optional[SchemaRegistry] = None


def get_schema_registry(config_path: Optional[str] = None) -> SchemaRegistry:
    """Get or create singleton schema registry."""
    global _schema_registry
    if _schema_registry is None:
        _schema_registry = SchemaRegistry(config_path)
    return _schema_registry

