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
    import jsonschema  # pyright: ignore[reportMissingModuleSource, reportUnusedImport]  # noqa: F401
    from jsonschema import Draft7Validator  # pyright: ignore[reportMissingModuleSource]
    JSONSCHEMA_AVAILABLE = True
    logger.debug("jsonschema available, using full validation")
except ImportError:
    JSONSCHEMA_AVAILABLE = False
    logger.warning("jsonschema not available, using basic validation only")


@dataclass
class SchemaValidationIssue:
    """Represents a validation error, warning, or info message."""
    path: str
    message: str
    severity: str = "error"  # error, warning, info


@dataclass
class ValidationResult:
    """Result of JSON Schema validation."""
    is_valid: bool
    errors: List[SchemaValidationIssue]
    warnings: List[SchemaValidationIssue]
    stats: Dict[str, Any]
    file_path: Optional[str] = None


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
        """Get the default schema path by searching upward for config directory."""
        # Start from current file and search upward for config directory
        current = Path(__file__).resolve()
        while current.parent != current:  # Stop at filesystem root
            config_dir = current / "config"
            schema_file = config_dir / "eventizer_patterns_schema.json"
            if schema_file.exists():
                return schema_file
            current = current.parent
        
        # Fallback to original logic if config not found
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
                errors=[SchemaValidationIssue("file", f"File not found: {file_path}")],
                warnings=[],
                stats={},
                file_path=str(file_path)
            )
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                errors=[SchemaValidationIssue("file", f"Invalid JSON: {e}")],
                warnings=[],
                stats={},
                file_path=str(file_path)
            )
        
        result = self.validate_data(data)
        result.file_path = str(file_path)
        return result
    
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
            errors.append(SchemaValidationIssue("validator", "Validator not available"))
            return ValidationResult(False, errors, warnings, stats)
        
        try:
            # Validate against schema
            validation_errors = list(self.validator.iter_errors(data))
            
            for error in validation_errors:
                path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
                # Check if error has severity hint (jsonschema doesn't support this natively,
                # but we can infer from error type or message)
                severity = "error"
                if hasattr(error, "severity"):
                    severity = error.severity
                errors.append(SchemaValidationIssue(
                    path=path,
                    message=error.message,
                    severity=severity
                ))
            
            # Additional custom validations
            self._custom_validations(data, errors, warnings)
            
            # Generate statistics
            stats = self._generate_stats(data)
            
            is_valid = len(errors) == 0
            
        except Exception as e:
            errors.append(SchemaValidationIssue("validation", f"Validation failed: {e}"))
            is_valid = False
        
        return ValidationResult(is_valid, errors, warnings, stats)
    
    def _basic_validation(self, data: Dict[str, Any], errors: List[SchemaValidationIssue], 
                         warnings: List[SchemaValidationIssue], stats: Dict[str, Any]) -> ValidationResult:
        """Basic validation without jsonschema library."""
        # Check required fields
        required_fields = ["version", "regex_patterns", "keyword_patterns", "entity_patterns"]
        for field in required_fields:
            if field not in data:
                errors.append(SchemaValidationIssue(field, f"Required field '{field}' is missing"))
        
        # Basic type checking
        if "version" in data and not isinstance(data["version"], str):
            errors.append(SchemaValidationIssue("version", "Version must be a string"))
        
        if "regex_patterns" in data and not isinstance(data["regex_patterns"], list):
            errors.append(SchemaValidationIssue("regex_patterns", "Regex patterns must be an array"))
        
        if "keyword_patterns" in data and not isinstance(data["keyword_patterns"], list):
            errors.append(SchemaValidationIssue("keyword_patterns", "Keyword patterns must be an array"))
        
        if "entity_patterns" in data and not isinstance(data["entity_patterns"], list):
            errors.append(SchemaValidationIssue("entity_patterns", "Entity patterns must be an array"))
        
        # Perform custom validations (same as full validation)
        self._custom_validations(data, errors, warnings)
        
        # Generate basic stats
        stats = self._generate_stats(data)
        
        return ValidationResult(len(errors) == 0, errors, warnings, stats)
    
    def _custom_validations(self, data: Dict[str, Any], errors: List[SchemaValidationIssue], 
                           warnings: List[SchemaValidationIssue]) -> None:
        """Perform custom validations beyond JSON Schema."""
        # Check for duplicate pattern IDs
        all_ids = set()
        
        for pattern_type in ["regex_patterns", "keyword_patterns", "entity_patterns"]:
            if pattern_type not in data:
                continue
                
            for i, pattern in enumerate(data[pattern_type]):
                if not isinstance(pattern, dict):
                    continue
                
                # Set default ID if missing
                pattern_id = pattern.setdefault("id", f"{pattern_type}_{i}")
                
                if pattern_id in all_ids:
                    errors.append(SchemaValidationIssue(
                        f"{pattern_type}[{i}].id",
                        f"Duplicate pattern ID: {pattern_id}"
                    ))
                else:
                    all_ids.add(pattern_id)
        
        # Check pattern limits
        settings = data.get("settings", {})
        max_patterns = settings.get("max_patterns", 20000)
        
        total_patterns = sum(len(data.get(pt, [])) for pt in ["regex_patterns", "keyword_patterns", "entity_patterns"])
        if total_patterns > max_patterns:
            warnings.append(SchemaValidationIssue(
                "patterns",
                f"Total patterns ({total_patterns}) exceeds recommended limit ({max_patterns})",
                severity="warning"
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
    
    def _require_type(self, value: Any, expected_type: type, path: str, 
                     errors: List[SchemaValidationIssue]) -> bool:
        """Helper to check if value is of expected type."""
        if not isinstance(value, expected_type):
            errors.append(SchemaValidationIssue(
                path,
                f"Expected {expected_type.__name__}, got {type(value).__name__}"
            ))
            return False
        return True
    
    def _validate_regex_patterns(self, patterns: List[Dict[str, Any]], 
                                errors: List[SchemaValidationIssue], warnings: List[SchemaValidationIssue]) -> None:
        """Validate regex patterns."""
        import re
        
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                errors.append(SchemaValidationIssue(
                    f"regex_patterns[{i}]",
                    "Pattern must be an object"
                ))
                continue
            
            pattern.setdefault("id", f"regex_{i}")
            regex = pattern.get("pattern")
            
            # Type check: pattern must be a string
            if not isinstance(regex, str):
                errors.append(SchemaValidationIssue(
                    f"regex_patterns[{i}].pattern",
                    f"Regex pattern must be a string (got {type(regex).__name__})"
                ))
                continue
            
            if not regex.strip():
                errors.append(SchemaValidationIssue(
                    f"regex_patterns[{i}].pattern",
                    "Regex pattern must be a non-empty string"
                ))
                continue
            
            # Validate flags type
            flags = pattern.get("flags", 0)
            if not isinstance(flags, int):
                errors.append(SchemaValidationIssue(
                    f"regex_patterns[{i}].flags",
                    f"flags must be an integer (got {type(flags).__name__})"
                ))
                continue
            
            # Compile regex to validate syntax
            try:
                re.compile(regex, flags)
            except re.error as e:
                errors.append(SchemaValidationIssue(
                    f"regex_patterns[{i}].pattern",
                    f"Invalid regex: {e}"
                ))
    
    def _validate_keyword_patterns(self, patterns: List[Dict[str, Any]], 
                                  errors: List[SchemaValidationIssue], warnings: List[SchemaValidationIssue]) -> None:
        """Validate keyword patterns."""
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                errors.append(SchemaValidationIssue(
                    f"keyword_patterns[{i}]",
                    "Pattern must be an object"
                ))
                continue
            
            pattern.setdefault("id", f"keyword_{i}")
            keywords = pattern.get("keywords")
            
            # Type check: keywords must be a list
            if not isinstance(keywords, list):
                errors.append(SchemaValidationIssue(
                    f"keyword_patterns[{i}].keywords",
                    f"Keywords must be a list (got {type(keywords).__name__})"
                ))
                continue
            
            if len(keywords) == 0:
                errors.append(SchemaValidationIssue(
                    f"keyword_patterns[{i}].keywords",
                    "Keywords must be a non-empty list"
                ))
                continue
            
            # Validate each keyword is a string
            invalid_keywords = [
                kw for kw in keywords
                if not isinstance(kw, str) or not kw.strip()
            ]
            
            if invalid_keywords:
                warnings.append(SchemaValidationIssue(
                    f"keyword_patterns[{i}].keywords",
                    f"{len(invalid_keywords)} invalid or empty keywords found",
                    severity="warning"
                ))
    
    def _validate_entity_patterns(self, patterns: List[Dict[str, Any]], 
                                 errors: List[SchemaValidationIssue], warnings: List[SchemaValidationIssue]) -> None:
        """Validate entity patterns."""
        import re
        
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, dict):
                errors.append(SchemaValidationIssue(
                    f"entity_patterns[{i}]",
                    "Pattern must be an object"
                ))
                continue
            
            pattern.setdefault("id", f"entity_{i}")
            sub_patterns = pattern.get("patterns")
            
            # Type check: patterns must be a list
            if not isinstance(sub_patterns, list):
                errors.append(SchemaValidationIssue(
                    f"entity_patterns[{i}].patterns",
                    f"Entity patterns must be a list (got {type(sub_patterns).__name__})"
                ))
                continue
            
            if len(sub_patterns) == 0:
                errors.append(SchemaValidationIssue(
                    f"entity_patterns[{i}].patterns",
                    "Entity patterns must be a non-empty list"
                ))
                continue
            
            # Validate each sub-pattern
            for j, sub in enumerate(sub_patterns):
                path = f"entity_patterns[{i}].patterns[{j}]"
                
                if not isinstance(sub, dict):
                    errors.append(SchemaValidationIssue(
                        path,
                        "Sub-pattern must be an object"
                    ))
                    continue
                
                regex_value = sub.get("regex")
                keywords_value = sub.get("keywords")
                
                has_regex = isinstance(regex_value, str)
                has_keywords = isinstance(keywords_value, list)
                
                if not has_regex and not has_keywords:
                    errors.append(SchemaValidationIssue(
                        path,
                        "Sub-pattern must have either 'regex' (string) or 'keywords' (list)"
                    ))
                    continue
                
                # Validate regex if present
                if has_regex:
                    if not regex_value.strip():
                        errors.append(SchemaValidationIssue(
                            path + ".regex",
                            "Regex pattern must be a non-empty string"
                        ))
                    else:
                        try:
                            re.compile(regex_value)
                        except re.error as exc:
                            errors.append(SchemaValidationIssue(
                                path + ".regex",
                                f"Invalid regex: {exc}"
                            ))
                
                # Validate keywords if present
                if has_keywords:
                    if len(keywords_value) == 0:
                        errors.append(SchemaValidationIssue(
                            path + ".keywords",
                            "Keywords list cannot be empty"
                        ))
                    else:
                        invalid = [
                            kw for kw in keywords_value
                            if not isinstance(kw, str) or not kw.strip()
                        ]
                        if invalid:
                            warnings.append(SchemaValidationIssue(
                                path + ".keywords",
                                f"{len(invalid)} invalid or empty keywords",
                                severity="warning"
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
            "invalid_patterns": 0,
            "version": data.get("version", "unknown"),
            "has_metadata": "metadata" in data,
            "has_settings": "settings" in data
        }
        
        for pattern_type in ["regex_patterns", "keyword_patterns", "entity_patterns"]:
            patterns = data.get(pattern_type, [])
            if not isinstance(patterns, list):
                continue
                
            count = 0
            for pattern in patterns:
                if isinstance(pattern, dict):
                    count += 1
                    # Count enabled/disabled patterns
                    if pattern.get("enabled", True):
                        stats["enabled_patterns"] += 1
                    else:
                        stats["disabled_patterns"] += 1
                else:
                    stats["invalid_patterns"] += 1
            
            stats[f"{pattern_type}"] = count
            stats["total_patterns"] += count
        
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