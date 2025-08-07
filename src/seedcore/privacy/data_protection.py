"""
Data protection and privacy compliance for SeedCore.

This module provides comprehensive data protection features including:
- PII detection and masking
- Data sanitization
- Compliance logging
- GDPR/CCPA compliance tools
- Secure data handling
"""

import re
import logging
import hashlib
import json
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DataClassification(Enum):
    """Data classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    PII = "pii"


class ComplianceFramework(Enum):
    """Supported compliance frameworks."""
    GDPR = "gdpr"
    CCPA = "ccpa"
    HIPAA = "hipaa"
    SOX = "sox"
    PCI_DSS = "pci_dss"


@dataclass
class PrivacyConfig:
    """Privacy and data protection configuration."""
    enable_pii_detection: bool = True
    enable_data_masking: bool = True
    enable_compliance_logging: bool = True
    enable_audit_trail: bool = True
    data_retention_days: int = 90
    compliance_frameworks: List[ComplianceFramework] = field(default_factory=list)
    allowed_data_types: Set[str] = field(default_factory=set)
    blocked_patterns: List[str] = field(default_factory=list)


class PIIDetector:
    """Detects and handles Personally Identifiable Information (PII)."""
    
    def __init__(self):
        # PII patterns for detection
        self.pii_patterns = {
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "phone": r'\b(?:\+?1[-.]?)?\(?([0-9]{3})\)?[-.]?([0-9]{3})[-.]?([0-9]{4})\b',
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
            "credit_card": r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b',
            "ip_address": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
            "mac_address": r'\b([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})\b',
            "date_of_birth": r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
            "address": r'\b\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b',
            "name": r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b'
        }
        
        # Compile patterns for efficiency
        self.compiled_patterns = {
            pattern_type: re.compile(pattern, re.IGNORECASE)
            for pattern_type, pattern in self.pii_patterns.items()
        }
    
    def detect_pii(self, text: str) -> Dict[str, List[str]]:
        """
        Detect PII in text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary of detected PII types and values
        """
        detected_pii = {}
        
        for pii_type, pattern in self.compiled_patterns.items():
            matches = pattern.findall(text)
            if matches:
                detected_pii[pii_type] = matches
        
        return detected_pii
    
    def mask_pii(self, text: str, mask_char: str = "*") -> Tuple[str, Dict[str, List[str]]]:
        """
        Mask PII in text.
        
        Args:
            text: Text to mask
            mask_char: Character to use for masking
            
        Returns:
            Tuple of (masked_text, detected_pii)
        """
        detected_pii = self.detect_pii(text)
        masked_text = text
        
        for pii_type, matches in detected_pii.items():
            for match in matches:
                if isinstance(match, tuple):
                    # Handle grouped matches
                    for group in match:
                        if group:
                            masked_text = masked_text.replace(group, mask_char * len(group))
                else:
                    # Handle single matches
                    masked_text = masked_text.replace(match, mask_char * len(match))
        
        return masked_text, detected_pii
    
    def hash_pii(self, pii_value: str, salt: str = "") -> str:
        """
        Hash PII values for secure storage.
        
        Args:
            pii_value: PII value to hash
            salt: Salt for hashing
            
        Returns:
            Hashed value
        """
        salted_value = pii_value + salt
        return hashlib.sha256(salted_value.encode()).hexdigest()


class DataSanitizer:
    """Sanitizes data for logging and storage."""
    
    def __init__(self, config: PrivacyConfig):
        self.config = config
        self.pii_detector = PIIDetector()
        
        # Sensitive field patterns
        self.sensitive_fields = {
            "password", "passwd", "pwd", "secret", "key", "token",
            "api_key", "auth", "credential", "private", "sensitive"
        }
    
    def sanitize_data(self, data: Any, classification: DataClassification = DataClassification.INTERNAL) -> Any:
        """
        Sanitize data based on classification.
        
        Args:
            data: Data to sanitize
            classification: Data classification level
            
        Returns:
            Sanitized data
        """
        if classification == DataClassification.PUBLIC:
            return self._sanitize_public(data)
        elif classification == DataClassification.PII:
            return self._sanitize_pii(data)
        elif classification == DataClassification.RESTRICTED:
            return self._sanitize_restricted(data)
        else:
            return self._sanitize_internal(data)
    
    def _sanitize_public(self, data: Any) -> Any:
        """Sanitize public data (minimal sanitization)."""
        if isinstance(data, str):
            return self._mask_sensitive_fields(data)
        elif isinstance(data, dict):
            return {k: self._sanitize_public(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_public(item) for item in data]
        else:
            return data
    
    def _sanitize_internal(self, data: Any) -> Any:
        """Sanitize internal data (moderate sanitization)."""
        if isinstance(data, str):
            masked_text, detected_pii = self.pii_detector.mask_pii(data)
            return self._mask_sensitive_fields(masked_text)
        elif isinstance(data, dict):
            return {k: self._sanitize_internal(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_internal(item) for item in data]
        else:
            return data
    
    def _sanitize_pii(self, data: Any) -> Any:
        """Sanitize PII data (aggressive sanitization)."""
        if isinstance(data, str):
            masked_text, _ = self.pii_detector.mask_pii(data)
            return self._mask_sensitive_fields(masked_text)
        elif isinstance(data, dict):
            return {k: self._sanitize_pii(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize_pii(item) for item in data]
        else:
            return "[REDACTED]"
    
    def _sanitize_restricted(self, data: Any) -> Any:
        """Sanitize restricted data (maximum sanitization)."""
        return "[RESTRICTED]"
    
    def _mask_sensitive_fields(self, text: str) -> str:
        """Mask sensitive field names in text."""
        for field in self.sensitive_fields:
            # Case-insensitive replacement
            pattern = re.compile(re.escape(field), re.IGNORECASE)
            text = pattern.sub("[MASKED]", text)
        return text


class ComplianceLogger:
    """Logs compliance-related activities."""
    
    def __init__(self, config: PrivacyConfig):
        self.config = config
        self.audit_trail = []
        self.compliance_events = []
    
    def log_data_access(self, user_id: str, data_type: str, classification: DataClassification, action: str):
        """Log data access events."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "data_type": data_type,
            "classification": classification.value,
            "action": action,
            "compliance_frameworks": [f.value for f in self.config.compliance_frameworks]
        }
        
        self.audit_trail.append(event)
        logger.info(f"Data access logged: {user_id} {action} {data_type} ({classification.value})")
    
    def log_pii_detection(self, data_source: str, pii_types: List[str], action_taken: str):
        """Log PII detection events."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "data_source": data_source,
            "pii_types": pii_types,
            "action_taken": action_taken,
            "compliance_frameworks": [f.value for f in self.config.compliance_frameworks]
        }
        
        self.compliance_events.append(event)
        logger.warning(f"PII detected in {data_source}: {pii_types} - {action_taken}")
    
    def log_data_retention(self, data_type: str, retention_days: int, action: str):
        """Log data retention events."""
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "data_type": data_type,
            "retention_days": retention_days,
            "action": action,
            "compliance_frameworks": [f.value for f in self.config.compliance_frameworks]
        }
        
        self.compliance_events.append(event)
        logger.info(f"Data retention: {data_type} {action} after {retention_days} days")
    
    def get_audit_trail(self, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[Dict]:
        """Get audit trail for specified period."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()
        
        filtered_trail = [
            event for event in self.audit_trail
            if start_date <= datetime.fromisoformat(event["timestamp"]) <= end_date
        ]
        
        return filtered_trail
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """Generate compliance report."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "compliance_frameworks": [f.value for f in self.config.compliance_frameworks],
            "audit_events_count": len(self.audit_trail),
            "compliance_events_count": len(self.compliance_events),
            "recent_audit_events": self.audit_trail[-10:],
            "recent_compliance_events": self.compliance_events[-10:]
        }


class DataProtectionManager:
    """
    Comprehensive data protection manager.
    
    This class provides:
    - PII detection and masking
    - Data sanitization
    - Compliance logging
    - Audit trail management
    - GDPR/CCPA compliance tools
    """
    
    def __init__(self, config: Optional[PrivacyConfig] = None):
        self.config = config or PrivacyConfig()
        self.pii_detector = PIIDetector()
        self.data_sanitizer = DataSanitizer(self.config)
        self.compliance_logger = ComplianceLogger(self.config)
        
        logger.info("✅ Data protection manager initialized")
    
    def process_cognitive_input(self, input_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Process cognitive task input with data protection.
        
        Args:
            input_data: Input data for cognitive task
            user_id: ID of the user making the request
            
        Returns:
            Processed input data with protection applied
        """
        # Log data access
        self.compliance_logger.log_data_access(
            user_id=user_id,
            data_type="cognitive_input",
            classification=DataClassification.INTERNAL,
            action="process"
        )
        
        # Detect PII in input
        input_text = json.dumps(input_data)
        detected_pii = self.pii_detector.detect_pii(input_text)
        
        if detected_pii:
            self.compliance_logger.log_pii_detection(
                data_source="cognitive_input",
                pii_types=list(detected_pii.keys()),
                action_taken="masked"
            )
        
        # Sanitize input data
        sanitized_data = self.data_sanitizer.sanitize_data(
            input_data, 
            DataClassification.INTERNAL
        )
        
        return {
            "original_data": input_data,
            "sanitized_data": sanitized_data,
            "detected_pii": detected_pii,
            "processing_timestamp": datetime.utcnow().isoformat()
        }
    
    def process_cognitive_output(self, output_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Process cognitive task output with data protection.
        
        Args:
            output_data: Output data from cognitive task
            user_id: ID of the user receiving the output
            
        Returns:
            Processed output data with protection applied
        """
        # Log data access
        self.compliance_logger.log_data_access(
            user_id=user_id,
            data_type="cognitive_output",
            classification=DataClassification.INTERNAL,
            action="generate"
        )
        
        # Detect PII in output
        output_text = json.dumps(output_data)
        detected_pii = self.pii_detector.detect_pii(output_text)
        
        if detected_pii:
            self.compliance_logger.log_pii_detection(
                data_source="cognitive_output",
                pii_types=list(detected_pii.keys()),
                action_taken="masked"
            )
        
        # Sanitize output data
        sanitized_output = self.data_sanitizer.sanitize_data(
            output_data,
            DataClassification.INTERNAL
        )
        
        return {
            "original_output": output_data,
            "sanitized_output": sanitized_output,
            "detected_pii": detected_pii,
            "processing_timestamp": datetime.utcnow().isoformat()
        }
    
    def sanitize_logs(self, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize data for logging.
        
        Args:
            log_data: Data to be logged
            
        Returns:
            Sanitized log data
        """
        return self.data_sanitizer.sanitize_data(log_data, DataClassification.PUBLIC)
    
    def check_compliance(self, data: Dict[str, Any], framework: ComplianceFramework) -> Dict[str, Any]:
        """
        Check compliance with specific framework.
        
        Args:
            data: Data to check
            framework: Compliance framework to check against
            
        Returns:
            Compliance check results
        """
        results = {
            "framework": framework.value,
            "timestamp": datetime.utcnow().isoformat(),
            "compliant": True,
            "issues": [],
            "recommendations": []
        }
        
        if framework == ComplianceFramework.GDPR:
            results.update(self._check_gdpr_compliance(data))
        elif framework == ComplianceFramework.CCPA:
            results.update(self._check_ccpa_compliance(data))
        elif framework == ComplianceFramework.HIPAA:
            results.update(self._check_hipaa_compliance(data))
        
        return results
    
    def _check_gdpr_compliance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check GDPR compliance."""
        issues = []
        recommendations = []
        
        # Check for PII
        data_text = json.dumps(data)
        detected_pii = self.pii_detector.detect_pii(data_text)
        
        if detected_pii:
            issues.append(f"PII detected: {list(detected_pii.keys())}")
            recommendations.append("Mask or remove PII before processing")
        
        # Check for data minimization
        if len(data_text) > 10000:  # Arbitrary threshold
            recommendations.append("Consider data minimization principles")
        
        return {
            "compliant": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations
        }
    
    def _check_ccpa_compliance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check CCPA compliance."""
        issues = []
        recommendations = []
        
        # Check for personal information
        data_text = json.dumps(data)
        detected_pii = self.pii_detector.detect_pii(data_text)
        
        if detected_pii:
            issues.append(f"Personal information detected: {list(detected_pii.keys())}")
            recommendations.append("Ensure proper consent and disclosure")
        
        return {
            "compliant": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations
        }
    
    def _check_hipaa_compliance(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Check HIPAA compliance."""
        issues = []
        recommendations = []
        
        # Check for PHI (Protected Health Information)
        phi_indicators = ["medical", "health", "diagnosis", "treatment", "patient", "doctor", "hospital"]
        data_text = json.dumps(data).lower()
        
        phi_found = [indicator for indicator in phi_indicators if indicator in data_text]
        if phi_found:
            issues.append(f"Potential PHI indicators found: {phi_found}")
            recommendations.append("Ensure HIPAA-compliant handling of health information")
        
        return {
            "compliant": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations
        }
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """Get comprehensive compliance report."""
        return {
            "data_protection_status": "active",
            "compliance_frameworks": [f.value for f in self.config.compliance_frameworks],
            "audit_trail": self.compliance_logger.get_audit_trail(),
            "compliance_report": self.compliance_logger.get_compliance_report(),
            "pii_detection_enabled": self.config.enable_pii_detection,
            "data_masking_enabled": self.config.enable_data_masking,
            "compliance_logging_enabled": self.config.enable_compliance_logging
        }


# Global data protection manager instance
_data_protection_manager: Optional[DataProtectionManager] = None


def get_data_protection_manager() -> DataProtectionManager:
    """Get the global data protection manager instance."""
    global _data_protection_manager
    if _data_protection_manager is None:
        _data_protection_manager = DataProtectionManager()
    return _data_protection_manager


def configure_data_protection(config: PrivacyConfig) -> DataProtectionManager:
    """Configure the global data protection manager."""
    global _data_protection_manager
    _data_protection_manager = DataProtectionManager(config)
    return _data_protection_manager


def protect_cognitive_data(input_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Protect cognitive task input data."""
    manager = get_data_protection_manager()
    return manager.process_cognitive_input(input_data, user_id)


def sanitize_log_data(log_data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize data for logging."""
    manager = get_data_protection_manager()
    return manager.sanitize_logs(log_data)


def check_compliance(data: Dict[str, Any], framework: ComplianceFramework) -> Dict[str, Any]:
    """Check compliance with specific framework."""
    manager = get_data_protection_manager()
    return manager.check_compliance(data, framework)


def get_compliance_report() -> Dict[str, Any]:
    """Get compliance report."""
    manager = get_data_protection_manager()
    return manager.get_compliance_report() 