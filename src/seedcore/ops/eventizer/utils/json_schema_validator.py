#!/usr/bin/env python3
"""
JSON Schema Validator for Eventizer Patterns

Validates eventizer_patterns.json files against the defined JSON Schema.
Provides detailed error reporting and validation statistics.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Try to import jsonschema, fall back to basic validation if not available
try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
    JSONSCHEMA_AVAILABLE = True
    logger.debug("jsonschema available, using full validation")
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not available, using basic validation only")


@dataclass
class ValidationError:
    """Represents a validation error."""
    path: str
    message: str
    severity: str = "error"  # error, warning, info


@dataclass
class ValidationResult:
    """Result of JSON Schema validation."""
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    stats: Dict[str, Any]


class EventizerPatternsValidator:
    """
    Validator for eventizer patterns JSON files.
    
    Provides comprehensive validation against the JSON Schema with
    detailed error reporting and statistics.
    """
    
    def __init__(self, schema_path: Optional[Path] = None):
        """
        Initialize the validator.
        
        Args:
            schema_path: Path to the JSON Schema file. If None, uses the default schema.
        """
        self.schema_path = schema_path or self._get_default_schema_path()
        self.schema = self._load_schema()
        self.validator = self._create_validator() if JSONSCHEMA_AVAILABLE else None
    
    def _get_default_schema_path(self) -> Path:
        """Get the default schema path."""
        # Look for schema in config directory (project root)
        project_root = Path(__file__).parent.parent.parent.parent.parent
        return project_root / "config" / "eventizer_patterns_schema.json"
    
    def _load_schema(self) -> Dict[str, Any]:
        """Load the JSON Schema."""
        try:
            with open(self.schema_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Schema file not found: {self.schema_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in schema file: {e}")
            raise
    
    def _create_validator(self) -> Optional[Draft7Validator]:
        """Create a JSON Schema validator."""
        if not JSONSCHEMA_AVAILABLE:
            return None
        
        try:
            return Draft7Validator(self.schema)
        except Exception as e:
            logger.error(f"Failed to create validator: {e}")
            return None
    
    def validate_file(self, file_path: Union[str, Path]) -> ValidationResult:
        """
        Validate a patterns file against the schema.
        
        Args:
            file_path: Path to the patterns JSON file
            
        Returns:
            ValidationResult with validation status and details
        """
        file_path = Path(file_path)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return ValidationResult(
                is_valid=False,
                errors=[ValidationError("file", f"File not found: {file_path}")],
                warnings=[],
                stats={}
            )
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                errors=[ValidationError("file", f"Invalid JSON: {e}")],
                warnings=[],
                stats={}
            )
        
        return self.validate_data(data)
    
    def validate_data(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate pattern data against the schema.
        
        Args:
            data: The pattern data to validate
            
        Returns:
            ValidationResult with validation status and details
        """
        errors = []
        warnings = []
        stats = {}
        
        if not JSONSCHEMA_AVAILABLE:
            # Basic validation without jsonschema
            return self._basic_validation(data, errors, warnings, stats)
        
        # Full validation with jsonschema
        if self.validator is None:
            errors.append(ValidationError("validator", "Validator not available"))
            return ValidationResult(False, errors, warnings, stats)
        
        try:
            # Validate against schema
            validation_errors = list(self.validator.iter_errors(data))
            
            for error in validation_errors:
                path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                errors.append(ValidationError(
                    path=path,
                    message=error.message,
                    severity="error"
                ))
            
            # Additional custom validations
            self._custom_validations(data, errors, warnings)
            
            # Generate statistics
            stats = self._generate_stats(data)
            
            is_valid = len(errors) == 0
            
        except Exception as e:
            errors.append(ValidationError("validation", f"Validation failed: {e}"))
            is_valid = False
        
        return ValidationResult(is_valid, errors, warnings, stats)
    
    def _basic_validation(self, data: Dict[str, Any], errors: List[ValidationError], 
                         warnings: List[ValidationError], stats: Dict[str, Any]) -> ValidationResult:
        """Basic validation without jsonschema library."""
        # Check required fields
        required_fields = ["version", "regex_patterns", "keyword_patterns", "entity_patterns"]
        for field in required_fields:
            if field not in data:
                errors.append(ValidationError(field, f"Required field '{field}' is missing"))
        
        # Basic type checking
        if "version" in data and not isinstance(data["version"], str):
            errors.append(ValidationError("version", "Version must be a string"))
        
        if "regex_patterns" in data and not isinstance(data["regex_patterns"], list):
            errors.append(ValidationError("regex_patterns", "Regex patterns must be an array"))
        
        if "keyword_patterns" in data and not isinstance(data["keyword_patterns"], list):
            errors.append(ValidationError("keyword_patterns", "Keyword patterns must be an array"))
        
        if "entity_patterns" in data and not isinstance(data["entity_patterns"], list):
            errors.append(ValidationError("entity_patterns", "Entity patterns must be an array"))
        
        # Generate basic stats
        stats = self._generate_stats(data)
        
        return ValidationResult(len(errors) == 0, errors, warnings, stats)
    
    def _custom_validations(self, data: Dict[str, Any], errors: List[ValidationError], 
                           warnings: List[ValidationError]) -> None:
        """Perform custom validations beyond JSON Schema."""
        # Check for duplicate pattern IDs
        all_ids = set()
        
        for pattern_type in ["regex_patterns", "keyword_patterns", "entity_patterns"]:
            if pattern_type not in data:
                continue
                
            for i, pattern in enumerate(data[pattern_type]):
                if not isinstance(pattern, dict):
                    continue
                
                pattern_id = pattern.get("id")
                if not pattern_id:
                    errors.append(ValidationError(
                        f"{pattern_type}[{i}].id",
                        "Pattern ID is required"
                    ))
                    continue
                
                if pattern_id in all_ids:
                    errors.append(ValidationError(
                        f"{pattern_type}[{i}].id",
                        f"Duplicate pattern ID: {pattern_id}"
                    ))
                else:
                    all_ids.add(pattern_id)
        
        # Check pattern limits
        settings = data.get("settings", {})
        max_patterns = settings.get("max_patterns", 10000)
        
        total_patterns = sum(len(data.get(pt, [])) for pt in ["regex_patterns", "keyword_patterns", "entity_patterns"])
        if total_patterns > max_patterns:
            warnings.append(ValidationError(
                "patterns",
                f"Total patterns ({total_patterns}) exceeds recommended limit ({max_patterns})"
            ))
        
        # Validate regex patterns
        if "regex_patterns" in data:
            self._validate_regex_patterns(data["regex_patterns"], errors, warnings)
        
        # Validate keyword patterns
        if "keyword_patterns" in data:
            self._validate_keyword_patterns(data["keyword_patterns"], errors, warnings)
        
        # Validate entity patterns
        if "entity_patterns" in data:
            self._validate_entity_patterns(data["entity_patterns"], errors, warnings)
    
    def _validate_regex_patterns(self, patterns: List[Dict[str, Any]], 
                                errors: List[ValidationError], warnings: List[ValidationError]) -> None:
        """Validate regex patterns."""
        import re
        
        for i, pattern in enumerate(patterns):
            pattern_id = pattern.get("id", f"regex_{i}")
            regex = pattern.get("pattern", "")
            
            if not regex:
                errors.append(ValidationError(
                    f"regex_patterns[{i}].pattern",
                    "Regex pattern cannot be empty"
                ))
                continue
            
            try:
                flags = pattern.get("flags", 0)
                re.compile(regex, flags)
            except re.error as e:
                errors.append(ValidationError(
                    f"regex_patterns[{i}].pattern",
                    f"Invalid regex pattern: {e}"
                ))
    
    def _validate_keyword_patterns(self, patterns: List[Dict[str, Any]], 
                                  errors: List[ValidationError], warnings: List[ValidationError]) -> None:
        """Validate keyword patterns."""
        for i, pattern in enumerate(patterns):
            pattern_id = pattern.get("id", f"keyword_{i}")
            keywords = pattern.get("keywords", [])
            
            if not keywords:
                errors.append(ValidationError(
                    f"keyword_patterns[{i}].keywords",
                    "Keywords list cannot be empty"
                ))
                continue
            
            # Check for empty keywords
            empty_keywords = [kw for kw in keywords if not kw.strip()]
            if empty_keywords:
                warnings.append(ValidationError(
                    f"keyword_patterns[{i}].keywords",
                    f"Found {len(empty_keywords)} empty keywords"
                ))
    
    def _validate_entity_patterns(self, patterns: List[Dict[str, Any]], 
                                 errors: List[ValidationError], warnings: List[ValidationError]) -> None:
        """Validate entity patterns."""
        for i, pattern in enumerate(patterns):
            pattern_id = pattern.get("id", f"entity_{i}")
            entity_patterns = pattern.get("patterns", [])
            
            if not entity_patterns:
                errors.append(ValidationError(
                    f"entity_patterns[{i}].patterns",
                    "Entity patterns list cannot be empty"
                ))
                continue
            
            # Validate each sub-pattern
            for j, sub_pattern in enumerate(entity_patterns):
                if not isinstance(sub_pattern, dict):
                    errors.append(ValidationError(
                        f"entity_patterns[{i}].patterns[{j}]",
                        "Entity sub-pattern must be an object"
                    ))
                    continue
                
                has_regex = "regex" in sub_pattern
                has_keywords = "keywords" in sub_pattern
                
                if not has_regex and not has_keywords:
                    errors.append(ValidationError(
                        f"entity_patterns[{i}].patterns[{j}]",
                        "Entity sub-pattern must have either 'regex' or 'keywords'"
                    ))
    
    def _generate_stats(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate validation statistics."""
        stats = {
            "total_patterns": 0,
            "regex_patterns": 0,
            "keyword_patterns": 0,
            "entity_patterns": 0,
            "enabled_patterns": 0,
            "disabled_patterns": 0,
            "version": data.get("version", "unknown"),
            "has_metadata": "metadata" in data,
            "has_settings": "settings" in data
        }
        
        for pattern_type in ["regex_patterns", "keyword_patterns", "entity_patterns"]:
            patterns = data.get(pattern_type, [])
            count = len(patterns)
            stats[f"{pattern_type}"] = count
            stats["total_patterns"] += count
            
            # Count enabled/disabled patterns
            for pattern in patterns:
                if isinstance(pattern, dict):
                    if pattern.get("enabled", True):
                        stats["enabled_patterns"] += 1
                    else:
                        stats["disabled_patterns"] += 1
        
        return stats


def validate_patterns_file(file_path: Union[str, Path]) -> ValidationResult:
    """
    Convenience function to validate a patterns file.
    
    Args:
        file_path: Path to the patterns JSON file
        
    Returns:
        ValidationResult with validation status and details
    """
    validator = EventizerPatternsValidator()
    return validator.validate_file(file_path)


def validate_patterns_data(data: Dict[str, Any]) -> ValidationResult:
    """
    Convenience function to validate pattern data.
    
    Args:
        data: The pattern data to validate
        
    Returns:
        ValidationResult with validation status and details
    """
    validator = EventizerPatternsValidator()
    return validator.validate_data(data)


def validate_enhanced_features(file_path: Union[str, Path]) -> bool:
    """
    Validate enhanced features like budget controls and domain support.
    
    Args:
        file_path: Path to the patterns JSON file
        
    Returns:
        True if enhanced features are valid, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate budget controls
        settings = data.get("settings", {})
        budget_soft = settings.get("budget_ms_soft", 40)
        budget_hard = settings.get("budget_ms_hard", 100)
        
        if budget_soft >= budget_hard:
            logger.error("budget_ms_soft must be less than budget_ms_hard")
            return False
        
        if budget_soft < 10 or budget_hard > 1000:
            logger.warning("Budget values seem unusual (soft: %d, hard: %d)", budget_soft, budget_hard)
        
        # Validate domain coverage
        metadata = data.get("metadata", {})
        domains = metadata.get("domains", [])
        if not domains:
            logger.warning("No domains specified in metadata")
        
        # Validate pattern distribution across domains
        regex_patterns = data.get("regex_patterns", [])
        keyword_patterns = data.get("keyword_patterns", [])
        
        domain_coverage = set()
        for pattern in regex_patterns + keyword_patterns:
            event_types = pattern.get("event_types", [])
            for event_type in event_types:
                # Map event types to domains
                if event_type in ["hvac", "security", "vip", "allergen", "emergency", "maintenance"]:
                    domain_coverage.add("hotel_ops")
                elif event_type in ["fraud"]:
                    domain_coverage.add("fintech")
                elif event_type in ["healthcare"]:
                    domain_coverage.add("healthcare")
                elif event_type in ["robotics"]:
                    domain_coverage.add("robotics")
        
        if not domain_coverage:
            logger.warning("No domain coverage detected in patterns")
        
        # Validate emits_tags and emits_attributes usage
        emits_usage = 0
        for pattern in regex_patterns + keyword_patterns:
            if pattern.get("emits_tags") or pattern.get("emits_attributes"):
                emits_usage += 1
        
        if emits_usage == 0:
            logger.info("No patterns use emits_tags or emits_attributes (PKG integration)")
        else:
            logger.info(f"{emits_usage} patterns use PKG integration features")
        
        return True
        
    except Exception as e:
        logger.error(f"Enhanced feature validation error: {e}")
        return False
